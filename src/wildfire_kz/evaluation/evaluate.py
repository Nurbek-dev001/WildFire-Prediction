"""Stage 11 — final evaluation on the untouched test years.

This is the first stage allowed to open the test years; it does so only after calibration,
thresholds and map class boundaries were frozen. Nothing computed here feeds back into model
selection, calibration or thresholds. Unfavourable and statistically unclear results are
flagged explicitly in ``result_flags.json``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from wildfire_kz.calibration.calibrate import Platt, class_frequencies, model_dirs
from wildfire_kz.config.schema import Config
from wildfire_kz.evaluation.bootstrap import paired_block_bootstrap, space_time_blocks
from wildfire_kz.evaluation.metrics import capture_rate, reliability_table, summary_metrics
from wildfire_kz.grid.grid import load_grid
from wildfire_kz.models.pipelines import FittedModel
from wildfire_kz.models.train import load_model
from wildfire_kz.paths import RunPaths
from wildfire_kz.splits.guard import FeatureStore, unlock_final_evaluation
from wildfire_kz.utils.resources import track_resources
from wildfire_kz.utils.runtime import derive_seed, get_logger, read_json, write_json

log = get_logger("evaluate")


def collect_models(
    paths: RunPaths,
) -> tuple[dict[str, FittedModel], dict[str, Platt], dict[str, float], dict[str, str]]:
    """All trained, calibrated models: main, class-weight variants, baselines, ablations."""
    calib = read_json(paths.stage("calibrate") / "calibration_artifacts.json")["models"]
    abl_cal_path = paths.stage("ablate") / "ablation_calibration.json"
    abl_cal = read_json(abl_cal_path) if abl_cal_path.exists() else {}
    models, platts, taus, kinds = {}, {}, {}, {}
    for name, d in model_dirs(paths.stage("train")).items():
        models[name] = load_model(d)
        c = calib[name]
        platts[name] = Platt(c["platt_a"], c["platt_b"])
        taus[name] = c["tau"]
        kinds[name] = "class_weight_sensitivity" if "__classweight" in name else "main"
    abl_dir = paths.stage("ablate") / "models"
    if abl_dir.exists():
        for name, d in model_dirs(abl_dir).items():
            models[name] = load_model(d)
            platts[name] = Platt(abl_cal[name]["platt_a"], abl_cal[name]["platt_b"])
            taus[name] = abl_cal[name]["tau"]
            kinds[name] = "ablation"
    return models, platts, taus, kinds


def comparison_pairs(cfg: Config, names: list[str], kinds: dict[str, str]) -> list[tuple[str, str]]:
    main = [n for n in names if kinds[n] == "main"]
    pairs = [(a, b) for i, a in enumerate(main) for b in main[i + 1 :]]
    for n in names:
        if kinds[n] == "class_weight_sensitivity":
            pairs.append((n.split("__")[0], n))
        elif kinds[n] == "ablation":
            pairs.append((n.split("__minus_")[0], n))
    return pairs


def stratified_metrics(
    cfg: Config, pred: pd.DataFrame, models: list[str], taus: dict[str, float]
) -> pd.DataFrame:
    rows = []
    min_pos = cfg.evaluation.min_positives_for_stratum
    strata = dict.fromkeys(cfg.evaluation.strata)
    pred = pred.assign(
        cropland=np.where(pred["lc_group"] == "cropland", "cropland", "non-cropland")
    )
    for col in [*strata, "cropland"]:
        for val, g in pred.groupby(col):
            y, w = g["label"].to_numpy(), g["w_eval"].to_numpy()
            for m in models:
                met = summary_metrics(
                    y,
                    g[f"p_{m}"].to_numpy(),
                    w,
                    taus[m],
                    g["p_reference"].to_numpy(),
                    cfg.evaluation.reliability_bins,
                )
                rows.append(
                    {
                        "stratum_type": col,
                        "stratum": str(val),
                        "model": m,
                        **met,
                        "unstable_few_positives": bool(y.sum() < min_pos),
                    }
                )
    return pd.DataFrame(rows)


def result_flags(
    cfg: Config,
    overall: pd.DataFrame,
    pairs: pd.DataFrame,
    strat: pd.DataFrame,
    spatial: pd.DataFrame | None,
) -> list[str]:
    """Explicit statements of negative, null or unstable results (generated, not curated)."""
    flags = []
    for rec in overall.to_dict(orient="records"):
        if float(rec["bss"]) <= 0:
            flags.append(
                f"{rec['model']}: Brier skill vs seasonal reference is not positive "
                f"(BSS={float(rec['bss']):.4f})"
            )
        if float(rec["average_precision"]) <= float(rec["prevalence"]):
            flags.append(f"{rec['model']}: AP does not exceed the no-skill prevalence")
    ap = {
        str(k): float(v)
        for k, v in zip(overall["model"], overall["average_precision"], strict=True)
    }
    for b in ("seasonal_landcover", "weather_logistic"):
        if b not in ap:
            continue
        for clf in cfg.models.classifiers:
            if clf in ap and ap[clf] <= ap[b]:
                flags.append(f"{clf}: test AP not above baseline {b}")
    for _, r in pairs.iterrows():
        if r["metric"] == "average_precision" and not r["ci_excludes_zero"]:
            flags.append(
                f"AP difference {r['model_a']} - {r['model_b']}: 95% block-bootstrap "
                f"CI [{r['ci_lo']:.4f}, {r['ci_hi']:.4f}] includes 0 (no clear "
                "difference)"
            )
    unstable = strat[strat["unstable_few_positives"]]
    if len(unstable):
        flags.append(
            f"{unstable[['stratum_type', 'stratum']].drop_duplicates().shape[0]} "
            f"strata have < {cfg.evaluation.min_positives_for_stratum} positives; "
            "their metrics are unstable"
        )
    if spatial is not None and len(spatial):
        agg = (
            spatial.groupby(["block_km", "model"])["average_precision"]
            .agg(["mean", "std"])
            .reset_index()
        )
        for rec in agg.to_dict(orient="records"):
            mean, sd = float(rec["mean"]), float(rec["std"])
            cv = sd / mean if mean > 0 else np.nan
            if np.isfinite(cv) and cv > 0.5:
                flags.append(
                    f"spatial CV ({float(rec['block_km']):.0f} km) {rec['model']}: AP "
                    "varies strongly across held-out regions (coefficient of "
                    f"variation {cv:.2f})"
                )
    return flags


def run_evaluate(cfg: Config, paths: RunPaths) -> dict[str, Any]:
    out = paths.stage("evaluate")
    out.mkdir(parents=True, exist_ok=True)
    unlock_final_evaluation(cfg, paths, "evaluate")
    store = FeatureStore(cfg, paths)
    test = store.load_partition("test", "test")
    test = test[test["in_eval"]].reset_index(drop=True)
    grid = load_grid(paths.grid_file)
    regions = pd.read_parquet(paths.stage("splits") / "cell_regions.parquet")
    g = pd.DataFrame(grid[["cell_id", "x", "y", "area_km2"]]).merge(regions, on="cell_id")
    test = test.merge(g, on="cell_id", how="left")
    models, platts, taus, kinds = collect_models(paths)
    names = sorted(models)
    pred = test[
        [
            "cell_id",
            "date",
            "year",
            "month",
            "lc_group",
            "region",
            "label",
            "w_eval",
            "x",
            "y",
            "area_km2",
        ]
    ].copy()
    resources = []
    for m in names:
        with track_resources() as usage:
            raw = models[m].decision_logit(test)
        pred[f"p_{m}"] = platts[m].apply(raw)
        pred[f"raw_{m}"] = raw
        resources.append(
            {
                "model": m,
                "inference_seconds": usage.wall_seconds,
                "inference_peak_rss_mb": usage.peak_rss_mb,
                "rows": len(test),
            }
        )
    # seasonal reference: land-cover x month climatology fitted on development years only
    ref = models["seasonal_landcover"].predict_proba(test)
    pred["p_reference"] = ref
    y, w = pred["label"].to_numpy(), pred["w_eval"].to_numpy()
    dev = store.load_partition("development", "train", columns=["label", "w_eval", "in_eval"])
    dev = dev[dev["in_eval"]]
    clim = float((dev["label"] * dev["w_eval"]).sum() / dev["w_eval"].sum())
    rows = []
    for m in names:
        met = summary_metrics(
            y, pred[f"p_{m}"].to_numpy(), w, taus[m], ref, cfg.evaluation.reliability_bins
        )
        met["bss_vs_climatology"] = 1 - met["brier"] / float(
            np.sum(w * (clim - y) ** 2) / np.sum(w)
        )
        rows.append({"model": m, "kind": kinds[m], **met})
    overall = pd.DataFrame(rows)
    overall.to_csv(out / "metrics_overall.csv", index=False)
    # reliability diagrams data (uniform = ECE definition, quantile = rare-event detail)
    rel = []
    for m in names:
        for binning in ("uniform", "quantile"):
            t = reliability_table(
                y,
                pred[f"p_{m}"].to_numpy(),
                w,
                cfg.evaluation.reliability_bins,
                binning,
                cfg.evaluation.wilson_z,
            )
            rel.append(t.assign(model=m, binning=binning))
    pd.concat(rel).to_csv(out / "reliability.csv", index=False)
    # capture rates
    cap = []
    for m in names:
        for mode in cfg.evaluation.capture_modes:
            for frac in cfg.evaluation.capture_fractions:
                c = capture_rate(
                    y,
                    pred[f"p_{m}"].to_numpy(),
                    frac,
                    w,
                    pred["area_km2"].to_numpy(),
                    pred["date"].to_numpy() if mode == "daily" else None,
                )
                cap.append({"model": m, "mode": mode, **c})
    pd.DataFrame(cap).to_csv(out / "capture_rates.csv", index=False)
    # stratified metrics (main models + baselines)
    main = [m for m in names if kinds[m] == "main"]
    strat = stratified_metrics(cfg, pred, main, taus)
    strat.to_csv(out / "metrics_stratified.csv", index=False)
    # paired space-time block bootstrap on identical resampled units
    bcfg = cfg.evaluation.bootstrap
    blocks = space_time_blocks(
        pred["x"].to_numpy(),
        pred["y"].to_numpy(),
        pred["date"],
        bcfg.spatial_block_km,
        bcfg.temporal_block_days,
    )
    pairs = comparison_pairs(cfg, names, kinds)
    model_ci, pair_ci = paired_block_bootstrap(
        y,
        w,
        blocks,
        {m: pred[f"p_{m}"].to_numpy() for m in names},
        ref,
        pairs,
        bcfg.n_resamples,
        derive_seed(cfg.project.seed, "bootstrap"),
        bcfg.ci_level,
        n_jobs=cfg.models.n_jobs,
    )
    model_ci.to_csv(out / "bootstrap_model_ci.csv", index=False)
    pair_ci.to_csv(out / "bootstrap_pairs.csv", index=False)
    # map classes: observed frequencies on the test years with frozen boundaries
    cal = read_json(paths.stage("calibrate") / "calibration_artifacts.json")
    mm = cal["map_model"]
    class_frequencies(
        pred[f"p_{mm}"].to_numpy(), y, w, cal["map_class_boundaries"], cal["map_class_labels"]
    ).to_csv(out / "map_class_frequencies_test.csv", index=False)
    # resources: training (from train stage) + inference
    sel = read_json(paths.stage("train") / "selection.json")["models"]
    res = pd.DataFrame(resources)
    res["train_seconds"] = res["model"].map(lambda m: sel.get(m, {}).get("train_seconds"))
    res["train_peak_rss_mb"] = res["model"].map(lambda m: sel.get(m, {}).get("peak_rss_mb"))
    res.to_csv(out / "resources.csv", index=False)
    spatial_path = paths.stage("train") / "spatial_cv_results.csv"
    spatial = pd.read_csv(spatial_path) if spatial_path.exists() else None
    flags = result_flags(cfg, overall[overall["kind"] != "ablation"], pair_ci, strat, spatial)
    write_json(out / "result_flags.json", {"flags": flags})
    pred.drop(columns=["x", "y"]).to_parquet(out / "test_predictions.parquet", index=False)
    log.info("evaluation done: %d models, %d flags", len(names), len(flags))
    return {"n_models": len(names), "n_flags": len(flags)}
