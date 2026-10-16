from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from wildfire_kz.config import Config
from wildfire_kz.data.rasters import native_terrain, zonal_raster


def test_native_terrain_direction_and_slope():
    values = np.tile(np.arange(4, dtype=float), (4, 1))
    terrain = native_terrain(values, 1, 1)
    np.testing.assert_allclose(terrain["slope"], 45)
    np.testing.assert_allclose(terrain["aspect_sin"], -1)  # downslope west
    np.testing.assert_allclose(terrain["aspect_cos"], 0, atol=1e-12)
    with pytest.raises(ValueError):
        native_terrain(values, 0, 1)


def test_exact_overlap_categorical_fractions(tmp_path: Path):
    crs = Config().grid.crs
    path = tmp_path / "cover.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint8",
        crs=crs,
        transform=from_origin(0, 20, 5, 5),
    ) as dst:
        dst.write(np.array([[1, 1, 2, 2]] * 4, dtype="uint8"), 1)
    grid = gpd.GeoDataFrame({"cell_id": ["a"]}, geometry=[box(2.5, 0, 12.5, 20)], crs=crs)
    result = zonal_raster(path, grid, categories={"forest": [1], "grassland": [2]})
    assert result.iloc[0].forest == pytest.approx(0.75)
    assert result.iloc[0].grassland == pytest.approx(0.25)
    assert result.iloc[0].forest_coverage == pytest.approx(1)
