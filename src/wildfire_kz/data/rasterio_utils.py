"""Small rasterio helpers shared by the synthetic generator and the aggregation engine."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine


def write_geotiff(
    path: Path,
    bands: np.ndarray,
    transform: Affine,
    crs: str,
    nodata: float | int | None = None,
    tags: dict[str, str] | None = None,
    band_descriptions: list[str] | None = None,
) -> None:
    """Write a (bands, rows, cols) or (rows, cols) array as a compressed GeoTIFF."""
    arr = bands if bands.ndim == 3 else bands[np.newaxis]
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": arr.shape[1],
        "width": arr.shape[2],
        "count": arr.shape[0],
        "dtype": arr.dtype.name,
        "crs": crs,
        "transform": transform,
        "compress": "deflate",
        "tiled": arr.shape[1] >= 256 and arr.shape[2] >= 256,
    }
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr)
        if tags:
            dst.update_tags(**tags)
        if band_descriptions:
            for i, desc in enumerate(band_descriptions, start=1):
                dst.set_band_description(i, desc)


def geographic_pixel_area_km2(lat_centers: np.ndarray, res_deg: float) -> np.ndarray:
    """Area (km²) of a res×res degree pixel centred on each latitude (spherical approx)."""
    r = 6371.0072
    lat1 = np.deg2rad(lat_centers - res_deg / 2)
    lat2 = np.deg2rad(lat_centers + res_deg / 2)
    return r * r * np.deg2rad(res_deg) * np.abs(np.sin(lat2) - np.sin(lat1))
