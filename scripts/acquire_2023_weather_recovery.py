"""Recover missing ERA5 containers through the original provider, after model freeze."""

from __future__ import annotations

import asyncio
import ctypes
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from omfiles import OmFileReaderAsync
from openmeteo_soil_api import CACHE, ENDPOINT, HOURS, START, STOP, OpenMeteoSoil

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import (
    PUBLIC,
    ROOT,
    complete,
    log,
    open_weather_series,
    permitted,
    save_npz,
)
from wildfire_kz.data.range_cache import RangeCachedS3

RUN = ROOT / "runs/public_hindcast"
RELEASE = RUN / "release.json"
MISSING_CHUNKS = [934, 935, 936, 937]
VARIABLES = [
    "temperature_2m",
    "dew_point_2m",
    "wind_u_component_10m",
    "wind_v_component_10m",
    "precipitation",
    "soil_moisture_0_to_7cm",
]
NAMES = ["tmax", "tmin", "temperature", "rh", "wind", "precip", "soil_moisture"]


def before_labels() -> None:
    permitted([2023], RELEASE)
    for year in [2023, 2024]:
        if (ROOT / f"data/real/normalized/detections_{year}.parquet").exists():
            raise PermissionError("Source recovery must finish before final labels are opened")


def daily_fields(
    temperature: np.ndarray,
    dewpoint: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    rain: np.ndarray,
    soil: np.ndarray,
    midnight: np.ndarray,
    days: int,
) -> dict[str, np.ndarray]:
    """The same UTC reducers, units and rain interval as the frozen native producer."""
    width = temperature.shape[0]

    def daily(array: np.ndarray, operation: str = "mean") -> np.ndarray:
        return getattr(np, operation)(array.reshape(width, days, 24), axis=-1).astype("float32")

    rh = 100 * np.exp(
        17.625 * dewpoint / (243.04 + dewpoint) - 17.625 * temperature / (243.04 + temperature)
    )
    return {
        "tmax": daily(temperature, "max"),
        "tmin": daily(temperature, "min"),
        "temperature": daily(temperature),
        "rh": daily(np.clip(rh, 0, 100)),
        "wind": daily(np.hypot(u, v)),
        "precip": daily(np.concatenate([rain[:, 1:], midnight], axis=-1), "sum"),
        "soil_moisture": daily(soil),
    }


class IncompleteSoil:
    """Temporary source absence stays NaN; no annual product is published this way."""

    def __init__(self, records: list[tuple[int, Any]]) -> None:
        self.records = records

    async def read_array(self, selection: tuple[Any, Any, slice]) -> np.ndarray:
        row, columns, times = selection
        start, stop = times.start or 0, times.stop or 8760
        result = np.full((columns.stop - columns.start, stop - start), np.nan, dtype="float32")
        semaphore = asyncio.Semaphore(4)

        async def read(offset: int, reader: Any) -> tuple[int, int, np.ndarray] | None:
            lo, hi = max(start, offset), min(stop, offset + reader.shape[-1])
            if hi <= lo:
                return None
            async with semaphore:
                values = await reader.read_array((row, columns, slice(lo - offset, hi - offset)))
            return lo, hi, values

        for item in await asyncio.gather(*(read(o, r) for o, r in self.records)):
            if item is not None:
                lo, hi, values = item
                result[:, lo - start : hi - start] = values
        return result

    def close(self) -> None:
        for _, reader in self.records:
            reader.close()


async def soil_series(fs: Any, provenance: list[dict[str, Any]]) -> IncompleteSoil:
    epoch = int(pd.Timestamp("2023-01-01").timestamp() // 3600)
    prefix = "openmeteo/data/copernicus_era5/soil_moisture_0_to_7cm"
    for chunk in MISSING_CHUNKS:
        try:
            await fs._info(f"{prefix}/chunk_{chunk}.om")
        except FileNotFoundError:
            continue
        raise RuntimeError("The supplier restored an object; prefer native acquisition")
    records = []
    for chunk in range(epoch // 504, (epoch + 8759) // 504 + 1):
        if chunk in MISSING_CHUNKS:
            continue
        key = f"{prefix}/chunk_{chunk}.om"
        reader = await OmFileReaderAsync.from_fsspec(fs, key)
        info = await fs._info(key)
        records.append((chunk * 504 - epoch, reader))
        provenance.append(
            {
                "source": "s3://" + key,
                "etag": info.get("ETag"),
                "provider_last_modified": str(info.get("LastModified")),
                "source_bytes": info["size"],
                "shape": reader.shape,
                "chunks": reader.chunks,
                "year_hour_offset": chunk * 504 - epoch,
            }
        )
    return IncompleteSoil(records)


def main() -> None:
    before_labels()
    target = PUBLIC / "weather/2023.npz"
    if complete(target):
        log("Verified existing 2023 annual weather; no source changed")
        return
    transport = OpenMeteoSoil()
    code_sha = checksum(Path(__file__))
    provenance: list[dict[str, Any]] = []
    dump_json(
        RUN / "progress.json",
        {
            "stage": "recover-final-soil-inputs",
            "started_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        },
    )

    async def acquire_native() -> None:
        fs = RangeCachedS3(
            anon=True,
            asynchronous=True,
            skip_instance_cache=True,
            config_kwargs={"max_pool_connections": 8},
        )
        readers: dict[str, Any] = {}
        try:
            for variable in VARIABLES[:-1]:
                readers[variable] = await open_weather_series(fs, variable, 2023, provenance)
            readers[VARIABLES[-1]] = await soil_series(fs, provenance)
            readers["next_rain"] = await open_weather_series(
                fs, "precipitation", 2024, provenance, stop_hour=1
            )
            for row in range(transport.y0, transport.y1):
                checkpoint = PUBLIC / f"weather/rows_2023/{row}.npz"
                if complete(checkpoint):
                    proof = json.loads(checkpoint.with_suffix(".sha256.json").read_text())
                    if proof.get("recovery_code_sha256") == code_sha:
                        continue
                used = transport.ix[transport.iy == row]
                if not len(used):
                    save_npz(
                        checkpoint,
                        **{
                            n: np.full((transport.x1 - transport.x0, 365), np.nan, dtype="float32")
                            for n in NAMES
                        },
                    )
                    continue
                left, right = int(used.min()), int(used.max()) + 1
                selection = (row, slice(left, right), slice(0, None))

                async def read(variable: str, selected: Any = selection) -> np.ndarray:
                    return (await readers[variable].read_array(selected)).astype(
                        "float32", copy=False
                    )

                arrays = await asyncio.gather(*(read(variable) for variable in VARIABLES))
                midnight = await readers["next_rain"].read_array(
                    (row, slice(left, right), slice(0, 1))
                )
                temperature, dewpoint, u, v, rain, soil = arrays
                values = daily_fields(temperature, dewpoint, u, v, rain, soil, midnight, 365)
                padded = {
                    n: np.full((transport.x1 - transport.x0, 365), np.nan, dtype="float32")
                    for n in NAMES
                }
                for name, array in values.items():
                    padded[name][left - transport.x0 : right - transport.x0] = array
                save_npz(checkpoint, **padded)
                dump_json(
                    checkpoint.with_suffix(".sha256.json"),
                    {
                        "sha256": checksum(checkpoint),
                        "recovery_code_sha256": code_sha,
                        "pending_observed_api_soil": True,
                    },
                )
                log(
                    f"Native ERA5 2023 prefetched latitude {row - transport.y0 + 1}/{transport.y1 - transport.y0}"
                )
        finally:
            for reader in readers.values():
                reader.close()
            if fs._s3creator is not None:
                await fs._s3creator.__aexit__(None, None, None)

    asyncio.run(acquire_native())
    gap = CACHE / "hourly_gap.npy"
    last_log = 0.0
    while not complete(gap) or not gap.with_suffix(".provenance.json").is_file():
        if time.time() - last_log > 50:
            log("Native fields ready; waiting for quota-compliant observed soil download")
            last_log = time.time()
        time.sleep(10)
    before_labels()
    validation = json.loads((CACHE / "development_validation.json").read_text())
    if not validation["passed"] or validation["transport_code_sha256"] != transport.code_sha256:
        raise PermissionError("Original-provider source equivalence is not verified")
    source_proof = json.loads(gap.with_suffix(".provenance.json").read_text())
    if source_proof["transport_code_sha256"] != transport.code_sha256:
        raise ValueError("Observed soil transport changed")
    hourly = np.load(gap, mmap_mode="r", allow_pickle=False)
    expected = (transport.y1 - transport.y0, transport.x1 - transport.x0, HOURS)
    if hourly.shape != expected:
        raise ValueError("Native soil geometry or UTC time coverage differs")
    daily = hourly.reshape(*expected[:2], 84, 24).mean(axis=-1)
    output = {n: np.full((*expected[:2], 365), np.nan, dtype="float32") for n in NAMES}
    for row in range(transport.y0, transport.y1):
        with np.load(PUBLIC / f"weather/rows_2023/{row}.npz") as checkpoint:
            for name in NAMES:
                output[name][row - transport.y0] = checkpoint[name]
    first = (pd.Timestamp(START) - pd.Timestamp("2023-01-01")).days
    output["soil_moisture"][:, :, first : first + 84] = daily
    if np.nanmin(output["precip"]) < -1e-5:
        raise ValueError("Negative deaccumulated precipitation")
    before_labels()
    save_npz(
        target,
        **output,
        first_day=np.array("2023-01-01"),
        native_cell_y=(transport.iy - transport.y0).astype("uint16"),
        native_cell_x=(transport.ix - transport.x0).astype("uint16"),
        y0=transport.y0,
        x0=transport.x0,
    )
    provenance.append(
        {
            "source": ENDPOINT,
            "parameter": "ERA5 soil_moisture_0_to_7cm",
            "unavailable_s3_chunks": MISSING_CHUNKS,
            "first_day": START,
            "last_day": STOP,
            "hourly_selection_sha256": checksum(gap),
            "selection_provenance_sha256": checksum(gap.with_suffix(".provenance.json")),
            "acquisition_plan_sha256": checksum(CACHE / "acquisition_plan.json"),
            "development_validation": validation,
            "source_adapter_code_sha256": transport.code_sha256,
        }
    )
    dump_json(
        target.with_suffix(".provenance.json"),
        {
            "sources": provenance,
            "provider": "Open-Meteo AWS ERA5 and original-provider ERA5 API",
            "resolution_deg": 0.25,
            "weather_release_lag_days": 5,
            "reprocessed_hindcast": True,
            "units": {
                "tmax": "C",
                "tmin": "C",
                "wind": "m/s",
                "rh": "%",
                "precip": "mm/calendar UTC day",
                "soil_moisture": "m3/m3",
            },
            "source_recovery_code_sha256": code_sha,
            "model_release_sha256": checksum(RELEASE),
            "model_or_feature_rules_changed": False,
            "test_labels_accessed": False,
        },
    )
    permitted([2023], RELEASE)
    log(
        "2023 weather registered from real original-provider observations; frozen artifacts unchanged"
    )


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    execution_state = ctypes.windll.kernel32.SetThreadExecutionState
    execution_state.argtypes = [ctypes.c_uint]
    execution_state.restype = ctypes.c_uint
    execution_state(0x80000001)
    try:
        main()
    finally:
        execution_state(0x80000000)
