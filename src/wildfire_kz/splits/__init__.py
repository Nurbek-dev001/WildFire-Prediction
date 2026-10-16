"""Rolling origin and contiguous spatial folds with polygon-distance buffers."""

from collections.abc import Iterator

import numpy as np
import pandas as pd
from shapely.geometry import box
from shapely.ops import unary_union


def rolling_folds(
    frame: pd.DataFrame, validation_years: list[int]
) -> Iterator[tuple[str, np.ndarray, np.ndarray]]:
    """Never train on a year at or beyond its validation year."""
    years = pd.to_datetime(frame.day).dt.year.to_numpy()
    for year in validation_years:
        yield f"temporal_{year}", np.flatnonzero(years < year), np.flatnonzero(years == year)


def spatial_folds(
    frame: pd.DataFrame, block_m: int, n_folds: int, buffer_m: int
) -> Iterator[tuple[str, np.ndarray, np.ndarray]]:
    """Group whole 100km blocks into contiguous west/east geographic bands.

    Buffer distance is to full held-out block polygons, not their centroids.
    Fold assignment uses coordinates alone, never outcomes or test geography.
    """
    cells = frame[["cell_id", "x", "y_coord"]].drop_duplicates("cell_id").copy()
    cells["bx"] = np.floor(cells.x / block_m).astype(int)
    cells["by"] = np.floor(cells.y_coord / block_m).astype(int)
    blocks = cells[["bx", "by"]].drop_duplicates().sort_values(["bx", "by"])
    if len(blocks) < n_folds:
        raise ValueError("Too few development blocks for requested spatial folds")
    for fold, indices in enumerate(np.array_split(np.arange(len(blocks)), n_folds)):
        chosen = blocks.iloc[indices]
        held = unary_union(
            [
                box(
                    int(bx) * block_m,
                    int(by) * block_m,
                    (int(bx) + 1) * block_m,
                    (int(by) + 1) * block_m,
                )
                for bx, by in chosen.to_numpy(dtype=int)
            ]
        )
        chosen_keys = set(map(tuple, chosen.to_numpy()))
        valid_cells = set(
            cells.loc[[tuple(r) in chosen_keys for r in cells[["bx", "by"]].to_numpy()], "cell_id"]
        )
        # Cell footprints are 5km in primary runs; exact geometries are supplied via cell_wkt.
        if "cell_wkt" not in frame:
            raise ValueError("cell_wkt is required for exact boundary-to-boundary buffer checks")
        from shapely import from_wkt

        geometries = frame.drop_duplicates("cell_id").set_index("cell_id").cell_wkt.map(from_wkt)
        training_cells = {
            cell
            for cell, geom in geometries.items()
            if cell not in valid_cells and geom.distance(held) >= buffer_m
        }
        train = np.flatnonzero(frame.cell_id.isin(training_cells))
        valid = np.flatnonzero(frame.cell_id.isin(valid_cells))
        if not len(train) or not len(valid):
            raise ValueError(f"Empty spatial fold {fold} after exclusion buffer")
        yield f"spatial_{block_m}_{fold}", train, valid
