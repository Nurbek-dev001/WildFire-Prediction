"""Guard boundaries and source-time logic for the separately documented variant."""

import asyncio
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import s3fs
from sklearn.metrics import average_precision_score

from wildfire_kz.data import checksum, dump_json, public_study
from wildfire_kz.data.public_predictors import WeatherSeries, permitted
from wildfire_kz.data.range_cache import RangeCachedS3
from wildfire_kz.public_evaluation import weighted_ap_sorted


def test_release_requires_model_calibration_and_threshold_hashes(tmp_path: Path):
    with pytest.raises(PermissionError):
        permitted([2023])
    files = ["models.joblib", "calibrators.joblib", "frozen.json"]
    for filename in files:
        (tmp_path / filename).write_text(filename)
    hashes = {f: checksum(tmp_path / f) for f in files}
    release = tmp_path / "release.json"
    dump_json(
        release,
        {
            "status": "frozen_before_final_evaluation",
            "synthetic": False,
            "model_file": "models.joblib",
            "model_sha256": hashes["models.joblib"],
            "artifact_hashes": hashes,
        },
    )
    permitted([2023, 2024], release)
    (tmp_path / "calibrators.joblib").write_text("changed after freeze")
    with pytest.raises(PermissionError, match="changed"):
        permitted([2023], release)


def test_utc_chunk_offsets_do_not_shift_year_boundary():
    class Reader:
        def __init__(self, a):
            self.a = a
            self.shape = a.shape

        async def read_array(self, key):
            return self.a[key]

    # First object starts two hours before the requested year.
    series = WeatherSeries(
        [(-2, Reader(np.array([[[98, 99, 0, 1]]]))), (2, Reader(np.array([[[2, 3, 4, 5]]])))], 6
    )
    result = asyncio.run(series.read_array((0, slice(None), slice(0, 5))))
    np.testing.assert_array_equal(result, [[0, 1, 2, 3, 4]])


def test_weather_observation_lag_is_strict_and_windows_cross_year(monkeypatch):
    def weather(year):
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        values = np.arange(366 if year == 2020 else 365, dtype="float32")[None, None, :]
        arrays = {n: values for n in public_study.WEATHER + ["temperature"]}
        return arrays, start, np.array([0]), np.array([0])

    monkeypatch.setattr(public_study, "weather_arrays", weather)
    result = public_study.meteorology(np.array([0]), pd.DatetimeIndex(["2021-01-08"], tz="UTC"))
    # D+1+5 must be strictly before Jan8 => latest observation Jan1.
    assert result["tmax"][0] == 0
    assert result["precip_7d"][0] == sum(range(360, 366))
    assert result["temperature_7d"][0] == pytest.approx(sum(range(360, 366)) / 7)


def test_future_predictor_read_rejected_before_file_lookup():
    with pytest.raises(PermissionError):
        public_study.cover_year(2022)
    with pytest.raises(PermissionError):
        public_study.feature_frame(
            pd.DataFrame({"day": pd.to_datetime(["2023-05-01"], utc=True), "cell_index": [0]})
        )


def test_cached_bootstrap_ap_preserves_ties_and_design_weights():
    y = np.array([0, 1, 1, 0, 1, 0])
    p = np.array([0.4, 0.4, 0.2, 0.2, 0.1, 0.1])
    w = np.array([100.0, 1.0, 1.0, 0.0, 1.0, 200.0])
    order = np.argsort(-p, kind="stable")
    endpoints = np.r_[np.flatnonzero(np.diff(p[order]) != 0), len(p) - 1]
    assert weighted_ap_sorted(y, w, order, endpoints) == pytest.approx(
        average_precision_score(y, p, sample_weight=w)
    )


def test_range_cache_preserves_bytes_and_coalesces_concurrent_reads(monkeypatch):
    payload = b"abcdefghijklmnopqrstuvwxyz"
    requests = []

    async def info(self, path):
        return {"size": len(payload)}

    async def fetch(self, path, start=None, end=None):
        requests.append((start, end))
        await asyncio.sleep(0)
        return payload[start:end]

    monkeypatch.setattr(s3fs.S3FileSystem, "_info", info)
    monkeypatch.setattr(s3fs.S3FileSystem, "_cat_file", fetch)
    fs = RangeCachedS3(anon=True, asynchronous=True, skip_instance_cache=True)
    fs.block_bytes = 8

    async def read():
        return await asyncio.gather(
            fs._cat_file("public-object", 2, 15), fs._cat_file("public-object", 3, 12)
        )

    a, b = asyncio.run(read())
    assert a == payload[2:15] and b == payload[3:12]
    assert sorted(requests) == [(0, 8), (8, 16)]
    assert sum(map(len, fs.blocks.values())) <= fs.maximum_blocks * fs.block_bytes
