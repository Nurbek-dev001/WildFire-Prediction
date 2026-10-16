"""End-to-end smoke test: synthetic data -> all 14 stages -> invariants on the artifacts.

Runs fully offline. The optional fire-history predictor is switched on here so that the
"later detections never enter predictors" guarantee is also checked on pipeline output.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio

from wildfire_kz.cli.pipeline import STAGE_LIST, run_stage
from wildfire_kz.config import load_config
from wildfire_kz.config.schema import Config
from wildfire_kz.data.synthetic import generate_synthetic
from wildfire_kz.features.fire_history import fire_history_counts
from wildfire_kz.features.leakage import check_no_leakage
from wildfire_kz.features.registry import FeatureSpec
from wildfire_kz.paths import RunPaths
from wildfire_kz.splits.guard import FeatureStore, TestSetAccessError
from wildfire_kz.utils.io import read_partitions
from wildfire_kz.utils.runtime import read_json

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
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


def test_all_stage_outputs_exist(smoke: tuple[Config, RunPaths]) -> None:
    _, paths = smoke
    for stage in STAGE_LIST:
        for out in stage.outputs:
            assert (paths.stage(stage.name) / out).exists(), (stage.name, out)


def test_stages_are_idempotent(smoke: tuple[Config, RunPaths]) -> None:
    cfg, _ = smoke
    assert run_stage("grid", cfg) is None and run_stage("report", cfg) is None


def test_manifest_flags_synthetic_and_has_checksums(smoke: tuple[Config, RunPaths]) -> None:
    _, paths = smoke
    man = read_json(paths.manifest)
    assert man["synthetic"] is True
    files = [f for s in man["sources"].values() for f in s["files"]]
    assert files and all(len(f["sha256"]) == 64 for f in files)


def test_every_feature_row_is_leakage_free(smoke: tuple[Config, RunPaths]) -> None:
    _, paths = smoke
    reg = read_json(paths.stage("features") / "feature_registry.json")
    specs = [FeatureSpec(**r) for r in reg["features"]]
    feats = read_partitions(paths.features, "year")  # direct read for auditing only
    report = check_no_leakage(feats, specs)
    assert report["passed"]
    assert (pd.to_datetime(feats["asof_weather"]) < pd.to_datetime(feats["date"])).all()
    veg = feats["asof_vegetation"].notna()
    assert (
        pd.to_datetime(feats.loc[veg, "asof_vegetation"]) < pd.to_datetime(feats.loc[veg, "date"])
    ).all()


def test_later_detections_never_enter_predictors(smoke: tuple[Config, RunPaths]) -> None:
    """Fire-history values equal a recomputation that sees only detections before t."""
    cfg, paths = smoke
    feats = read_partitions(
        paths.features, "year", columns=["cell_id", "date", "label", "hist_det_days"]
    )
    pos = feats[feats["label"] == 1].head(300)
    det = pd.read_parquet(paths.detections)
    expected = []
    for _, r in pos.iterrows():
        past = det[det["acq_datetime"] < pd.Timestamp(r["date"])]
        expected.append(
            fire_history_counts(
                past["cell_id"].to_numpy(),
                past["acq_datetime"].to_numpy(),
                np.array([r["cell_id"]]),
                np.array([r["date"]], dtype="datetime64[D]"),
                cfg.features.fire_history.window_days,
            )[0]
        )
    assert np.allclose(pos["hist_det_days"].to_numpy(), expected)


def test_positives_are_earliest_detections(smoke: tuple[Config, RunPaths]) -> None:
    _, paths = smoke
    det = pd.read_parquet(paths.detections)
    pos = pd.read_parquet(paths.positives)
    first = det.groupby("event_id")["acq_datetime"].min()
    for _, r in pos.head(200).iterrows():
        assert first[r["event_id"]].normalize() == r["date"]


def test_sampling_weights_reproduce_risk_set(smoke: tuple[Config, RunPaths]) -> None:
    _, paths = smoke
    summary = read_json(paths.stage("sampling") / "sampling_summary.json")
    for year, s in summary.items():
        assert s["train_weight_total"] == pytest.approx(s["risk_set_cell_days"]), year
        assert s["eval_weight_total"] == pytest.approx(s["risk_set_cell_days"]), year


def test_test_years_opened_only_after_calibration(smoke: tuple[Config, RunPaths]) -> None:
    _, paths = smoke
    ledger = read_json(paths.stage("evaluate") / "final_evaluation_ledger.json")
    cal = read_json(paths.stage("calibrate") / "calibration_artifacts.json")
    assert ledger["unlocked_by"] == "evaluate"
    assert ledger["unlocked_at"] >= cal["frozen_at"]


def test_evaluation_is_unbalanced_and_metrics_present(smoke: tuple[Config, RunPaths]) -> None:
    _, paths = smoke
    m = pd.read_csv(paths.stage("evaluate") / "metrics_overall.csv")
    assert {
        "average_precision",
        "roc_auc",
        "brier",
        "bss",
        "ece_10bin",
        "f1",
        "fpr",
        "fdp",
        "prevalence",
    } <= set(m.columns)
    assert (m["prevalence"] < 0.2).all()  # never a balanced evaluation set
    pairs = pd.read_csv(paths.stage("evaluate") / "bootstrap_pairs.csv")
    assert {"ci_lo", "ci_hi", "ci_excludes_zero"} <= set(pairs.columns)


def test_maps_are_qgis_ready(smoke: tuple[Config, RunPaths]) -> None:
    cfg, paths = smoke
    idx = pd.read_csv(paths.stage("map") / "map_index.csv")
    assert len(idx) > 0
    with rasterio.open(paths.stage("map") / idx["prob_file"].iloc[0]) as r:
        assert r.crs is not None and r.nodata == cfg.mapping.nodata
        tags = r.tags()
        assert "not damage" in tags["DESCRIPTION"] and tags["SYNTHETIC"] == "True"
        a = r.read(1)
        v = a[a != r.nodata]
        assert v.size and (v >= 0).all() and (v <= 1).all()


def test_report_is_generated_with_synthetic_banner(smoke: tuple[Config, RunPaths]) -> None:
    _, paths = smoke
    text = (paths.stage("report") / "REPORT.md").read_text()
    assert "SYNTHETIC DATA" in text
    assert "predictive associations of the model, not causal effects" in text
    rec = read_json(paths.stage("report") / "reproducibility_record.json")
    assert rec["seeds"]["global"] and rec["packages"]["xgboost"] != "not installed"
