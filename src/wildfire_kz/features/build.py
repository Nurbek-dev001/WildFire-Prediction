"""Stage 6 — feature assembly with strict as-of timestamps and the leakage check.

Expensive per-source layers are computed once and cached under ``features/layers``:
terrain (static), land cover (from the sampling stage), population per year, distances per
vector snapshot, MODIS composite aggregates, and the per-year weather cube (NetCDF, dims
date x cell). Feature rows for any set of (cell_id, date) pairs are then gathered from these
layers, so the same code serves model tables and full-grid daily maps.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from wildfire_kz.config.schema import Config
from wildfire_kz.data.manifest import enumerate_sources
from wildfire_kz.features.era5 import weather_feature_cube
from wildfire_kz.features.fire_history import fire_history_counts
from wildfire_kz.features.human import (
    HumanAvailability,
    check_snapshot_coverage,
    population_by_year,
    snapshot_distances,
    snapshot_for,
)
from wildfire_kz.features.landcover import LC_GROUPS, landcover_fractions
from wildfire_kz.features.leakage import check_no_leakage
from wildfire_kz.features.modis import aggregate_composites, vegetation_features, vegetation_regimes
from wildfire_kz.features.registry import FeatureSpec, feature_specs, registry_records
from wildfire_kz.features.terrain import terrain_features
from wildfire_kz.grid.grid import GridMeta, load_grid
from wildfire_kz.paths import RunPaths
from wildfire_kz.utils.io import read_partitions, write_partition
from wildfire_kz.utils.runtime import get_logger, read_json, write_json

log = get_logger("features")

META_COLUMNS = ["cell_id", "date", "label", "event_id", "month", "stratum", "in_train", "in_eval",
                "w_train", "w_eval", "q_train", "q_eval"]


class FeatureBuilder:
    """Assemble as-of features for arbitrary (cell_id, date) rows."""

    def __init__(self, cfg: Config, paths: RunPaths) -> None:
        self.cfg = cfg
        self.paths = paths
        self.layer_dir = paths.stage("features") / "layers"
        self.layer_dir.mkdir(parents=True, exist_ok=True)
        self.grid = load_grid(paths.grid_file)
        self.meta = GridMeta.load(paths.grid_meta)
        self.cell_index = pd.Series(np.arange(len(self.grid)), index=self.grid["cell_id"])
        self.availability = HumanAvailability()
        hc = cfg.features.human
        check_snapshot_coverage(cfg.sources.roads, cfg.study.start, "dist_road_km",
                                hc.use_roads, self.availability)
        check_snapshot_coverage(cfg.sources.settlements, cfg.study.start, "dist_settlement_km",
                                hc.use_settlements, self.availability)
        self.availability.usable["pop_density"] = hc.use_population
        self.specs = [s for s in feature_specs(cfg)
                      if self.availability.usable.get(s.name, True)]
        self._regimes: dict[str, np.ndarray] | None = None
        self._weather: dict[int, xr.Dataset] = {}

    # ------------------------------------------------------------------ cached layers
    def _cached(self, name: str, fn: Any) -> pd.DataFrame:
        path = self.layer_dir / f"{name}.parquet"
        if path.exists():
            return pd.read_parquet(path)
        df = fn()
        df.to_parquet(path, index=False)
        return df

    def terrain(self) -> pd.DataFrame:
        return self._cached("terrain", lambda: terrain_features(self.cfg, self.grid, self.meta))

    def landcover(self) -> pd.DataFrame:
        sampled = self.paths.stage("sampling") / "landcover_fractions.parquet"
        if sampled.exists():
            return pd.read_parquet(sampled)
        return self._cached("landcover", lambda: landcover_fractions(
            self.cfg, self.grid, self.meta, self.cfg.study.years))

    def population(self) -> pd.DataFrame:
        flags_path = self.layer_dir / "population_flags.json"

        def build() -> pd.DataFrame:
            df, flags = population_by_year(self.cfg, self.grid, self.meta, self.cfg.study.years)
            write_json(flags_path, flags)
            return df
        df = self._cached("population", build)
        if flags_path.exists():
            for f in read_json(flags_path):
                if f not in self.availability.flags:
                    self.availability.flags.append(f)
        return df

    def distances(self, kind: str) -> np.ndarray:
        path = self.layer_dir / f"distances_{kind}.npy"
        if path.exists():
            return np.load(path)
        src = self.cfg.sources.roads if kind == "roads" else self.cfg.sources.settlements
        arr = snapshot_distances(self.cfg, self.grid, src,
                                 "lines" if kind == "roads" else "points")
        np.save(path, arr)
        return arr

    def regimes(self) -> dict[str, np.ndarray]:
        if self._regimes is None:
            first = self.cfg.study.start - dt.timedelta(
                days=self.cfg.study.lookback_days + self.cfg.sources.mod13a2.max_gap_fill_days)
            comp = self._cached("modis_composites", lambda: aggregate_composites(
                self.cfg, self.grid, self.meta, first, self.cfg.study.end))
            self._regimes = vegetation_regimes(comp, len(self.grid),
                                               self.cfg.sources.mod13a2.max_gap_fill_days)
        return self._regimes

    def weather(self, year: int) -> xr.Dataset:
        if year in self._weather:
            return self._weather[year]
        path = self.layer_dir / "weather" / f"weather_{year}.nc"
        if not path.exists():
            files = next(s.files for s in enumerate_sources(self.cfg) if s.name == "era5_land")
            cube = weather_feature_cube(self.cfg, files, year, self.grid["lon"].to_numpy(),
                                        self.grid["lat"].to_numpy())
            path.parent.mkdir(parents=True, exist_ok=True)
            enc = {v: {"zlib": True, "complevel": 3} for v in cube.data_vars
                   if v != "asof_weather"}
            cube.to_netcdf(path, encoding=enc)
        self._weather[year] = xr.load_dataset(path)
        return self._weather[year]

    # ------------------------------------------------------------------ assembly
    def assemble(self, rows: pd.DataFrame) -> pd.DataFrame:
        """Return ``rows`` with all feature columns and ``asof_*`` columns added."""
        rows = rows.reset_index(drop=True).copy()
        rows["date"] = pd.to_datetime(rows["date"]).astype("datetime64[ns]")
        year = rows["date"].dt.year.to_numpy()
        cidx = self.cell_index.reindex(rows["cell_id"].to_numpy()).to_numpy()
        if np.isnan(cidx.astype(float)).any():
            raise KeyError("rows reference cell ids that are not in the grid")
        cidx = cidx.astype(np.int64)
        names = {s.name for s in self.specs}
        out = {}
        # ---- weather (prior day + antecedent + optional fire weather)
        wnames = [s.name for s in self.specs
                  if s.group in ("weather_prior_day", "weather_antecedent", "fire_weather")]
        wvals = {n: np.full(len(rows), np.nan, dtype=np.float32) for n in wnames}
        asof_w = np.full(len(rows), np.datetime64("NaT"), dtype="datetime64[ns]")
        for y in np.unique(year):
            m = year == y
            cube = self.weather(int(y))
            didx = (rows.loc[m, "date"].to_numpy(dtype="datetime64[D]")
                    - np.datetime64(f"{int(y)}-01-01")).astype(int)
            for n in wnames:
                wvals[n][m] = cube[n].values[didx, cidx[m]]
            asof_w[m] = cube["asof_weather"].values[didx]
        out.update(wvals)
        out["asof_weather"] = asof_w
        # ---- vegetation
        veg = vegetation_features(self.regimes(), cidx, rows["date"].to_numpy())
        for c in veg.columns:
            out[c] = veg[c].to_numpy()
        # ---- land cover (preceding-year map)
        lc = self.landcover()
        lcj = rows[["cell_id"]].assign(year=year).merge(lc, on=["cell_id", "year"], how="left")
        for g in LC_GROUPS:
            out[f"lc_frac_{g}"] = lcj[f"lc_frac_{g}"].to_numpy(dtype=np.float32)
        out["lc_group"] = lcj["lc_group"].fillna("other").to_numpy()
        out["asof_landcover"] = pd.to_datetime(lcj["lc_product_year"].astype(str) + "-12-31"
                                               ).to_numpy(dtype="datetime64[ns]")
        # ---- terrain
        ter = self.terrain().set_index("cell_id").reindex(rows["cell_id"].to_numpy())
        for c in ("elevation_m", "slope_deg", "aspect_sin", "aspect_cos", "asof_terrain"):
            out[c] = ter[c].to_numpy()
        # ---- anthropogenic
        asof_h = np.full(len(rows), np.datetime64("NaT"), dtype="datetime64[ns]")
        if "pop_density" in names:
            pop = rows[["cell_id"]].assign(year=year).merge(self.population(),
                                                            on=["cell_id", "year"], how="left")
            out["pop_density"] = pop["pop_density"].to_numpy(dtype=np.float32)
            asof_h = np.fmax(asof_h, pop["pop_asof"].to_numpy(dtype="datetime64[ns]"))
        for feat, kind, src in (("dist_settlement_km", "settlements", self.cfg.sources.settlements),
                                ("dist_road_km", "roads", self.cfg.sources.roads)):
            if feat not in names:
                continue
            dist = self.distances(kind)
            sidx = snapshot_for(src, rows["date"]).to_numpy()
            ok = sidx >= 0
            vals = np.full(len(rows), np.nan, dtype=np.float32)
            vals[ok] = dist[sidx[ok], cidx[ok]]
            out[feat] = vals
            sdates = np.array(sorted(np.datetime64(s.snapshot_date, "ns")
                                     for s in src.snapshots), dtype="datetime64[ns]")
            used = np.where(ok, sdates[np.where(ok, sidx, 0)], np.datetime64("NaT"))
            asof_h = np.fmax(asof_h, used.astype("datetime64[ns]"))
        out["asof_anthropogenic"] = asof_h
        # ---- optional fire history (detections strictly before t)
        if "hist_det_days" in names:
            out["hist_det_days"], out["asof_fire_history"] = self._fire_history(rows)
        # ---- calendar (deterministic)
        if self.cfg.features.include_calendar:
            doy = rows["date"].dt.dayofyear.to_numpy()
            out["doy_sin"] = np.sin(2 * np.pi * doy / 365.25).astype(np.float32)
            out["doy_cos"] = np.cos(2 * np.pi * doy / 365.25).astype(np.float32)
        feats = pd.DataFrame(out)
        return pd.concat([rows, feats.drop(columns=[c for c in feats.columns
                                                     if c in rows.columns])], axis=1)

    def _fire_history(self, rows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        det = pd.read_parquet(self.paths.detections, columns=["cell_id", "acq_datetime"])
        t = rows["date"].to_numpy(dtype="datetime64[D]")
        counts = fire_history_counts(det["cell_id"].to_numpy(), det["acq_datetime"].to_numpy(),
                                     rows["cell_id"].to_numpy(), t,
                                     self.cfg.features.fire_history.window_days)
        return counts, (t - np.timedelta64(1, "D")).astype("datetime64[ns]")

    def registry(self) -> dict[str, Any]:
        return {"features": registry_records(self.specs),
                "omitted_or_flagged": self.availability.flags,
                "usable": self.availability.usable}


def model_feature_names(specs: list[FeatureSpec]) -> list[str]:
    return [s.name for s in specs]


def run_features(cfg: Config, paths: RunPaths) -> dict[str, Any]:
    out_dir = paths.stage("features")
    builder = FeatureBuilder(cfg, paths)
    reports = {}
    total = 0
    for year in cfg.study.years:
        sample = read_partitions(paths.sample, "year", [year])
        cols = [c for c in META_COLUMNS if c in sample.columns] + ["lc_group"]
        feats = builder.assemble(sample[cols].drop(columns="lc_group"))
        reports[str(year)] = check_no_leakage(feats, builder.specs)
        write_partition(feats, out_dir / "features", "year", year)
        total += len(feats)
        log.info("features %d: %d rows, leakage check passed", year, len(feats))
    reg = builder.registry()
    write_json(out_dir / "feature_registry.json", reg)
    write_json(out_dir / "leakage_report.json", {"passed": True, "years": reports})
    for flag in reg["omitted_or_flagged"]:
        log.warning("FLAG: %s", flag)
    return {"rows": total, "n_features": len(builder.specs), "flags": reg["omitted_or_flagged"]}
