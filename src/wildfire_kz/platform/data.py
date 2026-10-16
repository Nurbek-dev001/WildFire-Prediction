"""Read-only access to run artifacts for the platform (days, overlays, model cards)."""

from __future__ import annotations

import io
from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import calculate_default_transform, reproject, transform_bounds

from wildfire_kz.config.schema import Config
from wildfire_kz.grid.grid import GridMeta, make_cell_id
from wildfire_kz.paths import RunPaths
from wildfire_kz.utils.runtime import read_json

WEB_MERCATOR = "EPSG:3857"


@dataclass(frozen=True)
class DayRecord:
    date: str
    source: str  # "map" (pipeline stage) or "forecast" (operational command)
    directory: Path

    @property
    def stem(self) -> str:
        return self.date.replace("-", "")

    @property
    def meta_path(self) -> Path:
        return self.directory / f"meta_{self.stem}.json"

    @property
    def cells_path(self) -> Path:
        return self.directory / f"cells_{self.stem}.parquet"

    @property
    def class_path(self) -> Path:
        return self.directory / f"class_{self.stem}.tif"

    @property
    def prob_path(self) -> Path:
        return self.directory / f"prob_{self.stem}.tif"


class RunArtifacts:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.paths = RunPaths.from_config(cfg)

    # ------------------------------------------------------------------ status
    def stage_done(self, stage: str) -> bool:
        return (self.paths.stage(stage) / "_stage.json").exists()

    def status(self) -> dict[str, Any]:
        stages = (
            "ingest",
            "grid",
            "events",
            "risk_set",
            "sampling",
            "features",
            "splits",
            "train",
            "calibrate",
            "ablate",
            "evaluate",
            "explain",
            "map",
            "report",
        )
        manifest = read_json(self.paths.manifest) if self.paths.manifest.exists() else {}
        return {
            "run_label": self.cfg.project.run_label,
            "grid": self.cfg.grid.active,
            "cell_size_m": self.cfg.grid.active_spec.cell_size_m,
            "synthetic": bool(manifest.get("synthetic", False)),
            "stages": {s: self.stage_done(s) for s in stages},
        }

    def boundary_geojson(self) -> str:
        from wildfire_kz.grid.grid import load_boundary

        b = load_boundary(self.cfg)
        b["geometry"] = b.geometry.simplify(self.cfg.platform.boundary_simplify_m)
        return str(b.to_crs("EPSG:4326").to_json())

    # ------------------------------------------------------------------ days
    def days(self) -> dict[str, DayRecord]:
        out: dict[str, DayRecord] = {}
        map_dir = self.paths.stage("map")
        for meta in sorted(map_dir.glob("meta_*.json")):
            d = meta.stem.split("_")[1]
            date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            out[date] = DayRecord(date, "map", map_dir)
        fc = self.paths.stage("forecast")
        for sub in sorted(fc.glob("*")):
            if (sub / f"meta_{sub.name}.json").exists():
                d = sub.name
                date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                out[date] = DayRecord(date, "forecast", sub)  # forecasts take precedence
        return dict(sorted(out.items()))

    def day_summary(self, rec: DayRecord) -> dict[str, Any]:
        meta = read_json(rec.meta_path)
        cells = pd.read_parquet(rec.cells_path)
        e = cells[cells["eligible"]]
        counts = (
            e["hazard_class"].value_counts().reindex(range(len(meta["class_labels"])), fill_value=0)
        )
        bounds = overlay_bounds(rec.class_path)
        return {
            **meta,
            "source": rec.source,
            "bounds_latlon": bounds,
            "class_counts": [int(v) for v in counts.to_numpy()],
            "max_p": float(e["p"].max()) if len(e) else None,
            "mean_p": float(e["p"].mean()) if len(e) else None,
            "observed_new_events": self.observed_cells(rec.date),
        }

    def observed_cells(self, date: str) -> list[dict[str, Any]] | None:
        ids = self.observed(date)
        if ids is None:
            return None
        g = self.grid_table.set_index("cell_id").reindex(ids)
        return [
            {"cell_id": int(c), "lat": float(la), "lon": float(lo)}
            for c, la, lo in zip(ids, g["lat"].to_numpy(), g["lon"].to_numpy(), strict=True)
        ]

    @cached_property
    def grid_table(self) -> pd.DataFrame:
        return pd.read_parquet(self.paths.grid_file, columns=["cell_id", "lat", "lon"])

    def observed(self, date: str) -> list[int] | None:
        """Observed new-event cells for past days (test years only once evaluated)."""
        ts = pd.Timestamp(date)
        if ts.year in self.cfg.splits.test_years and not self.stage_done("evaluate"):
            return None
        if not self.paths.positives.exists():
            return None
        if ts > pd.Timestamp(self.cfg.study.end):
            return None  # outside the labelled archive (operational forecast)
        pos = pd.read_parquet(self.paths.positives)
        hit = pos[pos["date"] == ts]
        return [int(c) for c in hit["cell_id"]]

    def cell_at(self, rec: DayRecord, lat: float, lon: float) -> dict[str, Any] | None:
        meta = GridMeta.load(self.paths.grid_meta)
        x, y = Transformer.from_crs("EPSG:4326", meta.crs, always_xy=True).transform(lon, lat)
        s = meta.cell_size_m
        cid = int(
            make_cell_id(np.array([int(np.floor(x / s))]), np.array([int(np.floor(y / s))]))[0]
        )
        cells = pd.read_parquet(rec.cells_path)
        row = cells[cells["cell_id"] == cid]
        if row.empty:
            return None
        return {
            str(k): (v.item() if hasattr(v, "item") else v)
            for k, v in row.iloc[0].to_dict().items()
        }

    def top_cells(self, rec: DayRecord, n: int) -> list[dict[str, Any]]:
        cells = pd.read_parquet(rec.cells_path)
        top = cells[cells["eligible"]].nlargest(n, "p")
        return clean_records(top[["cell_id", "lat", "lon", "p", "hazard_class"]])

    # ------------------------------------------------------------------ models
    def model_card(self) -> dict[str, Any]:
        sel = read_json(self.paths.stage("train") / "selection.json")
        cal = (
            read_json(self.paths.stage("calibrate") / "calibration_artifacts.json")
            if self.stage_done("calibrate")
            else {}
        )
        name = sel.get("production_model") or sel.get("best_classifier")
        m = sel["models"].get(name, {})
        card: dict[str, Any] = {
            "production_model": name,
            "selection_criterion": sel.get("criterion"),
            "candidates_dev_cv_ap": sel.get("candidates_dev_cv_ap", {}),
            "dev_cv_ap_by_fold": m.get("cv_weighted_ap_by_fold"),
            "params": m.get("params"),
            "training_scheme": m.get("scheme"),
            "n_features": len(m.get("features", [])),
            "features": m.get("features", []),
            "calibration": (cal.get("models", {}).get(name) if cal else None),
            "class_boundaries": cal.get("map_class_boundaries"),
            "class_labels": cal.get("map_class_labels"),
            "class_colors": self.cfg.platform.class_colors,
            "test_metrics": None,
        }
        mo = self.paths.stage("evaluate") / "metrics_overall.csv"
        if mo.exists():
            t = pd.read_csv(mo)
            r = t[t["model"] == name]
            if len(r):
                card["test_metrics"] = clean(r.iloc[0].to_dict())
        freq = self.paths.stage("calibrate") / "map_class_frequencies_calibration.csv"
        if freq.exists():
            card["class_frequencies_calibration"] = clean_records(pd.read_csv(freq))
        return card

    def models_table(self) -> list[dict[str, Any]]:
        sel = read_json(self.paths.stage("train") / "selection.json")
        rows = []
        for name, m in sel["models"].items():
            rows.append(
                {
                    "model": name,
                    "dev_cv_ap": m.get("cv_weighted_ap_mean"),
                    "scheme": m.get("scheme"),
                    "kind": "class_weight_sensitivity"
                    if "__classweight" in name
                    else "ensemble"
                    if name == self.cfg.models.ensemble.name
                    else "baseline"
                    if name in self.cfg.models.baselines
                    else "classifier",
                    "production": name == sel.get("production_model"),
                }
            )
        mo = self.paths.stage("evaluate") / "metrics_overall.csv"
        if mo.exists():
            t = pd.read_csv(mo).set_index("model")
            for r in rows:
                if r["model"] in t.index:
                    tm = t.loc[r["model"]]
                    for k in (
                        "prevalence",
                        "average_precision",
                        "roc_auc",
                        "brier",
                        "bss",
                        "ece_10bin",
                        "f1",
                    ):
                        r[f"test_{k}"] = clean_value(tm[k])
        return rows

    def evaluation(self) -> dict[str, Any] | None:
        ev = self.paths.stage("evaluate")
        if not (ev / "metrics_overall.csv").exists():
            return None
        sel = read_json(self.paths.stage("train") / "selection.json")
        name = sel.get("production_model")
        rel = pd.read_csv(ev / "reliability.csv")
        rel = rel[(rel["model"] == name) & (rel["binning"] == "quantile") & (rel["weight"] > 0)]
        cap = pd.read_csv(ev / "capture_rates.csv")
        return {
            "model": name,
            "reliability": clean_records(rel),
            "capture": clean_records(cap[cap["model"] == name]),
            "flags": read_json(ev / "result_flags.json")["flags"],
        }


# ---------------------------------------------------------------------- overlay rendering
@lru_cache(maxsize=64)
def overlay_bounds(class_tif: Path) -> list[list[float]]:
    with rasterio.open(class_tif) as src:
        w, s, e, n = transform_bounds(src.crs, WEB_MERCATOR, *src.bounds)
    lon_w, lat_s, lon_e, lat_n = transform_bounds(WEB_MERCATOR, "EPSG:4326", w, s, e, n)
    return [[lat_s, lon_w], [lat_n, lon_e]]


@lru_cache(maxsize=64)
def overlay_png(class_tif: Path, colors: tuple[str, ...], max_px: int) -> bytes:
    """Class raster warped (nearest) to Web Mercator and coloured, transparent nodata."""
    with rasterio.open(class_tif) as src:
        dst_crs = CRS.from_string(WEB_MERCATOR)
        _, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        factor = max_px / max(width, height)  # scale to fit (nearest keeps cells crisp)
        width, height = max(1, round(width * factor)), max(1, round(height * factor))
        w, s, e, n = transform_bounds(src.crs, dst_crs, *src.bounds)
        tr = from_bounds(w, s, e, n, width, height)
        nodata = src.nodata if src.nodata is not None else 255
        dst = np.full((height, width), nodata, dtype=np.uint8)
        reproject(
            rasterio.band(src, 1),
            dst,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=tr,
            dst_crs=dst_crs,
            resampling=Resampling.nearest,
            src_nodata=nodata,
            dst_nodata=nodata,
        )
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    for k, hexcol in enumerate(colors):
        m = dst == k
        rgba[m, :3] = [int(hexcol[i : i + 2], 16) for i in (1, 3, 5)]
        rgba[m, 3] = 215
    rgba[dst == nodata, 3] = 0
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def clean_value(v: Any) -> Any:
    if isinstance(v, float | np.floating):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def clean(d: dict[str, Any]) -> dict[str, Any]:
    return {str(k): clean_value(v) for k, v in d.items()}


def clean_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [clean({str(k): v for k, v in r.items()}) for r in df.to_dict(orient="records")]
