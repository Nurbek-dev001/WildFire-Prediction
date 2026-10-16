"""Stage 9 — sigmoid (Platt) calibration, decision threshold and map class boundaries.

Everything here is fitted on the calibration year(s) only, using the *representative*
evaluation design with inverse-inclusion weights (never a balanced sample):

* Platt scaling: p = sigmoid(a * s + b) with s the model's uncalibrated log-odds score;
* decision threshold tau = argmax weighted F1 of calibrated probabilities;
* map class boundaries = weighted quantiles of the calibrated probabilities of the mapping
  model, plus observed event frequencies per class.

The resulting ``calibration_artifacts.json`` is hashed when the test years are unlocked; any
later modification re-locks them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from wildfire_kz.config.schema import Config
from wildfire_kz.evaluation.metrics import best_f1_threshold
from wildfire_kz.models.pipelines import FittedModel
from wildfire_kz.models.train import load_model
from wildfire_kz.paths import RunPaths
from wildfire_kz.splits.guard import FeatureStore
from wildfire_kz.utils.runtime import get_logger, read_json, utc_now, write_json

log = get_logger("calibration")


@dataclass(frozen=True)
class Platt:
    a: float
    b: float

    def apply(self, score: np.ndarray) -> np.ndarray:
        z = np.clip(self.a * np.asarray(score, dtype=float) + self.b, -40, 40)
        return 1.0 / (1.0 + np.exp(-z))


def fit_platt(score: np.ndarray, y: np.ndarray, w: np.ndarray) -> Platt:
    """Unpenalised weighted logistic regression of y on the uncalibrated log-odds score."""
    lr = LogisticRegression(C=np.inf, solver="lbfgs", max_iter=1000)
    lr.fit(np.asarray(score, dtype=float).reshape(-1, 1), y, sample_weight=w)
    return Platt(a=float(lr.coef_[0, 0]), b=float(lr.intercept_[0]))


def weighted_quantiles(values: np.ndarray, weights: np.ndarray, qs: list[float]) -> list[float]:
    order = np.argsort(values, kind="mergesort")
    v, w = np.asarray(values)[order], np.asarray(weights)[order]
    cw = (np.cumsum(w) - 0.5 * w) / w.sum()
    return [float(np.interp(q, cw, v)) for q in qs]


def assign_classes(p: np.ndarray, boundaries: list[float]) -> np.ndarray:
    """Class index 0..len(boundaries) (right-open intervals)."""
    return np.searchsorted(np.asarray(boundaries), np.asarray(p), side="right")


def class_frequencies(p: np.ndarray, y: np.ndarray, w: np.ndarray, boundaries: list[float],
                      labels: list[str]) -> pd.DataFrame:
    cls = assign_classes(p, boundaries)
    rows = []
    for k, lab in enumerate(labels):
        m = cls == k
        sw = float(w[m].sum())
        rows.append({"class": k, "label": lab, "weighted_cell_days": sw,
                     "share_of_cell_days": sw / float(w.sum()),
                     "observed_event_frequency": float((w[m] * y[m]).sum() / sw) if sw else np.nan,
                     "share_of_events": float((w[m] * y[m]).sum() / (w * y).sum())
                     if (w * y).sum() else np.nan,
                     "mean_calibrated_p": float((w[m] * p[m]).sum() / sw) if sw else np.nan})
    return pd.DataFrame(rows)


def model_dirs(train_dir: Path) -> dict[str, Path]:
    return {p.name: p for p in sorted(train_dir.iterdir())
            if p.is_dir() and (p / "model.joblib").exists()}


def score_frame(fm: FittedModel, df: pd.DataFrame) -> np.ndarray:
    """Uncalibrated log-odds score of any model (baselines included)."""
    return fm.decision_logit(df)


def calibrate_models(cfg: Config, models: dict[str, FittedModel], cal: pd.DataFrame
                     ) -> tuple[dict[str, Any], pd.DataFrame]:
    """Fit Platt + tau for each model on the calibration rows; returns (params, predictions)."""
    y = cal["label"].to_numpy()
    w = cal["w_eval"].to_numpy(dtype=float)
    out: dict[str, Any] = {}
    preds = cal[["cell_id", "date", "label", "w_eval"]].copy()
    for name, fm in models.items():
        s = score_frame(fm, cal)
        platt = fit_platt(s, y, w)
        p = platt.apply(s)
        tau, f1 = best_f1_threshold(y, p, w)
        out[name] = {"platt_a": platt.a, "platt_b": platt.b, "tau": tau,
                     "weighted_f1_calibration": f1, "n_calibration_rows": len(cal),
                     "calibration_positives": int(y.sum())}
        preds[f"p_{name}"] = p
        preds[f"s_{name}"] = s
        log.info("calibrated %s: a=%.3f b=%.3f tau=%.4g (weighted F1 %.3f)", name, platt.a,
                 platt.b, tau, f1)
    return out, preds


def run_calibrate(cfg: Config, paths: RunPaths) -> dict[str, Any]:
    out_dir = paths.stage("calibrate")
    out_dir.mkdir(parents=True, exist_ok=True)
    store = FeatureStore(cfg, paths)
    cal = store.load(cfg.splits.calibration_years, "calibration")
    cal = cal[cal["in_eval"]].reset_index(drop=True)
    models = {n: load_model(p) for n, p in model_dirs(paths.stage("train")).items()}
    params, preds = calibrate_models(cfg, models, cal)
    selection = read_json(paths.stage("train") / "selection.json")
    map_model = selection["best_classifier"]
    mc = cfg.mapping
    p_map = preds[f"p_{map_model}"].to_numpy()
    boundaries = weighted_quantiles(p_map, preds["w_eval"].to_numpy(), mc.class_quantiles)
    freq = class_frequencies(p_map, preds["label"].to_numpy(), preds["w_eval"].to_numpy(),
                             boundaries, mc.class_labels)
    freq.to_csv(out_dir / "map_class_frequencies_calibration.csv", index=False)
    preds.to_parquet(out_dir / "calibration_predictions.parquet", index=False)
    artifacts = {
        "frozen_at": utc_now(), "calibration_years": cfg.splits.calibration_years,
        "method": "sigmoid (Platt) on uncalibrated log-odds, inverse-inclusion weighted",
        "threshold_rule": "maximise weighted F1 on the calibration year",
        "models": params, "map_model": map_model,
        "map_class_quantiles": mc.class_quantiles, "map_class_boundaries": boundaries,
        "map_class_labels": mc.class_labels,
    }
    write_json(out_dir / "calibration_artifacts.json", artifacts)
    return {"map_model": map_model, "n_models": len(params), "boundaries": boundaries}
