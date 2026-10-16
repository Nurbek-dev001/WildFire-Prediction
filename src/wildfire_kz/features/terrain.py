"""SRTM terrain: elevation, slope and aspect (sin/cos), derived at native resolution.

The DEM is warped (bilinear) into equal-area working windows at ~native resolution with a
halo, slope and aspect are computed per pixel *before* aggregation, and cell means are taken
afterwards. Aspect is aggregated as the mean of its unit-vector components (circular mean);
pixels flatter than ``flat_slope_threshold_deg`` have undefined aspect and are excluded.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from rasterio.enums import Resampling

from wildfire_kz.config.schema import Config
from wildfire_kz.data.rasters import GridAggregator, raster_catalog
from wildfire_kz.grid.grid import GridMeta


def slope_aspect(z: np.ndarray, res_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Slope (degrees) and aspect (radians clockwise from north, downslope direction).

    Rows increase southward; ``gy`` is the southward derivative.
    """
    gy, gx = np.gradient(z.astype(float), res_m)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    aspect = np.arctan2(-gx, gy)
    return slope, aspect


def terrain_features(cfg: Config, grid: pd.DataFrame, meta: GridMeta) -> pd.DataFrame:
    src = cfg.sources.srtm
    files = [e.path for e in raster_catalog(cfg, src)]
    flat = src.flat_slope_threshold_deg

    def pixel_fn(bands: list[np.ndarray], res: float) -> dict[str, np.ndarray]:
        z = bands[0]
        slope, aspect = slope_aspect(z, res)
        defined = slope >= flat
        return {"elevation_m": z, "slope_deg": slope,
                "aspect_sin": np.where(defined, np.sin(aspect), np.nan),
                "aspect_cos": np.where(defined, np.cos(aspect), np.nan)}

    agg = GridAggregator(grid, meta)
    res = agg.aggregate(files, src.working_resolution_m, src.window_size_km, Resampling.bilinear,
                        pixel_fn=pixel_fn, halo_px=2, src_nodata=src.nodata)
    df = pd.DataFrame({"cell_id": grid["cell_id"].to_numpy()})
    for k in ("elevation_m", "slope_deg", "aspect_sin", "aspect_cos"):
        df[k] = res.get(k, np.full(len(grid), np.nan)).astype(np.float32)
    df["asof_terrain"] = pd.Timestamp(src.reference_date)
    return df
