"""Direct cell rasterization with continuous probability and fixed calibration classes."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin


def export_daily(
    grid: gpd.GeoDataFrame,
    predictions: pd.DataFrame,
    destination: Path,
    resolution_m: int,
    boundaries: list[float],
    metadata: dict[str, str],
) -> None:
    """Write two-band QGIS-ready rasters. Ineligible/unobserved cells remain nodata."""
    destination.mkdir(parents=True, exist_ok=True)
    xmin, ymin, xmax, ymax = grid.total_bounds
    xmin, ymax = (
        np.floor(xmin / resolution_m) * resolution_m,
        np.ceil(ymax / resolution_m) * resolution_m,
    )
    transform = from_origin(xmin, ymax, resolution_m, resolution_m)
    width, height = (
        int(np.ceil((xmax - xmin) / resolution_m)),
        int(np.ceil((ymax - ymin) / resolution_m)),
    )
    for day, daily in predictions.groupby("day"):
        merged = grid.merge(daily[["cell_id", "probability"]], on="cell_id", how="inner")
        path = destination / f"probability_{day:%Y-%m-%d}.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=2,
            dtype="float32",
            crs=grid.crs,
            transform=transform,
            nodata=-9999,
            compress="deflate",
            tiled=True,
        ) as dst:
            # Rasterization in tiles bounds memory even for the 1km sensitivity grid.
            for _, window in dst.block_windows(1):
                local_transform = rasterio.windows.transform(window, transform)
                shapes = [
                    (geom, float(prob))
                    for geom, prob in zip(merged.geometry, merged.probability, strict=True)
                ]
                values = rasterize(
                    shapes,
                    out_shape=(int(window.height), int(window.width)),
                    transform=local_transform,
                    fill=-9999,
                    dtype="float32",
                )
                classes = np.where(
                    values == -9999, -9999, np.digitize(values, boundaries).astype("float32") + 1
                )
                dst.write(values, 1, window=window)
                dst.write(classes, 2, window=window)
            dst.set_band_description(1, "calibrated next-day new-event probability")
            dst.set_band_description(2, "class fixed on calibration data")
            dst.update_tags(
                **metadata,
                target_day=str(day),
                boundaries=str(boundaries),
                interpretation="occurrence hazard; predictive association; no damage/exposure model",
            )
