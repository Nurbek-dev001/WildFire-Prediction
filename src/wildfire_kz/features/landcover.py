"""MCD12Q1 land-cover area fractions per cell (preceding-year map)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from rasterio.enums import Resampling

from wildfire_kz.config.schema import Config
from wildfire_kz.data.rasters import GridAggregator, raster_catalog
from wildfire_kz.grid.grid import GridMeta
from wildfire_kz.utils.runtime import get_logger

log = get_logger("features.landcover")

LC_GROUPS = ("forest", "shrubland", "grassland", "cropland", "other")


def lc_year_for(target_year: int, available: list[int], offset: int) -> tuple[int, bool]:
    """Map year to the land-cover product year (preceding year by default).

    Returns (product_year, exact). Falls back to the latest *earlier* map if the preferred one
    is unavailable; never uses a later (future) map.
    """
    want = target_year + offset
    if want in available:
        return want, True
    earlier = [y for y in available if y <= want]
    if not earlier:
        raise FileNotFoundError(
            f"no land-cover map at or before {want} for target year "
            f"{target_year} (available: {sorted(available)})"
        )
    return max(earlier), False


def landcover_fractions(
    cfg: Config, grid: pd.DataFrame, meta: GridMeta, target_years: list[int]
) -> pd.DataFrame:
    """Per (cell, target year) fractions of each broad class and the dominant group."""
    src = cfg.sources.mcd12q1
    catalog = {e.year: e.path for e in raster_catalog(cfg, src) if e.year is not None}
    agg = GridAggregator(grid, meta)
    unknown = [c for c in src.classes if c not in LC_GROUPS]
    if unknown:
        raise ValueError(f"land-cover groups must be among {LC_GROUPS}; got {unknown}")
    cache: dict[int, dict[str, np.ndarray]] = {}
    frames = []
    for year in target_years:
        lc_year, exact = lc_year_for(year, sorted(catalog), src.year_offset)
        if not exact:
            log.warning(
                "land cover for %d: preferred map %d missing, using %d",
                year,
                year + src.year_offset,
                lc_year,
            )
        if lc_year not in cache:
            cache[lc_year] = agg.aggregate(
                [catalog[lc_year]],
                src.working_resolution_m,
                src.window_size_km,
                Resampling.nearest,
                categorical_classes=src.classes,
            )
        fr = cache[lc_year]
        df = pd.DataFrame(
            {"cell_id": grid["cell_id"].to_numpy(), "year": year, "lc_product_year": lc_year}
        )
        for g in LC_GROUPS:
            df[f"lc_frac_{g}"] = fr.get(g, np.full(len(grid), np.nan)).astype(np.float32)
        mat = df[[f"lc_frac_{g}" for g in LC_GROUPS]].to_numpy()
        dom = np.where(
            np.isnan(mat).all(axis=1),
            len(LC_GROUPS) - 1,
            np.nanargmax(np.nan_to_num(mat, nan=-1.0), axis=1),
        )
        df["lc_group"] = np.asarray(LC_GROUPS)[dom]
        frames.append(df)
    return pd.concat(frames, ignore_index=True)
