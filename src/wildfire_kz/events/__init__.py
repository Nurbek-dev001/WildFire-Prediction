"""Past-only eligibility and connected-component VIIRS event labels."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree


def link_events(
    detections: pd.DataFrame, radius_m: float = 2000, window_hours: float = 48
) -> pd.DataFrame:
    """Link detections transitively in projected space and UTC time.

    Only Suomi-NPP standard-processed nominal/high detections are allowed by the
    source contract. Confidence is categorical, never a MODIS percentage.
    """
    data = detections[detections.confidence.isin(["n", "h"])].copy()
    if "satellite" in data and not data.satellite.isin(["N", "Suomi-NPP"]).all():
        raise ValueError("Labels must be Suomi-NPP VIIRS only")
    data["timestamp"] = pd.to_datetime(data.timestamp, utc=True)
    data = (
        data.drop_duplicates(["timestamp", "x", "y_coord"])
        .sort_values(["timestamp", "x", "y_coord", "cell_id"])
        .reset_index(drop=True)
    )
    parent = list(range(len(data)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # A time-window tree bounds candidate searches; no national all-pairs matrix.
    seconds = data.timestamp.dt.as_unit("ns").astype("int64").to_numpy() / 1e9
    coords = data[["x", "y_coord"]].to_numpy()
    for start in range(0, len(data), 5000):
        stop = min(start + 5000, len(data))
        left = int(np.searchsorted(seconds, seconds[start] - window_hours * 3600))
        tree = cKDTree(coords[left:stop])
        for i in range(start, stop):
            for relative in tree.query_ball_point(coords[i], radius_m):
                j = relative + left
                if j < i and seconds[i] - seconds[j] <= window_hours * 3600:
                    a, b = find(i), find(j)
                    parent[max(a, b)] = min(a, b)
    roots = [find(i) for i in range(len(data))]
    keys = {
        r: hashlib.sha256(
            f"{data.iloc[r].timestamp}|{data.iloc[r].x}|{data.iloc[r].y_coord}".encode()
        ).hexdigest()[:20]
        for r in set(roots)
    }
    data["event_id"] = [keys[r] for r in roots]
    data["is_first"] = ~data.event_id.duplicated()
    data["day"] = data.timestamp.dt.floor("D")
    return data


def persistent_hotspots(
    detections: pd.DataFrame, nonvegetated: pd.Series, development_end: int, minimum_days: int
) -> set[str]:
    """Freeze industrial exclusions using development detections and a prior mask."""
    dev = detections[
        pd.to_datetime(detections.timestamp, utc=True).dt.year <= development_end
    ].copy()
    dev["day"] = pd.to_datetime(dev.timestamp, utc=True).dt.floor("D")
    counts = dev.groupby("cell_id").day.nunique()
    return set(
        counts[(counts >= minimum_days) & nonvegetated.reindex(counts.index).fillna(False)].index
    )


def risk_set(
    cells: pd.DataFrame,
    detections: pd.DataFrame,
    days: pd.DatetimeIndex,
    exclusion_hours: float = 48,
) -> pd.DataFrame:
    """Construct eligible cell-days; no current/future detection affects eligibility."""
    result = []
    delta = pd.Timedelta(hours=exclusion_hours).value
    for cell in cells.cell_id:
        history = detections.loc[detections.cell_id == cell].sort_values("timestamp")
        ts = pd.to_datetime(history.timestamp, utc=True).dt.as_unit("ns").astype("int64").to_numpy()
        targets = days.as_unit("ns").astype("int64").to_numpy()
        previous = np.searchsorted(ts, targets, side="left") - 1
        valid = previous >= 0
        excluded = np.zeros(len(days), dtype=bool)
        excluded[valid] = ts[previous[valid]] >= targets[valid] - delta
        first = history[history.is_first].day.unique()
        result.append(
            pd.DataFrame(
                {
                    "cell_id": cell,
                    "day": days,
                    "label": days.isin(first).astype(int),
                    "eligible": ~excluded,
                }
            )
        )
    return pd.concat(result, ignore_index=True)
