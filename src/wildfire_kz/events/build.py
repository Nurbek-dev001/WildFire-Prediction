"""Stage 3 — events: QC'd detections -> industrial screening -> linked events -> positives.

Positive cell-days are defined ONLY by the earliest detection of each connected event. Later
detections of an event are retained (with their event id) for grouping and description but
are never used to construct predictors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pyproj import Transformer

from wildfire_kz.config.schema import Config
from wildfire_kz.data.manifest import enumerate_sources
from wildfire_kz.data.rasters import raster_catalog, sample_points
from wildfire_kz.events.firms import QCCounts, deduplicate, read_firms
from wildfire_kz.events.linking import earliest_detection, link_detections
from wildfire_kz.grid.grid import GridMeta, cell_lookup, load_boundary, load_grid
from wildfire_kz.utils.runtime import get_logger, write_json

log = get_logger("events")


def project_and_clip(df: pd.DataFrame, cfg: Config, qc: QCCounts) -> pd.DataFrame:
    """Project to the equal-area CRS and keep detections inside boundary + border buffer."""
    tr = Transformer.from_crs(cfg.crs.geographic, cfg.crs.proj4, always_xy=True)
    x, y = tr.transform(df["longitude"].to_numpy(), df["latitude"].to_numpy())
    df = df.assign(x=x, y=y)
    import shapely

    buffered = load_boundary(cfg, buffer_km=cfg.sources.boundary.border_buffer_km).geometry.iloc[0]
    shapely.prepare(buffered)
    inside = shapely.contains_xy(buffered, df["x"].to_numpy(), df["y"].to_numpy())
    qc.add("dropped_outside_buffered_boundary", int((~inside).sum()))
    return df.loc[inside].reset_index(drop=True)


def build_industrial_mask(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Persistent non-vegetated hotspot mask from DEVELOPMENT-PERIOD evidence only.

    A screening pixel is masked when, within the development years, it has detections on at
    least ``min_detection_days`` distinct days in at least ``min_years`` distinct years AND
    (its mean non-vegetated land-cover fraction over development-year MCD12Q1 maps is at least
    ``min_non_vegetated_fraction`` OR, if enabled, FIRMS flags it as a static land source).
    """
    mcfg = cfg.events.industrial_mask
    dev_years = set(cfg.splits.development_years)
    dev = df[df["acq_datetime"].dt.year.isin(dev_years)]
    res = mcfg.screening_resolution_m
    px = np.floor(dev["x"] / res).astype(np.int64)
    py = np.floor(dev["y"] / res).astype(np.int64)
    stats = pd.DataFrame({
        "px": px, "py": py, "day": dev["acq_datetime"].dt.normalize(),
        "year": dev["acq_datetime"].dt.year, "static": dev["type"] == 2,
    }).groupby(["px", "py"]).agg(n_days=("day", "nunique"), n_years=("year", "nunique"),
                                 static_share=("static", "mean")).reset_index()
    cand = stats[(stats["n_days"] >= mcfg.min_detection_days)
                 & (stats["n_years"] >= mcfg.min_years)].copy()
    if cand.empty:
        cand["non_veg_fraction"] = []
        cand["masked"] = []
        return cand
    # non-vegetated share from development-year land-cover maps (5x5 sub-samples per pixel)
    lc_entries = [e for e in raster_catalog(cfg, cfg.sources.mcd12q1) if e.year in dev_years]
    offs = (np.arange(5) + 0.5) / 5
    sx = (cand["px"].to_numpy()[:, None, None] + offs[None, :, None]) * res
    sy = (cand["py"].to_numpy()[:, None, None] + offs[None, None, :]) * res
    sx, sy = np.broadcast_arrays(sx, sy)
    lon, lat = Transformer.from_crs(cfg.crs.proj4, cfg.crs.geographic,
                                    always_xy=True).transform(sx.ravel(), sy.ravel())
    nonveg = np.zeros(len(cand))
    for e in lc_entries:
        vals = sample_points(e.path, lon, lat).reshape(len(cand), -1)
        nonveg += np.isin(vals, cfg.sources.mcd12q1.non_vegetated_classes).mean(axis=1)
    cand["non_veg_fraction"] = nonveg / max(len(lc_entries), 1)
    masked = cand["non_veg_fraction"] >= mcfg.min_non_vegetated_fraction
    if mcfg.use_static_type_flag:
        masked |= cand["static_share"] >= 0.5
    cand["masked"] = masked
    cand["mask_years"] = ",".join(map(str, sorted(dev_years)))
    return cand.reset_index(drop=True)


def apply_vegetation_screens(df: pd.DataFrame, mask: pd.DataFrame, cfg: Config,
                             qc: QCCounts) -> pd.DataFrame:
    res = cfg.events.industrial_mask.screening_resolution_m
    keys = set(zip(mask.loc[mask["masked"], "px"], mask.loc[mask["masked"], "py"], strict=True))
    px = np.floor(df["x"] / res).astype(np.int64).to_numpy()
    py = np.floor(df["y"] / res).astype(np.int64).to_numpy()
    in_mask = np.fromiter(((a, b) in keys for a, b in zip(px, py, strict=True)), bool, len(df))
    qc.add("dropped_industrial_mask", int(in_mask.sum()))
    veg_types = cfg.sources.firms.vegetation_type_values
    non_veg = (df["type"] >= 0) & ~df["type"].isin(veg_types)
    qc.add("dropped_non_vegetation_type", int((non_veg & ~in_mask).sum()))
    return df.loc[~in_mask & ~non_veg].reset_index(drop=True)


def link_and_label(df: pd.DataFrame, grid: pd.DataFrame, meta: GridMeta, cfg: Config,
                   spatial_km: float, temporal_h: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach event ids; return (detections, events) where events carry the earliest detection."""
    t0 = pd.Timestamp(cfg.study.start) - pd.Timedelta(days=cfg.study.lookback_days)
    t_hours = ((df["acq_datetime"] - t0) / pd.Timedelta(hours=1)).to_numpy()
    df = df.assign(event_id=link_detections(df["x"].to_numpy(), df["y"].to_numpy(), t_hours,
                                            spatial_km, temporal_h,
                                            cfg.events.linking_window_days))
    first = earliest_detection(df, tie_break=tuple(cfg.events.tie_break))
    agg = df.groupby("event_id").agg(n_detections=("acq_datetime", "size"),
                                     last_detection=("acq_datetime", "max"))
    events = first.set_index("event_id")[["acq_datetime", "x", "y", "cell_id", "confidence",
                                          "frp"]].rename(columns={
        "acq_datetime": "first_detection", "x": "first_x", "y": "first_y",
        "cell_id": "first_cell_id"}).join(agg).reset_index()
    events["first_date"] = events["first_detection"].dt.normalize()
    events["first_in_grid"] = events["first_cell_id"] >= 0
    return df, events


def positives_from_events(events: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """One positive cell-day per event (earliest detection inside the grid & study period)."""
    start, end = pd.Timestamp(cfg.study.start), pd.Timestamp(cfg.study.end)
    ok = events["first_in_grid"] & events["first_date"].between(start, end)
    pos = events.loc[ok, ["first_cell_id", "first_date", "event_id"]].rename(
        columns={"first_cell_id": "cell_id", "first_date": "date"})
    # several events can start in the same cell on the same day -> one positive cell-day
    pos = pos.groupby(["cell_id", "date"], as_index=False).agg(
        event_id=("event_id", "min"), n_events=("event_id", "size"))
    return pos.sort_values(["date", "cell_id"]).reset_index(drop=True)


def run_events(cfg: Config, grid_file: Path, grid_meta_file: Path, out_dir: Path
               ) -> dict[str, Any]:
    grid = load_grid(grid_file)
    meta = GridMeta.load(grid_meta_file)
    qc = QCCounts()
    firms_files = next(s.files for s in enumerate_sources(cfg) if s.name == "firms")
    df = read_firms(firms_files, cfg.sources.firms, qc)
    t0 = pd.Timestamp(cfg.study.start) - pd.Timedelta(days=cfg.study.lookback_days)
    t1 = pd.Timestamp(cfg.study.end) + pd.Timedelta(days=1)
    in_period = (df["acq_datetime"] >= t0) & (df["acq_datetime"] < t1)
    qc.add("dropped_outside_study_period", int((~in_period).sum()))
    df = deduplicate(df.loc[in_period], cfg.events.dedupe_decimals, qc)
    df = project_and_clip(df, cfg, qc)
    mask = build_industrial_mask(df, cfg)
    df = apply_vegetation_screens(df, mask, cfg, qc)
    df["cell_id"] = cell_lookup(grid, meta, df["x"].to_numpy(), df["y"].to_numpy())
    df, events = link_and_label(df, grid, meta, cfg, cfg.events.spatial_link_km,
                                cfg.events.temporal_link_h)
    positives = positives_from_events(events, cfg)
    qc.add("events_total", len(events))
    qc.add("events_first_detection_outside_grid", int((~events["first_in_grid"]).sum()))
    qc.add("positive_cell_days", len(positives))

    out_dir.mkdir(parents=True, exist_ok=True)
    keep_cols = ["acq_datetime", "latitude", "longitude", "x", "y", "cell_id", "confidence",
                 "confidence_rank", "frp", "type", "event_id"]
    df[keep_cols].to_parquet(out_dir / "detections_qc.parquet", index=False)
    events.to_parquet(out_dir / "events.parquet", index=False)
    positives.to_parquet(out_dir / "positives.parquet", index=False)
    mask.to_parquet(out_dir / "industrial_mask.parquet", index=False)
    write_json(out_dir / "qc_counts.json", qc.counts)
    log.info("events: %s", qc.counts)
    if cfg.events.sensitivity.run:
        run_event_sensitivity(cfg, out_dir, grid_file, grid_meta_file)
    return qc.counts


def run_event_sensitivity(cfg: Config, out_dir: Path, grid_file: Path, grid_meta_file: Path
                          ) -> pd.DataFrame:
    """Event/positive counts for every spatial x temporal linkage setting (1–5 km x 24–72 h)."""
    grid = load_grid(grid_file)
    meta = GridMeta.load(grid_meta_file)
    det = pd.read_parquet(out_dir / "detections_qc.parquet").drop(columns="event_id")
    rows = []
    for skm in cfg.events.sensitivity.spatial_km:
        for th in cfg.events.sensitivity.temporal_h:
            _, ev = link_and_label(det, grid, meta, cfg, skm, th)
            pos = positives_from_events(ev, cfg)
            rows.append({"spatial_km": skm, "temporal_h": th, "n_events": len(ev),
                         "n_positive_cell_days": len(pos),
                         "median_detections_per_event": float(ev["n_detections"].median()),
                         "is_primary": (skm == cfg.events.spatial_link_km
                                        and th == cfg.events.temporal_link_h)})
    table = pd.DataFrame(rows)
    table.to_csv(out_dir / "event_linkage_sensitivity.csv", index=False)
    return table
