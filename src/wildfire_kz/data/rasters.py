"""Bounded-memory local raster tools; GEE may export the same input contracts."""

from collections.abc import Iterator
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from numpy.typing import NDArray
from pyproj import Transformer
from rasterio.warp import transform_bounds
from rasterio.windows import Window
from shapely import area, intersection, polygons, transform


def open_hourly(paths: list[Path], chunk_hours: int = 168) -> xr.Dataset:
    """Open NetCDF lazily; callers subset cells/time before computing."""
    return xr.open_mfdataset(
        [str(p) for p in paths], chunks={"time": chunk_hours}, combine="by_coords"
    )


def raster_chunks(path: Path, size: int = 512) -> Iterator[tuple[Window, NDArray]]:
    """Read masked chunks; no full-raster materialization."""
    with rasterio.open(path) as src:
        for row in range(0, src.height, size):
            for col in range(0, src.width, size):
                window = Window(col, row, min(size, src.width - col), min(size, src.height - row))
                yield window, src.read(1, window=window, masked=True)


def native_terrain(dem: NDArray, dx_m: float, dy_m: float) -> dict[str, NDArray]:
    """Derive terrain BEFORE cell aggregation, using native pixel spacing in metres.

    Supply a one-pixel halo for chunk seams. For geographic SRTM, compute geodesic
    pixel spacing per latitude strip; never treat degrees as metres.
    """
    if dx_m <= 0 or dy_m <= 0:
        raise ValueError("Native pixel spacing must be positive metres")
    north, east = np.gradient(np.asarray(dem, dtype=float), dy_m, dx_m)
    aspect = np.arctan2(-east, north)
    return {
        "elevation": dem,
        "slope": np.degrees(np.arctan(np.hypot(north, east))),
        "aspect_sin": np.sin(aspect),
        "aspect_cos": np.cos(aspect),
    }


def zonal_raster(
    path: Path,
    grid: gpd.GeoDataFrame,
    *,
    terrain: bool = False,
    categories: dict[str, list[int]] | None = None,
) -> pd.DataFrame:
    """Exact equal-area pixel-overlap means/fractions with bounded per-cell windows.

    Terrain gradients use a native one-pixel halo before aggregation. Geographic
    rasters use per-row geodesic pixel lengths. Categorical fractions normalize
    by valid observed area and retain a coverage fraction for quality auditing.
    This favors explicit geometry over approximate center-point counting.
    """
    records = []
    with rasterio.open(path) as src:
        if src.crs is None:
            raise ValueError("Raster CRS is required")
        if src.transform.b or src.transform.d:
            raise ValueError("Rotated native rasters require explicit preprocessing")
        to_equal_area = Transformer.from_crs(src.crs, grid.crs, always_xy=True)
        for cell in grid.itertuples():
            native_bounds = transform_bounds(
                grid.crs, src.crs, *cell.geometry.bounds, densify_pts=21
            )
            window = src.window(*native_bounds).round_offsets().round_lengths()
            window = Window(
                max(0, int(window.col_off) - 1),
                max(0, int(window.row_off) - 1),
                int(window.width) + 2,
                int(window.height) + 2,
            )
            window = window.intersection(Window(0, 0, src.width, src.height))
            values = src.read(1, window=window, masked=True).astype(float).filled(np.nan)
            affine = src.window_transform(window)
            rows, cols = np.indices(values.shape)
            vertices = np.empty((values.size, 4, 2), dtype=float)
            for corner, (dc, dr) in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
                vertices[:, corner, 0] = affine.c + (cols.ravel() + dc) * affine.a
                vertices[:, corner, 1] = affine.f + (rows.ravel() + dr) * affine.e
            footprint = transform(polygons(vertices), to_equal_area.transform, interleaved=False)
            weights = area(intersection(footprint, cell.geometry)).reshape(values.shape)
            channels: dict[str, NDArray] = {"value": values}
            if categories is not None:
                channels = {
                    name: np.where(
                        np.isfinite(values), np.isin(values, codes).astype(float), np.nan
                    )
                    for name, codes in categories.items()
                }
            if terrain:
                if src.crs.is_geographic:
                    lat = affine.f + (np.arange(values.shape[0]) + 0.5) * affine.e
                    lon = np.full_like(lat, affine.c + 0.5 * affine.a)
                    geod = src.crs.to_dict()
                    from pyproj import CRS

                    ellipsoid = CRS.from_user_input(geod).get_geod()
                    if ellipsoid is None:
                        raise ValueError("Geographic source requires a valid geodesic ellipsoid")
                    _, _, dx = ellipsoid.inv(lon, lat, lon + affine.a, lat)
                    _, _, dy = ellipsoid.inv(lon, lat, lon, lat + affine.e)
                    down, east = np.gradient(values)
                    down, east = down / np.abs(dy[:, None]), east / np.abs(dx[:, None])
                    aspect = np.arctan2(-east, down)
                    channels = {
                        "elevation": values,
                        "slope": np.degrees(np.arctan(np.hypot(down, east))),
                        "aspect_sin": np.sin(aspect),
                        "aspect_cos": np.cos(aspect),
                    }
                else:
                    channels = native_terrain(values, abs(affine.a), abs(affine.e))
            record = {"cell_id": cell.cell_id}
            for name, channel in channels.items():
                valid = np.isfinite(channel) & (weights > 0)
                denominator = float(weights[valid].sum())
                record[name] = (
                    float(np.average(channel[valid], weights=weights[valid]))
                    if denominator
                    else np.nan
                )
                record[f"{name}_coverage"] = denominator / cell.geometry.area
            records.append(record)
    return pd.DataFrame(records)
