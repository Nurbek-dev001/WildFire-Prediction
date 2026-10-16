"""Offline integration and failure-mode checks using real estimators and raster exports."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio

from wildfire_kz.config import load_config
from wildfire_kz.data import checksum
from wildfire_kz.data.store import FeatureStore
from wildfire_kz.data.synthetic import generate
from wildfire_kz.evaluation import cluster_draws, paired_intervals
from wildfire_kz.events import link_events, persistent_hotspots, risk_set
from wildfire_kz.features import assert_no_leakage
from wildfire_kz.pipeline import STAGES, PipelineRunner


def test_future_detection_does_not_change_past_eligibility():
    before = pd.DataFrame(
        {
            "cell_id": ["a"],
            "confidence": ["n"],
            "x": [0.0],
            "y_coord": [0.0],
            "timestamp": pd.to_datetime(["2020-01-01T12:00Z"]),
        }
    )
    after = pd.concat([before, before.assign(timestamp=pd.Timestamp("2020-02-01T12:00Z"))])
    days = pd.date_range("2020-01-01", "2020-01-10", tz="UTC")
    cells = pd.DataFrame({"cell_id": ["a"]})
    pd.testing.assert_frame_equal(
        risk_set(cells, link_events(before), days), risk_set(cells, link_events(after), days)
    )


def test_industrial_exclusion_uses_development_only():
    detections = pd.DataFrame(
        {"cell_id": ["a"] * 40, "timestamp": pd.date_range("2023-01-01", periods=40, tz="UTC")}
    )
    assert persistent_hotspots(detections, pd.Series({"a": True}), 2021, 30) == set()


def test_paired_bootstrap_identical_models():
    y = np.array([0, 1, 0, 1] * 10)
    p = np.array([0.1, 0.8, 0.4, 0.6] * 10)
    frame = pd.DataFrame(
        {
            "day": pd.date_range("2023-01-01", periods=40, tz="UTC"),
            "x": np.arange(40) * 100000,
            "y_coord": 0,
        }
    )
    draws = cluster_draws(frame, 20, 100000, 30, 42)
    table = paired_intervals(
        y, {"a": p, "b": p}, np.ones(40), {"a": 0.5, "b": 0.5}, np.full(40, 0.5), draws, 0.95
    )
    assert table.lower.eq(0).all() and table.upper.eq(0).all()


def test_end_to_end_smoke(tmp_path: Path):
    """Use all stages and model families; shrink compute budgets only for this fixture."""
    path = tmp_path / "configs" / "fixture.yaml"
    generate(tmp_path / "sources", path)
    cfg = load_config(path)
    cfg.output_dir = tmp_path / "run"
    # One primary geographic block design is sufficient for the smoke test;
    # block-size sensitivities have separate split assertions and run in the demo.
    cfg.splits.sensitivity_block_m = []
    cfg.models.n_estimators_min = 3
    cfg.models.n_estimators_max = 4
    cfg.evaluation.bootstrap_resamples = 3
    cfg.evaluation.shap_rows = 12
    runner = PipelineRunner(cfg)
    for stage in STAGES:
        result = runner.run(stage)
        assert result["seed"] == cfg.seed
        assert result["outputs"]
        if stage == "features":
            features = json.loads((runner.path(stage) / "features.json").read_text())["columns"]
            sample = FeatureStore(runner.path(stage) / "table", cfg, [2019]).sample(training=False)
            assert_no_leakage(sample, features)
            assert not any("detection" in f or "event" in f for f in features)
        if stage == "train":
            cv = pd.read_csv(runner.path(stage) / "cv.csv")
            assert set(cfg.models.names) <= set(cv.model)
            assert not (runner.path("evaluate") / "predictions.parquet").exists()
    index = runner.path("report") / "index.html"
    assert "SYNTHETIC DEMONSTRATION" in index.read_text(encoding="utf-8")
    assert "@@" not in index.read_text(encoding="utf-8")
    evaluated = pd.read_parquet(runner.path("evaluate") / "predictions.parquet")
    assert set(evaluated.day.dt.year) == {2023, 2024}
    assert evaluated.weight.eq(1).all()  # unbalanced full fixture evaluation
    rasters = list(runner.path("map").glob("*.tif"))
    assert len(rasters) == 731
    with rasterio.open(rasters[0]) as raster:
        assert raster.crs.is_projected and raster.count == 2
        assert raster.nodata == -9999
        values = raster.read(1, masked=True).compressed()
        assert np.all((values >= 0) & (values <= 1))
        assert raster.tags()["synthetic"] == "True"
    digest = checksum(index)
    runner.run("report")
    assert checksum(index) == digest
    # A modified source fails its supplied checksum, rather than being fabricated.
    with cfg.data.sources["weather"].path.open("ab") as stream:
        stream.write(b"corrupt")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        runner.run("ingest")
