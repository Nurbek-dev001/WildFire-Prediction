"""Freeze a 2022-only alert-policy revision before evaluating the fixed thresholds.

The original model, probability maps and first final evaluation remain immutable.
This is a disclosed revision prompted by already reported low recall, not a new
unseen test. No 2023/2024 label or score is opened by the select command.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from wildfire_kz import operating_policy
from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_study import RUN
from wildfire_kz.evaluation import cluster_draws
from wildfire_kz.operating_policy import choose_threshold, threshold_curve

ROOT = Path(__file__).resolve().parents[1]
DEST = RUN / "operating_v2"
POLICY = DEST / "policy.json"


def scores(frame: pd.DataFrame, p: np.ndarray, threshold: float) -> dict[str, float]:
    y, w = frame.label.to_numpy(), frame.weight.to_numpy()
    alert = p >= threshold
    tp = float(w[(y == 1) & alert].sum())
    fp = float(w[(y == 0) & alert].sum())
    positive = float(w[y == 1].sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / positive
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    f2 = 5 * precision * recall / (4 * precision + recall) if precision + recall else 0.0
    return dict(
        precision=precision,
        recall=recall,
        f1=f1,
        f2=f2,
        tp=tp,
        fp=fp,
        fn=positive - tp,
        alert_fraction=(tp + fp) / float(w.sum()),
        weighted_alert_cell_days=tp + fp,
    )


def select() -> None:
    if POLICY.exists():
        raise FileExistsError("A frozen policy already exists; do not overwrite it")
    release = json.loads((RUN / "release.json").read_text())
    for name, digest in release["artifact_hashes"].items():
        if checksum(RUN / name) != digest:
            raise ValueError(f"Original artifact changed: {name}")
    path = RUN / "features/2022_evaluation.parquet"
    metadata = json.loads(path.with_suffix(".sha256.json").read_text())
    if checksum(path) != metadata["sha256"]:
        raise ValueError("Calibration table checksum mismatch")
    frame = pd.read_parquet(path)
    if not frame.day.dt.year.eq(2022).all():
        raise PermissionError("Calibration contains dates outside 2022")
    industrial = json.loads((RUN / "industrial_cells.json").read_text())["cell_ids"]
    frame = frame.loc[~frame.cell_id.isin(industrial)].reset_index(drop=True)
    model = joblib.load(RUN / "models.joblib")["xgboost"]
    calibration = joblib.load(RUN / "calibrators.joblib")["xgboost"]
    p = calibration.predict(model.predict(frame))
    curve = threshold_curve(frame, p)
    frozen = json.loads((RUN / "frozen.json").read_text())
    profiles = {
        "precision": {
            "label": "Прежний · F1",
            "objective": "original_2022_maximum_weighted_F1",
            "threshold": frozen["thresholds"]["xgboost"],
        },
        "balanced": {
            "label": "Баланс · F2",
            "objective": "maximum_2022_design_weighted_F2",
            "threshold": float(choose_threshold(curve, 2).threshold),
        },
        "coverage": {
            "label": "Охват ≥30%",
            "objective": "maximum_2022_weighted_F2_subject_to_recall_at_least_0.30",
            "minimum_calibration_recall": 0.30,
            "threshold": float(choose_threshold(curve, 2, 0.30).threshold),
        },
    }
    for profile in profiles.values():
        profile["calibration_metrics"] = scores(frame, p, profile["threshold"])
    DEST.mkdir(parents=True, exist_ok=True)
    # Complete development curve retained locally; a small grid is enough for plotting.
    curve.to_csv(DEST / "calibration_curve.csv.gz", index=False, compression="gzip")
    curve.iloc[np.unique(np.linspace(0, len(curve) - 1, 800).astype(int))].to_csv(
        DEST / "calibration_curve_plot.csv", index=False
    )
    dump_json(
        POLICY,
        {
            "schema_version": 1,
            "policy_id": "xgboost_alerts_2022_v2",
            "synthetic": False,
            "frozen_utc": datetime.now(UTC).isoformat(),
            "model": "xgboost",
            "default_profile": "balanced",
            "profiles": profiles,
            "selection_year": 2022,
            "selection_max_year": 2022,
            "calibration_rows": len(frame),
            "calibration_positive_rows": int(frame.label.sum()),
            "calibration_prevalence": float(np.average(frame.label, weights=frame.weight)),
            "model_retrained": False,
            "probabilities_changed": False,
            "test_used_to_select_threshold": False,
            "test_previously_reported": True,
            "revision_reason": "User requested greater recall after first evaluation; all new thresholds selected only on 2022",
            "evaluation_caveat": "Reassessment on the previously reported 2023-2024 benchmark, not a new independent holdout",
            "model_release_sha256": checksum(RUN / "release.json"),
            "original_artifacts": release["artifact_hashes"],
            "selection_inputs": {
                "features/2022_evaluation.parquet": checksum(path),
                "industrial_cells.json": checksum(RUN / "industrial_cells.json"),
            },
            "selection_code_sha256": checksum(Path(operating_policy.__file__)),
            "runner_code_sha256": checksum(Path(__file__)),
            "calibration_curve_sha256": checksum(DEST / "calibration_curve.csv.gz"),
            "tie_break": "exact_equal_objective_highest_threshold",
            "score_comparison": "probability_greater_than_or_equal_to_threshold",
        },
    )
    print(json.dumps({"policy_sha256": checksum(POLICY), "profiles": profiles}, ensure_ascii=False))


def verified_policy() -> dict:
    policy = json.loads(POLICY.read_text())
    for name, digest in policy["original_artifacts"].items():
        if checksum(RUN / name) != digest:
            raise ValueError(f"Original release changed: {name}")
    if checksum(Path(__file__)) != policy["runner_code_sha256"]:
        raise ValueError("Policy runner changed after freeze")
    if checksum(Path(operating_policy.__file__)) != policy["selection_code_sha256"]:
        raise ValueError("Threshold-selection code changed after freeze")
    for name, digest in policy["selection_inputs"].items():
        if checksum(RUN / name) != digest:
            raise ValueError(f"Policy input changed: {name}")
    return policy


def evaluate() -> None:
    policy = verified_policy()  # Must succeed before opening any final labels/scores.
    out = DEST / "evaluation.json"
    if out.exists():
        raise FileExistsError("Evaluation already exists; preserve this one-shot reassessment")
    path = RUN / "evaluate/predictions_xgboost.parquet"
    original = json.loads((RUN / "evaluate/complete.json").read_text())
    for name, digest in original["outputs"].items():
        if checksum(RUN / "evaluate" / name) != digest:
            raise ValueError(f"Original evaluation changed: {name}")
    frame = pd.read_parquet(path)
    if not frame.day.dt.year.isin([2023, 2024]).all():
        raise ValueError("Unexpected final evaluation years")
    p = frame.probability.to_numpy()
    rows = []
    for key, profile in policy["profiles"].items():
        for period in ["2023–2024", "2023", "2024"]:
            mask = (
                np.ones(len(frame), dtype=bool)
                if "–" in period
                else frame.day.dt.year.eq(int(period)).to_numpy()
            )
            rows.append(
                {
                    "profile": key,
                    "period": period,
                    "threshold": profile["threshold"],
                    **scores(frame.loc[mask], p[mask], profile["threshold"]),
                }
            )
    pd.DataFrame(rows).to_csv(DEST / "metrics.csv", index=False)
    draws = cluster_draws(frame, 1000, 100000, 30, 42)
    y, w = frame.label.to_numpy(), frame.weight.to_numpy()
    by_cluster = lambda values: np.bincount(
        draws.codes, weights=values, minlength=draws.multiplicities.shape[1]
    )
    positive = draws.multiplicities @ by_cluster(w * y)
    total = draws.multiplicities @ by_cluster(w)
    estimates = {}
    intervals = []
    for key, profile in policy["profiles"].items():
        alert = p >= profile["threshold"]
        tp = draws.multiplicities @ by_cluster(w * y * alert)
        burden = draws.multiplicities @ by_cluster(w * alert)
        precision = np.divide(tp, burden, out=np.zeros_like(tp), where=burden > 0)
        recall = tp / positive
        f2 = np.divide(
            5 * precision * recall,
            4 * precision + recall,
            out=np.zeros_like(tp),
            where=4 * precision + recall > 0,
        )
        estimates[key] = {
            "precision": precision,
            "recall": recall,
            "f2": f2,
            "alert_fraction": burden / total,
        }
        for name, values in estimates[key].items():
            intervals.append(
                {
                    "profile": key,
                    "metric": name,
                    "lower": float(np.quantile(values, 0.025)),
                    "upper": float(np.quantile(values, 0.975)),
                    "resamples": 1000,
                }
            )
    for key in ["balanced", "coverage"]:
        for name in ["precision", "recall", "f2", "alert_fraction"]:
            values = estimates[key][name] - estimates["precision"][name]
            intervals.append(
                {
                    "profile": key + " minus precision",
                    "metric": name,
                    "lower": float(np.quantile(values, 0.025)),
                    "upper": float(np.quantile(values, 0.975)),
                    "resamples": 1000,
                }
            )
    pd.DataFrame(intervals).to_csv(DEST / "cluster_intervals.csv", index=False)
    combined = {row["profile"]: row for row in rows if row["period"] == "2023–2024"}
    dump_json(
        out,
        {
            "synthetic": False,
            "completed_utc": datetime.now(UTC).isoformat(),
            "policy_sha256": checksum(POLICY),
            "model_release_sha256": policy["model_release_sha256"],
            "evaluation_previously_reported": True,
            "policy_fixed_before_reassessment": True,
            "rows": len(frame),
            "positive_rows": int(frame.label.sum()),
            "weighted_cell_days": float(frame.weight.sum()),
            "metrics": combined,
            "prediction_table_sha256": checksum(path),
            "original_evaluation_sha256": checksum(RUN / "evaluate/complete.json"),
            "unchanged_discrimination": {
                name: original["metrics"]["xgboost"][name]
                for name in ["average_precision", "roc_auc", "brier"]
            },
            "bootstrap": {
                "resamples": 1000,
                "spatial_block_m": 100000,
                "temporal_block_days": 30,
                "seed": 42,
            },
            "outputs": {
                name: checksum(DEST / name) for name in ["metrics.csv", "cluster_intervals.csv"]
            },
        },
    )
    print(json.dumps(combined, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["select", "evaluate"])
    args = parser.parse_args()
    {"select": select, "evaluate": evaluate}[args.phase]()
