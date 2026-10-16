"""Optional past fire-activity predictor built strictly from detections before day t."""

from __future__ import annotations

import numpy as np
import pandas as pd


def fire_history_counts(
    det_cell: np.ndarray,
    det_time: np.ndarray,
    row_cell: np.ndarray,
    row_date: np.ndarray,
    window_days: int,
) -> np.ndarray:
    """Distinct detection days per row cell in the window [t - W days, t) (t excluded).

    Detections at or after the target day — including later detections of the very event
    that defines a positive label — can never influence the result.
    """
    det = pd.DataFrame(
        {"cell": np.asarray(det_cell), "day": pd.to_datetime(det_time).floor("D")}
    ).drop_duplicates()
    det = det[det["cell"] >= 0].sort_values(["cell", "day"])
    by_cell: dict[object, np.ndarray] = {
        c: g["day"].to_numpy(dtype="datetime64[D]") for c, g in det.groupby("cell")
    }
    t = np.asarray(row_date, dtype="datetime64[D]")
    counts = np.zeros(len(t), dtype=np.float32)
    rows = pd.Series(np.asarray(row_cell))
    for c, idx in rows.groupby(rows).indices.items():
        arr = by_cell.get(c)
        if arr is None:
            continue
        hi = np.searchsorted(arr, t[idx], side="left")  # strictly before t
        lo = np.searchsorted(arr, t[idx] - np.timedelta64(window_days, "D"), side="left")
        counts[idx] = hi - lo
    return counts
