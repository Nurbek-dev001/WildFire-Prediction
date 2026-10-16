"""Model specifications, leakage-safe preprocessing pipelines and baselines.

All preprocessing (feature screening, imputation, scaling, one-hot encoding) lives inside a
scikit-learn ``Pipeline`` and is therefore fitted on the training partition only; validation,
calibration and test rows are only ever *transformed*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.base import BaseEstimator, ClassifierMixin, TransformerMixin
from sklearn.compose import ColumnTransformer, make_column_selector
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier

from wildfire_kz.config.schema import Config

TREE_MODELS = ("random_forest", "xgboost", "catboost")


class FeatureScreen(BaseEstimator, TransformerMixin):  # type: ignore[misc]
    """Drop columns that are (almost) entirely missing or constant in the TRAINING data."""

    def __init__(self, max_missing: float = 0.99) -> None:
        self.max_missing = max_missing

    def fit(self, X: pd.DataFrame, y: Any = None) -> FeatureScreen:
        X = pd.DataFrame(X)
        miss = X.isna().mean()
        nunique = X.nunique(dropna=True)
        self.keep_ = [c for c in X.columns if miss[c] <= self.max_missing and nunique[c] > 1]
        self.dropped_ = [c for c in X.columns if c not in self.keep_]
        self.train_stats_ = {"n_rows": len(X), "missing_share": miss.to_dict()}
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(X)[self.keep_]

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        return np.asarray(self.keep_, dtype=object)


@dataclass
class ModelSpec:
    name: str
    estimator: str  # logistic | random_forest | xgboost | catboost | seasonal_landcover
    features: list[str]
    categorical: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def numeric(self) -> list[str]:
        return [f for f in self.features if f not in self.categorical]

    @property
    def is_tree(self) -> bool:
        return self.estimator in TREE_MODELS

    @property
    def early_stopping(self) -> bool:
        return self.estimator in ("xgboost", "catboost")


def make_preprocessor(spec: ModelSpec, cfg: Config) -> Pipeline:
    """Training-only fitted preprocessing; trees keep NaN natively where supported.

    Order: screening (drop near-empty / constant numeric columns, fitted on training rows)
    -> imputation (median + missing indicators; LR and RF) -> scaling (LR) -> one-hot encoding
    of categorical columns. Columns are selected by dtype after screening.
    """
    max_missing = cfg.models.feature_screening_max_missing
    screen = ColumnTransformer(
        [("screen", FeatureScreen(max_missing), spec.numeric)],
        remainder="passthrough",
        verbose_feature_names_out=False,
    )
    screen.set_output(transform="pandas")
    numeric_steps: list[tuple[str, Any]] = []
    if spec.estimator in ("logistic", "random_forest"):
        numeric_steps.append(("impute", SimpleImputer(strategy="median", add_indicator=True)))
    if spec.estimator == "logistic":
        numeric_steps.append(("scale", StandardScaler()))
    transformers: list[tuple[str, Any, Any]] = [
        (
            "num",
            Pipeline(numeric_steps) if numeric_steps else "passthrough",
            make_column_selector(dtype_include="number"),
        )
    ]
    if spec.categorical:
        transformers.append(
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                make_column_selector(dtype_exclude="number"),
            )
        )
    encode = ColumnTransformer(transformers, verbose_feature_names_out=False)
    encode.set_output(transform="pandas")
    return Pipeline([("screen", screen), ("encode", encode)])


def make_estimator(spec: ModelSpec, cfg: Config, seed: int) -> Any:
    p = dict(spec.params)
    n_jobs = cfg.models.n_jobs
    if spec.estimator == "logistic":
        return LogisticRegression(
            C=p.get("C", 1.0), l1_ratio=0.0, solver="lbfgs", max_iter=cfg.models.logistic_max_iter
        )
    if spec.estimator == "random_forest":
        return RandomForestClassifier(
            n_estimators=int(p.get("n_estimators", 300)),
            max_depth=p.get("max_depth"),
            min_samples_leaf=int(p.get("min_samples_leaf", 1)),
            max_features=p.get("max_features", "sqrt"),
            n_jobs=n_jobs,
            random_state=seed,
        )
    if spec.estimator == "xgboost":
        return XGBClassifier(
            n_estimators=int(p.get("n_estimators", 500)),
            max_depth=int(p.get("max_depth", 6)),
            min_child_weight=p.get("min_child_weight", 1.0),
            learning_rate=p.get("learning_rate", 0.05),
            reg_lambda=p.get("reg_lambda", 1.0),
            reg_alpha=p.get("reg_alpha", 0.0),
            subsample=p.get("subsample", 1.0),
            colsample_bytree=p.get("colsample_bytree", 1.0),
            tree_method="hist",
            eval_metric="aucpr",
            n_jobs=n_jobs,
            random_state=seed,
            early_stopping_rounds=p.get("_early_stopping_rounds"),
        )
    if spec.estimator == "catboost":
        return CatBoostClassifier(
            iterations=int(p.get("iterations", 500)),
            depth=int(p.get("depth", 6)),
            min_data_in_leaf=int(p.get("min_data_in_leaf", 1)),
            learning_rate=p.get("learning_rate", 0.05),
            l2_leaf_reg=p.get("l2_leaf_reg", 3.0),
            eval_metric="PRAUC",
            random_seed=seed,
            verbose=0,
            allow_writing_files=False,
            thread_count=n_jobs if n_jobs > 0 else -1,
        )
    if spec.estimator == "seasonal_landcover":
        return SeasonalLandcoverBaseline(alpha=cfg.models.seasonal_smoothing_alpha)
    raise ValueError(f"unknown estimator {spec.estimator}")


class SeasonalLandcoverBaseline(BaseEstimator, ClassifierMixin):  # type: ignore[misc]
    """Smoothed land-cover-group x calendar-month fire frequency (weighted).

    rate(g, m) = (sum w*y + alpha * rate_all) / (sum w + alpha), fitted with the training
    weights so that rates refer to the complete risk set rather than the sampled design.
    """

    def __init__(self, alpha: float = 50.0) -> None:
        self.alpha = alpha

    def fit(
        self, X: pd.DataFrame, y: np.ndarray, sample_weight: np.ndarray | None = None
    ) -> SeasonalLandcoverBaseline:
        w = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, float)
        df = pd.DataFrame(
            {
                "g": X["lc_group"].astype(str).to_numpy(),
                "m": X["month"].astype(int).to_numpy(),
                "wy": w * y,
                "w": w,
            }
        )
        self.overall_ = float(df["wy"].sum() / df["w"].sum())
        agg = df.groupby(["g", "m"])[["wy", "w"]].sum()
        self.table_ = (agg["wy"] + self.alpha * self.overall_) / (agg["w"] + self.alpha)
        self.classes_ = np.array([0, 1])
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        idx = pd.MultiIndex.from_arrays(
            [X["lc_group"].astype(str).to_numpy(), X["month"].astype(int).to_numpy()]
        )
        p = self.table_.reindex(idx).fillna(self.overall_).to_numpy()
        return np.column_stack([1 - p, p])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


@dataclass
class FittedModel:
    """Preprocessor + estimator fitted on a training partition."""

    spec: ModelSpec
    preprocessor: Pipeline | None
    estimator: Any
    best_iteration: int | None = None
    train_seconds: float = 0.0
    peak_rss_mb: float = 0.0

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        return X if self.preprocessor is None else self.preprocessor.transform(X)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Uncalibrated probability of a new-event start."""
        return np.asarray(self.estimator.predict_proba(self.transform(X))[:, 1])

    def decision_logit(self, X: pd.DataFrame) -> np.ndarray:
        """Uncalibrated log-odds score (input to Platt calibration and TreeSHAP)."""
        Xt = self.transform(X)
        if self.spec.estimator == "xgboost":
            return np.asarray(self.estimator.predict(Xt, output_margin=True))
        if self.spec.estimator == "catboost":
            return np.asarray(self.estimator.predict(Xt, prediction_type="RawFormulaVal"))
        if self.spec.estimator == "logistic":
            return np.asarray(self.estimator.decision_function(Xt))
        p = np.clip(self.estimator.predict_proba(Xt)[:, 1], 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))


def fit_model(
    spec: ModelSpec,
    cfg: Config,
    seed: int,
    X: pd.DataFrame,
    y: np.ndarray,
    w: np.ndarray,
    X_val: pd.DataFrame | None = None,
    y_val: np.ndarray | None = None,
    w_val: np.ndarray | None = None,
) -> FittedModel:
    """Fit preprocessing on training rows only, then the estimator (early stopping on val)."""
    from wildfire_kz.utils.resources import track_resources

    with track_resources() as usage:
        if spec.estimator == "seasonal_landcover":
            est = make_estimator(spec, cfg, seed).fit(X, y, sample_weight=w)
            fm = FittedModel(spec, None, est)
        else:
            pre = make_preprocessor(spec, cfg)
            Xt = pre.fit_transform(X[spec.features], y)
            use_es = spec.early_stopping and X_val is not None and y_val is not None
            if spec.estimator == "xgboost" and use_es:
                spec_es = ModelSpec(
                    **{
                        **spec.__dict__,
                        "params": {
                            **spec.params,
                            "_early_stopping_rounds": cfg.models.early_stopping_rounds,
                        },
                    }
                )
                est = make_estimator(spec_es, cfg, seed)
            else:
                est = make_estimator(spec, cfg, seed)
            best_it = None
            if use_es:
                Xv = pre.transform(X_val[spec.features])  # type: ignore[index]
                if spec.estimator == "xgboost":
                    est.fit(
                        Xt,
                        y,
                        sample_weight=w,
                        eval_set=[(Xv, y_val)],
                        sample_weight_eval_set=[w_val],
                        verbose=False,
                    )
                    best_it = int(est.best_iteration) + 1
                else:
                    from catboost import Pool

                    est.fit(
                        Pool(Xt, y, weight=w),
                        eval_set=Pool(Xv, y_val, weight=w_val),
                        early_stopping_rounds=cfg.models.early_stopping_rounds,
                        use_best_model=True,
                    )
                    best_it = int(est.get_best_iteration()) + 1
            else:
                est.fit(Xt, y, sample_weight=w)
            fm = FittedModel(spec, pre, est, best_iteration=best_it)
    fm.train_seconds = usage.wall_seconds
    fm.peak_rss_mb = usage.peak_rss_mb
    return fm
