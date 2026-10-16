"""Configuration validation and grid identifiers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from wildfire_kz.config import load_config
from wildfire_kz.config.schema import Config
from wildfire_kz.grid.grid import make_cell_id, split_cell_id

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["default.yaml", "synthetic.yaml", "test_smoke.yaml"])
def test_shipped_configs_validate(name: str) -> None:
    cfg = load_config([ROOT / "configs" / name])
    assert cfg.events.spatial_link_km == 2.0 and cfg.events.temporal_link_h == 48.0


def test_methodology_defaults() -> None:
    cfg = load_config([ROOT / "configs" / "default.yaml"])
    assert cfg.grid.primary.cell_size_m == 5000
    assert cfg.splits.development_years == list(range(2015, 2022))
    assert cfg.splits.calibration_years == [2022] and cfg.splits.test_years == [2023, 2024]
    assert cfg.splits.rolling_origin[0].train_years == [2015, 2016, 2017, 2018]
    assert cfg.splits.rolling_origin[0].val_year == 2019
    assert cfg.splits.spatial_cv.block_size_km == 100 and cfg.splits.spatial_cv.buffer_km == 25
    assert cfg.models.n_trials_ensemble == 50
    assert cfg.sources.mod13a2.max_gap_fill_days == 32
    assert cfg.evaluation.bootstrap.n_resamples == 1000


def test_overlapping_splits_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"splits": {"calibration_years": [2021]}})


def test_non_chronological_rolling_origin_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate(
            {"splits": {"rolling_origin": [{"train_years": [2019], "val_year": 2018}]}}
        )


def test_dotted_overrides() -> None:
    cfg = load_config([ROOT / "configs" / "default.yaml"], ["events.spatial_link_km=3"])
    assert cfg.events.spatial_link_km == 3


def test_cell_ids_are_stable_and_invertible() -> None:
    ix = np.array([-400, 0, 399])
    iy = np.array([-300, 5, 299])
    cid = make_cell_id(ix, iy)
    assert len(set(cid)) == 3
    rx, ry = split_cell_id(cid)
    assert (rx == ix).all() and (ry == iy).all()
