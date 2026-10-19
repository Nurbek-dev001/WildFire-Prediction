"""Export real, frozen, evaluated daily probabilities for the actual national grid."""

from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import rasterio

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import (
    geography,
    log,
    permitted,
    target_lattice,
)
from wildfire_kz.data.public_study import (
    RUN,
    feature_frame,
    industrial_cells,
    outcomes,
)


def export(destination: Path, *, dates: list[str] | None = None) -> None:
    """All dates are evaluated hindcasts; no synthetic probabilities or filled map cells."""
    release = RUN / "release.json"
    permitted([2023, 2024], release)
    evaluation = json.loads((RUN / "evaluate/complete.json").read_text())
    if evaluation["synthetic"] is not False or evaluation["release_sha256"] != checksum(release):
        raise PermissionError(
            "A completed matching final evaluation is required before map publication"
        )
    for filename, digest in evaluation["outputs"].items():
        if checksum(RUN / "evaluate" / filename) != digest:
            raise PermissionError(f"Final evaluation output changed: {filename}")
    frozen = json.loads((RUN / "frozen.json").read_text())
    selected = frozen["selected_model"]
    model = joblib.load(RUN / "models.joblib")[selected]
    calibration = joblib.load(RUN / "calibrators.joblib")[selected]
    grid, _, _ = geography()
    ids = pd.Index(grid.cell_id)
    records = list(struct.iter_unpack("<hhfffH8H", (destination / "cells.bin").read_bytes()))
    platform_ids = [f"g5000_{r[0]}_{r[1]}" for r in records]
    order = ids.get_indexer(platform_ids)
    if len(order) != len(ids) or np.any(order < 0) or len(np.unique(order)) != len(ids):
        raise ValueError("Platform cells must match the complete actual national grid")
    raw_events = pd.read_parquet(outcomes(2024, release), columns=["cell_id", "timestamp"])
    previous = raw_events.timestamp
    industrial = ids.isin(industrial_cells())
    days = dates or [d.strftime("%Y-%m-%d") for d in pd.date_range("2023-01-01", "2024-12-31")]
    output = destination / "predictions"
    output.mkdir(exist_ok=True, parents=True)
    raster_directory = RUN / "maps"
    raster_directory.mkdir(exist_ok=True, parents=True)
    shape, transform, rows, cols = target_lattice(grid)
    assets: dict[str, Any] = {}
    for iso in days:
        day = pd.Timestamp(iso, tz="UTC")
        if day.year not in [2023, 2024]:
            raise ValueError("The public map export is restricted to final-evaluated dates")
        payload_path = output / f"{iso}.f32.gz"
        proof_path = raster_directory / f"{iso}.json"
        if payload_path.is_file() and proof_path.is_file():
            proof = json.loads(proof_path.read_text())
            if proof["payload_sha256"] == checksum(payload_path) and proof[
                "release_sha256"
            ] == checksum(release):
                assets[iso] = proof
                continue
        keys = pd.DataFrame({"cell_index": np.arange(len(ids), dtype="int32"), "day": day})
        frame = feature_frame(keys, release)
        finite = frame.required_features_valid.to_numpy()
        recent = set(
            raw_events.loc[(previous >= day - pd.Timedelta(hours=48)) & (previous < day), "cell_id"]
        )
        eligible = finite & ~industrial & ~ids.isin(recent)
        probabilities = np.full(len(ids), np.nan, dtype="float32")
        probabilities[eligible] = calibration.predict(model.predict(frame.loc[eligible])).astype(
            "float32"
        )
        if ((probabilities[eligible] < 0) | (probabilities[eligible] > 1)).any():
            raise ValueError("Invalid model probability")
        raster_path = raster_directory / f"probability_{iso}.tif"
        image = np.full(shape, -9999, dtype="float32")
        image[rows[eligible], cols[eligible]] = probabilities[eligible]
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=shape[1],
            height=shape[0],
            count=1,
            dtype="float32",
            crs=grid.crs,
            transform=transform,
            nodata=-9999,
            compress="deflate",
            predictor=3,
        ) as raster:
            raster.write(image, 1)
            raster.update_tags(
                synthetic="False",
                model=selected,
                target_day=iso,
                variant="public_reprocessed_hindcast",
                release_sha256=checksum(release),
            )
        # IEEE float32 preserves calibrated values; NaN is missing, never a zero-risk claim.
        payload_path.write_bytes(
            gzip.compress(probabilities[order].astype("<f4").tobytes(), mtime=0)
        )
        proof = {
            "target_day": iso,
            "synthetic": False,
            "model": selected,
            "format": "little_endian_float32_gzip",
            "count": len(ids),
            "finite_cells": int(eligible.sum()),
            "retrospective": True,
            "payload_sha256": checksum(payload_path),
            "raster_sha256": checksum(raster_path),
            "release_sha256": checksum(release),
        }
        dump_json(proof_path, proof)
        assets[iso] = proof
        log(
            f"map {iso}: {eligible.sum():,} actual probabilities, {payload_path.stat().st_size:,} bytes"
        )
    manifest = {
        "ready": True,
        "synthetic": False,
        "model": selected,
        "available_days": sorted(assets),
        "format": "little_endian_float32_gzip",
        "retrospective": True,
        "missing_sources": [],
        "holdout_sealed": False,
        "evaluation_released": True,
        "release_sha256": checksum(release),
        "threshold": frozen["thresholds"][selected],
        "boundaries": frozen["map_boundaries"][selected],
        "prediction_assets": assets,
        "test_metrics": evaluation["metrics"],
        "test_years": [2023, 2024],
        "selection_years": [2015, 2021],
        "calibration_year": 2022,
        "message": "Реальная модель на открытых данных · ретроспективный эксперимент",
        "operational_validation": False,
    }
    dump_json(destination / "forecast-manifest.json", manifest)
    permitted([2023, 2024], release)
