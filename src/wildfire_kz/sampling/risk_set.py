"""Stage 4 — the new-event risk set of eligible cell-days.

A cell-day (i, t) is eligible unless cell i had ANY retained detection in the 48 h preceding
the prediction cutoff (00:00 UTC of day t), i.e. a detection time tau with t-48h <= tau < t.
Only past observations are used, so eligibility is known at prediction time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from wildfire_kz.config.schema import Config
from wildfire_kz.utils.io import write_partition
from wildfire_kz.utils.runtime import get_logger, write_json

log = get_logger("risk_set")


def excluded_cell_days(
    det_cell: np.ndarray, det_time: pd.Series | np.ndarray, exclusion_hours: float
) -> pd.DataFrame:
    """Cell-days (cell_id, date) with a detection in [date - H, date)."""
    t = pd.to_datetime(pd.Series(det_time)).reset_index(drop=True)
    cells = pd.Series(np.asarray(det_cell)).reset_index(drop=True)
    keep = cells >= 0
    t, cells = t[keep], cells[keep]
    base = t.dt.floor("D")
    h = pd.Timedelta(hours=exclusion_hours)
    frames = []
    k = 1
    while True:
        day = base + pd.Timedelta(days=k)
        ok = (day > t) & (day - h <= t)
        if not ok.any() and pd.Timedelta(days=k - 1) > h:
            break
        frames.append(pd.DataFrame({"cell_id": cells[ok].to_numpy(), "date": day[ok].to_numpy()}))
        k += 1
    if not frames:
        return pd.DataFrame(
            {"cell_id": np.array([], dtype=np.int64), "date": np.array([], dtype="datetime64[ns]")}
        )
    return pd.concat(frames, ignore_index=True).drop_duplicates().reset_index(drop=True)


def label_gap_days(cfg: Config) -> pd.DatetimeIndex:
    """UTC days whose labels are unknown: satellite-coverage gaps plus the days just after.

    During an archive outage no detection can be made, so those days are not negatives; on
    the days right after it, a fire that started during the gap would look like a new event
    and recent-detection eligibility cannot be established.
    """
    f = cfg.sources.firms.coverage_gaps_file
    if f is None:
        return pd.DatetimeIndex([])
    path = cfg.raw(f)
    if not path.exists():
        raise FileNotFoundError(f"coverage gaps file not found: {path}")
    gaps = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(path)["date"])).normalize()
    after = cfg.risk_set.gap_after_days
    n_after = int(np.ceil(cfg.risk_set.exclusion_hours / 24)) if after is None else after
    days = [g + pd.Timedelta(days=k) for g in gaps for k in range(n_after + 1)]
    return pd.DatetimeIndex(sorted(set(days)))


def build_year_risk_set(
    year: int,
    cell_ids: np.ndarray,
    excluded: pd.DataFrame,
    positives: pd.DataFrame,
    cfg: Config,
    gap_days: pd.DatetimeIndex | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    start = max(pd.Timestamp(year, 1, 1), pd.Timestamp(cfg.study.start))
    end = min(pd.Timestamp(year, 12, 31), pd.Timestamp(cfg.study.end))
    days = pd.date_range(start, end, freq="D")
    rs = pd.DataFrame(
        {
            "cell_id": np.tile(cell_ids, len(days)),
            "date": np.repeat(days.to_numpy(), len(cell_ids)),
        }
    )
    n_all = len(rs)
    ex = excluded[(excluded["date"] >= start) & (excluded["date"] <= end)]
    rs = rs.merge(ex.assign(_ex=True), on=["cell_id", "date"], how="left")
    is_ex = rs["_ex"].fillna(False).astype(bool).to_numpy()
    pos = positives[(positives["date"] >= start) & (positives["date"] <= end)]
    rs = rs.drop(columns="_ex").merge(
        pos[["cell_id", "date", "event_id"]], on=["cell_id", "date"], how="left"
    )
    rs["label"] = rs["event_id"].notna().astype(np.int8)
    in_gap = rs["date"].isin(gap_days).to_numpy() if gap_days is not None else np.zeros(n_all, bool)
    stats = {
        "cell_days_total": n_all,
        "cell_days_excluded_recent_detection": int(is_ex.sum()),
        "positives_total": int(rs["label"].sum()),
        "positives_excluded_recent_detection": int(rs.loc[is_ex, "label"].sum()),
        "days_excluded_coverage_gap": int(rs.loc[in_gap, "date"].nunique()),
        "cell_days_excluded_coverage_gap": int((in_gap & ~is_ex).sum()),
        "positives_excluded_coverage_gap": int(rs.loc[in_gap & ~is_ex, "label"].sum()),
    }
    rs = rs.loc[~is_ex & ~in_gap].reset_index(drop=True)
    rs["event_id"] = rs["event_id"].astype("Int64")
    stats["eligible_cell_days"] = len(rs)
    stats["eligible_positives"] = int(rs["label"].sum())
    return rs, stats


def run_risk_set(cfg: Config, grid_file: Path, events_dir: Path, out_dir: Path) -> dict[str, Any]:
    grid = pd.read_parquet(grid_file, columns=["cell_id"])
    det = pd.read_parquet(events_dir / "detections_qc.parquet", columns=["cell_id", "acq_datetime"])
    positives = pd.read_parquet(events_dir / "positives.parquet")
    excluded = excluded_cell_days(
        det["cell_id"].to_numpy(), det["acq_datetime"], cfg.risk_set.exclusion_hours
    )
    gaps = label_gap_days(cfg)
    if len(gaps):
        log.warning("%d days with unknown labels (coverage gaps + following days)", len(gaps))
    root = out_dir / "risk_set"
    summary: dict[str, Any] = {}
    for year in cfg.study.years:
        rs, stats = build_year_risk_set(
            year, grid["cell_id"].to_numpy(), excluded, positives, cfg, gaps
        )
        write_partition(rs, root, "year", year)
        summary[str(year)] = stats
        log.info("risk set %d: %s", year, stats)
    write_json(out_dir / "risk_set_summary.json", summary)
    return summary
