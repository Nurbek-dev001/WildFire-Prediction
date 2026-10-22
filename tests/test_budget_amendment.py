"""A smaller pre-test budget must never silently admit changed scientific inputs."""

import importlib.util
from pathlib import Path

import pytest


def amendment_module():
    path = Path(__file__).resolve().parents[1] / "scripts/amend_public_search_budget.py"
    spec = importlib.util.spec_from_file_location("budget_amendment", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_budget_reduction_rejects_another_model_or_split_change():
    module = amendment_module()
    original = {"models": {"trials": 50, "threads": 8}, "development_end": 2021}
    module.assert_only_budget_changed(
        original, {"models": {"trials": 5, "threads": 8}, "development_end": 2021}
    )
    for changed in [
        {"models": {"trials": 5, "threads": 4}, "development_end": 2021},
        {"models": {"trials": 5, "threads": 8}, "development_end": 2022},
    ]:
        with pytest.raises(PermissionError, match="Only models.trials"):
            module.assert_only_budget_changed(original, changed)


@pytest.mark.parametrize(
    "relative",
    [
        "runs/public_hindcast/release.json",
        "runs/public_hindcast/models.joblib",
        "runs/public_hindcast/validation/random_forest_2021.parquet",
        "data/real/normalized/detections_2023.parquet",
        "data/real/public_predictors/weather/rows_2024/0001.npz",
    ],
)
def test_budget_amendment_refuses_a_started_final_protocol(tmp_path: Path, relative: str):
    module = amendment_module()
    run = tmp_path / "runs/public_hindcast"
    module.assert_pretest(tmp_path, run)
    artifact = tmp_path / relative
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"presence alone is sufficient; do not parse")
    with pytest.raises(PermissionError, match="precede"):
        module.assert_pretest(tmp_path, run)
