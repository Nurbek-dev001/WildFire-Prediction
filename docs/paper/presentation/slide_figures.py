"""Slide versions of the article figures: same data and code (scripts/article_figures.py),
larger fonts for projection, plus a horizontal June 2023 map, a title-slide map and the two
data tables shown on the data slides."""

import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\nured\Documents\ChatGPT\WildFire")
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "scripts"))

import article_figures as af  # noqa: E402
import matplotlib  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import shapely.wkb  # noqa: E402
from pyproj import Transformer  # noqa: E402

plt.rcParams.update(
    {
        "font.size": 11,
        "axes.labelsize": 11,
        "legend.fontsize": 9.5,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "axes.titlesize": 11,
    }
)
af.OUT = OUT
_subplots = plt.subplots


def _larger(*args, figsize=None, **kwargs):
    """Same figures as the article, 25% larger canvas so the bigger slide fonts fit."""
    if figsize is not None:
        figsize = (figsize[0] * 1.25, figsize[1] * 1.25)
    return _subplots(*args, figsize=figsize, **kwargs)


plt.subplots = _larger
af.fig_performance()
af.fig_ablation()
af.fig_regions()
af.fig_reliability()
af.fig_shap()
plt.subplots = _subplots

RUN = af.RUN
laea = Transformer.from_crs(
    "EPSG:4326", "+proj=laea +lat_0=48 +lon_0=67 +datum=WGS84", always_xy=True
)
regions = pd.read_parquet(ROOT / "data/real/normalized/regions.parquet")
outlines = []
for wkb in regions.geometry:
    geom = shapely.wkb.loads(wkb)
    for poly in getattr(geom, "geoms", [geom]):
        x, y = laea.transform(*np.asarray(poly.exterior.coords).T)
        outlines.append((x / 1000, y / 1000))
events = pd.read_parquet(RUN / "outcomes/events_through_2024.parquet")
colors = matplotlib.colors.ListedColormap(["#f3efe6", "#f6c977", "#ec7d3a", "#b2182b"])


def day_map(ax, day, starts=True):
    import rasterio

    with rasterio.open(RUN / f"maps/probability_{day}.tif") as src:
        a = src.read(1, masked=True).astype(float).filled(np.nan)
        b = src.bounds
    finite = np.isfinite(a)
    ranks = np.full(a.shape, np.nan)
    ranks[finite] = pd.Series(a[finite]).rank(pct=True).to_numpy()
    classes = np.full(a.shape, np.nan)
    classes[finite] = np.digitize(ranks[finite], [0.80, 0.95, 0.99])
    ax.imshow(
        classes,
        extent=(b.left / 1000, b.right / 1000, b.bottom / 1000, b.top / 1000),
        cmap=colors,
        vmin=-0.5,
        vmax=3.5,
        interpolation="nearest",
    )
    for x, y in outlines:
        ax.plot(x, y, color="#555555", lw=0.4)
    if starts:
        s = events[(events.timestamp.dt.strftime("%Y-%m-%d") == day) & events.is_first]
        ax.scatter(
            s.x / 1000,
            s.y_coord / 1000,
            s=22,
            facecolor="none",
            edgecolor="#08306b",
            lw=1.1,
            zorder=3,
        )
    ax.set_xlim(b.left / 1000, b.right / 1000)
    ax.set_ylim(b.bottom / 1000, b.top / 1000)
    ax.set_axis_off()


# horizontal case figure
semei = laea.transform(80.623, 50.56)
fig, axes = plt.subplots(1, 3, figsize=(13, 3.3))
for ax, day, letter in zip(axes, ["2023-06-07", "2023-06-08", "2023-06-09"], "abc", strict=True):
    day_map(ax, day)
    bottom, top = ax.get_ylim()
    ax.set_ylim(bottom, top + 320)  # room above the map for the label
    ax.set_title(f"({letter}) {day}", loc="left", fontweight="bold")
    if day == "2023-06-08":
        ax.annotate(
            "Semei start: 78th percentile",
            xy=(semei[0] / 1000, semei[1] / 1000),
            xytext=(semei[0] / 1000 - 250, top + 230),
            fontsize=10,
            arrowprops={"arrowstyle": "->", "lw": 1.0},
            ha="center",
        )
handles = [
    matplotlib.patches.Patch(color=colors(i), label=t)
    for i, t in enumerate(["Below top 20%", "Top 5-20%", "Top 1-5%", "Top 1%"])
]
handles.append(
    matplotlib.lines.Line2D(
        [], [], marker="o", ls="", mfc="none", mec="#08306b", label="New fire start"
    )
)
fig.legend(handles=handles, loc="lower center", ncol=5, frameon=False, bbox_to_anchor=(0.5, 0.0))
fig.tight_layout(rect=(0, 0.07, 1, 1))
fig.savefig(OUT / "fig_case_wide.png", dpi=250, bbox_inches="tight")
plt.close(fig)

# title-slide map: one summer day, transparent background, no starts
fig, ax = plt.subplots(figsize=(7, 4))
day_map(ax, "2023-06-08", starts=False)
fig.savefig(OUT / "hero_map.png", dpi=250, bbox_inches="tight", transparent=True)
plt.close(fig)

# data tables for the data slides (real rows)
to_lonlat = Transformer.from_crs(
    "+proj=laea +lat_0=48 +lon_0=67 +datum=WGS84", "EPSG:4326", always_xy=True
)
raw = pd.read_parquet(ROOT / "data/real/normalized/detections_2023.parquet")
raw = raw[raw.confidence.isin(["n", "h"])].sort_values("timestamp")
raw = raw[raw.timestamp.dt.month == 6].head(5)
lon, lat = to_lonlat.transform(raw.x.to_numpy(), raw.y_coord.to_numpy())
raw_rows = [
    [
        t.strftime("%Y-%m-%d %H:%M"),
        f"{la:.3f}",
        f"{lo:.3f}",
        {"n": "nominal", "h": "high"}[c],
        "Suomi-NPP",
    ]
    for t, la, lo, c in zip(raw.timestamp, lat, lon, raw.confidence, strict=False)
]
f = pd.read_parquet(RUN / "features/2023_evaluation.parquet")
f = f[f.day.dt.month == 6]
rows = pd.concat([f[f.label == 1].head(3), f[(f.label == 0)].sample(2, random_state=3)])
feat_rows = [
    [
        d.strftime("%Y-%m-%d"),
        lc,
        f"{tm:.1f}",
        f"{pr:.1f}",
        "--" if np.isnan(nd) else f"{nd:.2f}",
        f"{el:.0f}",
        f"{pop:.1f}",
        str(int(lb)),
    ]
    for d, lc, tm, pr, nd, el, pop, lb in zip(
        rows.day,
        rows.landcover,
        rows.tmax,
        rows.precip_14d,
        rows.ndvi,
        rows.elevation,
        rows.population_density,
        rows.label,
        strict=False,
    )
]
(OUT / "tables.json").write_text(json.dumps({"raw": raw_rows, "features": feat_rows}, indent=1))
print(sorted(p.name for p in OUT.iterdir()))
