"""Stage 14 — report: tables, figures and the reproducibility record.

Every number in REPORT.md is read from artifacts produced by the pipeline run; nothing is
typed in by hand. When the inputs are synthetic the report says so on every page.
"""

from __future__ import annotations

import importlib.metadata as md
import os
import platform
import shutil
import subprocess
from typing import Any

import numpy as np
import pandas as pd
import psutil

from wildfire_kz import __version__
from wildfire_kz.config.loader import config_section_hash
from wildfire_kz.config.schema import Config
from wildfire_kz.paths import RunPaths
from wildfire_kz.report import figures as figs
from wildfire_kz.report.style import CAUSAL_NOTE, SYNTHETIC_BANNER
from wildfire_kz.utils.runtime import get_logger, read_json, sha256_file, utc_now, write_json

log = get_logger("report")

PACKAGES = [
    "numpy",
    "pandas",
    "scipy",
    "xarray",
    "dask",
    "netCDF4",
    "geopandas",
    "shapely",
    "pyproj",
    "rasterio",
    "pyarrow",
    "scikit-learn",
    "xgboost",
    "catboost",
    "optuna",
    "shap",
    "matplotlib",
    "pydantic",
    "typer",
    "wildfire-kz",
]


def _fmt(v: Any) -> str:
    if isinstance(v, float | np.floating):
        if not np.isfinite(v):
            return "n/a"
        return f"{v:.4g}"
    return str(v)


def md_table(df: pd.DataFrame, cols: list[str] | None = None, max_rows: int = 60) -> str:
    df = df[cols] if cols else df
    df = df.head(max_rows)
    head = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "|" + "|".join(["---"] * len(df.columns)) + "|"
    body = ["| " + " | ".join(_fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *body])


def reproducibility_record(cfg: Config, paths: RunPaths) -> dict[str, Any]:
    versions = {}
    for p in PACKAGES:
        try:
            versions[p] = md.version(p)
        except md.PackageNotFoundError:
            versions[p] = "not installed"
    try:
        commit = (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            ).stdout.strip()
            or "unknown"
        )
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    manifest = read_json(paths.manifest)
    sources = {
        k: {
            "source_id": v["meta"]["source_id"],
            "version": v["meta"].get("version"),
            "provider": v["meta"].get("provider"),
            "n_files": v["n_files"],
            "retrieved_on": v["retrieved_on"],
        }
        for k, v in manifest["sources"].items()
    }
    train_sel = read_json(paths.stage("train") / "selection.json")
    seeds = {
        "global": cfg.project.seed,
        "models": {m: v.get("seed") for m, v in train_sel["models"].items()},
    }
    st = paths.stage
    return {
        "generated_utc": utc_now(),
        "package_version": __version__,
        "git_commit": commit,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "hardware": {
            "cpu_count": os.cpu_count(),
            "processor": platform.processor(),
            "total_ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        },
        "packages": versions,
        "seeds": seeds,
        "config_sha256": config_section_hash(cfg),
        "synthetic_data": manifest["synthetic"],
        "data_manifest": {
            "path": str(paths.manifest),
            "sha256": sha256_file(paths.manifest),
            "sources": sources,
        },
        "exclusions": {
            "detection_qc": read_json(st("events") / "qc_counts.json"),
            "risk_set": read_json(st("risk_set") / "risk_set_summary.json"),
            "feature_flags": read_json(st("features") / "feature_registry.json")[
                "omitted_or_flagged"
            ],
        },
        "split_manifests": {
            "temporal": read_json(st("splits") / "temporal_splits.json"),
            "spatial": read_json(st("splits") / "spatial_splits.json"),
        },
        "test_access_ledger": read_json(st("evaluate") / "final_evaluation_ledger.json"),
        "crs": cfg.crs.model_dump(),
    }


def run_report(cfg: Config, paths: RunPaths) -> dict[str, Any]:
    out = paths.stage("report")
    fig_dir, tab_dir = out / "figures", out / "tables"
    fig_dir.mkdir(parents=True, exist_ok=True)
    tab_dir.mkdir(parents=True, exist_ok=True)
    st = paths.stage
    synthetic = read_json(paths.manifest)["synthetic"]
    note = SYNTHETIC_BANNER if synthetic else ""
    ev = st("evaluate")
    overall = pd.read_csv(ev / "metrics_overall.csv")
    main = overall[overall["kind"] == "main"]["model"].tolist()
    rel = pd.read_csv(ev / "reliability.csv")
    cap = pd.read_csv(ev / "capture_rates.csv")
    pairs = pd.read_csv(ev / "bootstrap_pairs.csv")
    model_ci = pd.read_csv(ev / "bootstrap_model_ci.csv")
    strat = pd.read_csv(ev / "metrics_stratified.csv")
    pred = pd.read_parquet(ev / "test_predictions.parquet")
    flags = read_json(ev / "result_flags.json")["flags"]
    sel = read_json(st("train") / "selection.json")
    spatial = (
        pd.read_csv(st("train") / "spatial_cv_results.csv")
        if (st("train") / "spatial_cv_results.csv").exists()
        else pd.DataFrame()
    )
    abl = pd.read_csv(st("ablate") / "ablation_validation.csv")
    cal = read_json(st("calibrate") / "calibration_artifacts.json")
    # ---- copy tables
    for f in [
        "metrics_overall.csv",
        "metrics_stratified.csv",
        "capture_rates.csv",
        "reliability.csv",
        "bootstrap_pairs.csv",
        "bootstrap_model_ci.csv",
        "resources.csv",
        "map_class_frequencies_test.csv",
    ]:
        shutil.copy(ev / f, tab_dir / f)
    for src in [
        st("ablate") / "ablation_validation.csv",
        st("train") / "spatial_cv_results.csv",
        st("events") / "event_linkage_sensitivity.csv",
        st("calibrate") / "map_class_frequencies_calibration.csv",
        st("sampling") / "strata_inclusion_probabilities.csv",
        st("explain") / "shap_global_importance.csv",
        st("explain") / "shap_feature_group_importance.csv",
        st("explain") / "shap_correlated_group_importance.csv",
        st("explain") / "shap_by_landcover.csv",
    ]:
        if src.exists():
            shutil.copy(src, tab_dir / src.name)
    # ---- figures
    figs.reliability_figure(rel, main, "uniform", fig_dir / "reliability_uniform", note)
    figs.reliability_figure(rel, main, "quantile", fig_dir / "reliability_quantile", note)
    figs.pr_curves(pred, main, fig_dir / "precision_recall_test", note)
    for mode in cfg.evaluation.capture_modes:
        figs.capture_figure(cap, main, mode, fig_dir / f"capture_{mode}", note)
    figs.forest_plot(pairs, "average_precision", fig_dir / "bootstrap_ap_differences", note)
    figs.forest_plot(pairs, "bss", fig_dir / "bootstrap_bss_differences", note)
    if len(spatial):
        figs.spatial_cv_figure(spatial, fig_dir / "spatial_cv_ap", note)
    if len(abl):
        figs.ablation_figure(abl, fig_dir / "ablation_dev_delta_ap", note)
    for png in st("explain").glob("shap_*.png"):
        shutil.copy(png, fig_dir / png.name)
    # ---- reproducibility record
    repro = reproducibility_record(cfg, paths)
    write_json(out / "reproducibility_record.json", repro)
    # ---- markdown report
    lines = [
        f"# {cfg.project.name} — run `{cfg.project.run_label}` "
        f"(grid: {cfg.grid.active}, {cfg.grid.active_spec.cell_size_m / 1000:g} km)",
        "",
    ]
    if synthetic:
        lines += [
            f"> **{SYNTHETIC_BANNER}.** Every number below was produced by running the "
            "pipeline on generated data; none of it is evidence about wildfire "
            "occurrence in Kazakhstan.",
            "",
        ]
    lines += [
        "**Target.** Calibrated probability that a new vegetation-fire event is *first "
        "detected* by Suomi-NPP VIIRS in a grid cell on UTC day t, using predictors observed "
        "up to t−1. This is occurrence hazard — not damage, exposure, vulnerability or risk. "
        "Absence of a detection is an observed negative, not verified absence of fire.",
        "",
        "## Data and labels",
        "",
        md_table(
            pd.DataFrame(
                list(repro["exclusions"]["detection_qc"].items()),
                columns=["quality-control step", "count"],
            )
        ),
        "",
        "Flagged/omitted predictors: "
        + ("; ".join(repro["exclusions"]["feature_flags"]) or "none"),
        "",
        "## Model selection (development years only)",
        "",
        f"Selected tree ensemble: **{sel['selected_tree_model']}**; best classifier for maps: "
        f"**{sel['best_classifier']}** ({sel['criterion']}).",
        "",
        md_table(
            pd.DataFrame(
                [
                    {
                        "model": m,
                        "dev_cv_weighted_ap": v["cv_weighted_ap_mean"],
                        "scheme": v["scheme"],
                        "train_seconds": v["train_seconds"],
                    }
                    for m, v in sel["models"].items()
                    if "cv_weighted_ap_mean" in v
                ]
            )
        ),
        "",
    ]
    if len(spatial):
        sp = (
            spatial.groupby(["block_km", "model"])
            .agg(
                ap_mean=("average_precision", "mean"),
                ap_min=("average_precision", "min"),
                ap_max=("average_precision", "max"),
                prevalence=("prevalence", "mean"),
            )
            .reset_index()
        )
        lines += [
            "## Spatial transfer (spatial-block CV within development years)",
            "",
            md_table(sp),
            "",
            "![](figures/spatial_cv_ap.png)",
            "",
        ]
    cols = [
        "model",
        "prevalence",
        "average_precision",
        "pr_auc_trapezoid",
        "roc_auc",
        "brier",
        "bss",
        "bss_vs_climatology",
        "ece_10bin",
        "tau",
        "precision",
        "recall",
        "f1",
        "fpr",
        "fdp",
        "accuracy",
    ]
    lines += [
        "## Calibration (calibration year only)",
        "",
        f"Platt scaling on inverse-inclusion-weighted data; threshold maximises weighted F1. "
        f"Map classes ({', '.join(cal['map_class_labels'])}) use boundaries "
        f"{[round(b, 6) for b in cal['map_class_boundaries']]} fixed before testing.",
        "",
        f"## Test-year evaluation ({', '.join(map(str, cfg.splits.test_years))})",
        "",
        "AP is the step-wise sum (R_k − R_{k−1})·P_k; the trapezoidal PR-AUC is shown only "
        "for contrast. Accuracy is reported but never used for selection. BSS is relative to "
        "the land-cover × month seasonal reference fitted on development years.",
        "",
        md_table(overall[overall["kind"] == "main"], cols),
        "",
        "![](figures/precision_recall_test.png)",
        "",
        "![](figures/reliability_uniform.png)",
        "",
        "![](figures/reliability_quantile.png)",
        "",
        "### Capture of new-event starts",
        "",
        md_table(
            cap[cap["model"].isin(main)],
            [
                "model",
                "mode",
                "fraction",
                "capture_rate",
                "mean_daily_flagged_area_km2",
                "false_alert_share",
            ],
        ),
        "",
        "![](figures/capture_pooled.png)",
        "",
        "### Paired comparisons (space–time block bootstrap, "
        f"{cfg.evaluation.bootstrap.n_resamples} resamples)",
        "",
        md_table(
            pairs[
                pairs["metric"].isin(["average_precision", "bss"])
                & pairs["model_a"].isin(main)
                & pairs["model_b"].isin(main)
            ],
            ["model_a", "model_b", "metric", "diff_mean", "ci_lo", "ci_hi", "ci_excludes_zero"],
        ),
        "",
        "![](figures/bootstrap_ap_differences.png)",
        "",
        "### Stratified results (cropland reported separately)",
        "",
        md_table(
            strat[strat["stratum_type"].isin(["cropland", "lc_group"])],
            [
                "stratum_type",
                "stratum",
                "model",
                "positives",
                "prevalence",
                "average_precision",
                "bss",
                "unstable_few_positives",
            ],
        ),
        "",
        "## Ablations",
        "",
        md_table(
            abl,
            [
                "model",
                "ablated_group",
                "n_features",
                "dev_cv_weighted_ap",
                "full_model_dev_cv_weighted_ap",
                "delta_ap_vs_full",
            ],
        ),
        "",
        "![](figures/ablation_dev_delta_ap.png)",
        "",
        "Test-year metrics of ablated models are in `tables/metrics_overall.csv` "
        "(kind = ablation) and their paired differences in `tables/bootstrap_pairs.csv`.",
        "",
        "## Explanations",
        "",
        f"> {CAUSAL_NOTE}.",
        "",
        "![](figures/shap_global_importance.png)",
        "",
        "![](figures/shap_feature_group_importance.png)",
        "",
        "## Negative, null or unstable results (generated)",
        "",
        *([f"- {f}" for f in flags] or ["- none flagged"]),
        "",
        "## Reproducibility",
        "",
        f"Seed {cfg.project.seed}; git commit `{repro['git_commit']}`; Python "
        f"{repro['python']}; {repro['hardware']['cpu_count']} CPUs, "
        f"{repro['hardware']['total_ram_gb']} GB RAM. Full record: "
        "`reproducibility_record.json` (package versions, source IDs, checksums manifest, "
        "exclusions, split manifests, test-access ledger).",
        "",
        "Per-model bootstrap intervals: `tables/bootstrap_model_ci.csv`; resources: "
        "`tables/resources.csv`.",
    ]
    _ = model_ci
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    log.info("report written to %s", out / "REPORT.md")
    return {"report": str(out / "REPORT.md"), "n_flags": len(flags)}
