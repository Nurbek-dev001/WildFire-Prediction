"""Spatial-block cross-validation folds with an exclusion buffer.

Cells are grouped into square blocks of ``block_size_km`` in the equal-area CRS. Block
centroids are clustered (seeded k-means) into ``n_folds`` geographically separated, compact
fold regions, so that every block — and therefore every cell — belongs to exactly one fold.
For held-out fold k, training cells closer than ``buffer_km`` (edge-to-edge distance between
cell squares) to any held-out cell are excluded from training ("buffer" role).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.cluster import KMeans


def assign_blocks(x: np.ndarray, y: np.ndarray, block_km: float) -> np.ndarray:
    b = block_km * 1000.0
    bx = np.floor(np.asarray(x) / b).astype(np.int64)
    by = np.floor(np.asarray(y) / b).astype(np.int64)
    return (bx + 100_000) * 1_000_000 + (by + 100_000)


def assign_folds(cells: pd.DataFrame, block_km: float, n_folds: int, seed: int) -> pd.DataFrame:
    """Return cells with ``block_id`` and ``fold`` (0..n_folds-1)."""
    out = cells[["cell_id", "x", "y"]].copy()
    out["block_id"] = assign_blocks(out["x"], out["y"], block_km)
    blocks = out.groupby("block_id")[["x", "y"]].mean()
    if len(blocks) < n_folds:
        raise ValueError(f"only {len(blocks)} blocks of {block_km} km for {n_folds} folds; "
                         "reduce block size or the number of folds")
    km = KMeans(n_clusters=n_folds, n_init=20, random_state=seed % (2**31))
    lab = km.fit_predict(blocks[["x", "y"]].to_numpy())
    # deterministic fold numbering: west -> east by fold centroid x
    order = np.argsort(km.cluster_centers_[:, 0])
    remap = np.empty(n_folds, dtype=int)
    remap[order] = np.arange(n_folds)
    out["fold"] = out["block_id"].map(pd.Series(remap[lab], index=blocks.index)).astype(int)
    return out


def edge_distance(dx: np.ndarray, dy: np.ndarray, cell_size: float) -> np.ndarray:
    """Edge-to-edge distance between two axis-aligned squares from centroid offsets."""
    ex = np.maximum(np.abs(dx) - cell_size, 0.0)
    ey = np.maximum(np.abs(dy) - cell_size, 0.0)
    return np.hypot(ex, ey)


def fold_roles(folds: pd.DataFrame, buffer_km: float, cell_size_m: float) -> pd.DataFrame:
    """Long table (cell_id, fold, role) with role in {test, train, buffer}."""
    xy = folds[["x", "y"]].to_numpy()
    tree = cKDTree(xy)
    buf = buffer_km * 1000.0
    radius = buf + cell_size_m * np.sqrt(2) + 1.0
    rows = []
    fold_arr = folds["fold"].to_numpy()
    for k in sorted(folds["fold"].unique()):
        test_idx = np.flatnonzero(fold_arr == k)
        role = np.where(fold_arr == k, "test", "train").astype(object)
        near = tree.query_ball_point(xy[test_idx], r=radius)
        cand = np.unique(np.concatenate([np.asarray(n, dtype=int) for n in near])) if len(
            near) else np.array([], int)
        cand = cand[fold_arr[cand] != k]
        if len(cand):
            # exact minimum edge distance to the held-out set
            sub = cKDTree(xy[test_idx])
            nb = sub.query_ball_point(xy[cand], r=radius)
            for c, lst in zip(cand, nb, strict=True):
                if not lst:
                    continue
                d = edge_distance(xy[test_idx][lst, 0] - xy[c, 0],
                                  xy[test_idx][lst, 1] - xy[c, 1], cell_size_m)
                if d.min() < buf:
                    role[c] = "buffer"
        rows.append(pd.DataFrame({"cell_id": folds["cell_id"].to_numpy(), "fold": k,
                                  "role": role}))
    return pd.concat(rows, ignore_index=True)


def min_train_test_distance(folds: pd.DataFrame, roles: pd.DataFrame, cell_size_m: float
                            ) -> dict[int, float]:
    """Diagnostic: minimum edge distance (km) between training and held-out cells per fold."""
    xy = folds.set_index("cell_id")[["x", "y"]]
    out = {}
    for k, g in roles.groupby("fold"):
        test = xy.loc[g.loc[g["role"] == "test", "cell_id"]].to_numpy()
        train = xy.loc[g.loc[g["role"] == "train", "cell_id"]].to_numpy()
        if len(test) == 0 or len(train) == 0:
            out[int(k)] = float("nan")
            continue
        d, idx = cKDTree(test).query(train, k=min(8, len(test)))
        d = np.atleast_2d(d.T).T if d.ndim == 1 else d
        idx = idx.reshape(len(train), -1)
        dx = test[idx, 0] - train[:, [0]]
        dy = test[idx, 1] - train[:, [1]]
        out[int(k)] = float(edge_distance(dx, dy, cell_size_m).min() / 1000.0)
    return out
