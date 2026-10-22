"""Recover observed ERA5 soil from the original provider's free API, within quotas."""

from __future__ import annotations

import ctypes
import gzip
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import numpy as np
import pandas as pd

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import (
    PUBLIC,
    ROOT,
    complete,
    geography,
    log,
    permitted,
    reserve,
)

CACHE = PUBLIC / "source_adapters/openmeteo_soil_api"
RELEASE = ROOT / "runs/public_hindcast/release.json"
ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
FIELD = "soil_moisture_0_to_7cm"
START, STOP = "2023-09-14", "2023-12-06"
HOURS = 84 * 24
LIMITS = [(60, 500), (3600, 4500), (86400, 9000)]


def budget_wait(history: list[dict[str, Any]], cost: int, now: float) -> float:
    delays = [h["cooldown_until"] - now for h in history if h.get("cooldown_until", 0) > now]
    for window, limit in LIMITS:
        active = sorted((h for h in history if now - h["time"] < window), key=lambda h: h["time"])
        total = sum(h["upper_bound_calls"] for h in active)
        for event in active:
            if total + cost <= limit:
                break
            total -= event["upper_bound_calls"]
            delays.append(max(0.0, event["time"] + window - now + 0.1))
    return max(delays, default=0.0)


def reserve_calls(cost: int) -> None:
    path = CACHE / "api_budget.json"
    history: list[dict[str, Any]] = (
        json.loads(path.read_text())
        if path.exists()
        else [
            {
                "time": time.time(),
                "upper_bound_calls": 20,
                "purpose": "conservative reserve for preceding manual diagnostic requests",
            }
        ]
    )
    last_log = 0.0
    while (delay := budget_wait(history, cost, time.time())) > 0:
        if time.time() - last_log > 50:
            log(f"Free API quota pause: {delay:.0f}s; checkpoints saved, no paid request")
            last_log = time.time()
        time.sleep(min(delay, 30))
    history = [
        h
        for h in history
        if time.time() - h["time"] < 86400 or h.get("cooldown_until", 0) > time.time()
    ]
    history.append(
        {"time": time.time(), "upper_bound_calls": cost, "purpose": "public ERA5 soil observations"}
    )
    dump_json(path, history)


def parse_rows(data: Any, points: np.ndarray, start: str, stop: str) -> np.ndarray:
    rows = data if isinstance(data, list) else [data]
    expected = (
        pd.date_range(start, pd.Timestamp(stop) + pd.Timedelta(hours=23), freq="h")
        .strftime("%Y-%m-%dT%H:%M")
        .tolist()
    )
    if len(rows) != len(points):
        raise ValueError("API location count differs")
    values = []
    for row, (iy, ix) in zip(rows, points, strict=True):
        if row.get("error"):
            raise ValueError(str(row))
        if (
            abs(row["latitude"] - (iy * 0.25 - 90)) > 1e-4
            or abs(row["longitude"] - (ix * 0.25 - 180)) > 1e-4
        ):
            raise ValueError("API selected a different native grid point")
        if row["utc_offset_seconds"] != 0 or row["hourly"]["time"] != expected:
            raise ValueError("API UTC hours differ")
        if row["hourly_units"][FIELD] != "m³/m³":
            raise ValueError("API soil units differ")
        array = np.asarray(row["hourly"][FIELD], dtype="float32")
        if array.shape != (len(expected),) or np.isinf(array).any():
            raise ValueError("API hourly soil array invalid")
        values.append(array)
    return np.stack(values)


def request(points: np.ndarray, start: str, stop: str, tag: str, code_sha: str) -> np.ndarray:
    path = CACHE / "responses" / f"{tag}.json.gz"
    params = {
        "latitude": ",".join(str(y * 0.25 - 90) for y, _ in points),
        "longitude": ",".join(str(x * 0.25 - 180) for _, x in points),
        "elevation": ",".join("nan" for _ in points),
        "start_date": start,
        "end_date": stop,
        "hourly": FIELD,
        "models": "era5",
        "timezone": "UTC",
        "cell_selection": "nearest",
    }
    url = ENDPOINT + "?" + urlencode(params, safe=",")
    if complete(path):
        proof = json.loads(path.with_name(path.name + ".provenance.json").read_text())
        if proof["url"] != url or proof["transport_code_sha256"] != code_sha:
            raise ValueError("Cached source response belongs to another request or transport")
        raw = gzip.decompress(path.read_bytes())
        if hashlib.sha256(raw).hexdigest() != proof["uncompressed_sha256"]:
            raise ValueError("Raw source response checksum mismatch")
        return parse_rows(json.loads(raw), points, start, stop)
    path.parent.mkdir(exist_ok=True, parents=True)
    headers = path.with_suffix(".headers.txt")
    for attempt in range(3):
        reserve_calls(len(points))
        result = subprocess.run(
            [
                "curl.exe",
                "--silent",
                "--show-error",
                "--compressed",
                "--max-time",
                "120",
                "--max-filesize",
                "20000000",
                "--dump-header",
                str(headers),
                url,
            ],
            capture_output=True,
            check=False,
        )
        try:
            data = json.loads(result.stdout)
        except (ValueError, UnicodeDecodeError):
            if attempt == 2:
                raise RuntimeError("Public API response was incomplete") from None
            time.sleep(10)
            continue
        if isinstance(data, dict) and data.get("error"):
            reason = str(data.get("reason", ""))
            if "limit" in reason.lower():
                # Stop the current invocation and preserve a conservative server
                # cooldown for the next run; never retry around a provider limit.
                window = (
                    86400
                    if any(term in reason.lower() for term in ["daily", "day"])
                    else 3600
                    if "hour" in reason.lower()
                    else 60
                )
                history = json.loads((CACHE / "api_budget.json").read_text())
                history.append(
                    {
                        "time": time.time(),
                        "upper_bound_calls": 0,
                        "cooldown_until": time.time() + window + 1,
                        "purpose": "server quota cooldown",
                    }
                )
                dump_json(CACHE / "api_budget.json", history)
            raise RuntimeError("Public API rejected request: " + reason)
        values = parse_rows(data, points, start, stop)
        reserve()
        path.write_bytes(gzip.compress(result.stdout, mtime=0))
        dump_json(path.with_name(path.name + ".sha256.json"), {"sha256": checksum(path)})
        dump_json(
            path.with_name(path.name + ".provenance.json"),
            {
                "url": url,
                "retrieved_utc": datetime.now(UTC).isoformat(),
                "provider": ENDPOINT,
                "transport_code_sha256": code_sha,
                "uncompressed_sha256": hashlib.sha256(result.stdout).hexdigest(),
                "equivalent_calls_upper_bound": len(points),
                "observations": "actual hourly ERA5 swvl1, no imputation",
            },
        )
        return values
    raise RuntimeError("Source request exhausted bounded retries")


class OpenMeteoSoil:
    def __init__(self) -> None:
        permitted([2023], RELEASE)
        CACHE.mkdir(exist_ok=True, parents=True)
        self.code_sha256 = checksum(Path(__file__))
        _, lon, lat = geography()
        self.iy = np.rint((lat + 90) / 0.25).astype(int)
        self.ix = np.rint((lon + 180) / 0.25).astype(int)
        self.y0, self.y1 = int(self.iy.min()), int(self.iy.max()) + 1
        self.x0, self.x1 = int(self.ix.min()), int(self.ix.max()) + 1
        self.points = np.unique(np.stack([self.iy, self.ix], axis=1), axis=0)
        self.plan = {
            "transport_code_sha256": self.code_sha256,
            "model_release_sha256": checksum(RELEASE),
            "native_points_sha256": hashlib.sha256(self.points.astype("<i4").tobytes()).hexdigest(),
            "native_points": len(self.points),
            "start_utc": START,
            "last_day_utc": STOP,
            "parameter": FIELD,
            "model": "era5",
            "timezone": "UTC",
            "grid_selection": "nearest",
            "model_and_feature_rules_changed": False,
            "quota_limits": [list(v) for v in LIMITS],
        }
        plan_path = CACHE / "acquisition_plan.json"
        if plan_path.exists():
            if json.loads(plan_path.read_text()) != self.plan:
                raise ValueError("An existing acquisition plan differs; refuse hidden changes")
        else:
            for year in [2023, 2024]:
                if (ROOT / f"data/real/normalized/detections_{year}.parquet").exists():
                    raise PermissionError(
                        "A new adapter must be declared before final label access"
                    )
            dump_json(plan_path, self.plan)

    def validate(self) -> Path:
        output = CACHE / "development_validation.json"
        if output.exists():
            previous = json.loads(output.read_text())
            if previous["transport_code_sha256"] != self.code_sha256 or not previous["passed"]:
                raise ValueError("Source validation does not match this transport")
            return output
        selected = np.sort(np.random.default_rng(42).choice(len(self.points), 200, replace=False))
        points = self.points[selected]
        records: list[dict[str, Any]] = []
        with np.load(PUBLIC / "weather/2021.npz") as reference:
            for day in ["2021-10-01", "2021-12-01"]:
                parts = [
                    request(
                        points[k : k + 50], day, day, f"validation_{day}_{k:04d}", self.code_sha256
                    )
                    for k in range(0, len(points), 50)
                ]
                hourly = np.concatenate(parts)
                actual = np.clip(hourly.mean(axis=-1), 0, 1)
                wanted = reference["soil_moisture"][
                    points[:, 0] - self.y0,
                    points[:, 1] - self.x0,
                    (pd.Timestamp(day) - pd.Timestamp("2021-01-01")).days,
                ]
                wanted = np.clip(wanted, 0, 1)
                if not np.array_equal(np.isfinite(actual), np.isfinite(wanted)):
                    raise ValueError("API mandatory-data coverage differs")
                finite = np.isfinite(wanted)
                errors = np.abs(actual[finite] - wanted[finite])
                records.append(
                    {
                        "day": day,
                        "native_points": len(points),
                        "maximum_absolute_difference": float(errors.max()),
                        "mean_absolute_difference": float(errors.mean()),
                    }
                )
        passed = all(row["maximum_absolute_difference"] <= 1e-6 for row in records)
        dump_json(
            output,
            {
                "passed": passed,
                "development_only": True,
                "test_labels_accessed": False,
                "transport_code_sha256": self.code_sha256,
                "tolerance_m3_m3": 1e-6,
                "days": records,
            },
        )
        if not passed:
            raise ValueError("Original-provider API does not reproduce the training archive")
        log("Original-provider API verified on 200 native points in two training days")
        return output

    def acquire(self) -> Path:
        self.validate()
        for k in range(0, len(self.points), 50):
            request(self.points[k : k + 50], START, STOP, f"gap_{k:04d}", self.code_sha256)
            log(
                f"Observed API soil: {min(k + 50, len(self.points))}/{len(self.points)} native points"
            )
        target = CACHE / "hourly_gap.npy"
        if complete(target):
            return target
        reserve()
        working = target.with_suffix(".working")
        output = np.lib.format.open_memmap(
            working, mode="w+", dtype="float32", shape=(self.y1 - self.y0, self.x1 - self.x0, HOURS)
        )
        output[:] = np.nan
        for k in range(0, len(self.points), 50):
            points = self.points[k : k + 50]
            values = request(points, START, STOP, f"gap_{k:04d}", self.code_sha256)
            output[points[:, 0] - self.y0, points[:, 1] - self.x0, :] = values
        output.flush()
        del output
        working.replace(target)
        dump_json(target.with_name(target.name + ".sha256.json"), {"sha256": checksum(target)})
        dump_json(
            target.with_suffix(".provenance.json"),
            {
                **self.plan,
                "units": "m3/m3",
                "hours": HOURS,
                "start": "2023-09-14T00:00:00Z",
                "stop_exclusive": "2023-12-07T00:00:00Z",
                "development_validation_sha256": checksum(self.validate()),
                "source_payloads": [
                    {"path": p.relative_to(ROOT).as_posix(), "sha256": checksum(p)}
                    for p in sorted((CACHE / "responses").glob("gap_*.json.gz"))
                ],
                "outside_required_country_native_points": "NaN, never used by the national model",
            },
        )
        log("All missing ERA5 soil observations recovered from the original public provider")
        return target


if __name__ == "__main__":
    execution_state = ctypes.windll.kernel32.SetThreadExecutionState
    execution_state.argtypes = [ctypes.c_uint]
    execution_state.restype = ctypes.c_uint
    execution_state(0x80000001)
    try:
        OpenMeteoSoil().acquire()
    finally:
        execution_state(0x80000000)
