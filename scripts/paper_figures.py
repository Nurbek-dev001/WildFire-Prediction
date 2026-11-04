"""Tables and figures for the Results and Discussion of the article (runs/public_hindcast).

Every number comes from the frozen public-data experiment of the Methods section: six models
(logistic regression, random forest, XGBoost, CatBoost, seasonal frequency, weather-only
logistic), rolling-origin validation 2019-2021, sigmoid calibration on 2022, untouched test
2023-2024, 1000 space-time block bootstrap resamples, the five-fold spatial-block audit and
TreeSHAP. Tables go out as CSV and LaTeX, figures as PNG (300 dpi) and PDF.
Usage: paper_figures.py   -> docs/paper/results/{tables,figures}
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.lines  # noqa: E402
import matplotlib.patches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import average_precision_score, precision_recall_curve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
RUN = ROOT / "runs/public_hindcast"
EVAL = RUN / "evaluate"
OUT = ROOT / "docs/paper/results"
TAB, FIG = OUT / "tables", OUT / "figures"
MODELS = ["xgboost", "catboost", "random_forest", "logistic", "weather_logistic", "seasonal"]
LABEL = {
    "xgboost": "XGBoost",
    "catboost": "CatBoost",
    "random_forest": "Random Forest",
    "logistic": "Logistic regression",
    "weather_logistic": "Weather-only logistic",
    "seasonal": "Seasonal frequency",
}
COLOR = {
    "xgboost": "#c0392b",
    "catboost": "#e67e22",
    "random_forest": "#27ae60",
    "logistic": "#2980b9",
    "weather_logistic": "#8e44ad",
    "seasonal": "#7f8c8d",
}
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "savefig.bbox": "tight",
    }
)


def save_table(frame: pd.DataFrame, name: str, caption: str, digits: int = 4) -> None:
    frame.to_csv(TAB / f"{name}.csv", index=False)
    latex = frame.to_latex(
        index=False, float_format=lambda v: f"{v:.{digits}g}", caption=caption, label=f"tab:{name}"
    )
    (TAB / f"{name}.tex").write_text(latex, encoding="utf-8")


def save_figure(fig: plt.Figure, name: str) -> None:
    fig.savefig(FIG / f"{name}.png", dpi=300)
    fig.savefig(FIG / f"{name}.pdf")
    plt.close(fig)


# ---------- tables ----------
def dataset_table() -> pd.DataFrame:
    rows = []
    for year in range(2015, 2025):
        kind = "train" if year <= 2018 else "evaluation"
        f = pd.read_parquet(RUN / f"features/{year}_{kind}.parquet", columns=["label", "weight"])
        role = "development" if year <= 2021 else "calibration" if year == 2022 else "test"
        rows.append(
            {
                "year": year,
                "role": role,
                "sampled_rows": len(f),
                "event_starts": int(f.label.sum()),
                "eligible_cell_days_weighted": float(f.weight.sum()),
                "prevalence": float((f.label * f.weight).sum() / f.weight.sum()),
            }
        )
    t = pd.DataFrame(rows)
    save_table(
        t,
        "T1_dataset",
        "Sampled cell-days, new-event starts and prevalence by year (weights restore the full risk set).",
    )
    return t


def main_table() -> pd.DataFrame:
    m = pd.read_csv(EVAL / "metrics.csv")
    t = m[m.period == "2023–2024"].set_index("model").loc[MODELS].reset_index()
    t = t[
        [
            "model",
            "average_precision",
            "roc_auc",
            "brier",
            "bss",
            "ece",
            "threshold",
            "precision",
            "recall",
            "f1",
            "fpr",
            "false_discovery_proportion",
            "accuracy",
            "prevalence",
        ]
    ]
    t["ap_lift_over_prevalence"] = t.average_precision / t.prevalence
    t.insert(1, "label", t.model.map(LABEL))
    save_table(
        t,
        "T2_test_metrics",
        "Test-period (2023-2024) performance; thresholds fixed on 2022; BSS relative to the seasonal reference.",
    )
    years = m[m.period.isin(["2023", "2024"])].pivot(
        index="model", columns="period", values=["average_precision", "roc_auc", "bss", "f1"]
    )
    years.columns = [f"{a}_{b}" for a, b in years.columns]
    years = years.loc[MODELS].reset_index()
    save_table(years, "T3_test_by_year", "Test metrics separately for 2023 and 2024.")
    return t


def validation_table() -> pd.DataFrame:
    c = pd.read_csv(RUN / "comparison.csv")
    t = c.pivot(index="model", columns="year", values="weighted_ap")
    t.columns = [f"ap_{y}" for y in t.columns]
    t["mean_ap"] = t.mean(axis=1)
    t = t.loc[MODELS].reset_index()
    save_table(
        t,
        "T4_rolling_validation",
        "Rolling-origin validation AP used for model selection (2019-2021).",
    )
    return t


def interval_table() -> pd.DataFrame:
    c = pd.read_csv(EVAL / "cluster_intervals.csv")
    t = c.pivot(index="model", columns="metric", values=["lower", "upper"])
    t.columns = [f"{m}_{b}" for b, m in t.columns]
    t = t.reset_index()
    save_table(
        t,
        "T5_bootstrap_intervals",
        "Paired 95% space-time block-bootstrap intervals (1000 resamples, 100 km x 30 days).",
        3,
    )
    return t


def spatial_table() -> pd.DataFrame:
    s = pd.read_csv(ROOT / "runs/spatial_audit_v1/metrics.csv")
    s = s[s.model == "xgboost"][
        ["fold", "rows", "prevalence", "average_precision", "roc_auc", "bss", "precision", "recall"]
    ]
    s["ap_lift"] = s.average_precision / s.prevalence
    summary = (
        s.drop(columns=["fold"])
        .agg(["mean", "std"])
        .reset_index()
        .rename(columns={"index": "fold"})
    )
    t = pd.concat([s, summary], ignore_index=True)
    save_table(
        t,
        "T6_spatial_blocks",
        "Five-fold spatial-block transfer (100 km blocks, 25 km buffer), XGBoost, development period.",
    )
    return s


def strata_tables() -> None:
    s = pd.read_csv(EVAL / "stratified_metrics.csv")
    keep = [
        "model",
        "group",
        "positive_rows",
        "prevalence",
        "average_precision",
        "roc_auc",
        "bss",
        "recall",
        "precision",
    ]
    for dim, name, caption in [
        ("landcover", "T7_landcover", "Test metrics by dominant land cover (2023-2024)."),
        ("region", "T8_region", "Test metrics by region (2023-2024)."),
        ("month", "T9_month", "Test metrics by calendar month (2023-2024)."),
    ]:
        t = s[(s.dimension == dim) & s.model.isin(["xgboost", "seasonal", "weather_logistic"])][
            keep
        ]
        t = t.assign(ap_lift=t.average_precision / t.prevalence)
        save_table(t.sort_values(["group", "model"]), name, caption)


def capture_table() -> pd.DataFrame:
    rows = []
    for m in MODELS:
        c = pd.read_csv(EVAL / f"top_capture_{m}.csv")
        for _, r in c.iterrows():
            rows.append(
                {
                    "model": m,
                    "top_fraction": r.nominal_fraction,
                    "captured_event_starts": r.capture_rate,
                    "false_alert_cell_days": r.false_alert_cell_days,
                }
            )
    t = pd.DataFrame(rows)
    wide = (
        t.pivot(index="model", columns="top_fraction", values="captured_event_starts")
        .loc[MODELS]
        .reset_index()
    )
    wide.columns = ["model", "capture_top5", "capture_top10", "capture_top20"]
    save_table(
        wide,
        "T10_top_capture",
        "Share of new-event starts inside the highest-scoring 5/10/20% of eligible cell-days.",
    )
    return t


def map_class_table() -> None:
    t = pd.read_csv(EVAL / "map_class_frequencies.csv")
    t = t[t.model == "xgboost"][
        [
            "class",
            "lower_inclusive",
            "upper_bound",
            "weighted_cell_days",
            "mean_prediction",
            "observed_frequency",
            "area_km2_days",
        ]
    ]
    save_table(
        t,
        "T11_map_classes",
        "XGBoost map classes fixed on 2022: mean predicted probability and observed frequency, 2023-2024.",
    )


def shap_tables() -> None:
    g = pd.read_csv(RUN / "explain/grouped.csv")
    lc = g[g.dimension == "landcover"].pivot(
        index="group", columns="feature_group", values="weighted_mean_abs_group_contribution"
    )
    save_table(
        lc.reset_index(),
        "T12_shap_groups_landcover",
        "Mean |SHAP| by predictor group and land cover (uncalibrated log-odds).",
        3,
    )
    rg = g[g.dimension == "region"].pivot(
        index="group", columns="feature_group", values="weighted_mean_abs_group_contribution"
    )
    save_table(
        rg.reset_index(),
        "T13_shap_groups_region",
        "Mean |SHAP| by predictor group and region (uncalibrated log-odds).",
        3,
    )


def compute_table() -> None:
    cpu = json.loads((RUN / "training_cpu.json").read_text())
    t = pd.DataFrame(
        [
            {
                "item": "Model development (tuning + fitting, six models)",
                "value": cpu["total_cpu_seconds"] / 3600,
                "unit": "CPU-hours",
            },
            {
                "item": "Optuna trials per ensemble",
                "value": json.loads((RUN / "design.json").read_text())[
                    "optuna_attempts_per_ensemble"
                ],
                "unit": "trials",
            },
        ]
    )
    save_table(t, "T14_compute", "Computational cost of the hindcast.")


# ---------- figures ----------
def predictions(model: str) -> pd.DataFrame:
    return pd.read_parquet(
        EVAL / f"predictions_{model}.parquet",
        columns=["label", "weight", "probability", "day", "x", "y_coord"],
    )


def fig_pr() -> None:
    fig, ax = plt.subplots(figsize=(4.6, 3.6))
    prevalence = None
    for m in MODELS:
        p = predictions(m)
        pr, rc, _ = precision_recall_curve(p.label, p.probability, sample_weight=p.weight)
        ap = average_precision_score(p.label, p.probability, sample_weight=p.weight)
        ax.plot(
            rc,
            pr,
            color=COLOR[m],
            lw=1.4 if m == "xgboost" else 1.0,
            label=f"{LABEL[m]} (AP {ap:.4f})",
        )
        prevalence = float((p.label * p.weight).sum() / p.weight.sum())
    ax.axhline(
        prevalence, color="black", ls=":", lw=0.8, label=f"No skill (prevalence {prevalence:.5f})"
    )
    ax.set(
        xlabel="Recall",
        ylabel="Precision",
        yscale="log",
        ylim=(1e-4, 1),
        title="Precision-recall, test 2023-2024",
    )
    ax.legend(fontsize=6.5, loc="upper right")
    save_figure(fig, "F1_precision_recall")


def fig_ap_intervals(t2: pd.DataFrame) -> None:
    c = pd.read_csv(EVAL / "cluster_intervals.csv")
    c = c[(c.metric == "average_precision") & c.model.isin(MODELS)].set_index("model")
    fig, ax = plt.subplots(figsize=(4.6, 2.8))
    order = t2.sort_values("average_precision").model.tolist()
    for i, m in enumerate(order):
        ap = float(t2.set_index("model").loc[m, "average_precision"])
        lo, hi = c.loc[m, "lower"], c.loc[m, "upper"]
        ax.barh(i, ap, color=COLOR[m], alpha=0.85)
        ax.errorbar(ap, i, xerr=[[ap - lo], [hi - ap]], color="black", capsize=3, lw=0.8)
    ax.set_yticks(range(len(order)), [LABEL[m] for m in order])
    ax.axvline(float(t2.prevalence.iloc[0]), color="black", ls=":", lw=0.8)
    ax.set(xlabel="Average precision (95% block-bootstrap CI)", title="Test 2023-2024")
    save_figure(fig, "F2_ap_with_intervals")


def fig_reliability() -> None:
    fig, axes = plt.subplots(2, 3, figsize=(7.2, 4.8), sharex=True, sharey=True)
    for ax, m in zip(axes.ravel(), MODELS, strict=True):
        r = pd.read_csv(EVAL / f"reliability_{m}.csv")
        r = r[r.weight > 0]
        lim = max(r.predicted.max(), r.observed.max()) * 1.15
        ax.plot([1e-6, 1], [1e-6, 1], color="black", lw=0.6, ls=":")
        ax.scatter(
            r.predicted,
            r.observed,
            s=np.clip(np.sqrt(r["count"]) * 1.2, 6, 120),
            color=COLOR[m],
            alpha=0.8,
            edgecolor="white",
            lw=0.4,
        )
        ax.plot(r.predicted, r.observed, color=COLOR[m], lw=0.8)
        ax.set(xscale="log", yscale="log", xlim=(1e-6, 1), ylim=(1e-6, 1), title=LABEL[m])
        _ = lim
    for ax in axes[1]:
        ax.set_xlabel("Mean predicted probability")
    for ax in axes[:, 0]:
        ax.set_ylabel("Observed frequency")
    fig.suptitle("Reliability on test 2023-2024 (marker size: sqrt of rows per bin)", fontsize=9)
    save_figure(fig, "F3_reliability")


def fig_rolling(t4: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    years = [2019, 2020, 2021]
    for _, r in t4.iterrows():
        ax.plot(
            years,
            [r[f"ap_{y}"] for y in years],
            marker="o",
            color=COLOR[r.model],
            label=LABEL[r.model],
        )
    ax.set(
        xticks=years,
        ylabel="Weighted AP",
        yscale="log",
        title="Rolling-origin validation (model selection)",
    )
    ax.legend(fontsize=6.5)
    save_figure(fig, "F4_rolling_validation")


def fig_shap() -> None:
    g = (
        pd.read_csv(RUN / "explain/global.csv")
        .sort_values("weighted_mean_abs_contribution")
        .tail(15)
    )
    fig, ax = plt.subplots(figsize=(4.6, 3.8))
    ax.barh(g.feature, g.weighted_mean_abs_contribution, color=COLOR["xgboost"])
    ax.set(
        xlabel="Mean |SHAP| (uncalibrated log-odds)", title="Global predictor importance, XGBoost"
    )
    save_figure(fig, "F5_shap_global")
    grouped = pd.read_csv(RUN / "explain/grouped.csv")
    lc = grouped[grouped.dimension == "landcover"].pivot(
        index="group", columns="feature_group", values="weighted_mean_abs_group_contribution"
    )
    fig, ax = plt.subplots(figsize=(5.4, 2.6))
    im = ax.imshow(lc.to_numpy(), cmap="OrRd", aspect="auto")
    ax.set_xticks(range(lc.shape[1]), [c.replace("_", "\n") for c in lc.columns], fontsize=7)
    ax.set_yticks(range(lc.shape[0]), lc.index)
    for i in range(lc.shape[0]):
        for j in range(lc.shape[1]):
            v = lc.iat[i, j]
            if np.isfinite(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=6.5)
    ax.grid(False)
    fig.colorbar(im, ax=ax, label="Mean |SHAP|")
    ax.set_title("Predictor-group contributions by land cover")
    save_figure(fig, "F6_shap_groups_landcover")
    for png in (RUN / "explain").glob("dependence_*.png"):
        shutil.copyfile(png, FIG / f"F7_{png.name}")


def fig_strata() -> None:
    s = pd.read_csv(EVAL / "stratified_metrics.csv")
    month = s[s.dimension == "month"].assign(group=lambda d: d.group.astype(int))
    fig, ax = plt.subplots(figsize=(5.2, 3.0))
    for m in ["xgboost", "seasonal", "weather_logistic"]:
        d = month[month.model == m].sort_values("group")
        ax.plot(d.group, d.average_precision, marker="o", color=COLOR[m], label=LABEL[m])
    prev = month[month.model == "xgboost"].sort_values("group")
    ax2 = ax.twinx()
    ax2.bar(prev.group, prev.positive_rows, color="grey", alpha=0.18, label="Event starts")
    ax2.set_ylabel("Event starts (test)")
    ax2.grid(False)
    ax.set(
        xticks=range(1, 13),
        xlabel="Month",
        ylabel="AP",
        yscale="log",
        title="Seasonality of skill, test 2023-2024",
    )
    ax.legend(fontsize=6.5, loc="upper left")
    save_figure(fig, "F8_ap_by_month")
    reg = s[(s.dimension == "region") & s.model.isin(["xgboost", "seasonal"])]
    piv = reg.pivot(index="group", columns="model", values="average_precision").sort_values(
        "xgboost"
    )
    fig, ax = plt.subplots(figsize=(5.2, 4.0))
    yy = np.arange(len(piv))
    ax.barh(yy - 0.2, piv.xgboost, height=0.4, color=COLOR["xgboost"], label="XGBoost")
    ax.barh(yy + 0.2, piv.seasonal, height=0.4, color=COLOR["seasonal"], label="Seasonal frequency")
    ax.set_yticks(yy, [g.replace(" Region", "") for g in piv.index])
    ax.set(xlabel="AP", xscale="log", title="Skill by region, test 2023-2024")
    ax.legend(fontsize=7)
    save_figure(fig, "F9_ap_by_region")
    lcv = s[(s.dimension == "landcover") & s.model.isin(MODELS)]
    piv = lcv.pivot(index="group", columns="model", values="average_precision")[MODELS]
    fig, ax = plt.subplots(figsize=(5.4, 3.0))
    width = 0.13
    for k, m in enumerate(MODELS):
        ax.bar(
            np.arange(len(piv)) + (k - 2.5) * width, piv[m], width, color=COLOR[m], label=LABEL[m]
        )
    ax.set_xticks(range(len(piv)), piv.index)
    ax.set(ylabel="AP", yscale="log", title="Skill by land cover, test 2023-2024")
    ax.legend(fontsize=6, ncol=2)
    save_figure(fig, "F10_ap_by_landcover")


def fig_capture() -> None:
    fig, ax = plt.subplots(figsize=(4.4, 3.4))
    for m in MODELS:
        p = predictions(m).sort_values("probability", ascending=False)
        share = p.weight.cumsum() / p.weight.sum()
        caught = (p.label * p.weight).cumsum() / (p.label * p.weight).sum()
        idx = np.searchsorted(share.to_numpy(), np.linspace(0, 1, 201)[1:])
        idx = np.clip(idx, 0, len(p) - 1)
        ax.plot(
            np.r_[0, share.to_numpy()[idx]],
            np.r_[0, caught.to_numpy()[idx]],
            color=COLOR[m],
            label=LABEL[m],
        )
    ax.plot([0, 1], [0, 1], color="black", ls=":", lw=0.8, label="Random")
    for f in (0.05, 0.1, 0.2):
        ax.axvline(f, color="grey", lw=0.5, ls="--")
    ax.set(
        xlabel="Share of eligible cell-days flagged",
        ylabel="Share of new-event starts captured",
        title="Capture curve, test 2023-2024",
    )
    ax.legend(fontsize=6.5, loc="lower right")
    save_figure(fig, "F11_capture_curve")


def fig_spatial(spatial: pd.DataFrame, t2: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(4.4, 2.8))
    ax.bar(range(len(spatial)), spatial.ap_lift, color=COLOR["xgboost"], alpha=0.85)
    ax.set_xticks(range(len(spatial)), [f"Fold {i + 1}" for i in range(len(spatial))])
    temporal = float(t2.set_index("model").loc["xgboost", "ap_lift_over_prevalence"])
    ax.axhline(
        temporal, color="black", ls="--", lw=0.8, label=f"Temporal test 2023-2024 ({temporal:.0f}x)"
    )
    ax.axhline(1, color="black", ls=":", lw=0.8, label="No skill")
    ax.set(ylabel="AP / prevalence", title="Geographic transfer: held-out 100 km blocks")
    ax.legend(fontsize=7)
    save_figure(fig, "F12_spatial_transfer")


def fig_case_map() -> None:
    """Early June 2023, when the Semei Ormany fire began (East Kazakhstan / Abay): each day's
    full-grid forecast as daily percentile classes, the new event starts of that day, and the
    full-grid percentile of every start in the eastern regions (Table T15)."""
    import rasterio
    from pyproj import Transformer

    events = pd.read_parquet(RUN / "outcomes/events_through_2024.parquet")
    regions = pd.read_parquet(
        EVAL / "predictions_xgboost.parquet", columns=["cell_id", "region"]
    ).drop_duplicates("cell_id")
    region_of = regions.set_index("cell_id").region
    threshold = json.loads((RUN / "frozen.json").read_text())["thresholds"]["xgboost"]
    rows = []
    days = ["2023-06-07", "2023-06-08", "2023-06-09"]
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.4))
    colors = matplotlib.colors.ListedColormap(["#f3efe6", "#f6c977", "#ec7d3a", "#b2182b"])
    for ax, day in zip(axes, days, strict=True):
        with rasterio.open(RUN / f"maps/probability_{day}.tif") as src:
            a = src.read(1, masked=True).astype(float).filled(np.nan)
            ext = (src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top)
            crs, index = src.crs, src.index
        finite = np.isfinite(a)
        ranks = np.full(a.shape, np.nan)
        ranks[finite] = pd.Series(a[finite]).rank(pct=True).to_numpy()
        classes = np.full(a.shape, np.nan)
        classes[finite] = np.digitize(ranks[finite], [0.80, 0.95, 0.99])
        ax.imshow(classes, extent=ext, cmap=colors, vmin=-0.5, vmax=3.5, interpolation="nearest")
        starts = events[(events.timestamp.dt.strftime("%Y-%m-%d") == day) & events.is_first]
        ax.scatter(starts.x, starts.y_coord, s=12, facecolor="none", edgecolor="#08306b", lw=0.9)
        to_lonlat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        for _, e in starts.iterrows():
            r, c = index(e.x, e.y_coord)
            if not (0 <= r < a.shape[0] and 0 <= c < a.shape[1]) or not finite[r, c]:
                continue
            region = str(region_of.get(e.cell_id, ""))
            lon, lat = to_lonlat.transform(e.x, e.y_coord)
            rows.append(
                {
                    "target_day": day,
                    "region": region,
                    "lat": round(lat, 3),
                    "lon": round(lon, 3),
                    "predicted_probability": float(a[r, c]),
                    "daily_percentile": float(ranks[r, c]),
                    "in_top_5pct": bool(ranks[r, c] >= 0.95),
                    "above_2022_threshold": bool(a[r, c] >= threshold),
                }
            )
        ax.set(title=day, xticks=[], yticks=[])
        ax.grid(False)
    handles = [
        matplotlib.patches.Patch(color=colors(i), label=t)
        for i, t in enumerate(["below top 20%", "top 5-20%", "top 1-5%", "top 1%"])
    ]
    handles.append(
        matplotlib.lines.Line2D(
            [], [], marker="o", ls="", mfc="none", mec="#08306b", label="new event start"
        )
    )
    fig.legend(handles=handles, loc="lower center", ncol=5, fontsize=7, frameon=False)
    fig.suptitle(
        "XGBoost next-day forecasts as daily percentile classes, early June 2023", fontsize=9
    )
    save_figure(fig, "F13_case_june_2023")
    t = pd.DataFrame(rows)
    save_table(
        t,
        "T15_case_june_2023_starts",
        "Full-grid daily percentile of the forecast at every new event start, 7-9 June 2023.",
    )
    east = t[t.region.str.contains("East Kazakhstan")]
    save_table(
        east,
        "T15b_case_june_2023_east",
        "Event starts in East Kazakhstan (including the later Abay Region), 7-9 June 2023.",
    )


def fig_ablation() -> None:
    """F14 and table A: test AP when each predictor group is dropped (paper_ablation.py)."""
    i = pd.read_csv(TAB / "ablation_intervals.csv")
    t = pd.read_csv(TAB / "ablation_test.csv").set_index("variant")
    r = pd.read_csv(TAB / "ablation_rolling.csv").pivot(
        index="variant", columns="year", values="ap"
    )
    d = i[(i.model_a == "full") & (i.metric == "average_precision")].set_index("model_b")
    rows = []
    for v in t.index:
        rows.append(
            {
                "variant": v,
                "features": int(t.loc[v, "features"]),
                "test_ap": t.loc[v, "average_precision"],
                "test_roc_auc": t.loc[v, "roc_auc"],
                "test_bss": t.loc[v, "bss"],
                "rolling_mean_ap": r.loc[v].mean(),
                "full_minus_variant_ap": d.loc[v, "difference"] if v in d.index else 0.0,
                "ci_lower": d.loc[v, "lower"] if v in d.index else 0.0,
                "ci_upper": d.loc[v, "upper"] if v in d.index else 0.0,
            }
        )
    a = pd.DataFrame(rows)
    save_table(
        a,
        "T16_ablation",
        "Predictor-group ablation (XGBoost, frozen hyperparameters): test 2023-2024, rolling validation 2019-2021 and paired 95% CI of the AP lost (full minus variant).",
    )
    a = a[a.variant != "full"].sort_values("full_minus_variant_ap")
    names = {
        "without_same_day_weather": "daily weather (D-7)",
        "without_antecedent_weather": "7/14-day weather",
        "without_vegetation": "vegetation (NDVI)",
        "without_land_cover": "land cover",
        "without_terrain": "terrain",
        "without_human": "human pressure",
        "without_season": "season",
        "weather_only": "all non-weather groups (weather-only model)",
    }
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    y = np.arange(len(a))
    colors = ["#c0392b" if lo > 0 else "#95a5a6" for lo in a.ci_lower]
    ax.barh(y, a.full_minus_variant_ap, color=colors)
    ax.errorbar(
        a.full_minus_variant_ap,
        y,
        xerr=[a.full_minus_variant_ap - a.ci_lower, a.ci_upper - a.full_minus_variant_ap],
        fmt="none",
        color="black",
        capsize=2,
        lw=0.8,
    )
    ax.axvline(0, color="black", lw=0.6)
    ax.set_yticks(y, [names[v] for v in a.variant])
    ax.set(
        xlabel="AP lost when the group is removed (95% CI)",
        title="Value of predictor groups, test 2023-2024",
    )
    save_figure(fig, "F14_ablation")


def main() -> None:
    TAB.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    dataset_table()
    t2 = main_table()
    t4 = validation_table()
    interval_table()
    spatial = spatial_table()
    strata_tables()
    capture_table()
    map_class_table()
    shap_tables()
    compute_table()
    fig_pr()
    fig_ap_intervals(t2)
    fig_reliability()
    fig_rolling(t4)
    fig_shap()
    fig_strata()
    fig_capture()
    fig_spatial(spatial, t2)
    fig_case_map()
    if (TAB / "ablation_intervals.csv").exists():
        fig_ablation()
    print("tables:", len(list(TAB.glob("*.csv"))), "figures:", len(list(FIG.glob("*.png"))))


if __name__ == "__main__":
    main()
