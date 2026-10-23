"""Export real, frozen, evaluated daily probabilities for the actual national grid."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import rasterio

from wildfire_kz import public_payloads
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

# This exact previous exporter has identical predictions for nonempty grids.
# Its original per-day code hash is retained, and both files are verified when
# resuming. Remove this compatibility entry if valid-cell computation changes.
NONEMPTY_LEGACY_EXPORTER = "a334906a291ffc60c45c2102e1c901be3363b57693221f8ba744cf04fe8b584c"
NODATA_LEGACY_EXPORTER = "7a2e07854ce2561b729d4f43b01854eda18f2e549451d6728d735e00498df711"


def calibrated_grid(
    frame: pd.DataFrame, eligible: np.ndarray, model: Any, calibration: Any
) -> np.ndarray:
    """An unavailable country-day stays entirely nodata; never infer on zero rows."""
    probabilities = np.full(len(frame), np.nan, dtype="float32")
    if eligible.any():
        probabilities[eligible] = calibration.predict(model.predict(frame.loc[eligible])).astype(
            "float32"
        )
    return probabilities


def reusable_map(
    proof: dict[str, Any], payload: Path, raster: Path, release_digest: str, exporter_digest: str
) -> bool:
    """Preserve transparent provenance for unchanged, checksum-verified old maps."""
    producer = proof.get("exporter_code_sha256")
    compatible = producer in {exporter_digest, NODATA_LEGACY_EXPORTER} or (
        producer == NONEMPTY_LEGACY_EXPORTER and proof.get("finite_cells", 0) > 0
    )
    return bool(
        compatible
        and proof.get("release_sha256") == release_digest
        and payload.is_file()
        and raster.is_file()
        and checksum(payload) == proof.get("payload_sha256")
        and checksum(raster) == proof.get("raster_sha256")
    )


def export(destination: Path, *, dates: list[str] | None = None) -> None:
    """All dates are evaluated hindcasts; no synthetic probabilities or filled map cells."""
    release = RUN / "release.json"
    exporter_digest = checksum(Path(__file__))
    transport_digest = checksum(Path(public_payloads.__file__))
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
            if reusable_map(
                proof,
                payload_path,
                raster_directory / f"probability_{iso}.tif",
                checksum(release),
                exporter_digest,
            ):
                if proof["format"] != public_payloads.FORMAT:
                    original = payload_path.read_bytes()
                    values = public_payloads.decode(original, proof["format"])
                    packed = public_payloads.encode(values)
                    if (
                        public_payloads.decode(packed, public_payloads.FORMAT).tobytes()
                        != values.tobytes()
                    ):
                        raise ValueError("Lossless probability transport changed bits")
                    backup = RUN / "source_checks/payloads_before_shuffle" / payload_path.name
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    if backup.is_file() and checksum(backup) != proof["payload_sha256"]:
                        raise ValueError("Original payload backup differs")
                    if not backup.is_file():
                        backup.write_bytes(original)
                    temporary = payload_path.with_suffix(".working")
                    temporary.write_bytes(packed)
                    temporary.replace(payload_path)
                    proof.update(
                        format=public_payloads.FORMAT,
                        lossless_source_payload_sha256=proof["payload_sha256"],
                        payload_sha256=checksum(payload_path),
                        payload_transport_code_sha256=transport_digest,
                    )
                    dump_json(proof_path, proof)
                    log(f"lossless map transport {iso}: {len(original):,} -> {len(packed):,} bytes")
                assets[iso] = proof
                continue
        keys = pd.DataFrame({"cell_index": np.arange(len(ids), dtype="int32"), "day": day})
        frame = feature_frame(keys, release)
        finite = frame.required_features_valid.to_numpy()
        recent = set(
            raw_events.loc[(previous >= day - pd.Timedelta(hours=48)) & (previous < day), "cell_id"]
        )
        eligible = finite & ~industrial & ~ids.isin(recent)
        probabilities = calibrated_grid(frame, eligible, model, calibration)
        if ((probabilities[eligible] < 0) | (probabilities[eligible] > 1)).any():
            raise ValueError("Invalid model probability")
        raster_path = raster_directory / f"probability_{iso}.tif"
        image = np.full(shape, -9999, dtype="float32")
        image[rows[eligible], cols[eligible]] = probabilities[eligible]
        classes = np.full(shape, -9999, dtype="float32")
        classes[rows[eligible], cols[eligible]] = 1 + np.searchsorted(
            frozen["map_boundaries"][selected], probabilities[eligible], side="right"
        )
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=shape[1],
            height=shape[0],
            count=2,
            dtype="float32",
            crs=grid.crs,
            transform=transform,
            nodata=-9999,
            compress="deflate",
            predictor=3,
        ) as raster:
            raster.write(image, 1)
            raster.write(classes, 2)
            raster.set_band_description(1, "calibrated_new_event_probability")
            raster.set_band_description(2, "calibration_frozen_probability_class_1_to_4")
            raster.update_tags(
                synthetic="False",
                model=selected,
                target_day=iso,
                variant="public_reprocessed_hindcast",
                release_sha256=checksum(release),
                class_boundaries_json=json.dumps(frozen["map_boundaries"][selected]),
                threshold=str(frozen["thresholds"][selected]),
                outcome="first satellite detection of a new connected event; occurrence hazard",
            )
        # IEEE float32 preserves calibrated values; NaN is missing, never a zero-risk claim.
        payload_path.write_bytes(public_payloads.encode(probabilities[order]))
        proof = {
            "target_day": iso,
            "synthetic": False,
            "model": selected,
            "format": public_payloads.FORMAT,
            "count": len(ids),
            "finite_cells": int(eligible.sum()),
            "retrospective": True,
            "payload_sha256": checksum(payload_path),
            "raster_sha256": checksum(raster_path),
            "release_sha256": checksum(release),
            "exporter_code_sha256": exporter_digest,
            "payload_transport_code_sha256": transport_digest,
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
        "input_features": getattr(model, "features", ["landcover", "calendar_month"]),
        "format": public_payloads.FORMAT,
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
