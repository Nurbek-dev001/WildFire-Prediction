"""Publication figures for the manuscript (docs/paper/manuscript/figures).

Same experiment and numbers as paper_figures.py (runs/public_hindcast), redrawn for the article:
no titles inside the plots (captions carry them), panel letters, one font size, region outlines
on the case map and log-spaced reliability bins, so that the many low-probability cell-days and
the few high-probability ones are both visible.
Usage: article_figures.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors  # noqa: E402
import matplotlib.lines  # noqa: E402
import matplotlib.patches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import shapely.wkb  # noqa: E402
from pyproj import Transformer  # noqa: E402
from sklearn.metrics import average_precision_score, precision_recall_curve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/public_hindcast"
EVAL = RUN / "evaluate"
TAB = ROOT / "docs/paper/results/tables"
OUT = ROOT / "docs/paper/manuscript/figures"
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
GROUP_OF = {
    **dict.fromkeys(["tmax", "tmin", "wind", "rh", "precip", "soil_moisture"], "Daily weather"),
    **dict.fromkeys(
        ["precip_7d", "precip_14d", "temperature_7d", "temperature_14d"], "7/14-day weather"
    ),
    **dict.fromkeys(["ndvi", "ndvi_missing", "ndvi_age_days"], "Vegetation"),
    **dict.fromkeys(["forest", "grassland", "shrubland", "cropland", "other"], "Land cover"),
    **dict.fromkeys(["elevation", "slope", "aspect_sin", "aspect_cos"], "Terrain"),
    **dict.fromkeys(["population_density", "settlement_distance"], "Human pressure"),
    **dict.fromkeys(["month_sin", "month_cos"], "Season"),
}
GROUP_COLOR = {
    "Daily weather": "#6baed6",
    "7/14-day weather": "#2171b5",
    "Vegetation": "#74c476",
    "Land cover": "#e6ab02",
    "Terrain": "#8c6d31",
    "Human pressure": "#c0392b",
    "Season": "#756bb1",
}
NICE = {
    "population_density": "Population density",
    "month_cos": "Month (cosine)",
    "month_sin": "Month (sine)",
    "temperature_14d": "Mean temperature, 14 days",
    "temperature_7d": "Mean temperature, 7 days",
    "cropland": "Cropland fraction",
    "elevation": "Elevation",
    "other": "Other land fraction",
    "ndvi": "NDVI",
    "slope": "Slope",
    "soil_moisture": "Soil moisture",
    "tmax": "Maximum temperature",
    "aspect_cos": "Aspect (cosine)",
    "settlement_distance": "Distance to settlement",
    "precip_14d": "Precipitation, 14 days",
}
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 8,
        "axes.titlesize": 8,
        "axes.labelsize": 8,
        "legend.fontsize": 7,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,
    }
)


def panel(ax: plt.Axes, letter: str) -> None:
    ax.text(-0.02, 1.02, f"({letter})", transform=ax.transAxes, ha="right", va="bottom",
            fontweight="bold")


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(OUT / f"{name}.pdf")
    fig.savefig(OUT / f"{name}.png", dpi=300)
    plt.close(fig)


def predictions(model: str) -> pd.DataFrame:
    return pd.read_parquet(EVAL / f"predictions_{model}.parquet",
                           columns=["label", "weight", "probability", "day", "cell_id",
                                    "area_km2"])


def daily_capture(p: pd.DataFrame, grid: np.ndarray) -> np.ndarray:
    """Share of new starts inside each day's highest-scoring area fraction, as in the
    evaluation module's top_capture: cells are ranked within their day and flagged while the
    area ranked above them is below the budget."""
    d = p.sort_values(["day", "probability", "cell_id"], ascending=[True, False, True])
    area = d.area_km2 * d.weight
    before = ((area.groupby(d.day).cumsum() - area) / area.groupby(d.day).transform("sum"))
    order = np.argsort(before.to_numpy(), kind="stable")
    hits = (d.label * d.weight).to_numpy()[order]
    caught = np.cumsum(hits) / hits.sum()
    idx = np.searchsorted(before.to_numpy()[order], grid, side="left")
    return np.r_[0.0, caught][idx]


def fig_performance() -> None:
    """(a) precision-recall curves, (b) share of new starts caught in the top-ranked cell-days."""
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 3.0))
    prevalence = 0.0
    for m in MODELS:
        p = predictions(m)
        pr, rc, _ = precision_recall_curve(p.label, p.probability, sample_weight=p.weight)
        ap = average_precision_score(p.label, p.probability, sample_weight=p.weight)
        lw = 1.6 if m == "xgboost" else 1.0
        a.plot(rc, pr, color=COLOR[m], lw=lw, label=f"{LABEL[m]} ({ap:.4f})")
        prevalence = float((p.label * p.weight).sum() / p.weight.sum())
        grid = np.linspace(0, 0.3, 301)
        b.plot(grid * 100, daily_capture(p, grid) * 100, color=COLOR[m], lw=lw)
    a.axhline(prevalence, color="black", ls=":", lw=0.8, label="No skill (prevalence)")
    a.set(xlabel="Recall", ylabel="Precision (log scale)", yscale="log", ylim=(1e-4, 1),
          xlim=(0, 1))
    a.legend(title="Model (AP)", title_fontsize=7, loc="upper right", frameon=False)
    b.plot([0, 30], [0, 30], color="black", ls=":", lw=0.8)
    b.axvline(5, color="grey", ls="--", lw=0.6)
    b.set(xlabel="Daily area flagged, highest scores first (%)",
          ylabel="New fire starts captured (%)", xlim=(0, 30), ylim=(0, 100))
    panel(a, "a")
    panel(b, "b")
    fig.tight_layout(w_pad=2.5)
    save(fig, "fig_performance")


def fig_ablation() -> None:
    t = pd.read_csv(TAB / "T16_ablation.csv")
    t = t[t.variant != "full"].sort_values("full_minus_variant_ap")
    names = {
        "without_same_day_weather": "Daily weather (day $t-7$)",
        "without_antecedent_weather": "7/14-day weather",
        "without_vegetation": "Vegetation (NDVI)",
        "without_land_cover": "Land cover",
        "without_terrain": "Terrain",
        "without_human": "Human pressure",
        "without_season": "Season",
        "weather_only": "All except weather\n(weather-only model)",
    }
    fig, ax = plt.subplots(figsize=(5.0, 3.0))
    y = np.arange(len(t))
    ax.barh(y, t.full_minus_variant_ap,
            color=["#c0392b" if lo > 0 else "#bdc3c7" for lo in t.ci_lower], height=0.6)
    ax.errorbar(t.full_minus_variant_ap, y,
                xerr=[t.full_minus_variant_ap - t.ci_lower, t.ci_upper - t.full_minus_variant_ap],
                fmt="none", color="black", capsize=2, lw=0.8)
    ax.axvline(0, color="black", lw=0.6)
    ax.set_yticks(y, [names[v] for v in t.variant])
    ax.set_xlabel("Average precision lost when the group is removed (95% CI)")
    ax.grid(axis="y", visible=False)
    save(fig, "fig_ablation")


def fig_transfer() -> None:
    """(a) AP/prevalence on future years and held-out regions, (b) AP by administrative region."""
    t3 = pd.read_csv(TAB / "T3_test_by_year.csv").set_index("model").loc["xgboost"]
    t1 = pd.read_csv(TAB / "T1_dataset.csv").set_index("year").prevalence
    s = pd.read_csv(TAB / "T6_spatial_blocks.csv")
    s = s[s.fold.str.startswith("spatial")]
    labels = ["Test\n2023", "Test\n2024"] + [f"Fold\n{i + 1}" for i in range(len(s))]
    lift = [t3.average_precision_2023 / t1[2023], t3.average_precision_2024 / t1[2024],
            *s.ap_lift]
    colors = ["#c0392b"] * 2 + ["#e6ab02"] * len(s)
    st = pd.read_csv(EVAL / "stratified_metrics.csv")
    reg = st[(st.dimension == "region") & st.model.isin(["xgboost", "seasonal"])]
    piv = reg.pivot(index="group", columns="model", values="average_precision")
    piv = piv.dropna().sort_values("xgboost")
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 3.3), gridspec_kw={"width_ratios": [1, 1.15]})
    a.bar(range(len(lift)), lift, color=colors)
    a.axhline(1, color="black", ls=":", lw=0.8)
    a.set_xticks(range(len(lift)), labels)
    a.set(yscale="log", ylabel="AP / prevalence (log scale)", ylim=(1, 400))
    a.legend(handles=[matplotlib.patches.Patch(color="#c0392b", label="Future years"),
                      matplotlib.patches.Patch(color="#e6ab02", label="Held-out 100 km blocks")],
             loc="upper right", frameon=False)
    a.grid(axis="x", visible=False)
    yy = np.arange(len(piv))
    b.barh(yy + 0.2, piv.xgboost, height=0.4, color=COLOR["xgboost"], label="XGBoost")
    b.barh(yy - 0.2, piv.seasonal, height=0.4, color=COLOR["seasonal"],
           label="Seasonal frequency")
    b.set_yticks(yy, [g.replace(" Region", "") if "Region" in g else f"{g} (city)"
                      for g in piv.index])
    b.set(xscale="log", xlabel="Average precision, 2023-2024 (log scale)")
    b.legend(loc="lower right", frameon=False)
    b.grid(axis="y", visible=False)
    panel(a, "a")
    panel(b, "b")
    fig.tight_layout(w_pad=2.0)
    save(fig, "fig_transfer")


def fig_reliability() -> None:
    """(a) log-binned reliability for XGBoost and CatBoost, (b) cell-days per bin."""
    edges = np.r_[0, np.logspace(-6, 0, 13)]
    fig, (a, b) = plt.subplots(2, 1, figsize=(4.4, 4.4), sharex=True,
                               gridspec_kw={"height_ratios": [2.2, 1]})
    a.plot([1e-6, 1], [1e-6, 1], color="black", ls=":", lw=0.8, label="Perfect calibration")
    for k, m in enumerate(["xgboost", "catboost"]):
        p = predictions(m)
        p["bin"] = np.digitize(p.probability, edges[1:-1])
        g = p.assign(wl=p.label * p.weight, wp=p.probability * p.weight).groupby("bin")
        r = pd.DataFrame({"w": g.weight.sum(), "pos": g.wl.sum(), "pred": g.wp.sum(),
                          "rows": g.size()})
        r = r[r.rows >= 20]
        r["predicted"] = r.pred / r.w
        r["observed"] = r.pos / r.w
        shown = r[r.observed > 0]
        a.plot(shown.predicted, shown.observed, marker="o", ms=4, color=COLOR[m], lw=1.1,
               label=LABEL[m])
        centers = np.sqrt(np.maximum(edges[r.index], 1e-7) * edges[np.minimum(r.index + 1, 13)])
        b.bar(centers * (0.85 if k == 0 else 1.15), r.w, width=centers * 0.3, color=COLOR[m])
    a.set(xscale="log", yscale="log", xlim=(1e-6, 1), ylim=(1e-6, 1),
          ylabel="Observed frequency")
    a.legend(loc="upper left", frameon=False)
    b.set(xscale="log", yscale="log", xlabel="Mean predicted probability (log scale)",
          ylabel="Cell-days")
    panel(a, "a")
    panel(b, "b")
    fig.tight_layout(h_pad=1.0)
    save(fig, "fig_reliability")


def fig_shap() -> None:
    """(a) the twelve strongest predictors, (b) group contributions by dominant land cover."""
    g = pd.read_csv(RUN / "explain/global.csv").nlargest(12, "weighted_mean_abs_contribution")
    g = g.iloc[::-1]
    grouped = pd.read_csv(RUN / "explain/grouped.csv")
    lc = grouped[grouped.dimension == "landcover"].pivot(
        index="group", columns="feature_group", values="weighted_mean_abs_group_contribution")
    order = ["human", "season", "antecedent_weather", "weather", "cover", "terrain", "vegetation"]
    heads = ["Human", "Season", "7/14-day\nweather", "Daily\nweather", "Land\ncover", "Terrain",
             "Vege-\ntation"]
    lc = lc.loc[["grassland", "cropland", "forest", "shrubland", "other"], order]
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 3.1), gridspec_kw={"width_ratios": [1, 1.1]})
    a.barh(range(len(g)), g.weighted_mean_abs_contribution,
           color=[GROUP_COLOR[GROUP_OF[f]] for f in g.feature])
    a.set_yticks(range(len(g)), [NICE.get(f, f) for f in g.feature])
    a.set_xlabel("Mean |SHAP| (log-odds)")
    a.grid(axis="y", visible=False)
    used = list(dict.fromkeys(GROUP_OF[f] for f in g.feature[::-1]))
    a.legend(handles=[matplotlib.patches.Patch(color=GROUP_COLOR[u], label=u) for u in used],
             loc="lower right", frameon=False, fontsize=6.5)
    im = b.imshow(lc.to_numpy(), cmap="OrRd", aspect="auto", vmin=0, vmax=1.8)
    b.set_xticks(range(len(order)), heads, rotation=40, ha="right", rotation_mode="anchor")
    b.set_yticks(range(len(lc)), [i.capitalize() for i in lc.index])
    for i in range(lc.shape[0]):
        for j in range(lc.shape[1]):
            v = lc.iat[i, j]
            b.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=6.5,
                   color="white" if v > 1.1 else "black")
    b.grid(False)
    fig.colorbar(im, ax=b, label="Mean |SHAP| of the group", shrink=0.9)
    panel(a, "a")
    panel(b, "b")
    fig.tight_layout(w_pad=1.5)
    save(fig, "fig_shap")


def fig_case() -> None:
    """Forecast percentile classes for 7-9 June 2023, region outlines and each day's new starts."""
    import rasterio

    laea = Transformer.from_crs("EPSG:4326", "+proj=laea +lat_0=48 +lon_0=67 +datum=WGS84",
                                always_xy=True)
    regions = pd.read_parquet(ROOT / "data/real/normalized/regions.parquet")
    outlines = []
    for wkb in regions.geometry:
        geom = shapely.wkb.loads(wkb)
        for poly in getattr(geom, "geoms", [geom]):
            x, y = laea.transform(*np.asarray(poly.exterior.coords).T)
            outlines.append((x / 1000, y / 1000))
    events = pd.read_parquet(RUN / "outcomes/events_through_2024.parquet")
    semei = laea.transform(80.623, 50.56)
    days = ["2023-06-07", "2023-06-08", "2023-06-09"]
    colors = matplotlib.colors.ListedColormap(["#f3efe6", "#f6c977", "#ec7d3a", "#b2182b"])
    fig, axes = plt.subplots(3, 1, figsize=(5.6, 8.1))
    for ax, day, letter in zip(axes, days, "abc", strict=True):
        with rasterio.open(RUN / f"maps/probability_{day}.tif") as src:
            a = src.read(1, masked=True).astype(float).filled(np.nan)
            b = src.bounds
        finite = np.isfinite(a)
        ranks = np.full(a.shape, np.nan)
        ranks[finite] = pd.Series(a[finite]).rank(pct=True).to_numpy()
        classes = np.full(a.shape, np.nan)
        classes[finite] = np.digitize(ranks[finite], [0.80, 0.95, 0.99])
        ax.imshow(classes, extent=(b.left / 1000, b.right / 1000, b.bottom / 1000, b.top / 1000),
                  cmap=colors, vmin=-0.5, vmax=3.5, interpolation="nearest")
        for x, y in outlines:
            ax.plot(x, y, color="#555555", lw=0.35)
        starts = events[(events.timestamp.dt.strftime("%Y-%m-%d") == day) & events.is_first]
        ax.scatter(starts.x / 1000, starts.y_coord / 1000, s=16, facecolor="none",
                   edgecolor="#08306b", lw=1.0, zorder=3)
        if day == "2023-06-08":
            ax.annotate("Semei start\n(78th percentile)", xy=(semei[0] / 1000, semei[1] / 1000),
                        xytext=(semei[0] / 1000 - 330, semei[1] / 1000 + 330), fontsize=7,
                        arrowprops={"arrowstyle": "->", "lw": 0.8}, ha="center")
        ax.set_xlim(b.left / 1000, b.right / 1000)
        ax.set_ylim(b.bottom / 1000, b.top / 1000)
        ax.set_axis_off()
        ax.text(0.0, 0.98, f"({letter}) {day}", transform=ax.transAxes, fontweight="bold",
                va="top")
    handles = [matplotlib.patches.Patch(color=colors(i), label=t) for i, t in
               enumerate(["Below top 20%", "Top 5-20%", "Top 1-5%", "Top 1%"])]
    handles.append(matplotlib.lines.Line2D([], [], marker="o", ls="", mfc="none", mec="#08306b",
                                           label="New fire start"))
    fig.legend(handles=handles, loc="lower center", ncol=5, frameon=False,
               bbox_to_anchor=(0.5, -0.01), handlelength=1.2, columnspacing=1.0)
    fig.tight_layout(h_pad=0.3, rect=(0, 0.03, 1, 1))
    save(fig, "fig_case")


def comparability_table() -> None:
    """Numbers that put the test results next to studies evaluated on balanced samples or on
    hazard classes: AP after re-weighting negatives to a 1:1 balance (same predictions, nothing
    refitted) and the share of new starts and of cell-days in each frozen map class."""
    frozen = json.loads((RUN / "frozen.json").read_text())
    rows = []
    for m in MODELS:
        p = predictions(m)
        pos = float((p.label * p.weight).sum())
        neg = float(((1 - p.label) * p.weight).sum())
        balanced = np.where(p.label == 1, p.weight, p.weight * pos / neg)
        cls = np.digitize(p.probability, frozen["map_boundaries"][m])
        starts = (p.label * p.weight).groupby(cls).sum() / pos
        days = p.weight.groupby(cls).sum() / p.weight.sum()
        rows.append({
            "model": m,
            "ap_balanced_1to1": average_precision_score(p.label, p.probability,
                                                        sample_weight=balanced),
            **{f"starts_class{k + 1}": starts.get(k, 0.0) for k in range(4)},
            **{f"cell_days_class{k + 1}": days.get(k, 0.0) for k in range(4)},
        })
    pd.DataFrame(rows).to_csv(TAB / "T17_comparability.csv", index=False)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig_performance()
    fig_ablation()
    fig_transfer()
    fig_reliability()
    fig_shap()
    fig_case()
    comparability_table()
    print(sorted(p.name for p in OUT.glob("fig_*.pdf")))


if __name__ == "__main__":
    main()
