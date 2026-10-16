"""Production inference: calibrated daily hazard for every grid cell, maps and explanations.

The production model is the candidate with the best development-period validation score
(`selection.json` -> ``production_model``; never chosen on calibration or test data),
calibrated with the frozen Platt parameters and mapped with the frozen class boundaries.
The same engine serves the ``map`` stage, the ``forecast`` command and the platform API.
"""

from __future__ import annotations

import datetime as dt
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from rasterio.crs import CRS

from wildfire_kz.calibration.calibrate import Platt, assign_classes
from wildfire_kz.config.schema import Config
from wildfire_kz.explain.contributions import contributions, top_drivers
from wildfire_kz.features.build import FeatureBuilder
from wildfire_kz.grid.grid import GridMeta, load_grid
from wildfire_kz.models.pipelines import FittedModel
from wildfire_kz.models.train import load_model
from wildfire_kz.paths import RunPaths
from wildfire_kz.sampling.risk_set import excluded_cell_days
from wildfire_kz.splits.guard import TestSetAccessError, test_years_unlocked
from wildfire_kz.utils.runtime import get_logger, read_json, sha256_file, utc_now, write_json

log = get_logger("forecast")

DISCLAIMER = (
    "Calibrated probability that a NEW vegetation-fire event is first detected by "
    "Suomi-NPP VIIRS in this cell on this UTC day, given information up to the "
    "previous day. Occurrence hazard only: not damage, exposure, vulnerability or "
    "risk. Absence of detection is not verified absence of fire."
)


class ForecastEngine:
    def __init__(self, cfg: Config, paths: RunPaths) -> None:
        self.cfg = cfg
        self.paths = paths
        self.cal_path = paths.stage("calibrate") / "calibration_artifacts.json"
        if not self.cal_path.exists():
            raise FileNotFoundError("run the pipeline through 'calibrate' before forecasting")
        self.cal = read_json(self.cal_path)
        selection = read_json(paths.stage("train") / "selection.json")
        self.model_name: str = selection.get("production_model") or self.cal["map_model"]
        c = self.cal["models"][self.model_name]
        self.platt = Platt(c["platt_a"], c["platt_b"])
        self.tau = float(c["tau"])
        self.boundaries: list[float] = self.cal["map_class_boundaries"]
        self.labels: list[str] = self.cal["map_class_labels"]
        self.grid = load_grid(paths.grid_file)
        self.meta = GridMeta.load(paths.grid_meta)
        self.synthetic = (cfg.project.raw_dir / "SYNTHETIC_DATA.txt").exists()

    # ------------------------------------------------------------------ lazy resources
    @cached_property
    def model(self) -> FittedModel:
        return load_model(self.paths.stage("train") / self.model_name)

    @cached_property
    def builder(self) -> FeatureBuilder:
        return FeatureBuilder(self.cfg, self.paths)

    @cached_property
    def _exclusions(self) -> tuple[set[tuple[int, np.datetime64]], pd.Timestamp]:
        det = pd.read_parquet(self.paths.detections, columns=["cell_id", "acq_datetime"])
        ex = excluded_cell_days(
            det["cell_id"].to_numpy(), det["acq_datetime"], self.cfg.risk_set.exclusion_hours
        )
        keys = set(
            zip(ex["cell_id"].to_numpy(), ex["date"].to_numpy(dtype="datetime64[D]"), strict=True)
        )
        # the archive covers the whole study period even if its last days had no fires
        covered = max(
            pd.Timestamp(det["acq_datetime"].max()),
            pd.Timestamp(self.cfg.study.end) + pd.Timedelta(hours=23, minutes=59),
        )
        return keys, covered

    # ------------------------------------------------------------------ protocol guard
    def check_allowed(self, day: pd.Timestamp) -> None:
        """Test-year maps are only produced after the final evaluation has been run."""
        if (
            day.year in self.cfg.splits.test_years
            and self.cfg.forecast.require_evaluation_for_test_years
            and not test_years_unlocked(self.cfg, self.paths)
        ):
            raise TestSetAccessError(
                f"{day:%Y-%m-%d} lies in a test year; run the 'evaluate' stage first"
            )

    def partition(self, day: pd.Timestamp) -> str:
        s = self.cfg.splits
        if day.year in s.test_years:
            return "test"
        if day.year in s.calibration_years:
            return "calibration"
        if day.year in s.development_years:
            return "development"
        return "operational"

    # ------------------------------------------------------------------ prediction
    def features(self, day: pd.Timestamp, cell_ids: np.ndarray | None = None) -> pd.DataFrame:
        ids = self.grid["cell_id"].to_numpy() if cell_ids is None else np.asarray(cell_ids)
        feats = self.builder.assemble(pd.DataFrame({"cell_id": ids, "date": day}))
        feats["month"] = day.month
        return feats

    def predict_day(self, day: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Calibrated probability, class and eligibility for every cell on ``day``."""
        self.check_allowed(day)
        feats = self.features(day)
        raw = self.model.decision_logit(feats)
        p = self.platt.apply(raw)
        excl, last_det = self._exclusions
        d64 = np.datetime64(day.date())
        eligible = np.array([(cid, d64) not in excl for cid in self.grid["cell_id"]])
        df = pd.DataFrame(
            {
                "cell_id": self.grid["cell_id"].to_numpy(),
                "row": self.grid["row"].to_numpy(),
                "col": self.grid["col"].to_numpy(),
                "lon": self.grid["lon"].to_numpy(),
                "lat": self.grid["lat"].to_numpy(),
                "p": p.astype(np.float32),
                "score_logit": raw.astype(np.float32),
                "hazard_class": assign_classes(p, self.boundaries).astype(np.int16),
                "eligible": eligible,
            }
        )
        info = {
            "date": f"{day:%Y-%m-%d}",
            "predictors_up_to": f"{day - pd.Timedelta(days=1):%Y-%m-%d}",
            "model": self.model_name,
            "partition": self.partition(day),
            "eligible_cells": int(eligible.sum()),
            "max_p": float(p[eligible].max()) if eligible.any() else None,
            "tau": self.tau,
            "class_boundaries": self.boundaries,
            "class_labels": self.labels,
            "detections_known_until": f"{last_det:%Y-%m-%d %H:%M}",
            "eligibility_note": (
                "eligibility uses detections up to the previous day"
                if last_det >= day - pd.Timedelta(days=1)
                else "WARNING: detection archive ends before the previous day; recent-fire "
                "exclusion may be incomplete"
            ),
            "synthetic": self.synthetic,
            "disclaimer": DISCLAIMER,
            "generated_utc": utc_now(),
        }
        return df, info

    def explain_cells(
        self, day: pd.Timestamp, cell_ids: list[int], n: int
    ) -> dict[int, dict[str, Any]]:
        """Top contributions (uncalibrated score scale) for selected cells on ``day``."""
        self.check_allowed(day)
        feats = self.features(day, np.asarray(cell_ids))
        try:
            c = contributions(self.model, feats)
        except NotImplementedError:
            return {}
        out = {}
        for i, cid in enumerate(cell_ids):
            out[int(cid)] = {
                "scale": c.scale,
                "base_value": c.base_value,
                "drivers": top_drivers(c, i, n),
                "note": "predictive association, not a causal effect",
            }
        return out

    # ------------------------------------------------------------------ outputs
    def tags(self, day: pd.Timestamp) -> dict[str, str]:
        return {
            "DESCRIPTION": DISCLAIMER,
            "MODEL": self.model_name,
            "CALIBRATION": "Platt sigmoid fitted on calibration years "
            f"{self.cfg.splits.calibration_years}",
            "CALIBRATION_SHA256": sha256_file(self.cal_path),
            "CRS_NAME": self.meta.crs_name,
            "CELL_SIZE_M": str(self.meta.cell_size_m),
            "CLASS_BOUNDARIES": str(self.boundaries),
            "CLASS_LABELS": str(self.labels),
            "SYNTHETIC": str(self.synthetic),
            "TARGET_DATE_UTC": f"{day:%Y-%m-%d}",
            "PREDICTORS_UP_TO_UTC": f"{day - pd.Timedelta(days=1):%Y-%m-%d}",
            "PARTITION": self.partition(day),
        }

    def write_day(
        self, day: pd.Timestamp, df: pd.DataFrame, info: dict[str, Any], out_dir: Path
    ) -> dict[str, str]:
        """prob_/class_ GeoTIFFs (+ .qml), a per-cell Parquet table and a JSON sidecar."""
        out_dir.mkdir(parents=True, exist_ok=True)
        mc = self.cfg.mapping
        m = self.meta
        e = df["eligible"].to_numpy()
        rr, cc = df["row"].to_numpy()[e], df["col"].to_numpy()[e]
        prob = np.full((m.height, m.width), mc.nodata, dtype=np.float32)
        prob[rr, cc] = df["p"].to_numpy()[e]
        cls = np.full((m.height, m.width), mc.class_nodata, dtype=np.uint8)
        cls[rr, cc] = df["hazard_class"].to_numpy()[e].astype(np.uint8)
        stem = f"{day:%Y%m%d}"
        pf, cf = out_dir / f"prob_{stem}.tif", out_dir / f"class_{stem}.tif"
        tags = self.tags(day)
        write_raster(pf, prob, m, mc.nodata, tags, "calibrated new-event probability")
        write_raster(cf, cls, m, mc.class_nodata, tags, "hazard class (fixed boundaries)")
        write_qml(
            cf.with_suffix(".qml"), self.boundaries, self.labels, self.cfg.platform.class_colors
        )
        df.to_parquet(out_dir / f"cells_{stem}.parquet", index=False)
        write_json(out_dir / f"meta_{stem}.json", info)
        return {"prob_file": pf.name, "class_file": cf.name}


def write_raster(
    path: Path,
    arr: np.ndarray,
    meta: GridMeta,
    nodata: float | int,
    tags: dict[str, str],
    description: str,
) -> None:
    profile = {
        "driver": "GTiff",
        "height": meta.height,
        "width": meta.width,
        "count": 1,
        "dtype": arr.dtype.name,
        "crs": CRS.from_proj4(meta.crs),
        "transform": meta.transform,
        "nodata": nodata,
        "compress": "deflate",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr, 1)
        dst.update_tags(**tags)
        dst.set_band_description(1, description)


def write_qml(path: Path, boundaries: list[float], labels: list[str], colors: list[str]) -> None:
    entries = "\n".join(
        f'        <paletteEntry value="{k}" label="{labels[k]}" '
        f'color="{colors[min(k, len(colors) - 1)]}" alpha="255"/>'
        for k in range(len(labels))
    )
    path.write_text(f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28">
  <pipe>
    <rasterrenderer type="paletted" band="1" opacity="1">
      <colorPalette>
{entries}
      </colorPalette>
    </rasterrenderer>
  </pipe>
  <!-- class boundaries (calibrated probability, fixed on calibration data): {boundaries} -->
</qgis>
""")


def run_forecast(cfg: Config, paths: RunPaths, day: dt.date) -> dict[str, Any]:
    """Operational next-day forecast for ``day`` (predictors up to ``day - 1``)."""
    engine = ForecastEngine(cfg, paths)
    ts = pd.Timestamp(day)
    df, info = engine.predict_day(ts)
    files = engine.write_day(ts, df, info, paths.stage("forecast") / f"{ts:%Y%m%d}")
    log.info("forecast %s written with model %s", info["date"], engine.model_name)
    return {**info, **files}
