"""Stage 13 — daily calibrated probability maps as QGIS-ready GeoTIFFs.

One pixel = one grid cell (the raster *is* the equal-area grid; no point interpolation).
For each mapped day two files are written:

* ``prob_YYYYMMDD.tif`` — float32 calibrated probability of a new-event first detection;
  nodata outside the grid and for cells ineligible on that day (detection in the previous
  48 h, i.e. not in the new-event risk set);
* ``class_YYYYMMDD.tif`` — uint8 class index using boundaries fixed on the calibration year
  before testing, with a QGIS ``.qml`` style.

Values are occurrence hazard, not damage, exposure or risk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from rasterio.crs import CRS

from wildfire_kz.calibration.calibrate import Platt, assign_classes
from wildfire_kz.config.schema import Config
from wildfire_kz.features.build import FeatureBuilder
from wildfire_kz.grid.grid import GridMeta, load_grid
from wildfire_kz.models.train import load_model
from wildfire_kz.paths import RunPaths
from wildfire_kz.sampling.risk_set import excluded_cell_days
from wildfire_kz.splits.guard import unlock_final_evaluation
from wildfire_kz.utils.runtime import get_logger, read_json, sha256_file

log = get_logger("map")

DISCLAIMER = ("Calibrated probability that a NEW vegetation-fire event is first detected by "
              "Suomi-NPP VIIRS in this cell on this UTC day, given information up to the "
              "previous day. Occurrence hazard only: not damage, exposure, vulnerability or "
              "risk. Absence of detection is not verified absence of fire.")


def mapping_dates(cfg: Config) -> list[pd.Timestamp]:
    days = [d for y in cfg.mapping.years for d in pd.date_range(f"{y}-01-01", f"{y}-12-31")
            if pd.Timestamp(cfg.study.start) <= d <= pd.Timestamp(cfg.study.end)]
    if cfg.mapping.max_days and len(days) > cfg.mapping.max_days:
        idx = np.linspace(0, len(days) - 1, cfg.mapping.max_days).round().astype(int)
        days = [days[i] for i in np.unique(idx)]
    return days


def write_qml(path: Path, boundaries: list[float], labels: list[str]) -> None:
    colors = ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c", "#08306b", "#041f4a"]
    entries = "\n".join(
        f'        <paletteEntry value="{k}" label="{labels[k]}" color="{colors[k % len(colors)]}"'
        ' alpha="255"/>' for k in range(len(labels)))
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


def _write(path: Path, arr: np.ndarray, meta: GridMeta, nodata: float | int,
           tags: dict[str, str], description: str) -> None:
    profile = {"driver": "GTiff", "height": meta.height, "width": meta.width, "count": 1,
               "dtype": arr.dtype.name, "crs": CRS.from_proj4(meta.crs),
               "transform": meta.transform, "nodata": nodata, "compress": "deflate"}
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr, 1)
        dst.update_tags(**tags)
        dst.set_band_description(1, description)


def run_map(cfg: Config, paths: RunPaths) -> dict[str, Any]:
    out = paths.stage("map")
    out.mkdir(parents=True, exist_ok=True)
    cal_path = paths.stage("calibrate") / "calibration_artifacts.json"
    cal = read_json(cal_path)
    if set(cfg.mapping.years) & set(cfg.splits.test_years):
        unlock_final_evaluation(cfg, paths, "map")
    model_name = cal["map_model"]
    fm = load_model(paths.stage("train") / model_name)
    c = cal["models"][model_name]
    platt = Platt(c["platt_a"], c["platt_b"])
    bounds, labels = cal["map_class_boundaries"], cal["map_class_labels"]
    grid = load_grid(paths.grid_file)
    meta = GridMeta.load(paths.grid_meta)
    builder = FeatureBuilder(cfg, paths)
    det = pd.read_parquet(paths.detections, columns=["cell_id", "acq_datetime"])
    excl = excluded_cell_days(det["cell_id"].to_numpy(), det["acq_datetime"],
                              cfg.risk_set.exclusion_hours)
    excl_set = set(zip(excl["cell_id"].to_numpy(), excl["date"].to_numpy(dtype="datetime64[D]"),
                       strict=True))
    positives = pd.read_parquet(paths.positives)
    mc = cfg.mapping
    tags_common = {
        "DESCRIPTION": DISCLAIMER, "MODEL": model_name,
        "CALIBRATION": "Platt sigmoid fitted on calibration years "
                       f"{cfg.splits.calibration_years}",
        "CALIBRATION_SHA256": sha256_file(cal_path), "CRS_NAME": meta.crs_name,
        "CELL_SIZE_M": str(meta.cell_size_m), "CLASS_BOUNDARIES": str(bounds),
        "CLASS_LABELS": str(labels), "SYNTHETIC": str(
            (cfg.project.raw_dir / "SYNTHETIC_DATA.txt").exists()),
    }
    write_qml(out / "class_style.qml", bounds, labels)
    rows = []
    rr, cc = grid["row"].to_numpy(), grid["col"].to_numpy()
    for day in mapping_dates(cfg):
        frame = pd.DataFrame({"cell_id": grid["cell_id"].to_numpy(), "date": day})
        feats = builder.assemble(frame)
        feats["month"] = day.month
        p = platt.apply(fm.decision_logit(feats))
        d64 = np.datetime64(day.date())
        eligible = np.array([(cid, d64) not in excl_set for cid in grid["cell_id"]])
        prob = np.full((meta.height, meta.width), mc.nodata, dtype=np.float32)
        prob[rr[eligible], cc[eligible]] = p[eligible].astype(np.float32)
        cls = np.full((meta.height, meta.width), mc.class_nodata, dtype=np.uint8)
        cls[rr[eligible], cc[eligible]] = assign_classes(p[eligible], bounds).astype(np.uint8)
        tags = {**tags_common, "TARGET_DATE_UTC": f"{day:%Y-%m-%d}",
                "PREDICTORS_UP_TO_UTC": f"{day - pd.Timedelta(days=1):%Y-%m-%d}",
                "PARTITION": "test" if day.year in cfg.splits.test_years else "calibration"
                if day.year in cfg.splits.calibration_years else "development"}
        pf, cf = out / f"prob_{day:%Y%m%d}.tif", out / f"class_{day:%Y%m%d}.tif"
        _write(pf, prob, meta, mc.nodata, tags, "calibrated new-event probability")
        _write(cf, cls, meta, mc.class_nodata, tags, "hazard class (fixed boundaries)")
        (cf.with_suffix(".qml")).write_text((out / "class_style.qml").read_text())
        obs = positives[positives["date"] == day]
        obs_cls = assign_classes(p[np.isin(grid["cell_id"], obs["cell_id"])], bounds)
        row = {"date": f"{day:%Y-%m-%d}", "prob_file": pf.name, "class_file": cf.name,
               "eligible_cells": int(eligible.sum()), "observed_new_events": len(obs)}
        for k, lab in enumerate(labels):
            row[f"cells_{lab}"] = int((assign_classes(p[eligible], bounds) == k).sum())
            row[f"events_{lab}"] = int((obs_cls == k).sum())
        rows.append(row)
    pd.DataFrame(rows).to_csv(out / "map_index.csv", index=False)
    log.info("exported %d daily maps", len(rows))
    return {"n_days": len(rows), "model": model_name}
