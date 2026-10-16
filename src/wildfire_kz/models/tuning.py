"""Optuna hyper-parameter search with a weighted-average-precision objective.

Each trial fits the full pipeline on every development fold's training rows (training
design, IPW or class weights) and scores weighted AP on the fold's validation rows
(unbalanced evaluation design, evaluation weights). Early stopping for boosted trees uses the
same development-fold validation rows only. The refit iteration count for boosted trees is
the mean best iteration across folds.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import optuna
import pandas as pd

from wildfire_kz.config.schema import Config, FloatRange, IntRange
from wildfire_kz.evaluation.metrics import average_precision
from wildfire_kz.models.pipelines import ModelSpec, fit_model
from wildfire_kz.utils.runtime import get_logger

log = get_logger("models.tuning")
optuna.logging.set_verbosity(optuna.logging.WARNING)


@dataclass
class Fold:
    name: str
    train: pd.DataFrame
    val: pd.DataFrame


def training_weights(df: pd.DataFrame, scheme: str) -> np.ndarray:
    """Training weights normalised to mean 1 (normalisation does not change the optimum)."""
    if scheme == "inverse_inclusion":
        w = df["w_train"].to_numpy(dtype=float)
    elif scheme == "class_weight":
        y = df["label"].to_numpy()
        n, n1 = len(y), max(int(y.sum()), 1)
        w = np.where(y == 1, n / (2 * n1), n / (2 * max(n - n1, 1)))
    else:
        raise ValueError(scheme)
    return w / w.mean()


def eval_weights(df: pd.DataFrame) -> np.ndarray:
    return df["w_eval"].to_numpy(dtype=float)


def _suggest(trial: optuna.Trial, name: str, rng: IntRange | FloatRange) -> Any:
    if isinstance(rng, IntRange):
        return trial.suggest_int(name, rng.low, rng.high, log=rng.log)
    return trial.suggest_float(name, rng.low, rng.high, log=rng.log)


def search_space(cfg: Config, estimator: str) -> dict[str, IntRange | FloatRange]:
    spaces = cfg.models.search_spaces
    space = {
        "logistic": spaces.logistic,
        "random_forest": spaces.random_forest,
        "xgboost": spaces.xgboost,
        "catboost": spaces.catboost,
    }[estimator]
    return {k: getattr(space, k) for k in type(space).model_fields}


def n_trials_for(cfg: Config, estimator: str, spatial: bool = False) -> int:
    if estimator == "seasonal_landcover":
        return 0
    if spatial:
        return cfg.models.n_trials_spatial_cv
    return cfg.models.n_trials_logistic if estimator == "logistic" else cfg.models.n_trials_ensemble


def evaluate_params(
    spec: ModelSpec, cfg: Config, folds: list[Fold], seed: int, scheme: str
) -> tuple[float, list[float], list[int | None]]:
    scores, iters = [], []
    for fold in folds:
        tr, va = fold.train, fold.val
        fm = fit_model(
            spec,
            cfg,
            seed,
            tr,
            tr["label"].to_numpy(),
            training_weights(tr, scheme),
            va,
            va["label"].to_numpy(),
            eval_weights(va),
        )
        p = fm.predict_proba(va)
        scores.append(average_precision(va["label"].to_numpy(), p, eval_weights(va)))
        iters.append(fm.best_iteration)
    return float(np.nanmean(scores)), scores, iters


def tune(
    spec: ModelSpec,
    cfg: Config,
    folds: list[Fold],
    seed: int,
    scheme: str,
    n_trials: int,
    on_trial: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Return (best params incl. refit iteration count, trials table)."""
    if n_trials <= 0:
        mean, scores, _ = evaluate_params(spec, cfg, folds, seed, scheme)
        table = pd.DataFrame(
            [
                {
                    "trial": 0,
                    "value": mean,
                    **{f"ap_{f.name}": s for f, s in zip(folds, scores, strict=True)},
                }
            ]
        )
        return dict(spec.params), table
    space = search_space(cfg, spec.estimator)
    records: list[dict[str, Any]] = []

    def objective(trial: optuna.Trial) -> float:
        params = {k: _suggest(trial, k, r) for k, r in space.items()}
        trial_spec = ModelSpec(
            spec.name, spec.estimator, spec.features, spec.categorical, {**spec.params, **params}
        )
        mean, scores, iters = evaluate_params(trial_spec, cfg, folds, seed, scheme)
        rec = {
            "trial": trial.number,
            "value": mean,
            **params,
            **{f"ap_{f.name}": s for f, s in zip(folds, scores, strict=True)},
            "best_iterations": [i for i in iters if i is not None],
        }
        trial.set_user_attr("best_iterations", rec["best_iterations"])
        records.append(rec)
        if on_trial:
            on_trial(rec)
        return mean if np.isfinite(mean) else -1.0

    study = optuna.create_study(
        direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed % (2**31))
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    best = dict(study.best_params)
    its = study.best_trial.user_attrs.get("best_iterations") or []
    if its and spec.early_stopping:
        key = "n_estimators" if spec.estimator == "xgboost" else "iterations"
        best[key] = max(1, round(float(np.mean(its))))
    return {**spec.params, **best}, pd.DataFrame(records)
