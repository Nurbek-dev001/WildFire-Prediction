"""Stage 8 — train: tune, select and refit all classifiers and baselines.

Temporal experiment: Optuna on rolling-origin development folds, selection by mean weighted
AP on development validation years, refit on all development years. Identical rows and
features are used for every model. A class-weighting sensitivity variant is refitted with the
selected hyper-parameters. A separate spatial-block CV experiment re-runs preprocessing and
tuning inside every fold.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from wildfire_kz.config.schema import Config
from wildfire_kz.evaluation.metrics import average_precision, brier, prevalence, roc_auc
from wildfire_kz.features.registry import FeatureSpec, resolve_group_refs
from wildfire_kz.models.pipelines import TREE_MODELS, FittedModel, ModelSpec, fit_model
from wildfire_kz.models.tuning import (
    Fold,
    eval_weights,
    n_trials_for,
    training_weights,
    tune,
)
from wildfire_kz.paths import RunPaths
from wildfire_kz.splits.guard import FeatureStore
from wildfire_kz.utils.runtime import derive_seed, get_logger, read_json, write_json

log = get_logger("models.train")


def load_specs(paths: RunPaths) -> list[FeatureSpec]:
    reg = read_json(paths.stage("features") / "feature_registry.json")
    return [FeatureSpec(**r) for r in reg["features"]]


def model_specs(cfg: Config, specs: list[FeatureSpec],
                exclude: list[str] | None = None) -> dict[str, ModelSpec]:
    """Classifier + baseline specifications sharing the same feature information."""
    exclude = exclude or []
    feats = [s.name for s in specs if s.name not in exclude]
    cats = [s.name for s in specs if s.categorical and s.name in feats]
    out: dict[str, ModelSpec] = {}
    for m in cfg.models.classifiers:
        out[m] = ModelSpec(m, m, feats, cats)
    if "seasonal_landcover" in cfg.models.baselines:
        out["seasonal_landcover"] = ModelSpec("seasonal_landcover", "seasonal_landcover",
                                              ["lc_group", "month"], [])
    if "weather_logistic" in cfg.models.baselines:
        wf = resolve_group_refs([f"@{g}" for g in cfg.features.groups.weather_only_groups], specs)
        out["weather_logistic"] = ModelSpec("weather_logistic", "logistic",
                                            [f for f in wf if f in feats], [])
    return out


def rolling_folds(cfg: Config, dev: pd.DataFrame, mask: pd.Series | None = None) -> list[Fold]:
    folds = []
    for f in cfg.splits.rolling_origin:
        sel = dev if mask is None else dev[mask]
        tr = sel[sel["year"].isin(f.train_years) & sel["in_train"]]
        va = sel[(sel["year"] == f.val_year) & sel["in_eval"]]
        folds.append(Fold(f"val{f.val_year}", tr.reset_index(drop=True),
                          va.reset_index(drop=True)))
    return folds


def save_model(fm: FittedModel, path: Path, meta: dict[str, Any]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    joblib.dump(fm, path / "model.joblib")
    write_json(path / "model_meta.json", meta)


def load_model(path: Path) -> FittedModel:
    return joblib.load(path / "model.joblib")  # type: ignore[no-any-return]


def train_temporal(cfg: Config, paths: RunPaths, dev: pd.DataFrame,
                   specs: dict[str, ModelSpec], out_dir: Path, tag: str = "") -> dict[str, Any]:
    """Tune on rolling-origin folds, refit on all development years; returns selection info."""
    scheme = cfg.sampling.training_weighting
    folds = rolling_folds(cfg, dev)
    train_all = dev[dev["in_train"]].reset_index(drop=True)
    results: dict[str, Any] = {}
    for name, spec in specs.items():
        seed = derive_seed(cfg.project.seed, "model", name, tag)
        n_trials = n_trials_for(cfg, spec.estimator)
        log.info("tuning %s%s (%d trials, %d folds)", name, tag, n_trials, len(folds))
        best, trials = tune(spec, cfg, folds, seed, scheme, n_trials)
        trials.to_csv(out_dir / f"trials_{name}{tag}.csv", index=False)
        best_value = float(trials["value"].max()) if len(trials) else float("nan")
        best_row = trials.loc[trials["value"].idxmax()] if len(trials) else pd.Series(dtype=float)
        fold_scores = {f.name: float(best_row.get(f"ap_{f.name}", np.nan)) for f in folds}
        final_spec = ModelSpec(spec.name, spec.estimator, spec.features, spec.categorical, best)
        fm = fit_model(final_spec, cfg, seed, train_all, train_all["label"].to_numpy(),
                       training_weights(train_all, scheme))
        meta = {"params": best, "cv_weighted_ap_mean": best_value,
                "cv_weighted_ap_by_fold": fold_scores, "seed": seed, "scheme": scheme,
                "features": spec.features, "train_rows": len(train_all),
                "train_seconds": fm.train_seconds, "peak_rss_mb": fm.peak_rss_mb}
        save_model(fm, out_dir / f"{name}{tag}", meta)
        results[f"{name}{tag}"] = meta
        log.info("%s%s: dev CV weighted AP %.4f", name, tag, best_value)
    return results


def train_class_weight_variants(cfg: Config, dev: pd.DataFrame, selection: dict[str, Any],
                                specs: dict[str, ModelSpec], out_dir: Path) -> dict[str, Any]:
    """Sensitivity alternative: training-only class weighting with the selected params."""
    train_all = dev[dev["in_train"]].reset_index(drop=True)
    out = {}
    for name in cfg.models.classifiers:
        spec = specs[name]
        params = selection[name]["params"]
        seed = derive_seed(cfg.project.seed, "model", name, "classweight")
        fm = fit_model(ModelSpec(name, spec.estimator, spec.features, spec.categorical, params),
                       cfg, seed, train_all, train_all["label"].to_numpy(),
                       training_weights(train_all, "class_weight"))
        meta = {"params": params, "scheme": "class_weight", "seed": seed,
                "features": spec.features, "train_seconds": fm.train_seconds,
                "peak_rss_mb": fm.peak_rss_mb, "sensitivity_of": name}
        save_model(fm, out_dir / f"{name}__classweight", meta)
        out[f"{name}__classweight"] = meta
    return out


def spatial_cv(cfg: Config, paths: RunPaths, dev: pd.DataFrame, specs: dict[str, ModelSpec],
               out_dir: Path) -> pd.DataFrame:
    """Spatial-transfer experiment: tuning + preprocessing re-run inside each spatial fold."""
    sc = cfg.splits.spatial_cv
    scheme = cfg.sampling.training_weighting
    dev_years = sorted(cfg.splits.development_years)
    inner_val, inner_train = dev_years[-1], dev_years[:-1]
    rows = []
    for block in [sc.block_size_km, *sc.sensitivity_block_sizes_km]:
        tag = f"{int(block)}km"
        roles = pd.read_parquet(paths.stage("splits") / f"spatial_roles_{tag}.parquet")
        for k in sorted(roles["fold"].unique()):
            r = roles[roles["fold"] == k].set_index("cell_id")["role"]
            role = dev["cell_id"].map(r)
            train_reg = dev[role == "train"]
            test_reg = dev[(role == "test") & dev["in_eval"]].reset_index(drop=True)
            inner = [Fold("inner", train_reg[train_reg["year"].isin(inner_train)
                                             & train_reg["in_train"]].reset_index(drop=True),
                          train_reg[(train_reg["year"] == inner_val)
                                    & train_reg["in_eval"]].reset_index(drop=True))]
            full_train = train_reg[train_reg["in_train"]].reset_index(drop=True)
            for name, spec in specs.items():
                seed = derive_seed(cfg.project.seed, "spatial", tag, k, name)
                best, _ = tune(spec, cfg, inner, seed, scheme,
                               n_trials_for(cfg, spec.estimator, spatial=True))
                fm = fit_model(ModelSpec(name, spec.estimator, spec.features, spec.categorical,
                                         best), cfg, seed, full_train,
                               full_train["label"].to_numpy(),
                               training_weights(full_train, scheme))
                y = test_reg["label"].to_numpy()
                w = eval_weights(test_reg)
                p = fm.predict_proba(test_reg)
                rows.append({"block_km": block, "fold": int(k), "model": name,
                             "n_test_rows": len(test_reg), "test_positives": int(y.sum()),
                             "prevalence": prevalence(y, w),
                             "average_precision": average_precision(y, p, w),
                             "roc_auc": roc_auc(y, p, w), "brier_uncalibrated": brier(y, p, w),
                             "n_buffer_cells": int((r == "buffer").sum()),
                             "params": str(best)})
                if spec.estimator in TREE_MODELS and block == sc.block_size_km:
                    save_model(fm, out_dir / "spatial_cv" / tag / name / f"fold_{k}",
                               {"params": best, "fold": int(k), "block_km": block})
            log.info("spatial CV %s fold %d done", tag, k)
    table = pd.DataFrame(rows)
    table.to_csv(out_dir / "spatial_cv_results.csv", index=False)
    return table


def select_models(cfg: Config, results: dict[str, Any]) -> dict[str, Any]:
    """Selection uses development validation scores only (never calibration or test)."""
    trees = {m: results[m]["cv_weighted_ap_mean"] for m in cfg.models.classifiers
             if m in TREE_MODELS and m in results}
    allm = {m: results[m]["cv_weighted_ap_mean"] for m in cfg.models.classifiers if m in results}

    def pick(d: dict[str, float]) -> str | None:
        return max(d, key=lambda k: (np.nan_to_num(d[k], nan=-1), k)) if d else None

    return {"selected_tree_model": pick(trees), "best_classifier": pick(allm),
            "criterion": "mean weighted AP over rolling-origin development validation years"}


def run_train(cfg: Config, paths: RunPaths) -> dict[str, Any]:
    out_dir = paths.stage("train")
    out_dir.mkdir(parents=True, exist_ok=True)
    store = FeatureStore(cfg, paths)
    dev = store.load(cfg.splits.development_years, "train")
    fspecs = load_specs(paths)
    specs = model_specs(cfg, fspecs)
    results = train_temporal(cfg, paths, dev, specs, out_dir)
    selection = select_models(cfg, results)
    if cfg.models.run_class_weight_sensitivity:
        results.update(train_class_weight_variants(cfg, dev, results, specs, out_dir))
    summary: dict[str, Any] = {"models": results, **selection}
    if cfg.models.run_spatial_cv:
        table = spatial_cv(cfg, paths, dev, specs, out_dir)
        summary["spatial_cv_mean_ap"] = table.groupby(["block_km", "model"])[
            "average_precision"].mean().reset_index().to_dict(orient="records")
    write_json(out_dir / "selection.json", summary)
    return {k: v for k, v in selection.items()}
