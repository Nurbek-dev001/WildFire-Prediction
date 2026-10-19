"""Complete a final-only weather boundary after model freeze; preserve calibration inputs."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import (
    PUBLIC,
    complete,
    log,
    open_weather_series,
    permitted,
    save_npz,
)
from wildfire_kz.data.public_study import FEATURES, RUN, feature_frame, weather_arrays
from wildfire_kz.data.range_cache import RangeCachedS3


def main() -> None:
    release = RUN / "release.json"
    permitted([2023], release)
    source = PUBLIC / "weather/2022.npz"
    audit_path = RUN / "final_weather_boundary.json"
    calibration = RUN / "features/2022_evaluation.parquet"
    if audit_path.is_file():
        audit = json.loads(audit_path.read_text())
        if (
            checksum(source) != audit["final_weather_sha256"]
            or checksum(RUN / audit["frozen_backup"]) != audit["frozen_weather_sha256"]
            or checksum(calibration) != audit["calibration_feature_table_sha256"]
        ):
            raise ValueError("Final boundary inputs changed")
        log("Verified final weather boundary and unchanged calibration feature table")
        return
    registry = json.loads((RUN / "source_registry.json").read_text())
    expected = next(r["sha256"] for r in registry["sources"] if r["path"] == "weather/2022.npz")
    if not complete(source) or checksum(source) != expected:
        raise ValueError("Expected the unmodified, frozen calibration-year source")
    backup = RUN / "frozen_inputs/weather_2022_before_final_boundary.npz"
    backup.parent.mkdir(exist_ok=True)
    if not backup.exists():
        shutil.copyfile(source, backup)
    if checksum(backup) != expected:
        raise ValueError("Frozen weather backup differs")
    with np.load(source) as src:
        arrays = {name: src[name].copy() for name in src.files}
    ny, nx = arrays["precip"].shape[:2]
    y0, x0 = int(arrays["y0"]), int(arrays["x0"])
    provenance: list[dict] = []

    async def acquire() -> np.ndarray:
        fs = RangeCachedS3(
            anon=True,
            asynchronous=True,
            skip_instance_cache=True,
            config_kwargs={"max_pool_connections": 8},
        )
        # ERA5 timestamps end the precipitation interval. Dec31 needs 23 hours
        # within 2022 plus Jan1 2023 00:00; that final hour was sealed earlier.
        reader = None
        result = np.full((ny, nx), np.nan, dtype="float32")
        try:
            reader = await open_weather_series(
                fs, "precipitation", 2022, provenance, first_hour=8737, stop_hour=8761
            )
            for row in range(ny):
                hourly = await reader.read_array((y0 + row, slice(x0, x0 + nx), slice(8737, 8761)))
                result[row] = hourly.astype("float32").sum(axis=-1)
        finally:
            if reader is not None:
                reader.close()
            if fs._s3creator is not None:
                await fs._s3creator.__aexit__(None, None, None)
        return result

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    checkpoint = RUN / "final_inputs/rain_2022_12_31.npz"
    if complete(checkpoint):
        with np.load(checkpoint) as cached:
            rain = cached["precip"].copy()
        provenance = json.loads(checkpoint.with_suffix(".provenance.json").read_text())
    else:
        for attempt in range(6):
            try:
                rain = asyncio.run(acquire())
                break
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(15)
        save_npz(checkpoint, precip=rain)
        dump_json(checkpoint.with_suffix(".provenance.json"), provenance)
    rain = np.where(np.isfinite(arrays["tmax"][:, :, -1]), rain, np.nan)
    if not np.isfinite(rain).any() or np.nanmin(rain) < 0:
        raise ValueError("Invalid final-boundary precipitation")
    calibration_hash = checksum(calibration)
    arrays["precip"][:, :, -1] = rain
    save_npz(source, **arrays)
    # The changed day can first enter target Jan7 2023. Recompute actual 2022
    # predictor columns to verify that no calibration covariate was affected.
    try:
        reference = pd.read_parquet(calibration)
        weather_arrays.cache_clear()
        rebuilt = feature_frame(reference[["cell_index", "day"]])
        np.testing.assert_allclose(
            rebuilt[FEATURES], reference[FEATURES], atol=0, rtol=0, equal_nan=True
        )
        if checksum(calibration) != calibration_hash:
            raise ValueError("Calibration feature table changed")
    except Exception:
        shutil.copyfile(backup, source)
        dump_json(
            source.with_suffix(".sha256.json"), {"sha256": expected, "bytes": source.stat().st_size}
        )
        raise
    permitted([2023], release)
    dump_json(
        audit_path,
        {
            "completed_utc": datetime.now(UTC).isoformat(),
            "release_sha256": checksum(release),
            "changed_observation_day": "2022-12-31",
            "changed_variable": "precip",
            "first_affected_target_day": "2023-01-07",
            "frozen_weather_sha256": expected,
            "frozen_backup": str(backup.relative_to(RUN)),
            "final_weather_sha256": checksum(source),
            "calibration_feature_table_sha256": calibration_hash,
            "calibration_predictor_columns_verified_identical": True,
            "models_calibrators_thresholds_unchanged": True,
            "source_objects": provenance,
            "reason": "complete final-only predictors after freeze; preserve the exact original calibration-year source snapshot",
        },
    )
    log(
        "Final-only weather boundary completed; all actual 2022 calibration predictor columns are unchanged"
    )


if __name__ == "__main__":
    main()
