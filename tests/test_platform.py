"""Production-model selection, ensemble, explanations, forecasts and the platform API."""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from wildfire_kz.config.schema import Config
from wildfire_kz.explain.contributions import contributions
from wildfire_kz.forecast.engine import ForecastEngine, run_forecast
from wildfire_kz.models.pipelines import ModelSpec, fit_model, make_ensemble
from wildfire_kz.models.train import select_models
from wildfire_kz.paths import RunPaths
from wildfire_kz.platform.api import create_app
from wildfire_kz.splits.guard import TestSetAccessError
from wildfire_kz.utils.runtime import read_json

# ----------------------------------------------------------------------------- unit level


def _toy(n: int = 1500, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    z = rng.normal(size=n)
    logit = -3 + 1.5 * x - 0.8 * z
    return pd.DataFrame(
        {
            "x": np.where(rng.random(n) < 0.1, np.nan, x),
            "z": z,
            "lc_group": rng.choice(["forest", "cropland"], n),
            "label": (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int),
        }
    )


@pytest.fixture(scope="module")
def toy_models() -> dict[str, object]:
    cfg = Config.model_validate({"models": {"n_jobs": 1}})
    df = _toy()
    y, w = df["label"].to_numpy(), np.ones(len(df))
    feats, cats = ["x", "z", "lc_group"], ["lc_group"]
    out: dict[str, object] = {"df": df}
    for est, params in [
        ("logistic", {"C": 1.0}),
        ("xgboost", {"n_estimators": 30}),
        ("catboost", {"iterations": 30}),
    ]:
        out[est] = fit_model(ModelSpec(est, est, feats, cats, params), cfg, 0, df, y, w)
    return out


def test_ensemble_is_mean_of_member_logits(toy_models: dict[str, object]) -> None:
    df = toy_models["df"]
    ens = make_ensemble("ens", [toy_models["xgboost"], toy_models["catboost"]])  # type: ignore[list-item]
    expected = (
        toy_models["xgboost"].decision_logit(df)  # type: ignore[attr-defined]
        + toy_models["catboost"].decision_logit(df)
    ) / 2  # type: ignore[attr-defined]
    assert np.allclose(ens.decision_logit(df), expected)
    p = ens.predict_proba(df)
    assert np.allclose(p, 1 / (1 + np.exp(-expected)))


@pytest.mark.parametrize("name", ["logistic", "xgboost", "catboost", "ensemble"])
def test_contributions_are_additive_on_log_odds(toy_models: dict[str, object], name: str) -> None:
    df = toy_models["df"].head(200)
    if name == "ensemble":
        fm = make_ensemble("ens", [toy_models["xgboost"], toy_models["catboost"]])  # type: ignore[list-item]
    else:
        fm = toy_models[name]  # type: ignore[assignment]
    c = contributions(fm, df)  # type: ignore[arg-type]
    assert c.scale == "log-odds"
    assert set(c.values.columns) <= {"x", "z", "lc_group"}  # mapped back to source features
    recon = c.base_value + c.values.sum(axis=1).to_numpy()
    assert np.allclose(recon, fm.decision_logit(df), atol=1e-4)  # type: ignore[attr-defined]


def test_production_model_selected_on_development_scores_only() -> None:
    cfg = Config()
    results = {
        "logistic": {"cv_weighted_ap_mean": 0.10},
        "xgboost": {"cv_weighted_ap_mean": 0.12},
        "ensemble_trees": {"cv_weighted_ap_mean": 0.13},
        "seasonal_landcover": {"cv_weighted_ap_mean": 0.50},
    }  # baselines never promoted
    sel = select_models(cfg, results)
    assert sel["production_model"] == "ensemble_trees"
    assert sel["selected_tree_model"] == "xgboost"
    cfg_off = Config.model_validate({"models": {"ensemble": {"enabled": False}}})
    assert select_models(cfg_off, results)["production_model"] == "xgboost"


# ----------------------------------------------------------------------------- pipeline level


@pytest.fixture(scope="module")
def client(smoke: tuple[Config, RunPaths]) -> TestClient:
    cfg, _ = smoke
    return TestClient(create_app(cfg))


@pytest.mark.slow
def test_training_produced_ensemble_and_production_model(smoke: tuple[Config, RunPaths]) -> None:
    cfg, paths = smoke
    sel = read_json(paths.stage("train") / "selection.json")
    assert cfg.models.ensemble.name in sel["candidates_dev_cv_ap"]
    best = max(sel["candidates_dev_cv_ap"], key=sel["candidates_dev_cv_ap"].get)
    assert sel["production_model"] == best
    cal = read_json(paths.stage("calibrate") / "calibration_artifacts.json")
    assert cfg.models.ensemble.name in cal["models"]


@pytest.mark.slow
def test_forecast_writes_maps_and_respects_partition(smoke: tuple[Config, RunPaths]) -> None:
    cfg, paths = smoke
    out = run_forecast(cfg, paths, pd.Timestamp("2018-07-01").date())
    assert out["partition"] == "calibration" and out["predictors_up_to"] == "2018-06-30"
    d = paths.stage("forecast") / "20180701"
    cells = pd.read_parquet(d / "cells_20180701.parquet")
    assert cells["p"].between(0, 1).all() and cells["eligible"].any()
    assert (d / "prob_20180701.tif").exists() and (d / "class_20180701.qml").exists()


@pytest.mark.slow
def test_forecast_guard_for_test_years_without_evaluation(
    smoke: tuple[Config, RunPaths], tmp_path: object
) -> None:
    cfg, paths = smoke
    engine = ForecastEngine(cfg, paths)
    ledger = paths.stage("evaluate") / "final_evaluation_ledger.json"
    backup = ledger.read_bytes()
    ledger.unlink()
    try:
        with pytest.raises(TestSetAccessError):
            engine.check_allowed(pd.Timestamp(f"{cfg.splits.test_years[0]}-06-01"))
        engine.check_allowed(pd.Timestamp(f"{cfg.splits.calibration_years[0]}-06-01"))
    finally:
        ledger.write_bytes(backup)


@pytest.mark.slow
def test_api_endpoints(client: TestClient, smoke: tuple[Config, RunPaths]) -> None:
    _ = smoke
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["synthetic"] is True and all(h["stages"].values())
    card = client.get("/api/model").json()
    assert card["production_model"] in card["candidates_dev_cv_ap"]
    assert card["test_metrics"] is not None and card["calibration"]["tau"] > 0
    models = client.get("/api/models").json()
    assert sum(m["production"] for m in models) == 1
    assert client.get("/api/evaluation").status_code == 200
    days = client.get("/api/days").json()
    assert days, "map stage should have produced days"
    date = days[0]["date"]
    s = client.get(f"/api/days/{date}").json()
    assert len(s["class_counts"]) == len(s["class_labels"])
    (lat_s, lon_w), (lat_n, lon_e) = s["bounds_latlon"]
    assert lat_s < lat_n and lon_w < lon_e
    png = client.get(f"/api/days/{date}/overlay.png")
    assert png.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(png.content)).mode == "RGBA"
    top = client.get(f"/api/days/{date}/top?n=3").json()
    assert len(top) == 3 and top[0]["p"] >= top[-1]["p"]
    cell = client.get(
        f"/api/days/{date}/cell", params={"lat": top[0]["lat"], "lon": top[0]["lon"]}
    ).json()
    assert cell["cell_id"] == top[0]["cell_id"] and cell["p"] == pytest.approx(top[0]["p"])
    assert cell["explanation"]["drivers"] and "not a causal" in cell["explanation"]["note"]
    assert client.get(f"/api/days/{date}/cell", params={"lat": 0, "lon": 0}).status_code == 404
    assert client.get("/api/days/1999-01-01").status_code == 404
    assert client.get("/api/boundary").json()["type"] == "FeatureCollection"
    assert "Leaflet" in client.get("/vendor/leaflet/leaflet.js").text[:200]
    assert "<title>" in client.get("/").text


@pytest.mark.slow
def test_api_forecast_endpoint(client: TestClient, smoke: tuple[Config, RunPaths]) -> None:
    cfg, _ = smoke
    r = client.post("/api/forecast", params={"date": f"{cfg.splits.calibration_years[0]}-08-15"})
    assert r.status_code == 200 and r.json()["model"]
    assert any(d["source"] == "forecast" for d in client.get("/api/days").json())


@pytest.mark.slow
def test_export_site_snapshot(smoke: tuple[Config, RunPaths], tmp_path: object) -> None:
    from pathlib import Path

    from wildfire_kz.platform.static_site import export_site

    cfg, _ = smoke
    out = export_site(cfg, Path(str(tmp_path)) / "snap.html", step_days=60)
    html = out.read_text()
    assert "<title>Kazakhstan Fire Hazard Map</title>" in html
    assert "__DATA__" not in html and "data:image/png;base64," in html
    assert "SYNTHETIC" in html or '"synthetic":true' in html
