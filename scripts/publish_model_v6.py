"""Publish frozen model v6 to the site, next to (not over) the hash-locked v5 assets.

Reads the daily maps written by export_model_v6.py and their proofs, then writes:
  platform/dist/assets/predictions-v6/   daily payloads (gitignored, bound by the manifest)
  platform/dist/assets/forecast-manifest-v6.json
  platform/dist/assets/events-v6.bin/.json   observed first detections with v6 alert flags
  platform/dist/v6/                       release, test and reliability records, hash-bound
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import export_model_v6 as ex  # noqa: E402
import test_2026 as t26  # noqa: E402

from wildfire_kz.data import checksum, dump_json  # noqa: E402

DIST = ROOT / "platform/dist"
ASSETS = DIST / "assets"
RECORDS = DIST / "v6"
METRICS = [
    "precision",
    "recall",
    "f1",
    "average_precision",
    "roc_auc",
    "brier",
    "bss",
    "ece",
    "prevalence",
    "top_0.1pct",
    "top_1pct",
]
HEAT_MIN = 20
# Log-spaced probability bins, the same edges as the map legend's classes.
EDGES = [0, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1.0]


def decode(path: Path, n: int) -> np.ndarray:
    raw = np.frombuffer(gzip.decompress(path.read_bytes()), dtype="uint8")
    return np.frombuffer(raw.reshape(2, n).T.tobytes(), dtype="<f2").astype("float32")


def reliability() -> dict:
    sample = pd.concat(
        [
            pd.read_parquet(p, columns=["label", "weight", "p_v5", "p_v6"])
            for p in sorted((t26.RUN / "months").glob("*.parquet"))
        ]
    )
    out = {}
    for model in ["v6", "v5"]:
        p = sample[f"p_{model}"].to_numpy()
        w = sample.weight.to_numpy()
        y = sample.label.to_numpy()
        # The top edge is closed so that p == 1 falls in the last bin.
        b = np.clip(np.searchsorted(EDGES, p, side="right") - 1, 0, len(EDGES) - 2)
        rows = []
        for i in range(len(EDGES) - 1):
            m = b == i
            weight = float(w[m].sum())
            rows.append(
                {
                    "low": EDGES[i],
                    "high": EDGES[i + 1],
                    "share": weight / float(w.sum()),
                    "predicted": float((p[m] * w[m]).sum() / weight) if weight else None,
                    "observed": float((y[m] * w[m]).sum() / weight) if weight else None,
                    "positives": int(y[m].sum()),
                    "rows": int(m.sum()),
                }
            )
        out[model] = rows
    return {
        "synthetic": False,
        "period": [str(t26.START.date()), str(t26.END.date())],
        "weighting": "inverse negative-sampling weights of the registered 2026 test sample",
        "edges": EDGES,
        "bins": out,
        "computed_after_test": True,
        "used_for_selection_or_recalibration": False,
    }


def heat_sources() -> list[str]:
    """Cells with at least HEAT_MIN VIIRS detections in every year 2015–2022 (cells.bin history).

    Smelters, steel works and gas flares that the frozen industrial list missed; the map
    hides them by default with the same rule. Development years only, no test data.
    """
    raw = np.frombuffer((ASSETS / "cells.bin").read_bytes(), dtype=np.uint8).reshape(-1, 34)
    rows = raw[:, 0:2].copy().view("<i2").ravel()
    cols = raw[:, 2:4].copy().view("<i2").ravel()
    history = raw[:, 18:34].copy().view("<u2").reshape(-1, 8)
    keep = history.min(axis=1) >= HEAT_MIN
    return [f"g5000_{r}_{c}" for r, c in zip(rows[keep], cols[keep], strict=True)]


def sensitivity() -> dict:
    """Post-hoc check: the registered 2026 metrics with and without persistent heat sources."""
    sample = pd.concat(
        [
            pd.read_parquet(p, columns=["cell_id", "label", "weight", "p_v5", "p_v6"])
            for p in sorted((t26.RUN / "months").glob("*.parquet"))
        ]
    )
    cells = heat_sources()
    thresholds = {
        "v6": json.loads((t26.V6 / "frozen.json").read_text())["threshold"],
        "v5": json.loads((t26.V5 / "frozen.json").read_text())["threshold"],
    }

    def score(part: pd.DataFrame) -> dict:
        out = {}
        for model, threshold in thresholds.items():
            p, y, w = (
                part[f"p_{model}"].to_numpy(),
                part.label.to_numpy() == 1,
                part.weight.to_numpy(),
            )
            alert = p >= threshold
            tp, fp, fn = (w * (alert & y)).sum(), (w * (alert & ~y)).sum(), (w * (~alert & y)).sum()
            precision, recall = tp / (tp + fp), tp / (tp + fn)
            out[model] = {
                "precision": float(precision),
                "recall": float(recall),
                "f1": float(2 * precision * recall / (precision + recall)),
                "average_precision": float(average_precision_score(y, p, sample_weight=w)),
                "true_positives": int(round(tp)),
            }
        return out

    full = score(sample)
    registered = json.loads((t26.RUN / "evaluation.json").read_text())["metrics"]
    for model in thresholds:
        for key in ["precision", "recall"]:
            if abs(full[model][key] - registered[model][key]) > 1e-9:
                raise ValueError(f"Sensitivity does not reproduce the registered {model} {key}")
    inside = sample.cell_id.isin(cells)
    return {
        "synthetic": False,
        "post_hoc": True,
        "used_for_selection_or_recalibration": False,
        "rule": f"at least {HEAT_MIN} VIIRS detections in every year 2015–2022 (cells.bin history)",
        "cells": cells,
        "rows_in_cells": int(inside.sum()),
        "positives_in_cells": int(sample.label[inside].sum()),
        "positives": int(sample.label.sum()),
        "thresholds": thresholds,
        "all_cells": full,
        "without_heat_sources": score(sample[~inside]),
    }


def records() -> dict:
    RECORDS.mkdir(parents=True, exist_ok=True)
    copies = {
        "release.json": t26.V6 / "release.json",
        "frozen.json": t26.V6 / "frozen.json",
        "training.json": t26.V6 / "training.json",
        "development_comparison.csv": t26.V6 / "development_comparison.csv",
        "development_selection.json": t26.V6 / "development_selection.json",
        "protocol_2026.json": t26.RUN / "protocol.json",
        "evaluation_2026.json": t26.RUN / "evaluation.json",
    }
    for name, source in copies.items():
        shutil.copyfile(source, RECORDS / name)
    dump_json(RECORDS / "reliability_2026.json", reliability())
    dump_json(RECORDS / "sensitivity_2026.json", sensitivity())
    return {
        name.removesuffix(".json").removesuffix(".csv"): {
            "path": f"./v6/{name}",
            "sha256": checksum(RECORDS / name),
        }
        for name in [*copies, "reliability_2026.json", "sensitivity_2026.json"]
    }


def events(available: list[str], frozen: dict) -> dict:
    binary = (ASSETS / "cells.bin").read_bytes()
    n = len(binary) // 34
    raw = np.frombuffer(binary, dtype=np.uint8).reshape(-1, 34)
    rows = raw[:, 0:2].copy().view("<i2").ravel()
    cols = raw[:, 2:4].copy().view("<i2").ravel()
    index = {f"g5000_{r}_{c}": i for i, (r, c) in enumerate(zip(rows, cols, strict=True))}
    columns = ["cell_id", "timestamp", "x", "y_coord", "day"]
    old = pd.read_parquet(ROOT / "runs/model_stack_v5/audit/events.parquet", columns=columns)
    new = pd.read_parquet(t26.RUN / "events.parquet", columns=[*columns, "is_first"])
    new = new[new.is_first][columns]
    found = pd.concat([old, new], ignore_index=True)
    found["iso"] = found.day.dt.strftime("%Y-%m-%d")
    days = {d: i for i, d in enumerate(available)}
    found = found[found.iso.isin(days)].sort_values(["day", "timestamp"]).reset_index(drop=True)
    found["cell"] = found.cell_id.map(index).fillna(-1).astype(int)

    covered = np.zeros(len(found), bool)
    hit = np.zeros(len(found), bool)
    before = np.zeros(len(found), bool)
    threshold = frozen["threshold"]
    previous_iso, previous = None, None
    for iso, group in found.groupby("iso", sort=True):
        p = decode(ASSETS / f"predictions-v6/{iso}.f16.gz", n)
        prior = str((pd.Timestamp(iso) - pd.Timedelta(days=1)).date())
        q = previous if previous_iso == prior else None
        if q is None and prior in days:
            q = decode(ASSETS / f"predictions-v6/{prior}.f16.gz", n)
        at = group.cell.to_numpy()
        ok = at >= 0
        rows = group.index.to_numpy()
        values = np.where(ok, p[np.where(ok, at, 0)], np.nan)
        covered[rows] = np.isfinite(values)
        hit[rows] = np.nan_to_num(values, nan=-1) >= threshold
        if q is not None:
            before[rows] = (
                np.nan_to_num(np.where(ok, q[np.where(ok, at, 0)], np.nan), nan=-1) >= threshold
            )
        previous_iso, previous = iso, p

    record = np.zeros(
        len(found),
        dtype=[
            ("day", "<u2"),
            ("flags", "u1"),
            ("pad", "u1"),
            ("cell", "<i4"),
            ("x", "<f4"),
            ("y", "<f4"),
        ],
    )
    record["day"] = found.iso.map(days).to_numpy()
    record["flags"] = covered * 1 + hit * 2 + before * 4
    record["cell"] = found.cell.to_numpy()
    record["x"] = found.x.to_numpy() / 1000
    record["y"] = -found.y_coord.to_numpy() / 1000
    payload = record.tobytes()
    (ASSETS / "events-v6.bin").write_bytes(payload)
    meta = {
        "sources": [
            "runs/model_stack_v5/audit/events.parquet (2023–2024, SNPP standard processing)",
            "runs/test_2026/events.parquet (2026, NASA GIBS S-NPP NRT, first detection of each event)",
        ],
        "definition": "First SNPP VIIRS nominal/high detection of each event connected within 2 km and 48 hours",
        "labels_opened_after_release": True,
        "release_sha256": checksum(t26.V6 / "release.json"),
        "events": len(found),
        "covered": int(covered.sum()),
        "hit_same_day": int(hit.sum()),
        "record_bytes": 16,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    dump_json(ASSETS / "events-v6.json", meta)
    return meta


def main() -> None:
    release = t26.verify_v6()
    frozen = json.loads((t26.V6 / "frozen.json").read_text())
    evaluation = json.loads((t26.RUN / "evaluation.json").read_text())
    target = ASSETS / "predictions-v6"
    target.mkdir(parents=True, exist_ok=True)
    assets = {}
    for iso in ex.days():
        proof = json.loads((ex.PROOFS / f"{iso}.json").read_text())
        source = ex.OUT / f"{iso}.f16.gz"
        if checksum(source) != proof["payload_sha256"]:
            raise ValueError(f"Payload changed: {iso}")
        if (
            not (target / source.name).exists()
            or checksum(target / source.name) != proof["payload_sha256"]
        ):
            shutil.copyfile(source, target / source.name)
        assets[iso] = proof
    available = sorted(assets)
    bound = records()
    observed = events(available, frozen)
    metrics = evaluation["metrics"]
    manifest = {
        "ready": True,
        "synthetic": False,
        "model": "xgboost_v6",
        "available_days": available,
        "test_days": [d for d in available if d.startswith("2026")],
        "input_features": frozen["features"],
        "format": ex.FORMAT,
        "prediction_path": "./assets/predictions-v6/",
        "prediction_assets": assets,
        "events_path": "./assets/events-v6",
        "retrospective": True,
        "operational_validation": False,
        "evaluation_released": True,
        "release_sha256": checksum(t26.V6 / "release.json"),
        "release_frozen_utc": release["frozen_utc"],
        "threshold": frozen["threshold"],
        "selection_years": [2015, 2022],
        "calibration_year": 2022,
        "test_years": [2026],
        "test_metrics": {
            "xgboost_v6": {k: metrics["v6"][k] for k in METRICS},
            "xgboost_spatiotemporal": {k: metrics["v5"][k] for k in METRICS},
        },
        "test_2026": {
            "period": [str(t26.START.date()), str(t26.END.date())],
            "excluded_days": t26.EXCLUDED,
            "label_source": "NASA GIBS S-NPP NRT",
            "rows": evaluation["rows"],
            "positive_cell_days": evaluation["positive_cell_days"],
            "ci": evaluation["confidence_intervals_95"],
            "paired_difference": evaluation["paired_difference_v6_minus_v5_95"],
        },
        "records": bound,
        "observed_events": {"events": observed["events"], "sha256": observed["sha256"]},
        "calibration_warning": (
            "On 2026 the v6 probabilities are not calibrated. Around the alert threshold "
            "(0.3–3%) the observed rate was 4–6 times higher than shown; in the rare cells "
            "above 3% it was about 2.7 times lower. Brier skill -0.062 against +0.009 for v5. "
            "Read v6 values as a relative risk ranking, not as a chance of fire."
        ),
        "continuity_note": (
            "2023–2024 maps are shown for continuity only and are not a test of v6: "
            "its design was informed by an audit of 2023–2024"
        ),
    }
    dump_json(ASSETS / "forecast-manifest-v6.json", manifest)
    print(json.dumps({"days": len(available), "events": observed["events"], "records": len(bound)}))


if __name__ == "__main__":
    main()
