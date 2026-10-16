"""Self-contained HTML snapshot of the platform (no server needed).

Precomputes, for a set of days, the hazard overlay (PNG data URI), per-cell probabilities,
classes, eligibility, observed new-event starts and each cell's top model drivers, and writes
one HTML file that renders the same map/model views as the live platform. Useful for sharing
results where running a server is not possible.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from wildfire_kz.config.schema import Config
from wildfire_kz.explain.contributions import contributions
from wildfire_kz.forecast.engine import DISCLAIMER, ForecastEngine
from wildfire_kz.paths import RunPaths
from wildfire_kz.platform.data import RunArtifacts, clean, overlay_bounds, overlay_png
from wildfire_kz.utils.runtime import get_logger

log = get_logger("platform.export")

LEAFLET_JS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"
STATIC = Path(__file__).parent / "static"


def season_days(cfg: Config, step_days: int, months: tuple[int, int]) -> list[pd.Timestamp]:
    """Every ``step_days`` within the fire-season months of calibration and test years."""
    out = []
    for y in [*cfg.splits.calibration_years, *cfg.splits.test_years]:
        days = pd.date_range(f"{y}-{months[0]:02d}-01", f"{y}-{months[1]:02d}-28")
        out += list(days[::step_days])
    return [d for d in out if pd.Timestamp(cfg.study.start) <= d <= pd.Timestamp(cfg.study.end)]


def build_payload(cfg: Config, days: list[pd.Timestamp], n_drivers: int) -> dict[str, Any]:
    paths = RunPaths.from_config(cfg)
    art = RunArtifacts(cfg)
    engine = ForecastEngine(cfg, paths)
    tmp = paths.stage("forecast") / "_export"
    out_days = []
    for day in days:
        df, info = engine.predict_day(day)
        engine.write_day(day, df, info, tmp)
        stem = f"{day:%Y%m%d}"
        cls_tif = tmp / f"class_{stem}.tif"
        png = overlay_png(cls_tif, tuple(cfg.platform.class_colors), 1024)
        e = df["eligible"].to_numpy()
        feats = engine.features(day, df.loc[e, "cell_id"].to_numpy())
        try:
            c = contributions(engine.model, feats)
            drivers = []
            for i in range(len(feats)):
                s = c.values.iloc[i]
                s = s.reindex(s.abs().sort_values(ascending=False).index)[:n_drivers]
                drivers.append([[str(k), round(float(v), 3)] for k, v in s.items()])
            scale = c.scale
        except NotImplementedError:
            drivers, scale = [[] for _ in range(int(e.sum()))], ""
        dmap = dict(zip(df.loc[e, "cell_id"].astype(int), drivers, strict=True))
        observed = art.observed(f"{day:%Y-%m-%d}") or []
        cells = [
            [
                int(cid),
                round(float(la), 4),
                round(float(lo), 4),
                round(float(p), 6),
                int(k),
                bool(el),
                dmap.get(int(cid), []),
            ]
            for cid, la, lo, p, k, el in zip(
                df["cell_id"].to_numpy(),
                df["lat"].to_numpy(),
                df["lon"].to_numpy(),
                df["p"].to_numpy(),
                df["hazard_class"].to_numpy(),
                df["eligible"].to_numpy(),
                strict=True,
            )
        ]
        counts = np.bincount(
            df.loc[e, "hazard_class"].to_numpy(), minlength=len(engine.labels)
        ).tolist()
        out_days.append(
            {
                "date": info["date"],
                "partition": info["partition"],
                "cutoff": info["predictors_up_to"],
                "bounds": overlay_bounds(cls_tif),
                "overlay": "data:image/png;base64," + base64.b64encode(png).decode(),
                "counts": counts,
                "observed": [int(o) for o in observed],
                "cells": cells,
                "scale": scale,
                "max_p": info["max_p"],
            }
        )
        log.info("exported %s", info["date"])
    card = art.model_card()
    models = art.models_table()
    ev = art.evaluation()
    return {
        "title": cfg.platform.title,
        "disclaimer": DISCLAIMER,
        "status": art.status(),
        "class_labels": engine.labels,
        "class_boundaries": engine.boundaries,
        "class_colors": cfg.platform.class_colors,
        "card": clean(card),
        "models": models,
        "evaluation": ev,
        "days": out_days,
        "boundary": json.loads(art.boundary_geojson()),
        "cell_size_km": cfg.grid.active_spec.cell_size_m / 1000,
    }


def export_site(
    cfg: Config,
    out_file: Path,
    step_days: int = 10,
    months: tuple[int, int] = (4, 10),
    n_drivers: int = 5,
) -> Path:
    payload = build_payload(cfg, season_days(cfg, step_days, months), n_drivers)
    template = (STATIC / "snapshot_template.html").read_text()
    leaflet_css = (STATIC / "vendor" / "leaflet" / "leaflet.css").read_text()
    html = (
        template.replace("/*__LEAFLET_CSS__*/", leaflet_css)
        .replace("__LEAFLET_JS__", LEAFLET_JS)
        .replace("__DATA__", json.dumps(payload, separators=(",", ":")).replace("</", "<\\/"))
    )
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html)
    log.info("snapshot written to %s (%.1f MB)", out_file, out_file.stat().st_size / 2**20)
    return out_file
