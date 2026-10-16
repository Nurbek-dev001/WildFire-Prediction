"""Self-contained HTML snapshot of the platform (no server needed).

Precomputes, for a set of days, the hazard overlay (PNG data URI), per-cell probabilities,
classes, eligibility, observed new-event starts and the top model drivers of the highest-hazard
and observed cells, and writes one HTML file that renders the same map/model views as the live
platform. Useful for sharing results where running a server is not possible.

Per-cell arrays are packed as base64 binary (a national 5 km grid has ~1e5 cells): cell
coordinates once, and per day probabilities on a 16-bit log scale (relative precision ~3e-4),
classes, and an eligibility bitmask.
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


P_FLOOR_LOG10 = -9.0


def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def pack_probabilities(p: np.ndarray) -> np.ndarray:
    """uint16 code of log10(p) on [P_FLOOR_LOG10, 0] (decoded in the page)."""
    lg = np.log10(np.clip(np.asarray(p, dtype=float), 10**P_FLOOR_LOG10, 1.0))
    return np.round((lg - P_FLOOR_LOG10) / -P_FLOOR_LOG10 * 65535).astype("<u2")


def unpack_probabilities(q: np.ndarray) -> np.ndarray:
    return np.asarray(10 ** (P_FLOOR_LOG10 * (1 - q.astype(float) / 65535)))


def season_days(cfg: Config, step_days: int, months: tuple[int, int]) -> list[pd.Timestamp]:
    """Every ``step_days`` within the fire-season months of calibration and test years."""
    r = cfg.splits.resolved()
    days = pd.date_range(r.calibration.start, r.test.end)
    days = days[(days.month >= months[0]) & (days.month <= months[1])]
    return [
        d
        for d in days[::step_days]
        if pd.Timestamp(cfg.study.start) <= d <= pd.Timestamp(cfg.study.end)
    ]


def build_payload(
    cfg: Config, days: list[pd.Timestamp], n_drivers: int, n_explained: int = 300
) -> dict[str, Any]:
    paths = RunPaths.from_config(cfg)
    art = RunArtifacts(cfg)
    engine = ForecastEngine(cfg, paths)
    tmp = paths.stage("forecast") / "_export"
    grid = engine.grid
    payload_grid = {
        "id": _b64(grid["cell_id"].to_numpy().astype("<f8")),  # ids exceed int32
        "lat": _b64(np.round(grid["lat"].to_numpy() * 1e4).astype("<i4")),
        "lon": _b64(np.round(grid["lon"].to_numpy() * 1e4).astype("<i4")),
    }
    out_days = []
    for day in days:
        df, info = engine.predict_day(day)
        engine.write_day(day, df, info, tmp)
        stem = f"{day:%Y%m%d}"
        cls_tif = tmp / f"class_{stem}.tif"
        png = overlay_png(cls_tif, tuple(cfg.platform.class_colors), 1024)
        e = df["eligible"].to_numpy()
        observed = [int(o) for o in (art.observed(f"{day:%Y-%m-%d}") or [])]
        # drivers for the highest-hazard eligible cells and every observed new-event cell
        pos_all = np.arange(len(df))
        top = pos_all[e][np.argsort(-df["p"].to_numpy()[e])[:n_explained]]
        obs_pos = pos_all[df["cell_id"].isin(observed).to_numpy() & e]
        explain = np.unique(np.concatenate([top, obs_pos]))
        drivers: dict[str, list[list[Any]]] = {}
        scale = ""
        if len(explain):
            feats = engine.features(day, df["cell_id"].to_numpy()[explain])
            try:
                c = contributions(engine.model, feats)
                for j, i in enumerate(explain):
                    v = c.values.iloc[j]
                    v = v.reindex(v.abs().sort_values(ascending=False).index)[:n_drivers]
                    drivers[str(int(i))] = [[str(k), round(float(x), 3)] for k, x in v.items()]
                scale = c.scale
            except NotImplementedError:
                pass
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
                "observed": observed,
                "p": _b64(pack_probabilities(df["p"].to_numpy())),
                "cls": _b64(df["hazard_class"].to_numpy().astype(np.uint8)),
                "elig": _b64(np.packbits(e.astype(np.uint8), bitorder="little")),
                "drivers": drivers,
                "n_explained": len(top),
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
        "grid": payload_grid,
        "p_floor_log10": P_FLOOR_LOG10,
        "boundary": json.loads(art.boundary_geojson()),
        "cell_size_km": cfg.grid.active_spec.cell_size_m / 1000,
    }


def export_site(
    cfg: Config,
    out_file: Path,
    step_days: int = 10,
    months: tuple[int, int] = (4, 10),
    n_drivers: int = 5,
    extra_days: list[pd.Timestamp] | None = None,
) -> Path:
    """Write the snapshot; ``extra_days`` adds e.g. operational forecast days."""
    days = sorted(set(season_days(cfg, step_days, months)) | set(extra_days or []))
    payload = build_payload(cfg, days, n_drivers)
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
