"""Report figures (PNG + PDF), all drawn from saved stage artifacts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from wildfire_kz.evaluation.metrics import precision_recall_steps
from wildfire_kz.report.style import (
    CATEGORICAL,
    OTHER,
    TEXT_SECONDARY,
    apply_style,
    color_for,
    save,
)


def reliability_figure(
    rel: pd.DataFrame, models: list[str], binning: str, path: Path, note: str
) -> None:
    """Small multiples (one panel per model): observed vs predicted, Wilson CI, bin counts."""
    import matplotlib.pyplot as plt

    apply_style()
    n = len(models)
    cols = min(3, n)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3.4 * cols, 3.2 * rows), squeeze=False)
    for ax, m in zip(axes.ravel(), models, strict=False):
        t = rel[(rel["model"] == m) & (rel["binning"] == binning) & (rel["weight"] > 0)]
        log_axes = binning == "quantile"
        lo_lim = max(float(t["mean_pred"].min()), 1e-5) * 0.5 if log_axes else 0.0
        hi = float(np.nanmax([t["mean_pred"].max(), t["obs_hi"].max(), 1e-6])) * 1.15
        ax.plot([lo_lim, hi], [lo_lim, hi], color=OTHER, linewidth=1, linestyle="--")
        obs = t["obs_freq"].clip(lower=lo_lim) if log_axes else t["obs_freq"]
        ax.errorbar(
            t["mean_pred"],
            obs,
            yerr=[(obs - t["obs_lo"].clip(lower=lo_lim)).clip(lower=0), t["obs_hi"] - obs],
            fmt="o",
            color=CATEGORICAL[0],
            ecolor=CATEGORICAL[0],
            elinewidth=1,
            markersize=5,
            capsize=2,
        )
        if log_axes:
            ax.set_xscale("log")
            ax.set_yscale("log")
        last = -np.inf
        span = np.log10(hi / lo_lim) if log_axes else hi
        for _, r in t.sort_values("mean_pred").iterrows():
            pos = np.log10(max(r["mean_pred"], lo_lim)) if log_axes else r["mean_pred"]
            if pos - last < 0.12 * span or (log_axes and r["obs_freq"] <= lo_lim):
                continue  # skip labels that would collide (counts stay in the CSV)
            last = pos
            ax.annotate(
                f"n={int(r['n'])}",
                (r["mean_pred"], max(r["obs_freq"], lo_lim)),
                fontsize=6,
                color=TEXT_SECONDARY,
                xytext=(4, -9),
                textcoords="offset points",
            )
        ax.set_xlim(lo_lim, hi)
        ax.set_ylim(lo_lim, hi)
        ax.set_title(m, loc="left")
        ax.set_xlabel("mean calibrated probability")
        ax.set_ylabel("observed frequency (weighted)")
    for ax in axes.ravel()[n:]:
        ax.set_visible(False)
    scale = "log–log axes; " if binning == "quantile" else ""
    fig.suptitle(
        f"Reliability ({binning} bins, {scale}95% Wilson interval on effective n; "
        "all bin counts in reliability.csv)",
        x=0.01,
        ha="left",
        fontsize=10,
    )
    fig.tight_layout()
    save(fig, path, note)


def pr_curves(pred: pd.DataFrame, models: list[str], path: Path, note: str) -> None:
    import matplotlib.pyplot as plt

    apply_style()
    colors = color_for(models)
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    y, w = pred["label"].to_numpy(), pred["w_eval"].to_numpy()
    for m in models:
        p, r, _ = precision_recall_steps(y, pred[f"p_{m}"].to_numpy(), w)
        ax.step(np.r_[0, r], np.r_[p[0], p], where="pre", color=colors[m], linewidth=1.6, label=m)
    prev = float((w * y).sum() / w.sum())
    ax.axhline(prev, color=OTHER, linestyle="--", linewidth=1, label="no-skill (prevalence)")
    ax.set_xlabel("recall (weighted)")
    ax.set_ylabel("precision (weighted)")
    ax.set_title("Precision–recall on the test years (step-wise, as used for AP)", loc="left")
    ax.legend(fontsize=7, loc="upper right")
    save(fig, path, note)


def capture_figure(cap: pd.DataFrame, models: list[str], mode: str, path: Path, note: str) -> None:
    import matplotlib.pyplot as plt

    apply_style()
    colors = color_for(models)
    t = cap[(cap["mode"] == mode) & cap["model"].isin(models)]
    fracs = sorted(t["fraction"].unique())
    width = 0.8 / max(len(models), 1)
    fig, ax = plt.subplots(figsize=(6.0, 3.8))
    for i, m in enumerate(sorted(models)):
        s = t[t["model"] == m].set_index("fraction").reindex(fracs)
        ax.bar(
            np.arange(len(fracs)) + i * width,
            s["capture_rate"],
            width * 0.92,
            color=colors[m],
            label=m,
        )
    ax.plot(
        np.arange(len(fracs)) + 0.4 - width / 2,
        fracs,
        color=OTHER,
        marker="_",
        markersize=18,
        linestyle="none",
        label="random ranking",
    )
    ax.set_xticks(np.arange(len(fracs)) + 0.4 - width / 2, [f"top {f:.0%}" for f in fracs])
    ax.set_ylabel("share of new-event starts captured")
    ax.set_title(f"Capture rate ({mode} ranking of eligible cell-days)", loc="left")
    ax.legend(fontsize=7, ncols=2)
    ax.grid(axis="x", visible=False)
    save(fig, path, note)


def forest_plot(pairs: pd.DataFrame, metric: str, path: Path, note: str) -> None:
    import matplotlib.pyplot as plt

    apply_style()
    t = pairs[pairs["metric"] == metric].copy()
    if t.empty:
        return
    t["label"] = t["model_a"] + "  −  " + t["model_b"]
    t = t.sort_values("diff_mean")
    fig, ax = plt.subplots(figsize=(6.6, 0.3 * len(t) + 1.3))
    yy = np.arange(len(t))
    col = np.where(t["ci_excludes_zero"], CATEGORICAL[0], OTHER)
    ax.hlines(yy, t["ci_lo"], t["ci_hi"], color=col, linewidth=2)
    ax.scatter(t["diff_mean"], yy, color=col, s=18, zorder=3)
    ax.axvline(0, color=TEXT_SECONDARY, linewidth=0.8)
    ax.set_yticks(yy, t["label"], fontsize=7)
    ax.set_xlabel(f"difference in {metric} (paired space–time block bootstrap, 95% CI)")
    ax.set_title("Paired model differences (gray: CI includes 0)", loc="left")
    ax.grid(axis="y", visible=False)
    save(fig, path, note)


def spatial_cv_figure(sp: pd.DataFrame, path: Path, note: str) -> None:
    import matplotlib.pyplot as plt

    apply_style()
    models = sorted(sp["model"].unique())
    colors = color_for(models)
    blocks = sorted(sp["block_km"].unique())
    fig, axes = plt.subplots(
        1, len(blocks), figsize=(4.2 * len(blocks), 3.6), squeeze=False, sharey=True
    )
    for ax, b in zip(axes.ravel(), blocks, strict=True):
        t = sp[sp["block_km"] == b]
        for i, m in enumerate(models):
            s = t[t["model"] == m]
            ax.scatter(np.full(len(s), i), s["average_precision"], color=colors[m], s=22)
            ax.scatter(np.full(len(s), i), s["prevalence"], color=OTHER, marker="_", s=120)
        ax.set_xticks(range(len(models)), models, rotation=35, ha="right", fontsize=7)
        ax.set_title(f"{b:.0f} km blocks — held-out folds", loc="left")
        ax.set_ylabel("weighted AP (dots); prevalence (gray dash)")
        ax.grid(axis="x", visible=False)
    fig.tight_layout()
    save(fig, path, note)


def ablation_figure(abl: pd.DataFrame, path: Path, note: str) -> None:
    import matplotlib.pyplot as plt

    apply_style()
    t = abl.sort_values("delta_ap_vs_full")
    labels = t["model"] + " − " + t["ablated_group"]
    fig, ax = plt.subplots(figsize=(6.4, 0.28 * len(t) + 1.3))
    col = [CATEGORICAL[7] if d < 0 else CATEGORICAL[0] for d in t["delta_ap_vs_full"]]
    ax.barh(labels, t["delta_ap_vs_full"], color=col, height=0.7)
    ax.axvline(0, color=TEXT_SECONDARY, linewidth=0.8)
    ax.set_xlabel("Δ weighted AP vs full model (development rolling-origin validation)")
    ax.set_title("Grouped ablations (red: removing the group lowers AP)", loc="left")
    ax.tick_params(axis="y", labelsize=7)
    ax.grid(axis="y", visible=False)
    save(fig, path, note)
