"""Shared matplotlib style: fixed categorical order, recessive axes, thin marks."""

from __future__ import annotations

from pathlib import Path

import matplotlib
from cycler import cycler

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# validated reference categorical order (assigned in fixed order, never cycled)
CATEGORICAL = [
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#6250d6",
    "#e34948",
]
OTHER = "#8a8984"
SEQUENTIAL_CMAP = "Blues"
DIVERGING = ("#2a78d6", "#e34948")  # cool / warm poles, gray midpoint
TEXT = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
SYNTHETIC_BANNER = "SYNTHETIC DATA — illustrates the pipeline only, not findings about Kazakhstan"
CAUSAL_NOTE = "SHAP values describe predictive associations of the model, not causal effects"


def apply_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": TEXT_SECONDARY,
            "axes.titlecolor": TEXT,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.color": TEXT_SECONDARY,
            "ytick.color": TEXT_SECONDARY,
            "lines.linewidth": 2.0,
            "lines.markersize": 5,
            "font.size": 9,
            "axes.titlesize": 10,
            "legend.frameon": False,
            "axes.prop_cycle": cycler(color=CATEGORICAL),
        }
    )


def color_for(names: list[str]) -> dict[str, str]:
    """Stable entity -> colour mapping (sorted names; >8 entities fold into gray 'other')."""
    out = {}
    for i, n in enumerate(sorted(names)):
        out[n] = CATEGORICAL[i] if i < len(CATEGORICAL) else OTHER
    return out


def save(fig: plt.Figure, path: Path, note: str | None = None) -> None:
    if note:
        fig.text(0.01, 0.005, note, fontsize=7, color=TEXT_SECONDARY, ha="left", va="bottom")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path.with_suffix(".png"), dpi=150, bbox_inches="tight")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
