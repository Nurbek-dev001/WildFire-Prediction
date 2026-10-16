"""Stage 7 — split manifests: rolling-origin temporal folds and spatial-block CV folds."""

from __future__ import annotations

from typing import Any

import geopandas as gpd
import pandas as pd

from wildfire_kz.config.schema import Config
from wildfire_kz.grid.grid import GridMeta, load_grid
from wildfire_kz.paths import RunPaths
from wildfire_kz.splits.spatial import assign_folds, fold_roles, min_train_test_distance
from wildfire_kz.utils.io import read_partitions
from wildfire_kz.utils.runtime import derive_seed, get_logger, write_json

log = get_logger("splits")


def temporal_manifest(cfg: Config, paths: RunPaths) -> dict[str, Any]:
    """Describe every temporal partition with row/positive/weight counts (no test features
    are loaded: counts come from the sampling tables)."""
    s = cfg.splits
    counts: dict[str, Any] = {}
    for year in cfg.study.years:
        df = read_partitions(
            paths.sample,
            "year",
            [year],
            columns=["label", "in_train", "in_eval", "w_train", "w_eval"],
        )
        counts[str(year)] = {
            "train_rows": int(df["in_train"].sum()),
            "eval_rows": int(df["in_eval"].sum()),
            "positives": int(df["label"].sum()),
            "risk_set_weight_train": float(df["w_train"].sum()),
            "risk_set_weight_eval": float(df["w_eval"].sum()),
        }
    return {
        "partitions": s.resolved().model_dump(mode="json"),
        "test_policy": "locked until the final evaluation stage (FeatureStore guard)",
        "per_year": counts,
    }


def regions_for_cells(
    cfg: Config, grid: gpd.GeoDataFrame, primary_folds: pd.DataFrame
) -> pd.DataFrame:
    """Region label per cell: configured admin regions if available, else spatial fold."""
    src = cfg.sources.regions
    if src is not None and src.snapshots:
        reg = gpd.read_file(cfg.raw(src.snapshots[-1].path)).to_crs(cfg.crs.proj4)
        name_col = next(
            (c for c in ("name", "NAME_1", "shapeName", "region") if c in reg.columns),
            reg.columns[0],
        )
        pts = gpd.GeoDataFrame(
            grid[["cell_id"]], geometry=gpd.points_from_xy(grid.x, grid.y), crs=cfg.crs.proj4
        )
        j = gpd.sjoin(pts, reg[[name_col, "geometry"]], how="left", predicate="within")
        j = j.drop_duplicates("cell_id")
        return pd.DataFrame(
            {
                "cell_id": j["cell_id"].to_numpy(),
                "region": j[name_col].fillna("unassigned").astype(str).to_numpy(),
                "region_source": "admin_regions",
            }
        )
    return pd.DataFrame(
        {
            "cell_id": primary_folds["cell_id"].to_numpy(),
            "region": "spatial_fold_" + primary_folds["fold"].astype(str),
            "region_source": "spatial_cv_folds",
        }
    )


def run_splits(cfg: Config, paths: RunPaths) -> dict[str, Any]:
    out = paths.stage("splits")
    out.mkdir(parents=True, exist_ok=True)
    grid = load_grid(paths.grid_file)
    meta = GridMeta.load(paths.grid_meta)
    sc = cfg.splits.spatial_cv
    write_json(out / "temporal_splits.json", temporal_manifest(cfg, paths))
    summary: dict[str, Any] = {}
    primary = None
    for block in [sc.block_size_km, *sc.sensitivity_block_sizes_km]:
        seed = derive_seed(cfg.project.seed, "spatial_folds", block)
        folds = assign_folds(grid, block, sc.n_folds, seed)
        roles = fold_roles(folds, sc.buffer_km, meta.cell_size_m)
        dist = min_train_test_distance(folds, roles, meta.cell_size_m)
        tag = f"{int(block)}km"
        folds.to_parquet(out / f"spatial_folds_{tag}.parquet", index=False)
        roles.to_parquet(out / f"spatial_roles_{tag}.parquet", index=False)
        counts = roles.groupby(["fold", "role"]).size().unstack(fill_value=0)
        summary[tag] = {
            "min_train_test_edge_distance_km": dist,
            "role_counts": counts.to_dict(orient="index"),
            "n_blocks": int(folds["block_id"].nunique()),
        }
        if block == sc.block_size_km:
            primary = folds
            folds.to_parquet(out / "spatial_blocks.parquet", index=False)
        log.info("spatial folds %s: min edge distance train-test %s km", tag, dist)
    assert primary is not None
    regions_for_cells(cfg, grid, primary).to_parquet(out / "cell_regions.parquet", index=False)
    write_json(
        out / "spatial_splits.json",
        {"buffer_km": sc.buffer_km, "n_folds": sc.n_folds, "folds": summary},
    )
    return summary
