"""Stage 10 — grouped feature ablations.

Each ablation removes ONE named group (anthropogenic variables, lagged/antecedent weather,
vegetation, and each correlated predictor group) and re-fits the model on identical rows.
Correlated predictors are never dropped automatically: correlation clusters found in the
development training data are reported and ablated *as groups*.

Ablated models use the hyper-parameters selected for the full model (``ablation.retune``
false by default) and are scored on the same rolling-origin development folds; they are
calibrated on the calibration year like every other model and evaluated on the test years
only by the final evaluation stage.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from wildfire_kz.calibration.calibrate import calibrate_models
from wildfire_kz.config.schema import Config
from wildfire_kz.features.registry import FeatureSpec, resolve_group_refs
from wildfire_kz.models.pipelines import ModelSpec, fit_model
from wildfire_kz.models.train import load_specs, model_specs, rolling_folds, save_model
from wildfire_kz.models.tuning import evaluate_params, n_trials_for, training_weights, tune
from wildfire_kz.paths import RunPaths
from wildfire_kz.splits.guard import FeatureStore
from wildfire_kz.utils.runtime import derive_seed, get_logger, read_json, write_json

log = get_logger("ablation")


def correlation_clusters(
    df: pd.DataFrame, features: list[str], threshold: float
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Spearman |rho| clustering (complete linkage at 1 - threshold) on training rows."""
    num = df[features].select_dtypes("number")
    num = num.loc[:, num.nunique() > 1]
    corr = num.corr(method="spearman").fillna(0.0)
    dist = 1.0 - corr.abs().to_numpy()
    np.fill_diagonal(dist, 0.0)
    labels = fcluster(
        linkage(squareform(dist, checks=False), method="complete"),
        t=1.0 - threshold,
        criterion="distance",
    )
    clusters: dict[str, list[str]] = {}
    for f, lab in zip(corr.columns, labels, strict=True):
        clusters.setdefault(f"corr_cluster_{lab}", []).append(f)
    clusters = {k: v for k, v in clusters.items() if len(v) > 1}
    stacked = corr.where(np.triu(np.ones(corr.shape, bool), 1)).stack()
    stacked = stacked[(stacked.abs() >= threshold).to_numpy()]
    pairs = pd.DataFrame(
        {
            "feature_a": stacked.index.get_level_values(0),
            "feature_b": stacked.index.get_level_values(1),
            "spearman_rho": stacked.to_numpy(),
        }
    )
    return pairs, clusters


def ablation_groups(
    cfg: Config, specs: list[FeatureSpec], clusters: dict[str, list[str]]
) -> dict[str, list[str]]:
    g = cfg.features.groups
    groups = {name: resolve_group_refs(refs, specs) for name, refs in g.ablation_groups.items()}
    if cfg.ablation.include_correlated_groups:
        for name, refs in g.correlated_groups.items():
            groups[f"correlated_{name}"] = resolve_group_refs(refs, specs)
        groups.update(clusters)
    return {k: v for k, v in groups.items() if v}


def run_ablation(cfg: Config, paths: RunPaths) -> dict[str, Any]:
    out_dir = paths.stage("ablate")
    out_dir.mkdir(parents=True, exist_ok=True)
    store = FeatureStore(cfg, paths)
    dev = store.load(cfg.splits.development_years, "train")
    cal = store.load(cfg.splits.calibration_years, "calibration")
    cal = cal[cal["in_eval"]].reset_index(drop=True)
    specs = load_specs(paths)
    selection = read_json(paths.stage("train") / "selection.json")["models"]
    scheme = cfg.sampling.training_weighting
    train_rows = dev[dev["in_train"]].reset_index(drop=True)
    pairs, clusters = correlation_clusters(
        train_rows, [s.name for s in specs], cfg.features.groups.correlation_threshold
    )
    pairs.to_csv(out_dir / "correlated_feature_pairs.csv", index=False)
    write_json(out_dir / "correlation_clusters.json", clusters)
    groups = ablation_groups(cfg, specs, clusters)
    write_json(out_dir / "ablation_groups.json", groups)
    folds = rolling_folds(cfg, dev)
    rows = []
    fitted = {}
    for model in cfg.ablation.models:
        base_params = selection[model]["params"]
        full_spec = model_specs(cfg, specs)[model]
        seed = derive_seed(cfg.project.seed, "ablation", model)
        full_spec = ModelSpec(
            model, full_spec.estimator, full_spec.features, full_spec.categorical, base_params
        )
        full_mean, full_scores, _ = evaluate_params(full_spec, cfg, folds, seed, scheme)
        for gname, feats in groups.items():
            keep = [f for f in full_spec.features if f not in feats]
            spec = ModelSpec(
                f"{model}__minus_{gname}",
                full_spec.estimator,
                keep,
                [c for c in full_spec.categorical if c in keep],
                base_params,
            )
            if cfg.ablation.retune:
                params, _ = tune(spec, cfg, folds, seed, scheme, n_trials_for(cfg, spec.estimator))
                spec = ModelSpec(spec.name, spec.estimator, keep, spec.categorical, params)
            mean, scores, _ = evaluate_params(spec, cfg, folds, seed, scheme)
            rows.append(
                {
                    "model": model,
                    "ablated_group": gname,
                    "removed_features": feats,
                    "n_features": len(keep),
                    "dev_cv_weighted_ap": mean,
                    "full_model_dev_cv_weighted_ap": full_mean,
                    "delta_ap_vs_full": mean - full_mean,
                    **{f"ap_{f.name}": s for f, s in zip(folds, scores, strict=True)},
                    **{f"full_ap_{f.name}": s for f, s in zip(folds, full_scores, strict=True)},
                }
            )
            fm = fit_model(
                spec,
                cfg,
                seed,
                train_rows,
                train_rows["label"].to_numpy(),
                training_weights(train_rows, scheme),
            )
            save_model(
                fm,
                out_dir / "models" / spec.name,
                {"params": spec.params, "removed": feats, "of_model": model, "group": gname},
            )
            fitted[spec.name] = fm
            log.info("ablation %s: dev AP %.4f (full %.4f)", spec.name, mean, full_mean)
    table = pd.DataFrame(rows)
    table.to_csv(out_dir / "ablation_validation.csv", index=False)
    params, _ = calibrate_models(cfg, fitted, cal)
    write_json(out_dir / "ablation_calibration.json", params)
    return {"n_ablations": len(rows)}
