"""Final-only evaluation of a hash-frozen public hindcast experiment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import complete, log, permitted
from wildfire_kz.data.public_study import RUN, industrial_cells, record_table, table
from wildfire_kz.evaluation import cluster_draws, metrics, reliability, top_capture


def weighted_ap_sorted(
    y: np.ndarray, w: np.ndarray, order: np.ndarray, endpoints: np.ndarray
) -> float:
    """Exact stepwise AP including score ties, with order cached across bootstrap draws."""
    positive = np.cumsum((w * y)[order])
    total_positive = positive[-1]
    if total_positive <= 0:
        return float("nan")
    total = np.cumsum(w[order])[endpoints]
    tp = positive[endpoints]
    precision = np.divide(tp, total, out=np.zeros_like(tp), where=total > 0)
    return float(np.sum(np.diff(np.r_[0, tp]) * precision) / total_positive)


def bootstrap(
    frame: pd.DataFrame,
    predictions: dict[str, np.ndarray],
    selected: str,
    destination: Path,
    resamples: int = 1000,
) -> None:
    """Pair the same 100 km × 30 day cluster draws for every frozen model."""
    y, w = frame.label.to_numpy(), frame.weight.to_numpy()
    draws = cluster_draws(frame, resamples, 100000, 30, 42)
    weight_by_cluster = np.bincount(draws.codes, weights=w)
    denominator = draws.multiplicities @ weight_by_cluster
    estimates: dict[str, dict[str, np.ndarray]] = {}
    for name, p in predictions.items():
        order = np.argsort(-p, kind="stable")
        endpoints = np.r_[np.flatnonzero(np.diff(p[order]) != 0), len(p) - 1]
        squared_by_cluster = np.bincount(draws.codes, weights=w * (p - y) ** 2)
        brier = (draws.multiplicities @ squared_by_cluster) / denominator
        ap = np.array([weighted_ap_sorted(y, w * draw, order, endpoints) for draw in draws])
        estimates[name] = {"average_precision": ap, "brier": brier}
        log(f"Final bootstrap {name}: {resamples} paired cluster draws complete")
    rows = []
    for name in estimates:
        for metric, values in estimates[name].items():
            good = values[np.isfinite(values)]
            rows.append(
                {
                    "model": name,
                    "metric": metric,
                    "lower": float(np.quantile(good, 0.025)),
                    "upper": float(np.quantile(good, 0.975)),
                    "valid_resamples": len(good),
                    "requested_resamples": resamples,
                }
            )
            if name != selected:
                differences = estimates[selected][metric] - values
                good = differences[np.isfinite(differences)]
                rows.append(
                    {
                        "model": f"{selected} minus {name}",
                        "metric": metric,
                        "lower": float(np.quantile(good, 0.025)),
                        "upper": float(np.quantile(good, 0.975)),
                        "valid_resamples": len(good),
                        "requested_resamples": resamples,
                    }
                )
    pd.DataFrame(rows).to_csv(destination / "cluster_intervals.csv", index=False)


def evaluate(*, resamples: int = 1000) -> None:
    release = RUN / "release.json"
    permitted([2023, 2024], release)
    destination = RUN / "evaluate"
    destination.mkdir(parents=True, exist_ok=True)
    frozen = json.loads((RUN / "frozen.json").read_text())
    models = joblib.load(RUN / "models.joblib")
    calibrators = joblib.load(RUN / "calibrators.joblib")
    frame = pd.concat(
        [pd.read_parquet(table(year, training=False, release=release)) for year in [2023, 2024]],
        ignore_index=True,
    )
    frame = frame.loc[~frame.cell_id.isin(industrial_cells())].reset_index(drop=True)
    columns = ["cell_id", "day", "label", "weight", "x", "y_coord", "area_km2", "landcover"]
    predictions = {}
    for name, model in models.items():
        path = destination / f"predictions_{name}.parquet"
        if complete(path):
            saved = pd.read_parquet(path)
            if not saved[["cell_id", "day"]].equals(frame[["cell_id", "day"]]):
                raise ValueError("Final prediction keys changed")
            predictions[name] = saved.probability.to_numpy()
        else:
            p = calibrators[name].predict(model.predict(frame))
            predictions[name] = p
            record_table(
                path,
                frame[columns].assign(probability=p),
                {"synthetic": False, "release_sha256": checksum(release), "model": name},
            )
    reference = predictions["seasonal"]
    rows, combined = [], {}
    for name, p in predictions.items():
        threshold = frozen["thresholds"][name]
        summary = metrics(frame.label.to_numpy(), p, frame.weight.to_numpy(), threshold, reference)
        combined[name] = summary
        rows.append({"model": name, "period": "2023–2024", "threshold": threshold, **summary})
        for year in [2023, 2024]:
            mask = frame.day.dt.year.to_numpy() == year
            rows.append(
                {
                    "model": name,
                    "period": str(year),
                    "threshold": threshold,
                    **metrics(
                        frame.label.to_numpy()[mask],
                        p[mask],
                        frame.weight.to_numpy()[mask],
                        threshold,
                        reference[mask],
                    ),
                }
            )
        reliability(frame.label.to_numpy(), p, frame.weight.to_numpy()).to_csv(
            destination / f"reliability_{name}.csv", index=False
        )
        top_capture(frame, p, [0.05, 0.1, 0.2]).to_csv(
            destination / f"top_capture_{name}.csv", index=False
        )
        log(
            f"FINAL {name}: AP={summary['average_precision']:.6f}, ROC-AUC={summary['roc_auc']:.6f}"
        )
    pd.DataFrame(rows).to_csv(destination / "metrics.csv", index=False)
    if not (destination / "cluster_intervals.csv").is_file():
        bootstrap(frame, predictions, frozen["selected_model"], destination, resamples)
    report: dict[str, Any] = {
        "synthetic": False,
        "variant": "public_reprocessed_hindcast",
        "release_sha256": checksum(release),
        "selected_model": frozen["selected_model"],
        "selection_fixed_before_test": True,
        "test_years": [2023, 2024],
        "rows": len(frame),
        "positive_rows": int(frame.label.sum()),
        "weighted_cell_days": float(frame.weight.sum()),
        "metrics": combined,
        "bootstrap_resamples": resamples,
        "operational_validation": False,
        "outputs": {p.name: checksum(p) for p in destination.glob("*.csv")},
    }
    dump_json(destination / "complete.json", report)
    permitted([2023, 2024], release)
    log("Final evaluation complete; original model selection and hashes remain unchanged")
