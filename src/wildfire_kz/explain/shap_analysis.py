"""Stage 12 — TreeSHAP explanations of the selected tree ensemble.

* Explanations are computed on the model's **uncalibrated** output: log-odds (margin) for
  XGBoost and CatBoost. scikit-learn Random Forests only expose probabilities, so if RF is
  the selected tree model its SHAP values are on the probability scale; this is recorded in
  the output metadata.
* Correlated predictors are also analysed together (summed SHAP per correlated group and
  per feature group), because individual attributions are unstable among correlated inputs.
* Contributions are compared across land-cover groups and across held-out spatial-CV regions.
* All outputs describe **predictive associations of the model, not causal effects**.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import shap

from wildfire_kz.calibration.calibrate import Platt
from wildfire_kz.config.schema import Config
from wildfire_kz.features.registry import resolve_group_refs
from wildfire_kz.models.pipelines import FittedModel
from wildfire_kz.models.train import load_model, load_specs
from wildfire_kz.paths import RunPaths
from wildfire_kz.report.style import CATEGORICAL, CAUSAL_NOTE, apply_style, save
from wildfire_kz.splits.guard import FeatureStore, unlock_final_evaluation
from wildfire_kz.utils.runtime import derive_seed, get_logger, read_json, write_json

log = get_logger("explain")


def tree_shap(fm: FittedModel, X: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """SHAP values (rows x transformed features), transformed X, and the output scale."""
    Xt = fm.transform(X)
    est = fm.estimator
    if fm.spec.estimator == "random_forest":
        expl = shap.TreeExplainer(est)
        vals = expl.shap_values(Xt, check_additivity=False)
        vals = vals[..., 1] if np.ndim(vals) == 3 else vals[1]
        scale = "probability (sklearn RandomForest exposes no log-odds)"
    else:
        expl = shap.TreeExplainer(est, model_output="raw")
        vals = expl.shap_values(Xt, check_additivity=False)
        scale = "uncalibrated log-odds (raw margin)"
    return pd.DataFrame(np.asarray(vals), columns=Xt.columns, index=X.index), Xt, scale


def base_feature(col: str, categorical: list[str]) -> str:
    """Map transformed column names (one-hot, missing indicators) back to source features."""
    for c in categorical:
        if col.startswith(f"{c}_"):
            return c
    if col.startswith("missingindicator_"):
        return col[len("missingindicator_"):]
    return col


def aggregate_columns(sv: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Sum SHAP columns into groups (additivity makes summed SHAP a valid group effect)."""
    groups: dict[str, list[str]] = {}
    for col in sv.columns:
        groups.setdefault(mapping.get(col, col), []).append(col)
    return pd.DataFrame({g: sv[cols].sum(axis=1) for g, cols in groups.items()})


def _sample_rows(df: pd.DataFrame, max_rows: int, seed: int) -> pd.DataFrame:
    """Keep all positives (up to half the budget) plus a random set of negatives."""
    pos = df[df["label"] == 1]
    neg = df[df["label"] == 0]
    n_pos = min(len(pos), max_rows // 2)
    pos = pos.sample(n_pos, random_state=seed) if len(pos) > n_pos else pos
    neg = neg.sample(min(len(neg), max_rows - len(pos)), random_state=seed)
    return pd.concat([pos, neg]).reset_index(drop=True)


def _bar(series: pd.Series, title: str, path: Any, note: str) -> None:
    import matplotlib.pyplot as plt

    s = series.sort_values().tail(20)
    fig, ax = plt.subplots(figsize=(6.4, 0.28 * len(s) + 1.2))
    ax.barh(s.index, s.to_numpy(), color=CATEGORICAL[0], height=0.7)
    ax.set_xlabel("mean |SHAP|")
    ax.set_title(title, loc="left")
    ax.grid(axis="y", visible=False)
    save(fig, path, note)


def run_explain(cfg: Config, paths: RunPaths) -> dict[str, Any]:
    out = paths.stage("explain")
    out.mkdir(parents=True, exist_ok=True)
    apply_style()
    import matplotlib.pyplot as plt

    selection = read_json(paths.stage("train") / "selection.json")
    model_name = selection["selected_tree_model"]
    fm = load_model(paths.stage("train") / model_name)
    cal = read_json(paths.stage("calibrate") / "calibration_artifacts.json")["models"][model_name]
    platt, tau = Platt(cal["platt_a"], cal["platt_b"]), cal["tau"]
    specs = load_specs(paths)
    cats = fm.spec.categorical
    note = f"{CAUSAL_NOTE}. Model: {model_name}."
    if set(cfg.explain.partitions) & {"test"}:
        unlock_final_evaluation(cfg, paths, "explain")
    store = FeatureStore(cfg, paths)
    seed = derive_seed(cfg.project.seed, "explain")
    frames = []
    for part in cfg.explain.partitions:
        years = cfg.splits.calibration_years if part == "calibration" else cfg.splits.test_years
        df = store.load(years, "explain" if part == "test" else "calibration")
        frames.append(_sample_rows(df[df["in_eval"]], cfg.explain.max_rows, seed)
                      .assign(partition=part))
    data = pd.concat(frames, ignore_index=True)
    sv, Xt, scale = tree_shap(fm, data)
    raw = fm.decision_logit(data)
    data["p_calibrated"] = platt.apply(raw)
    mapping = {c: base_feature(c, cats) for c in sv.columns}
    sv_feat = aggregate_columns(sv, mapping)
    # ---- global importance (per feature, per correlated group, per feature group)
    glob = sv_feat.abs().mean().sort_values(ascending=False).rename("mean_abs_shap")
    glob.to_frame().assign(output_scale=scale).to_csv(out / "shap_global_importance.csv")
    group_of = {s.name: s.group for s in specs}
    sv_group = aggregate_columns(sv_feat, {f: group_of.get(f, f) for f in sv_feat.columns})
    sv_group.abs().mean().sort_values(ascending=False).rename("mean_abs_shap").to_csv(
        out / "shap_feature_group_importance.csv")
    corr_map: dict[str, str] = {}
    for gname, refs in cfg.features.groups.correlated_groups.items():
        for f in resolve_group_refs(refs, specs):
            corr_map[f] = gname
    clusters_path = paths.stage("ablate") / "correlation_clusters.json"
    clusters = read_json(clusters_path) if clusters_path.exists() else {}
    sv_corr = aggregate_columns(sv_feat, corr_map)
    sv_corr.abs().mean().sort_values(ascending=False).rename("mean_abs_shap").to_csv(
        out / "shap_correlated_group_importance.csv")
    write_json(out / "explain_meta.json", {
        "model": model_name, "output_scale": scale, "partitions": cfg.explain.partitions,
        "n_rows": len(data), "interpretation": CAUSAL_NOTE,
        "data_driven_correlation_clusters": clusters})
    _bar(glob, f"Global mean |SHAP| — {model_name}, {scale}", out / "shap_global_importance",
         note)
    _bar(sv_group.abs().mean(), "Mean |summed SHAP| by feature group",
         out / "shap_feature_group_importance", note)
    # ---- dependence plots for the top features
    for f in [f for f in glob.index if f in Xt.columns][: cfg.explain.n_dependence_plots]:
        fig, ax = plt.subplots(figsize=(4.8, 3.4))
        ax.scatter(Xt[f], sv_feat[f], s=6, alpha=0.35, color=CATEGORICAL[0], linewidths=0)
        ax.axhline(0, color="#8a8984", linewidth=0.8)
        ax.set_xlabel(f)
        ax.set_ylabel(f"SHAP ({'log-odds' if 'log-odds' in scale else 'probability'})")
        ax.set_title(f"Dependence: {f}", loc="left")
        save(fig, out / "dependence" / f"dependence_{f}", note)
    # ---- local examples: high-scoring, false positives, false negatives
    y = data["label"].to_numpy()
    p = data["p_calibrated"].to_numpy()
    n = cfg.explain.n_local_examples
    picks = {
        "high_scoring": np.argsort(-p)[:n],
        "false_positive": [i for i in np.argsort(-p) if y[i] == 0 and p[i] >= tau][:n],
        "false_negative": [i for i in np.argsort(p) if y[i] == 1 and p[i] < tau][:n],
    }
    local_rows = []
    for kind, idx in picks.items():
        for j, i in enumerate(idx):
            contrib = sv_feat.iloc[i].sort_values(key=np.abs, ascending=False)
            for f, v in contrib.head(10).items():
                local_rows.append({"example_type": kind, "rank": j,
                                   "cell_id": int(data.loc[i, "cell_id"]),
                                   "date": data.loc[i, "date"], "label": int(y[i]),
                                   "p_calibrated": float(p[i]), "feature": f, "shap": float(v),
                                   "partition": data.loc[i, "partition"]})
            if j == 0:
                top = contrib.head(10)[::-1]
                fig, ax = plt.subplots(figsize=(5.6, 3.6))
                ax.barh(top.index, top.to_numpy(), height=0.7,
                        color=[CATEGORICAL[7] if v > 0 else CATEGORICAL[0] for v in top])
                ax.axvline(0, color="#8a8984", linewidth=0.8)
                ax.set_title(f"{kind}: cell {int(data.loc[i, 'cell_id'])}, "
                             f"{pd.Timestamp(data.loc[i, 'date']):%Y-%m-%d}, p={p[i]:.3f}, "
                             f"y={int(y[i])}", loc="left")
                ax.set_xlabel("SHAP contribution (red raises, blue lowers the score)")
                ax.grid(axis="y", visible=False)
                save(fig, out / "local" / f"local_{kind}", note)
    pd.DataFrame(local_rows).to_csv(out / "shap_local_examples.csv", index=False)
    # ---- comparison across land-cover groups
    by_lc = sv_feat.abs().groupby(data["lc_group"].to_numpy()).mean().T
    by_lc.to_csv(out / "shap_by_landcover.csv")
    # ---- comparison across held-out spatial-CV regions (fold models on their held-out cells)
    tag = f"{int(cfg.splits.spatial_cv.block_size_km)}km"
    fold_dir = paths.stage("train") / "spatial_cv" / tag / model_name
    region_imp = {}
    if fold_dir.exists():
        roles = pd.read_parquet(paths.stage("splits") / f"spatial_roles_{tag}.parquet")
        dev = store.load(cfg.splits.development_years, "train")
        dev = dev[dev["in_eval"]]
        for d in sorted(fold_dir.glob("fold_*")):
            k = int(d.name.split("_")[1])
            cells = roles[(roles["fold"] == k) & (roles["role"] == "test")]["cell_id"]
            sub = dev[dev["cell_id"].isin(cells)]
            if sub.empty:
                continue
            sub = _sample_rows(sub, cfg.explain.max_rows, seed)
            fold_model = load_model(d)
            fsv, _, _ = tree_shap(fold_model, sub)
            fsv = aggregate_columns(fsv, {c: base_feature(c, cats) for c in fsv.columns})
            region_imp[f"heldout_fold_{k}"] = fsv.abs().mean()
    if region_imp:
        reg = pd.DataFrame(region_imp).assign(final_model=glob)
        reg.to_csv(out / "shap_by_heldout_region.csv")
        rho = reg.corr(method="spearman")  # rank stability across regions
        rho.to_csv(out / "shap_rank_stability_spearman.csv")
    log.info("SHAP done for %s on %d rows (%s)", model_name, len(data), scale)
    return {"model": model_name, "rows": len(data), "scale": scale}
