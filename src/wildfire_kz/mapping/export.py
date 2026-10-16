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

from typing import Any

import numpy as np
import pandas as pd

from wildfire_kz.calibration.calibrate import assign_classes
from wildfire_kz.config.schema import Config
from wildfire_kz.forecast.engine import DISCLAIMER, ForecastEngine, write_qml
from wildfire_kz.paths import RunPaths
from wildfire_kz.splits.guard import unlock_final_evaluation
from wildfire_kz.utils.runtime import get_logger

log = get_logger("map")

__all__ = ["DISCLAIMER", "mapping_dates", "run_map"]


def mapping_dates(cfg: Config) -> list[pd.Timestamp]:
    days = [
        d
        for y in cfg.mapping.years
        for d in pd.date_range(f"{y}-01-01", f"{y}-12-31")
        if pd.Timestamp(cfg.study.start) <= d <= pd.Timestamp(cfg.study.end)
    ]
    if cfg.mapping.max_days and len(days) > cfg.mapping.max_days:
        idx = np.linspace(0, len(days) - 1, cfg.mapping.max_days).round().astype(int)
        days = [days[i] for i in np.unique(idx)]
    return days


def run_map(cfg: Config, paths: RunPaths) -> dict[str, Any]:
    out = paths.stage("map")
    out.mkdir(parents=True, exist_ok=True)
    if any(cfg.splits.resolved().test.contains(d.date()) for d in mapping_dates(cfg)):
        unlock_final_evaluation(cfg, paths, "map")
    engine = ForecastEngine(cfg, paths)
    write_qml(out / "class_style.qml", engine.boundaries, engine.labels, cfg.platform.class_colors)
    positives = pd.read_parquet(paths.positives)
    rows = []
    for day in mapping_dates(cfg):
        df, info = engine.predict_day(day)
        files = engine.write_day(day, df, info, out)
        e = df["eligible"].to_numpy()
        obs = positives[positives["date"] == day]
        obs_cls = df.loc[df["cell_id"].isin(obs["cell_id"]), "hazard_class"].to_numpy()
        row = {
            "date": f"{day:%Y-%m-%d}",
            **files,
            "eligible_cells": int(e.sum()),
            "observed_new_events": len(obs),
            "partition": info["partition"],
        }
        cls = assign_classes(df["p"].to_numpy()[e], engine.boundaries)
        for k, lab in enumerate(engine.labels):
            row[f"cells_{lab}"] = int((cls == k).sum())
            row[f"events_{lab}"] = int((obs_cls == k).sum())
        rows.append(row)
    pd.DataFrame(rows).to_csv(out / "map_index.csv", index=False)
    log.info("exported %d daily maps with model %s", len(rows), engine.model_name)
    return {"n_days": len(rows), "model": engine.model_name}
