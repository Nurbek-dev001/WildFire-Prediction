"""Anthropogenic predictors: WorldPop density, settlement and road proximity.

Road (and settlement) proximity uses only snapshots dated strictly before the target day.
If no historical snapshot predates every target day of the study period, the variable is
omitted from the primary experiment and flagged; present-day roads are never silently
substituted.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from rasterio.enums import Resampling
from scipy.spatial import cKDTree

from wildfire_kz.config.schema import Config, VectorSource
from wildfire_kz.data.rasters import GridAggregator, raster_catalog
from wildfire_kz.features.landcover import lc_year_for
from wildfire_kz.grid.grid import GridMeta
from wildfire_kz.utils.runtime import get_logger

log = get_logger("features.human")


@dataclass
class HumanAvailability:
    """Which anthropogenic variables can enter the primary experiment, and why not."""

    usable: dict[str, bool] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)


def check_snapshot_coverage(src: VectorSource, first_target: dt.date, name: str,
                            enabled: bool, avail: HumanAvailability) -> None:
    if not enabled:
        avail.usable[name] = False
        avail.flags.append(f"{name}: disabled in configuration")
        return
    dates = sorted(s.snapshot_date for s in src.snapshots)
    if not dates:
        avail.usable[name] = False
        avail.flags.append(f"{name}: no historical snapshot configured -> omitted from the "
                           "primary experiment (present-day data are never substituted)")
    elif dates[0] >= first_target:
        avail.usable[name] = False
        avail.flags.append(f"{name}: earliest snapshot {dates[0]} does not predate the first "
                           f"target day {first_target} -> omitted from the primary experiment")
    else:
        avail.usable[name] = True


def snapshot_for(src: VectorSource, target: pd.Series) -> pd.Series:
    """Index of the latest snapshot with snapshot_date < target (or -1)."""
    snaps = sorted(src.snapshots, key=lambda s: s.snapshot_date)
    dates = np.array([np.datetime64(s.snapshot_date) for s in snaps], dtype="datetime64[D]")
    t = target.to_numpy(dtype="datetime64[D]")
    return pd.Series(np.searchsorted(dates, t, side="left") - 1, index=target.index)


def snapshot_distances(cfg: Config, grid: pd.DataFrame, src: VectorSource, kind: str
                       ) -> np.ndarray:
    """(n_snapshots, n_cells) distance (km) from cell centroids to the nearest feature."""
    snaps = sorted(src.snapshots, key=lambda s: s.snapshot_date)
    out = np.full((len(snaps), len(grid)), np.nan, dtype=np.float32)
    xy = grid[["x", "y"]].to_numpy()
    for i, snap in enumerate(snaps):
        gdf = gpd.read_file(cfg.raw(snap.path)).to_crs(cfg.crs.proj4)
        if gdf.empty:
            continue
        if kind == "points":
            pts = np.column_stack([gdf.geometry.x, gdf.geometry.y])
            out[i] = cKDTree(pts).query(xy)[0] / 1000.0
        else:
            tree = shapely.STRtree(gdf.geometry.values)
            cent = shapely.points(xy)
            idx, dist = tree.query_nearest(cent, return_distance=True, all_matches=False)
            d = np.full(len(grid), np.nan)
            d[idx[0]] = dist
            out[i] = d / 1000.0
    return out


def population_by_year(cfg: Config, grid: pd.DataFrame, meta: GridMeta, years: list[int]
                       ) -> tuple[pd.DataFrame, list[str]]:
    """Population density (persons/km²) per target year using the preceding-year product."""
    src = cfg.sources.worldpop
    catalog = {e.year: e.path for e in raster_catalog(cfg, src) if e.year is not None}
    agg = GridAggregator(grid, meta)
    cache: dict[int, np.ndarray] = {}
    flags: list[str] = []
    frames = []
    for year in years:
        pyear, exact = lc_year_for(year, sorted(catalog), src.year_offset)
        if not exact:
            flags.append(f"population for {year}: product {year + src.year_offset} missing, "
                         f"using earlier {pyear}")
        if pyear not in cache:
            if src.product == "ppp_counts":
                # counts are summed into cells (mass-preserving) then divided by area
                res = agg.aggregate([catalog[pyear]], meta.cell_size_m, src.window_size_km,
                                    Resampling.sum)
                # WorldPop counts only land inside the country -> divide by the inside area
                cache[pyear] = res["value"] / grid["area_km2"].to_numpy()
            else:
                res = agg.aggregate([catalog[pyear]], src.working_resolution_m,
                                    src.window_size_km, Resampling.average)
                cache[pyear] = res["value"]
        frames.append(pd.DataFrame({"cell_id": grid["cell_id"].to_numpy(), "year": year,
                                    "pop_density": cache[pyear].astype(np.float32),
                                    "pop_asof": pd.Timestamp(pyear, 12, 31)}))
    return pd.concat(frames, ignore_index=True), flags
