"""Fold-local preprocessing, weighted baselines, nested validation and Optuna tuning."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from wildfire_kz.config import Config
from wildfire_kz.data.store import FeatureStore
from wildfire_kz.features import WEATHER
from wildfire_kz.sampling import sample_training
from wildfire_kz.splits import rolling_folds, spatial_folds


@dataclass
class FittedModel:
    """Serializable preprocessing and estimator with an explicit feature order."""

    name: str
    features: list[str]
    pipeline: Pipeline

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return self.pipeline.predict_proba(frame[self.features])[:, 1]


@dataclass
class SeasonalModel:
    """Development-only smoothed land-cover x calendar-month frequency baseline."""

    rates: dict[tuple[str, int], float]
    prior: float
    name: str = "seasonal"

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.array(
            [
                self.rates.get((str(c), int(m)), self.prior)
                for c, m in zip(frame.landcover, frame.day.dt.month, strict=True)
            ]
        )


def fit_seasonal(frame: pd.DataFrame, smoothing: float) -> SeasonalModel:
    weights = frame.get("weight", pd.Series(1.0, index=frame.index))
    prior = float(np.average(frame.label, weights=weights))
    data = frame.assign(month=frame.day.dt.month, weighted_y=frame.label * weights, weight=weights)
    grouped = data.groupby(["landcover", "month"], observed=True).agg(
        positive=("weighted_y", "sum"), total=("weight", "sum")
    )
    rates = {
        (str(c), int(m)): float((float(positive) + smoothing * prior) / (float(total) + smoothing))
        for c, m, positive, total in grouped.reset_index().to_numpy()
    }
    return SeasonalModel(rates, prior)


def suggest(trial: optuna.Trial, name: str, cfg: Config) -> dict[str, Any]:
    """Search only specified ensemble complexity and regularization parameters."""
    params: dict[str, Any] = {
        "n_estimators": trial.suggest_int(
            "n_estimators", cfg.models.n_estimators_min, cfg.models.n_estimators_max
        ),
        "max_depth": trial.suggest_int("max_depth", 3, 10),
    }
    if name == "random_forest":
        params.update(
            min_samples_leaf=trial.suggest_int("min_samples_leaf", 2, 40),
            max_features=trial.suggest_float("max_features", 0.4, 1.0),
            ccp_alpha=trial.suggest_float("ccp_alpha", 1e-8, 1e-2, log=True),
        )
    else:
        params["learning_rate"] = trial.suggest_float("learning_rate", 0.01, 0.2, log=True)
        if name == "xgboost":
            params.update(
                min_child_weight=trial.suggest_float("min_child_weight", 1, 40),
                reg_lambda=trial.suggest_float("reg_lambda", 0.01, 100, log=True),
                reg_alpha=trial.suggest_float("reg_alpha", 1e-4, 10, log=True),
            )
        else:
            params.update(
                min_data_in_leaf=trial.suggest_int("min_data_in_leaf", 2, 40),
                l2_leaf_reg=trial.suggest_float("l2_leaf_reg", 0.01, 100, log=True),
            )
    return params


def fit_model(
    name: str,
    train: pd.DataFrame,
    features: list[str],
    cfg: Config,
    params: dict[str, Any] | None = None,
    validation: pd.DataFrame | None = None,
    *,
    sampled: bool = False,
) -> FittedModel:
    """Fit transforms on TRAIN ONLY; early stopping sees development validation only."""
    data = train if sampled else sample_training(train, cfg.sampling, cfg.seed)
    params = dict(params or {})
    pre = Pipeline(
        [
            (
                "impute",
                SimpleImputer(strategy="median", add_indicator=False, keep_empty_features=True),
            ),
            ("scale", StandardScaler()),
        ]
    )
    transformed = pre.fit_transform(data[features])
    weights = data.weight.to_numpy().copy()
    if cfg.sampling.mode == "class_weight":
        counts = np.bincount(data.label.astype(int), minlength=2)
        weights *= np.where(
            data.label == 1,
            len(data) / (2 * max(1, counts[1])),
            len(data) / (2 * max(1, counts[0])),
        )
    if name in ["logistic", "weather_logistic"]:
        estimator: Any = LogisticRegression(C=1.0, max_iter=2000, random_state=cfg.seed)
    elif name == "random_forest":
        estimator = RandomForestClassifier(
            **params, random_state=cfg.seed, n_jobs=cfg.models.threads
        )
    elif name == "xgboost":
        from xgboost import XGBClassifier

        estimator = XGBClassifier(
            **params,
            objective="binary:logistic",
            eval_metric="logloss",
            tree_method="hist",
            random_state=cfg.seed,
            n_jobs=cfg.models.threads,
            **(
                {"early_stopping_rounds": cfg.models.early_stopping_rounds}
                if validation is not None
                else {}
            ),
        )
    elif name == "catboost":
        from catboost import CatBoostClassifier

        if "max_depth" in params:
            params["depth"] = params.pop("max_depth")
        # Lossguide makes min_data_in_leaf an active parameter.
        estimator = CatBoostClassifier(
            **params,
            grow_policy="Lossguide",
            loss_function="Logloss",
            random_seed=cfg.seed,
            thread_count=cfg.models.threads,
            verbose=False,
            allow_writing_files=False,
        )
    else:
        raise ValueError(name)
    kwargs: dict[str, Any] = {"sample_weight": weights}
    if validation is not None:
        if validation.day.dt.year.max() > cfg.splits.development_end:
            raise PermissionError("Early stopping must use development data only")
        vx = pre.transform(validation[features])
        vw = validation.get("weight", pd.Series(1.0, index=validation.index)).to_numpy()
        if name == "xgboost":
            kwargs.update(
                eval_set=[(vx, validation.label)], sample_weight_eval_set=[vw], verbose=False
            )
        elif name == "catboost":
            from catboost import Pool

            kwargs.update(
                eval_set=Pool(vx, validation.label, weight=vw),
                early_stopping_rounds=cfg.models.early_stopping_rounds,
                use_best_model=True,
            )
    estimator.fit(transformed, data.label, **kwargs)
    pipeline = Pipeline([("preprocess", pre), ("estimator", estimator)])
    return FittedModel(name, features, pipeline)


def tune(
    name: str,
    data: pd.DataFrame | FeatureStore,
    features: list[str],
    cfg: Config,
    validation_years: list[int],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Optimize weighted AP on rolling development folds; refit transforms per trial/fold."""
    if name in ["logistic", "weather_logistic"]:
        return {}, []
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    if isinstance(data, FeatureStore):
        prepared = [
            (
                data.view([y for y in data.years if y < year]).sample(training=True),
                data.view([year]).sample(training=False),
            )
            for year in validation_years
        ]
    else:
        prepared = [
            (data.iloc[ti], data.iloc[vi]) for _, ti, vi in rolling_folds(data, validation_years)
        ]
    if not prepared or any(not len(t) or not len(v) for t, v in prepared):
        raise ValueError("Tuning requires nonempty chronological training/validation folds")
    best_iterations: dict[int, list[int]] = {}

    def objective(trial: optuna.Trial) -> float:
        params = suggest(trial, name, cfg)
        scores, lengths, iterations = [], [], []
        for train, valid in prepared:
            model = fit_model(
                name, train, features, cfg, params, valid, sampled=isinstance(data, FeatureStore)
            )
            scores.append(
                average_precision_score(
                    valid.label, model.predict(valid), sample_weight=valid.weight
                )
            )
            lengths.append(float(valid.weight.sum()))
            estimator = model.pipeline.named_steps["estimator"]
            if name == "xgboost":
                iterations.append(int(estimator.best_iteration) + 1)
            elif name == "catboost":
                iterations.append(int(estimator.tree_count_))
        best_iterations[trial.number] = iterations
        return float(np.average(scores, weights=lengths))

    study = optuna.create_study(
        direction="maximize", sampler=optuna.samplers.TPESampler(seed=cfg.seed)
    )
    study.optimize(objective, n_trials=cfg.models.trials)
    selected = dict(study.best_params)
    if best_iterations[study.best_trial.number]:
        selected["n_estimators"] = max(2, int(np.median(best_iterations[study.best_trial.number])))
    trials = [
        {"number": t.number, "weighted_ap": t.value, "params": t.params} for t in study.trials
    ]
    return selected, trials


def train_store_suite(
    store: FeatureStore,
    cells: pd.DataFrame,
    features: list[str],
    cfg: Config,
    artifact_dir: Path | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any], pd.DataFrame]:
    """Memory-bounded nested validation: define each fold before reading/sampling rows."""
    folds: list[tuple[str, FeatureStore, FeatureStore]] = []
    for year in cfg.splits.validation_years:
        folds.append(
            (
                f"temporal_{year}",
                store.view([y for y in store.years if y < year]),
                store.view([year]),
            )
        )
    for size in [cfg.splits.block_m] + cfg.splits.sensitivity_block_m:
        for name, ti, vi in spatial_folds(
            cells, size, cfg.splits.spatial_folds, cfg.splits.buffer_m
        ):
            folds.append(
                (
                    name,
                    store.view(store.years, set(cells.iloc[ti].cell_id)),
                    store.view(store.years, set(cells.iloc[vi].cell_id)),
                )
            )
    rows: list[dict[str, Any]] = []
    trials: dict[str, Any] = {}
    heldout: list[pd.DataFrame] = []
    names = cfg.models.names + ["weather_logistic", "seasonal"]
    for fold, train_view, valid_view in folds:
        logging.getLogger("wildfire_kz").info("training outer fold %s", fold)
        train, valid = train_view.sample(training=True), valid_view.sample(training=False)
        if artifact_dir is not None:
            samples = artifact_dir / "samples"
            samples.mkdir(exist_ok=True, parents=True)
            train[["cell_id", "day", "label", "q", "weight"]].to_parquet(
                samples / f"{fold}.parquet", index=False
            )
        inner_years = [y for y in cfg.splits.validation_years if y <= max(train_view.years)]
        if not inner_years:
            inner_years = [max(train_view.years)]
        for name in names:
            started = time.perf_counter()
            cols = [f for f in features if f in WEATHER] if name == "weather_logistic" else features
            if name == "seasonal":
                model: Any = fit_seasonal(train, cfg.models.seasonal_smoothing)
            else:
                params, history = tune(name, train_view, cols, cfg, inner_years)
                trials[f"{fold}/{name}"] = {"trials": history, "selected": params}
                model = fit_model(name, train, cols, cfg, params, sampled=True)
            prediction = model.predict(valid)
            rows.append(
                {
                    "fold": fold,
                    "model": name,
                    "weighted_ap": float(
                        average_precision_score(valid.label, prediction, sample_weight=valid.weight)
                    ),
                    "train_rows": len(train),
                    "validation_rows": len(valid),
                    "validation_weight": float(valid.weight.sum()),
                    "fit_and_tune_seconds": time.perf_counter() - started,
                }
            )
            if fold.startswith(f"spatial_{cfg.splits.block_m}_"):
                heldout.append(
                    valid[["cell_id", "day", "label", "landcover", "region"]].assign(
                        model=name, probability=prediction, fold=fold
                    )
                )
    fitted: dict[str, Any] = {}
    train = store.sample(training=True)
    if artifact_dir is not None:
        train[["cell_id", "day", "label", "q", "weight"]].to_parquet(
            artifact_dir / "samples" / "final.parquet", index=False
        )
    for name in names:
        started = time.perf_counter()
        cols = [f for f in features if f in WEATHER] if name == "weather_logistic" else features
        if name == "seasonal":
            fitted[name] = fit_seasonal(train, cfg.models.seasonal_smoothing)
        else:
            params, history = tune(name, store, cols, cfg, cfg.splits.validation_years)
            trials[f"final/{name}"] = {"trials": history, "selected": params}
            fitted[name] = fit_model(name, train, cols, cfg, params, sampled=True)
        trials[f"final_timing/{name}"] = {"seconds": time.perf_counter() - started}
    return fitted, pd.DataFrame(rows), trials, pd.concat(heldout, ignore_index=True)
