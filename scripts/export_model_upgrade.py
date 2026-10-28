"""Export every frozen upgraded-model date, retaining explicit nodata and hashes."""

from __future__ import annotations

import argparse
import gzip
import json
import struct
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import rasterio

from wildfire_kz import model_upgrade as mu
from wildfire_kz import stacked_model
from wildfire_kz.data import checksum, dump_json, public_predictors, public_study
from wildfire_kz.data.public_predictors import geography, target_lattice
from wildfire_kz.data.public_study import feature_frame

RUN, OLD = mu.ROOT / "runs/model_stack_v5", mu.OLD
FORMAT = "little_endian_float16_byte_shuffle_gzip"


def main(start_day: str = "2023-01-01", end_day: str = "2024-12-31") -> None:
    release = RUN / "release.json"
    record = mu.verify_release(release)
    if checksum(Path(stacked_model.__file__)) != record["model_code_sha256"]:
        raise ValueError("Frozen stack code changed")
    evaluation = json.loads((RUN / "evaluation.json").read_text())
    if evaluation["release_sha256"] != checksum(release):
        raise ValueError("Final evaluation must match new frozen model")
    # The legacy weather routine checks the same release in every lag loop.
    # Verify it once per calendar day, retaining full checks at the boundaries;
    # this changes no feature equation, model score or eligibility condition.
    original_guard = public_study.permitted

    @cache
    def daily_guard(years, release_path):
        original_guard(list(years), release_path)

    def cached_guard(years, release_path=None):
        daily_guard(tuple(years), release_path)

    public_study.permitted = cached_guard
    public_predictors.permitted = cached_guard
    selected = joblib.load(RUN / "model.joblib")
    calibration = joblib.load(RUN / "calibrator.joblib")
    frozen = json.loads((RUN / "frozen.json").read_text())
    grid, _, _ = geography()
    ids = pd.Index(grid.cell_id)
    binary = (mu.ROOT / "platform/dist/assets/cells.bin").read_bytes()
    browser_ids = pd.Index(
        [f"g5000_{r[0]}_{r[1]}" for r in struct.iter_unpack("<hhfffH8H", binary)]
    )
    order = ids.get_indexer(browser_ids)
    if len(order) != len(ids) or (order < 0).any() or len(np.unique(order)) != len(ids):
        raise ValueError("Actual grid order differs")
    benchmark = pd.read_parquet(
        RUN / "predictions.parquet", columns=["cell_id", "day", "probability"]
    )
    expected = {day.strftime("%Y-%m-%d"): group for day, group in benchmark.groupby("day")}

    def verify_benchmark(iso, probabilities, index):
        if iso not in expected:
            return
        sample = expected[iso]
        position = index.get_indexer(sample.cell_id)
        if (position < 0).any() or not np.array_equal(
            probabilities[position], sample.probability.to_numpy()
        ):
            raise ValueError(f"Map differs from frozen benchmark predictions: {iso}")

    history = mu.FireHistory(mu.load_history(2024, release))
    # Exclusion inputs preserve the original benchmark's risk set; feature
    # history separately enforces the seven-day publication lag.
    detections = pd.read_parquet(
        OLD / "outcomes/events_through_2024.parquet", columns=["cell_id", "timestamp"]
    )
    dates = detections.timestamp
    industrial = ids.isin(json.loads((OLD / "industrial_cells.json").read_text())["cell_ids"])
    destination = RUN / "site_assets"
    payloads = destination / "predictions"
    rasters = RUN / "maps"
    payloads.mkdir(parents=True, exist_ok=True)
    rasters.mkdir(exist_ok=True)
    shape, transform, rows, cols = target_lattice(grid)
    assets = {}
    for day in pd.date_range(start_day, end_day, tz="UTC"):
        daily_guard.cache_clear()
        iso = day.strftime("%Y-%m-%d")
        payload = payloads / f"{iso}.f16.gz"
        raster_path = rasters / f"probability_{iso}.tif"
        proof_path = rasters / f"{iso}.json"
        if proof_path.exists() and payload.exists() and raster_path.exists():
            proof = json.loads(proof_path.read_text())
            if (
                proof["release_sha256"] != checksum(release)
                or checksum(payload) != proof["payload_sha256"]
                or checksum(raster_path) != proof["raster_sha256"]
            ):
                raise ValueError("Existing export differs from frozen model")
            raw = (
                np.frombuffer(gzip.decompress(payload.read_bytes()), dtype="uint8")
                .reshape(2, -1)
                .T.tobytes()
            )
            verify_benchmark(iso, np.frombuffer(raw, dtype="<f2").astype("float32"), browser_ids)
            assets[iso] = proof
            continue
        f = feature_frame(
            pd.DataFrame({"cell_index": np.arange(len(ids), dtype="int32"), "day": day}),
            OLD / "release.json",
        )
        f = mu.augment(f, history, release)
        recent = set(
            detections.loc[(dates >= day - pd.Timedelta(hours=48)) & (dates < day), "cell_id"]
        )
        eligible = f.required_features_valid.to_numpy() & ~industrial & ~ids.isin(recent)
        p = np.full(len(ids), np.nan, dtype="float32")
        if eligible.any():
            raw = selected["estimator"].predict_proba(f.loc[eligible, selected["features"]])[:, 1]
            p[eligible] = mu.published_probability(calibration.predict(raw))
        verify_benchmark(iso, p, ids)
        bits = np.asarray(p[order], dtype="<f2").view("uint8").reshape(-1, 2)
        payload.write_bytes(gzip.compress(bits.T.tobytes(), mtime=0))
        # Independent decode before raster creation; NaN payloads retain missingness.
        decoded = np.frombuffer(
            np.frombuffer(gzip.decompress(payload.read_bytes()), dtype="uint8")
            .reshape(2, -1)
            .T.tobytes(),
            dtype="<f2",
        ).astype("float32")
        if not np.array_equal(decoded, p[order], equal_nan=True):
            raise ValueError("Published values differ from evaluated float16 probabilities")
        image = np.full(shape, -9999, dtype="float32")
        image[rows[eligible], cols[eligible]] = p[eligible]
        classes = np.full(shape, -9999, dtype="float32")
        classes[rows[eligible], cols[eligible]] = 1 + np.searchsorted(
            frozen["boundaries"], p[eligible], side="right"
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
        ) as raster:
            raster.write(image, 1)
            raster.write(classes, 2)
            raster.update_tags(
                model="xgboost_spatiotemporal",
                target_day=iso,
                release_sha256=checksum(release),
                synthetic="False",
                threshold=str(frozen["threshold"]),
            )
        proof = {
            "target_day": iso,
            "synthetic": False,
            "model": "xgboost_spatiotemporal",
            "format": FORMAT,
            "count": len(ids),
            "finite_cells": int(eligible.sum()),
            "payload_sha256": checksum(payload),
            "raster_sha256": checksum(raster_path),
            "release_sha256": checksum(release),
            "alert_cells": int(np.sum(p >= frozen["threshold"])),
            "retrospective": True,
        }
        dump_json(proof_path, proof)
        assets[iso] = proof
        if len(assets) % 10 == 0 or iso == "2023-01-01":
            print(
                datetime.now(UTC).isoformat(),
                f"export {len(assets)}/731: {iso}, {eligible.sum():,} cells",
                flush=True,
            )
    if len(assets) != 731:
        print(
            f"Completed disjoint export range {start_day} through {end_day}: {len(assets)} dates; run full cached pass to finalize",
            flush=True,
        )
        return
    old_evaluation = json.loads((OLD / "evaluate/complete.json").read_text())
    new_metrics = next(
        m
        for m in evaluation["metrics"]
        if m["model"] == "xgboost_spatiotemporal" and m["period"] == "2023–2024"
    )
    manifest = {
        "ready": True,
        "synthetic": False,
        "model": "xgboost_spatiotemporal",
        "available_days": sorted(assets),
        "input_features": selected["features"],
        "format": FORMAT,
        "retrospective": True,
        "missing_sources": [],
        "holdout_sealed": False,
        "evaluation_released": True,
        "release_sha256": checksum(release),
        "threshold": frozen["threshold"],
        "boundaries": frozen["boundaries"],
        "prediction_assets": assets,
        "test_metrics": {**old_evaluation["metrics"], "xgboost_spatiotemporal": new_metrics},
        "test_years": [2023, 2024],
        "selection_years": [2015, 2021],
        "calibration_year": 2022,
        "operational_validation": False,
        "upgrade": {
            "release_path": "./upgrade/release.json",
            "release_sha256": checksum(release),
            "evaluation_path": "./upgrade/evaluation.json",
            "evaluation_sha256": checksum(RUN / "evaluation.json"),
            "report_path": "./upgrade/",
            "selection_max_year": 2022,
            "history_lag_days": 2,
            "transport": "float16",
            "precision_floor": frozen["precision_floor"],
        },
    }
    dump_json(destination / "forecast-manifest.json", manifest)
    original_guard([2023, 2024], OLD / "release.json")
    mu.verify_release(release)
    dump_json(
        RUN / "export_complete.json",
        {
            "synthetic": False,
            "release_sha256": checksum(release),
            "days": len(assets),
            "payload_bytes": sum(p.stat().st_size for p in payloads.glob("*.gz")),
            "grid_cells": len(ids),
            "missing_days": [d for d, p in assets.items() if p["finite_cells"] == 0],
            "manifest_sha256": checksum(destination / "forecast-manifest.json"),
        },
    )
    print("Full upgraded-model export complete", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2024-12-31")
    args = parser.parse_args()
    main(args.start, args.end)
