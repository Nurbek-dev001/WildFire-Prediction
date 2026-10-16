"""Space–time linkage of detections into events and earliest-detection labelling."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree


def link_detections(x_m: np.ndarray, y_m: np.ndarray, t_hours: np.ndarray,
                    spatial_km: float, temporal_h: float, window_days: float = 30.0
                    ) -> np.ndarray:
    """Return an event label per detection (connected components of the linkage graph).

    Two detections are linked when their planar distance is ``<= spatial_km`` AND their
    acquisition times differ by ``<= temporal_h``. Events are the transitive closure
    (single-linkage). Processing uses sliding time windows of ``window_days`` with a
    ``temporal_h`` overlap, which finds every linked pair exactly once or more while keeping
    the KD-trees small; the result is identical to a global computation.
    """
    n = len(t_hours)
    if n == 0:
        return np.zeros(0, dtype=np.int64)
    x_m, y_m, t_hours = (np.asarray(a, dtype=float) for a in (x_m, y_m, t_hours))
    r = spatial_km * 1000.0
    win = window_days * 24.0
    order = np.argsort(t_hours, kind="stable")
    ts = t_hours[order]
    rows: list[np.ndarray] = []
    cols: list[np.ndarray] = []
    start = ts[0]
    while start <= ts[-1]:
        lo = np.searchsorted(ts, start, side="left")
        hi = np.searchsorted(ts, start + win + temporal_h, side="right")
        idx = order[lo:hi]
        if len(idx) > 1:
            tree = cKDTree(np.column_stack([x_m[idx], y_m[idx]]))
            pairs = tree.query_pairs(r, output_type="ndarray")
            if len(pairs):
                a, b = idx[pairs[:, 0]], idx[pairs[:, 1]]
                ok = np.abs(t_hours[a] - t_hours[b]) <= temporal_h
                rows.append(a[ok])
                cols.append(b[ok])
        start += win
    if rows:
        a = np.concatenate(rows)
        b = np.concatenate(cols)
    else:
        a = b = np.zeros(0, dtype=np.int64)
    graph = coo_matrix((np.ones(len(a), dtype=np.int8), (a, b)), shape=(n, n))
    _, labels = connected_components(graph, directed=False)
    return relabel_chronologically(labels, t_hours, x_m, y_m)


def relabel_chronologically(labels: np.ndarray, t: np.ndarray, x: np.ndarray, y: np.ndarray
                            ) -> np.ndarray:
    """Deterministic event ids ordered by (first time, x, y) of each component."""
    df = pd.DataFrame({"lab": labels, "t": t, "x": x, "y": y})
    first = df.sort_values(["t", "x", "y"]).groupby("lab", sort=False).head(1)
    first = first.sort_values(["t", "x", "y"])
    mapping = pd.Series(np.arange(len(first), dtype=np.int64), index=first["lab"].to_numpy())
    return mapping.loc[labels].to_numpy()


def earliest_detection(df: pd.DataFrame, event_col: str = "event_id",
                       tie_break: tuple[str, ...] = ("acq_datetime", "confidence_rank", "-frp",
                                                     "cell_id")) -> pd.DataFrame:
    """One row per event: the earliest detection, ties broken deterministically.

    ``tie_break`` lists columns in priority order; a leading '-' sorts descending.
    """
    cols = [c.lstrip("-") for c in tie_break]
    asc = [not c.startswith("-") for c in tie_break]
    ordered = df.sort_values([event_col, *cols], ascending=[True, *asc], kind="mergesort",
                             na_position="last")
    return ordered.groupby(event_col, sort=True).head(1).reset_index(drop=True)
