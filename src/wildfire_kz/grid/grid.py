"""Stage 2 — equal-area analysis grid with stable cell identifiers.

Cells are squares aligned to integer multiples of the cell size in the documented equal-area
CRS, so a cell's identifier depends only on (CRS, cell size, position) — never on the order in
which cells are generated or on the boundary version. A cell is retained when at least
``grid.min_inside_fraction`` of its area lies inside the (projected) boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from rasterio.transform import Affine, from_origin
from shapely.geometry import box

from wildfire_kz.config.schema import Config, GridSpec
from wildfire_kz.utils.runtime import get_logger, read_json, write_json

log = get_logger("grid")

_ID_OFFSET = 1_000_000
_ID_MULT = 10_000_000


def make_cell_id(ix: np.ndarray, iy: np.ndarray) -> np.ndarray:
    """Stable int64 id from absolute CRS indices (ix = x_left/size, iy = y_bottom/size)."""
    return (ix.astype(np.int64) + _ID_OFFSET) * _ID_MULT + (iy.astype(np.int64) + _ID_OFFSET)


def split_cell_id(cell_id: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    cid = np.asarray(cell_id, dtype=np.int64)
    return cid // _ID_MULT - _ID_OFFSET, cid % _ID_MULT - _ID_OFFSET


@dataclass(frozen=True)
class GridMeta:
    crs: str
    crs_name: str
    cell_size_m: float
    xmin: float
    ymax: float
    width: int
    height: int
    n_cells: int
    variant: str

    @property
    def transform(self) -> Affine:
        return from_origin(self.xmin, self.ymax, self.cell_size_m, self.cell_size_m)

    @property
    def cell_area_km2(self) -> float:
        return (self.cell_size_m / 1000.0) ** 2

    def save(self, path: Path) -> None:
        write_json(path, asdict(self))

    @classmethod
    def load(cls, path: Path) -> GridMeta:
        return cls(**read_json(path))


def load_boundary(cfg: Config, buffer_km: float = 0.0) -> gpd.GeoDataFrame:
    """Boundary dissolved to one polygon in the equal-area CRS (optionally buffered)."""
    path = cfg.raw(cfg.sources.boundary.path)
    if not path.exists():
        raise FileNotFoundError(f"boundary file not found: {path}")
    gdf = gpd.read_file(path).to_crs(cfg.crs.proj4)
    geom = shapely.union_all(gdf.geometry.values)
    if buffer_km:
        geom = geom.buffer(buffer_km * 1000.0)
    return gpd.GeoDataFrame(geometry=[geom], crs=cfg.crs.proj4)


def build_grid(cfg: Config, spec: GridSpec, variant: str) -> tuple[gpd.GeoDataFrame, GridMeta]:
    """Construct the grid for one spec (primary 5 km national or 1 km regional sensitivity)."""
    boundary = load_boundary(cfg)
    domain = boundary.geometry.iloc[0]
    if spec.region_bbox_lonlat is not None:
        region = gpd.GeoSeries([box(*spec.region_bbox_lonlat)], crs=cfg.crs.geographic)
        domain = domain.intersection(region.to_crs(cfg.crs.proj4).iloc[0])
        if domain.is_empty:
            raise ValueError("grid region_bbox_lonlat does not intersect the boundary")
    s = float(spec.cell_size_m)
    minx, miny, maxx, maxy = domain.bounds
    ix0, ix1 = int(np.floor(minx / s)), int(np.ceil(maxx / s))
    iy0, iy1 = int(np.floor(miny / s)), int(np.ceil(maxy / s))
    gx, gy = np.meshgrid(np.arange(ix0, ix1), np.arange(iy0, iy1))
    ixs, iys = gx.ravel(), gy.ravel()
    cells = shapely.box(ixs * s, iys * s, (ixs + 1) * s, (iys + 1) * s)
    shapely.prepare(domain)
    candidate = shapely.intersects(domain, cells)
    ixs, iys, cells = ixs[candidate], iys[candidate], cells[candidate]
    inside_area = shapely.area(shapely.intersection(cells, domain))
    frac = inside_area / (s * s)
    keep = frac >= cfg.grid.min_inside_fraction
    ixs, iys, cells, frac = ixs[keep], iys[keep], cells[keep], frac[keep]
    xmin, ymax = ix0 * s, iy1 * s
    meta = GridMeta(
        crs=cfg.crs.proj4,
        crs_name=cfg.crs.name,
        cell_size_m=s,
        xmin=xmin,
        ymax=ymax,
        width=ix1 - ix0,
        height=iy1 - iy0,
        n_cells=int(keep.sum()),
        variant=variant,
    )
    cx, cy = (ixs + 0.5) * s, (iys + 0.5) * s
    lon, lat = Transformer.from_crs(cfg.crs.proj4, cfg.crs.geographic, always_xy=True).transform(
        cx, cy
    )
    gdf = (
        gpd.GeoDataFrame(
            {
                "cell_id": make_cell_id(ixs, iys),
                "ix": ixs.astype(np.int32),
                "iy": iys.astype(np.int32),
                "col": (ixs - ix0).astype(np.int32),
                "row": (iy1 - 1 - iys).astype(np.int32),
                "x": cx,
                "y": cy,
                "lon": lon,
                "lat": lat,
                "inside_fraction": frac.astype(np.float32),
                "area_km2": (frac * s * s / 1e6).astype(np.float32),
            },
            geometry=cells,
            crs=cfg.crs.proj4,
        )
        .sort_values("cell_id")
        .reset_index(drop=True)
    )
    log.info(
        "grid '%s': %d cells of %.0f m (%dx%d raster)",
        variant,
        len(gdf),
        s,
        meta.width,
        meta.height,
    )
    return gdf, meta


def load_grid(grid_file: Path) -> gpd.GeoDataFrame:
    if not grid_file.exists():
        raise FileNotFoundError(f"grid not built yet: {grid_file} (run `wildfire-kz grid`)")
    return gpd.read_parquet(grid_file)


def cell_lookup(grid: pd.DataFrame, meta: GridMeta, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Map projected coordinates to cell_id (-1 where the point is outside the retained grid)."""
    s = meta.cell_size_m
    ix = np.floor(np.asarray(x) / s).astype(np.int64)
    iy = np.floor(np.asarray(y) / s).astype(np.int64)
    cid = make_cell_id(ix, iy)
    valid = np.isin(cid, grid["cell_id"].to_numpy())
    return np.where(valid, cid, -1)


def run_grid(cfg: Config, out_dir: Path) -> dict[str, int]:
    """Build both the active grid (written as grid.parquet) and, for reference, record sizes."""
    spec = cfg.grid.active_spec
    gdf, meta = build_grid(cfg, spec, cfg.grid.active)
    out_dir.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(out_dir / "grid.parquet")
    meta.save(out_dir / "grid_meta.json")
    return {"n_cells": meta.n_cells}
