"""Raster catalogs and the chunked raster-to-grid aggregation engine.

Large national rasters (SRTM 30 m, WorldPop 100 m, MODIS 1 km) never need to fit in memory:
the grid extent is processed in square windows (``window_size_km``). For every window, each
overlapping source file is warped into an equal-area *working raster* at roughly native
resolution (mosaicking tiles and including a halo so derivatives such as slope have no
seams), an optional per-pixel transform is applied (e.g. slope at native resolution), and
results are accumulated per grid cell with ``np.bincount`` (area-weighted means, because
working pixels are equal-area). Categorical layers are summarised as class-area fractions.

This is the local backend; the optional GEE backend only *exports* files that are then read
by exactly this code, so the two are swappable.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds

from wildfire_kz.config.schema import Config, RasterCatalogSource
from wildfire_kz.grid.grid import GridMeta
from wildfire_kz.utils.runtime import get_logger

log = get_logger("rasters")


@dataclass(frozen=True)
class CatalogEntry:
    path: Path
    year: int | None
    doy: int | None

    @property
    def start_date(self) -> dt.date | None:
        if self.year is None:
            return None
        return dt.date(self.year, 1, 1) + dt.timedelta(days=(self.doy or 1) - 1)


def raster_catalog(cfg: Config, src: RasterCatalogSource) -> list[CatalogEntry]:
    root = cfg.raw(src.path)
    rx = re.compile(src.filename_regex)
    out = []
    for p in sorted(root.glob(src.glob)):
        m = rx.search(p.name)
        if not m:
            continue
        gd = m.groupdict()
        out.append(CatalogEntry(path=p, year=int(gd["year"]) if "year" in gd else None,
                                doy=int(gd["doy"]) if "doy" in gd else None))
    if not out:
        raise FileNotFoundError(f"no rasters matching {src.filename_regex!r} in {root}")
    return out


# --------------------------------------------------------------------------- aggregation
PixelFn = Callable[[list[np.ndarray], float], dict[str, np.ndarray]]
"""Per-window transform: (band arrays on the working raster, working resolution) -> layers."""


@dataclass
class _Accumulator:
    sums: dict[str, np.ndarray]
    counts: dict[str, np.ndarray]


class GridAggregator:
    """Aggregate rasters to grid cells, window by window, in the equal-area CRS."""

    def __init__(self, grid: pd.DataFrame, meta: GridMeta) -> None:
        self.meta = meta
        self.n = len(grid)
        s = meta.cell_size_m
        # dense lookup raster: grid (row, col) -> position in the grid table (or -1)
        self.lookup = np.full((meta.height, meta.width), -1, dtype=np.int64)
        self.lookup[grid["row"].to_numpy(), grid["col"].to_numpy()] = np.arange(self.n)
        self.s = s

    def _windows(self, window_km: float) -> list[tuple[int, int, int, int]]:
        step = max(1, int(round(window_km * 1000 / self.s)))
        wins = []
        for r0 in range(0, self.meta.height, step):
            for c0 in range(0, self.meta.width, step):
                r1, c1 = min(r0 + step, self.meta.height), min(c0 + step, self.meta.width)
                if (self.lookup[r0:r1, c0:c1] >= 0).any():
                    wins.append((r0, r1, c0, c1))
        return wins

    def aggregate(self, files: list[Path], working_res_m: float, window_km: float,
                  resampling: Resampling, pixel_fn: PixelFn | None = None,
                  halo_px: int = 0, src_nodata: float | None = None,
                  bands: tuple[int, ...] = (1,),
                  categorical_classes: dict[str, list[int]] | None = None,
                  ) -> dict[str, np.ndarray]:
        """Return per-cell means of each output layer (NaN where no valid pixels).

        * continuous: mean of ``pixel_fn`` outputs (or the band itself) over valid pixels;
        * categorical: fraction of valid pixels in each named class group.
        """
        # the effective working resolution is adjusted so that it divides the cell size
        k = max(1, int(round(self.s / working_res_m)))
        res = self.s / k
        acc = _Accumulator(sums={}, counts={})
        srcs = [rasterio.open(f) for f in files]
        try:
            for r0, r1, c0, c1 in self._windows(window_km):
                west = self.meta.xmin + c0 * self.s - halo_px * res
                north = self.meta.ymax - r0 * self.s + halo_px * res
                h = (r1 - r0) * k + 2 * halo_px
                w = (c1 - c0) * k + 2 * halo_px
                dst_tr = from_origin(west, north, res, res)
                dsts = [np.full((h, w), np.nan, dtype=np.float32) for _ in bands]
                bounds = (west, north - h * res, west + w * res, north)
                for src in srcs:
                    sb = transform_bounds(self.meta.crs, src.crs, *bounds, densify_pts=21)
                    b = src.bounds
                    if sb[0] > b.right or sb[2] < b.left or sb[1] > b.top or sb[3] < b.bottom:
                        continue
                    for band, dst in zip(bands, dsts, strict=True):
                        tmp = np.full((h, w), np.nan, dtype=np.float32)
                        reproject(
                            source=rasterio.band(src, band), destination=tmp,
                            src_transform=src.transform, src_crs=src.crs,
                            src_nodata=src_nodata if src_nodata is not None else src.nodata,
                            dst_transform=dst_tr, dst_crs=self.meta.crs, dst_nodata=np.nan,
                            resampling=resampling,
                        )
                        fill = np.isnan(dst) & ~np.isnan(tmp)
                        dst[fill] = tmp[fill]
                layers = pixel_fn(dsts, res) if pixel_fn else {"value": dsts[0]}
                rr = np.arange(h - 2 * halo_px) // k + r0
                cc = np.arange(w - 2 * halo_px) // k + c0
                cell_idx = self.lookup[rr[:, None], cc[None, :]]
                inner = (slice(halo_px, h - halo_px), slice(halo_px, w - halo_px))
                for name, arr in layers.items():
                    a = arr[inner]
                    valid = (cell_idx >= 0) & np.isfinite(a)
                    if categorical_classes is not None:
                        self._acc_categorical(acc, a, valid, cell_idx, categorical_classes)
                    else:
                        self._acc(acc, name, cell_idx[valid], a[valid])
        finally:
            for s in srcs:
                s.close()
        out = {}
        for name, sums in acc.sums.items():
            cnt = acc.counts[name]
            with np.errstate(invalid="ignore", divide="ignore"):
                out[name] = np.where(cnt > 0, sums / np.maximum(cnt, 1), np.nan)
        return out

    def _acc(self, acc: _Accumulator, name: str, idx: np.ndarray, vals: np.ndarray) -> None:
        if name not in acc.sums:
            acc.sums[name] = np.zeros(self.n)
            acc.counts[name] = np.zeros(self.n)
        acc.sums[name] += np.bincount(idx, weights=vals.astype(float), minlength=self.n)
        acc.counts[name] += np.bincount(idx, minlength=self.n)

    def _acc_categorical(self, acc: _Accumulator, a: np.ndarray, valid: np.ndarray,
                         cell_idx: np.ndarray, classes: dict[str, list[int]]) -> None:
        idx = cell_idx[valid]
        vals = a[valid].astype(np.int64)
        for name, codes in classes.items():
            hit = np.isin(vals, codes).astype(float)
            self._acc(acc, name, idx, hit)


def sample_points(path: Path, lon: np.ndarray, lat: np.ndarray, band: int = 1) -> np.ndarray:
    """Sample a raster at lon/lat points (nearest pixel); NaN outside/nodata."""
    with rasterio.open(path) as src:
        if src.crs and src.crs.to_string() != "EPSG:4326":
            tr = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
            xs, ys = tr.transform(lon, lat)
        else:
            xs, ys = lon, lat
        vals = np.array([v[0] for v in src.sample(zip(xs, ys, strict=True), indexes=band)],
                        dtype=float)
        if src.nodata is not None:
            vals[vals == src.nodata] = np.nan
        b = src.bounds
        outside = (np.asarray(xs) < b.left) | (np.asarray(xs) > b.right) | (
            np.asarray(ys) < b.bottom) | (np.asarray(ys) > b.top)
        vals[outside] = np.nan
    return vals
