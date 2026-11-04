"""Run the code shown in the presentation's code cells on the real experiment data and save
their printed outputs, so every output on a slide comes from an actual run."""

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\nured\Documents\ChatGPT\WildFire")
RUN = ROOT / "runs/public_hindcast"
OUT = Path(sys.argv[1])
cells = {}


def cell(name):
    def wrap(fn):
        buf = io.StringIO()
        with redirect_stdout(buf):
            fn()
        cells[name] = buf.getvalue().rstrip()
        return fn
    return wrap


@cell("raw")
def _():
    raw = pd.read_parquet(ROOT / "data/real/normalized/detections_2023.parquet")
    print(f"{len(raw):,} VIIRS fire detections in 2023")
    print(raw[["timestamp", "x", "y_coord", "confidence"]].head(3).to_string(index=False))


@cell("events")
def _():
    events = pd.read_parquet(RUN / "outcomes/events_through_2024.parquet",
                             columns=["day", "is_first"])
    years = events.day.dt.year.between(2015, 2024)
    print(f"{years.sum():,} detections (2015-2024)")
    print(f"{(events.is_first & years).sum():,} separate fire events")


@cell("sampling")
def _():
    test = pd.read_parquet(RUN / "features/2023_evaluation.parquet",
                           columns=["label", "weight"])
    print(f"{len(test):,} sampled rows in 2023")
    print(f"{int(test.label.sum()):,} new fire starts (all kept)")
    print(f"{test.weight.sum():,.0f} cell-days represented")


@cell("evaluate")
def _():
    from sklearn.metrics import average_precision_score, roc_auc_score
    p = pd.read_parquet(RUN / "evaluate/predictions_xgboost.parquet",
                        columns=["label", "weight", "probability"])
    y, w, s = p.label, p.weight, p.probability
    prevalence = (y * w).sum() / w.sum()
    ap = average_precision_score(y, s, sample_weight=w)
    auc = roc_auc_score(y, s, sample_weight=w)
    print(f"Fire rate (no-skill AP): {prevalence:.2e}")
    print(f"AP      = {ap:.4f}  ({ap / prevalence:.0f} x no-skill)")
    print(f"ROC-AUC = {auc:.3f}")


@cell("capture")
def _():
    sys.path.insert(0, str(ROOT / "src"))
    from wildfire_kz.evaluation import top_capture
    p = pd.read_parquet(RUN / "evaluate/predictions_xgboost.parquet")
    table = top_capture(p, p.probability.to_numpy(), [0.05, 0.10, 0.20])
    for _, r in table.iterrows():
        print(f"top {r.nominal_fraction:.0%} of area -> {r.capture_rate:.1%} of new fires")


@cell("shap")
def _():
    g = pd.read_csv(RUN / "explain/global.csv").nlargest(5, "weighted_mean_abs_contribution")
    for _, r in g.iterrows():
        print(f"{r.feature:<20} {r.weighted_mean_abs_contribution:.2f}")


@cell("calibration")
def _():
    frozen = json.loads((RUN / "frozen.json").read_text())
    print(f"alert threshold (2022): {frozen['thresholds']['xgboost']:.3f}")
    b = frozen["map_boundaries"]["xgboost"]
    print("map class limits:", ", ".join(f"{v:.1e}" for v in b))


@cell("tuning")
def _():
    t = json.loads((RUN / "tuning.json").read_text())["xgboost"]
    for k, v in t["selected"].items():
        print(f"{k:<17} {v:.4g}" if isinstance(v, float) else f"{k:<17} {v}")
    print(f"validation AP     {t['development_selection_ap']:.4f}")


OUT.write_text(json.dumps(cells, indent=1), encoding="utf-8")
for k, v in cells.items():
    print(f"--- {k}\n{v}")
