"""Shared fixtures: one synthetic end-to-end pipeline run per test session."""

from __future__ import annotations

from pathlib import Path

import pytest

from wildfire_kz.cli.pipeline import STAGE_LIST, run_stage
from wildfire_kz.config import load_config
from wildfire_kz.config.schema import Config
from wildfire_kz.data.synthetic import generate_synthetic
from wildfire_kz.paths import RunPaths
from wildfire_kz.splits.guard import FeatureStore, TestSetAccessError

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def smoke(tmp_path_factory: pytest.TempPathFactory) -> tuple[Config, RunPaths]:
    tmp = tmp_path_factory.mktemp("smoke")
    cfg = load_config(
        [ROOT / "configs" / "test_smoke.yaml"],
        [
            f"project.raw_dir={tmp / 'raw'}",
            f"project.work_dir={tmp / 'work'}",
            "features.fire_history.enabled=true",
        ],
    )
    generate_synthetic(cfg)
    paths = RunPaths.from_config(cfg)
    for stage in STAGE_LIST:
        if stage.name == "evaluate":
            # before the final stage the test years must be inaccessible
            with pytest.raises(TestSetAccessError):
                FeatureStore(cfg, paths).load(cfg.splits.test_years, "test")
        run_stage(stage.name, cfg)
    return cfg, paths
