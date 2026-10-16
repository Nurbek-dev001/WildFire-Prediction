"""Spatial-block CV (no block overlap, >= 25 km buffer) and the test-year access guard."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from wildfire_kz.config.schema import Config
from wildfire_kz.paths import RunPaths
from wildfire_kz.splits.guard import FeatureStore, TestSetAccessError, unlock_final_evaluation
from wildfire_kz.splits.spatial import assign_folds, edge_distance, fold_roles
from wildfire_kz.utils.io import write_partition
from wildfire_kz.utils.runtime import write_json

CELL = 5000.0


def _grid(nx: int = 80, ny: int = 60) -> pd.DataFrame:
    ix, iy = np.meshgrid(np.arange(nx), np.arange(ny))
    return pd.DataFrame(
        {
            "cell_id": np.arange(ix.size),
            "x": (ix.ravel() + 0.5) * CELL,
            "y": (iy.ravel() + 0.5) * CELL,
        }
    )


@pytest.fixture(scope="module")
def folds_roles() -> tuple[pd.DataFrame, pd.DataFrame]:
    folds = assign_folds(_grid(), block_km=100, n_folds=5, seed=7)
    return folds, fold_roles(folds, buffer_km=25, cell_size_m=CELL)


def test_every_block_in_exactly_one_fold(folds_roles) -> None:  # type: ignore[no-untyped-def]
    folds, _ = folds_roles
    per_block = folds.groupby("block_id")["fold"].nunique()
    assert (per_block == 1).all()
    assert sorted(folds["fold"].unique()) == [0, 1, 2, 3, 4]


def test_each_cell_is_test_exactly_once(folds_roles) -> None:  # type: ignore[no-untyped-def]
    _, roles = folds_roles
    n_test = roles[roles["role"] == "test"].groupby("cell_id").size()
    assert (n_test == 1).all() and len(n_test) == roles["cell_id"].nunique()


def test_buffer_of_25km_is_respected_brute_force(folds_roles) -> None:  # type: ignore[no-untyped-def]
    folds, roles = folds_roles
    xy = folds.set_index("cell_id")[["x", "y"]]
    for k, g in roles.groupby("fold"):
        test = xy.loc[g.loc[g.role == "test", "cell_id"]].to_numpy()
        train = xy.loc[g.loc[g.role == "train", "cell_id"]].to_numpy()
        dx = train[:, None, 0] - test[None, :, 0]
        dy = train[:, None, 1] - test[None, :, 1]
        assert edge_distance(dx, dy, CELL).min() >= 25_000 - 1e-6, k
        # and the buffer is not excessive: buffer cells are all within 25 km
        buf = xy.loc[g.loc[g.role == "buffer", "cell_id"]].to_numpy()
        if len(buf):
            d = edge_distance(
                buf[:, None, 0] - test[None, :, 0], buf[:, None, 1] - test[None, :, 1], CELL
            ).min(axis=1)
            assert (d < 25_000).all()


def test_folds_are_geographically_separated(folds_roles) -> None:  # type: ignore[no-untyped-def]
    folds, _ = folds_roles
    cent = folds.groupby("fold")[["x", "y"]].mean().to_numpy()
    spread = folds.groupby("fold")[["x", "y"]].std().to_numpy().max()
    d = np.hypot(*(cent[:, None, :] - cent[None, :, :]).transpose(2, 0, 1))
    np.fill_diagonal(d, np.inf)
    assert d.min() > 0.5 * spread  # compact, distinct regions rather than interleaved blocks


def test_block_sensitivity_sizes() -> None:
    for b in (50, 150):
        f = assign_folds(_grid(), block_km=b, n_folds=5, seed=1)
        assert f.groupby("block_id")["fold"].nunique().max() == 1


def test_too_few_blocks_raises() -> None:
    with pytest.raises(ValueError):
        assign_folds(_grid(10, 10), block_km=100, n_folds=5, seed=1)


# ----------------------------------------------------------------------------- guard


def _store(tmp_path: Path) -> tuple[Config, RunPaths]:
    cfg = Config.model_validate({"project": {"work_dir": str(tmp_path), "run_label": "g"}})
    paths = RunPaths.from_config(cfg)
    for y in (2021, 2022, 2023):
        write_partition(pd.DataFrame({"cell_id": [1], "label": [0]}), paths.features, "year", y)
    return cfg, paths


def test_test_years_locked_before_final_stage(tmp_path: Path) -> None:
    cfg, paths = _store(tmp_path)
    store = FeatureStore(cfg, paths)
    assert len(store.load([2021], "train")) == 1
    with pytest.raises(TestSetAccessError):
        store.load([2023], "test")
    with pytest.raises(TestSetAccessError):
        store.load([2023], "train")
    with pytest.raises(TestSetAccessError):
        store.load([2022], "train")  # calibration year never used for fitting


def test_unlock_requires_frozen_calibration(tmp_path: Path) -> None:
    cfg, paths = _store(tmp_path)
    with pytest.raises(TestSetAccessError):
        unlock_final_evaluation(cfg, paths, "evaluate")
    write_json(paths.stage("calibrate") / "calibration_artifacts.json", {"tau": 0.1})
    with pytest.raises(TestSetAccessError):
        unlock_final_evaluation(cfg, paths, "train")  # only final stages may unlock
    unlock_final_evaluation(cfg, paths, "evaluate")
    store = FeatureStore(cfg, paths)
    assert len(store.load([2023], "test")) == 1
    with pytest.raises(TestSetAccessError):
        store.load([2023], "calibration")  # still never for calibration
    # changing calibration after unlocking re-locks the test years
    write_json(paths.stage("calibrate") / "calibration_artifacts.json", {"tau": 0.2})
    with pytest.raises(TestSetAccessError):
        store.load([2023], "test")
