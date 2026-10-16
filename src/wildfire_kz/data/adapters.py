"""Explicit local source adapters with no retrieval or contemporary-road substitution."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely import STRtree


def firms_csv(path: Path, grid: gpd.GeoDataFrame, *, standard_processed: bool) -> pd.DataFrame:
    """Normalize a declared archived standard Suomi-NPP VIIRS CSV and clip to cells."""
    if not standard_processed:
        raise ValueError("NRT detections cannot be substituted for standard-processed labels")
    raw = pd.read_csv(path, dtype={"acq_time": str, "confidence": str})
    required = {"latitude", "longitude", "acq_date", "acq_time", "confidence", "satellite"}
    if missing := required - set(raw.columns):
        raise ValueError(f"FIRMS CSV missing: {sorted(missing)}")
    if not raw.satellite.astype(str).isin(["N", "Suomi-NPP"]).all():
        raise ValueError("Only Suomi-NPP is permitted")
    if "instrument" in raw and not raw.instrument.eq("VIIRS").all():
        raise ValueError("Only VIIRS labels are permitted")
    if not raw.confidence.isin(["n", "h", "l"]).all():
        raise ValueError("VIIRS confidence must be categorical n/h/l")
    raw["timestamp"] = pd.to_datetime(
        raw.acq_date.astype(str)
        + "T"
        + raw.acq_time.str.zfill(4).str[:2]
        + ":"
        + raw.acq_time.str.zfill(4).str[2:]
        + ":00Z",
        utc=True,
    )
    transform = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    raw["x"], raw["y_coord"] = transform.transform(
        raw.longitude.to_numpy(), raw.latitude.to_numpy()
    )
    points = gpd.GeoDataFrame(raw, geometry=gpd.points_from_xy(raw.x, raw.y_coord), crs=grid.crs)
    joined = gpd.sjoin(points, grid[["cell_id", "geometry"]], predicate="intersects")
    # A point on a shared boundary is assigned once, deterministically.
    joined = joined.reset_index().sort_values("cell_id").drop_duplicates("index")
    result = pd.DataFrame(
        joined[["cell_id", "timestamp", "x", "y_coord", "confidence", "satellite"]]
    )
    result["year"] = result.timestamp.dt.year
    return result


def historical_proximity(
    grid: gpd.GeoDataFrame, snapshot: gpd.GeoDataFrame, available_at: pd.Timestamp, field: str
) -> pd.DataFrame:
    """Compute cell-center proximity to an explicitly dated roads/settlement snapshot."""
    if field not in ["road_distance", "settlement_distance"]:
        raise ValueError("Unsupported proximity field")
    if pd.isna(available_at) or available_at.tzinfo is None:
        raise ValueError("A timezone-aware historical availability timestamp is required")
    source = snapshot.to_crs(grid.crs)
    if source.empty:
        raise ValueError("Historical snapshot is empty; omit the variable explicitly")
    centers = grid.geometry.centroid.to_numpy()
    _, distances = STRtree(source.geometry.to_numpy()).query_nearest(
        centers, return_distance=True, all_matches=False
    )
    return pd.DataFrame(
        {
            "cell_id": grid.cell_id,
            field: np.asarray(distances),
            "available_at": available_at,
            "year": available_at.year,
        }
    )
