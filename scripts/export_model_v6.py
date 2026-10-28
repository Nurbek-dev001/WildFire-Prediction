"""Export daily full-grid maps of frozen model v6, next to (not over) the hash-locked v5 maps.

Days: 2023–2024, for continuity with the published map (not a test for v6), and the
2026 test period, whose sampled cells must equal the registered test predictions.
Usage: export_model_v6.py --start 2026-01-01 --end 2026-05-31   (ranges run in parallel);
then publish_model_v6.py writes the site manifest.
"""

from __future__ import annotations

import argparse
import gzip
import json
import struct
import sys
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import test_2026 as t26  # noqa: E402

from wildfire_kz import model_upgrade as mu  # noqa: E402
from wildfire_kz.data import checksum, dump_json, public_predictors, public_study  # noqa: E402

RUN = ROOT / "runs/model_v6"
OUT = RUN / "site_assets/predictions"
PROOFS = RUN / "maps"
FORMAT = "little_endian_float16_byte_shuffle_gzip"
PERIODS = [("2023-01-01", "2024-12-31"), ("2026-01-01", str(t26.END.date()))]


def log(message: str) -> None:
    print(datetime.now(UTC).isoformat(), message, flush=True)


def days() -> list[str]:
    out = []
    for a, b in PERIODS:
        out += [str(d.date()) for d in pd.date_range(a, b) if str(d.date()) not in t26.EXCLUDED]
    return out


def export(start: str, end: str) -> None:
    t26.verify_v6()
    mu.verify_release(t26.V5 / "release.json")
    year = int(start[:4])
    if int(end[:4]) != year and not (year == 2023 and end[:4] == "2024"):
        raise ValueError("A range stays inside one period")
    # The legacy year guard re-hashes the frozen release on every call; check once per day.
    original = public_study.permitted

    @cache
    def guard_once(years: tuple, release_path: Path | None) -> None:
        original(list(years), release_path)

    def cached(years, release_path=None):
        guard_once(tuple(years), release_path)

    public_study.permitted = cached
    public_predictors.permitted = cached

    grid = public_predictors.geography()[0]
    ids = pd.Index(grid.cell_id)
    n = len(ids)
    binary = (ROOT / "platform/dist/assets/cells.bin").read_bytes()
    order = ids.get_indexer(
        pd.Index([f"g5000_{r[0]}_{r[1]}" for r in struct.iter_unpack("<hhfffH8H", binary)])
    )
    if (order < 0).any():
        raise ValueError("Grid order differs from cells.bin")
    industrial = ids.isin(json.loads((mu.OLD / "industrial_cells.json").read_text())["cell_ids"])

    history = mu.load_history(2024, t26.V5 / "release.json")
    if year == 2026:
        raw25 = pd.read_parquet(
            t26.independent.RUN / "detections_2025.parquet", columns=["cell_id", "timestamp"]
        )
        raw26 = pd.read_parquet(
            t26.RUN / "detections_2026.parquet", columns=["cell_id", "timestamp"]
        )
        extra = pd.concat([raw25, raw26], ignore_index=True)
        extra["day"] = extra.timestamp.dt.floor("D")
        history = pd.concat(
            [history, extra[["cell_id", "day"]]], ignore_index=True
        ).drop_duplicates()
        exclusion = pd.read_parquet(t26.RUN / "events.parquet", columns=["cell_id", "timestamp"])
    else:
        exclusion = pd.read_parquet(
            mu.OLD / "outcomes/events_through_2024.parquet", columns=["cell_id", "timestamp"]
        )
    fire_history = mu.FireHistory(history)
    cells = t26.CellHistory(
        history.assign(cell=history.cell_id.map(pd.Series(np.arange(n), index=ids)))
        .dropna(subset=["cell"])
        .astype({"cell": np.int64}),
        n,
    )

    model = joblib.load(t26.V6 / "model.joblib")
    model["estimator"].set_params(n_jobs=2)
    calibration = joblib.load(t26.V6 / "calibrator.joblib")
    frozen = json.loads((t26.V6 / "frozen.json").read_text())

    check = {}
    if year == 2026:
        sample = pd.concat(
            [
                pd.read_parquet(p, columns=["cell_id", "day", "p_v6"])
                for p in sorted((t26.RUN / "months").glob("*.parquet"))
            ]
        )
        check = {str(d.date()): g for d, g in sample.groupby("day")}

    OUT.mkdir(parents=True, exist_ok=True)
    PROOFS.mkdir(parents=True, exist_ok=True)
    selected = [d for d in days() if start <= d <= end]
    for iso in selected:
        payload, proof_path = OUT / f"{iso}.f16.gz", PROOFS / f"{iso}.json"
        if (
            proof_path.exists()
            and payload.exists()
            and checksum(payload) == json.loads(proof_path.read_text())["payload_sha256"]
        ):
            continue
        day = pd.Timestamp(iso, tz="UTC")
        keys = pd.DataFrame({"cell_index": np.arange(n, dtype="int32"), "day": day})
        f = (
            t26.feature_frame(keys)
            if year == 2026
            else public_study.feature_frame(keys, mu.OLD / "release.json")
        )
        f = mu.augment(f, fire_history, t26.V5 / "release.json")
        for name, values in cells.features(f).items():
            f[name] = values
        recent = set(
            exclusion.loc[
                (exclusion.timestamp >= day - pd.Timedelta(hours=48)) & (exclusion.timestamp < day),
                "cell_id",
            ]
        )
        eligible = f.required_features_valid.to_numpy() & ~industrial & ~ids.isin(recent)
        p = np.full(n, np.nan, dtype="float32")
        if eligible.any():
            raw = model["estimator"].predict_proba(f.loc[eligible, model["features"]])[:, 1]
            p[eligible] = mu.published_probability(calibration.predict(raw))
        if iso in check:
            s = check[iso]
            pos = ids.get_indexer(s.cell_id)
            if (pos < 0).any() or not np.array_equal(p[pos], s.p_v6.to_numpy()):
                raise ValueError(f"Map differs from the registered 2026 test predictions: {iso}")
        bits = np.asarray(p[order], dtype="<f2").view("uint8").reshape(-1, 2)
        payload.write_bytes(gzip.compress(bits.T.tobytes(), mtime=0))
        decoded = np.frombuffer(
            np.frombuffer(gzip.decompress(payload.read_bytes()), dtype="uint8")
            .reshape(2, -1)
            .T.tobytes(),
            dtype="<f2",
        ).astype("float32")
        if not np.array_equal(decoded, p[order], equal_nan=True):
            raise ValueError("Payload does not round-trip")
        dump_json(
            proof_path,
            {
                "target_day": iso,
                "synthetic": False,
                "model": "xgboost_v6",
                "format": FORMAT,
                "count": n,
                "finite_cells": int(eligible.sum()),
                "payload_sha256": checksum(payload),
                "release_sha256": checksum(t26.V6 / "release.json"),
                "alert_cells": int(np.sum(p >= frozen["threshold"])),
                "retrospective": True,
                "test_period": year == 2026,
                "checked_against_test_sample": iso in check,
            },
        )
        if iso.endswith("-01"):
            log(f"v6 export through {iso}")
    log(f"v6 export {start}..{end}: {len(selected)} days")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2024-12-31")
    a = parser.parse_args()
    export(a.start, a.end)
