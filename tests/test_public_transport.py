"""Offline checks for the post-freeze original-provider input transport."""

import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def transport_modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("openmeteo_soil_api"), importlib.import_module(
        "acquire_2023_weather_recovery"
    )


def test_daily_recovery_preserves_utc_rain_interval_and_native_units(transport_modules):
    _, module = transport_modules
    temperature = np.arange(48, dtype="float32")[None, :]
    fields = module.daily_fields(
        temperature,
        temperature.copy(),
        np.full_like(temperature, 3),
        np.full_like(temperature, 4),
        temperature.copy(),
        np.full_like(temperature, 0.2),
        np.array([[48]], dtype="float32"),
        2,
    )
    np.testing.assert_array_equal(fields["precip"], [[300, 876]])
    np.testing.assert_array_equal(fields["wind"], [[5, 5]])
    np.testing.assert_array_equal(fields["rh"], [[100, 100]])
    np.testing.assert_array_equal(fields["tmax"], [[23, 47]])
    np.testing.assert_array_equal(fields["tmin"], [[0, 24]])
    np.testing.assert_allclose(fields["soil_moisture"], 0.2)


def test_source_api_rejects_wrong_coordinate_time_or_units_and_preserves_nodata(
    transport_modules,
):
    module, _ = transport_modules
    row = {
        "latitude": 50.0,
        "longitude": 70.0,
        "utc_offset_seconds": 0,
        "hourly_units": {module.FIELD: "m³/m³"},
        "hourly": {
            "time": pd.date_range("2021-12-01", periods=24, freq="h")
            .strftime("%Y-%m-%dT%H:%M")
            .tolist(),
            module.FIELD: [None] + [0.2] * 23,
        },
    }
    points = np.array([[560, 1000]])
    values = module.parse_rows(row, points, "2021-12-01", "2021-12-01")
    assert np.isnan(values[0, 0]) and values.shape == (1, 24)
    for changed in [
        {**row, "longitude": 70.25},
        {**row, "utc_offset_seconds": 18000},
        {**row, "hourly_units": {module.FIELD: "percent"}},
    ]:
        with pytest.raises(ValueError):
            module.parse_rows(changed, points, "2021-12-01", "2021-12-01")


def test_api_quota_wait_respects_hourly_weight_and_server_cooldown(transport_modules):
    module, _ = transport_modules
    now = 10000.0
    history = [
        {"time": now - 90, "upper_bound_calls": 4000},
        {"time": now - 20, "upper_bound_calls": 500},
    ]
    delay = module.budget_wait(history, 50, now)
    assert delay == pytest.approx(3510.1)
    assert module.budget_wait(history, 50, now + delay) == 0
    assert (
        module.budget_wait(
            [{"time": now, "upper_bound_calls": 0, "cooldown_until": now + 70}], 50, now
        )
        == 70
    )


def test_recovery_refuses_a_new_source_after_final_labels_opened(
    transport_modules,
    monkeypatch,
    tmp_path: Path,
):
    _, module = transport_modules
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "permitted", lambda *args: None)
    normalized = tmp_path / "data/real/normalized/detections_2023.parquet"
    normalized.parent.mkdir(parents=True)
    normalized.write_bytes(b"presence only; never parsed")
    with pytest.raises(PermissionError, match="before final labels"):
        module.before_labels()
