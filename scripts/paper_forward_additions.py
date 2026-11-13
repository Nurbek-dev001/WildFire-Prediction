"""Forward predictor-group additions for the poster (RQ1): start from weather only and add one
group at a time until all 26 inputs are used.

Same data, frozen XGBoost hyperparameters, sigmoid calibration on 2022 and test years 2023-2024
as scripts/paper_ablation.py (which removes one group at a time). Post hoc: the test years were
already opened for the final evaluation, so this analysis explains the result and selects
nothing. The order of additions is fixed in advance below; another order can give different
step sizes, but the last row is always the full model.
Usage: paper_forward_additions.py   -> docs/paper/results/tables/forward_additions.csv
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from paper_ablation import GROUPS, RUN, table  # noqa: E402

from wildfire_kz.calibration import fit_sigmoid  # noqa: E402
from wildfire_kz.evaluation import metrics, top_capture  # noqa: E402
from wildfire_kz.models import fit_model, fit_seasonal  # noqa: E402
from wildfire_kz.public_experiment import config  # noqa: E402

OUT = ROOT / "docs/paper/results/tables"
STEPS = [
    ("weather only", GROUPS["same_day_weather"] + GROUPS["antecedent_weather"]),
    ("+ vegetation", GROUPS["vegetation"]),
    ("+ land cover", GROUPS["land_cover"]),
    ("+ terrain", GROUPS["terrain"]),
    ("+ human pressure", GROUPS["human"]),
    ("+ season (all 26)", GROUPS["season"]),
]


def main() -> None:
    cfg = config(5)
    cfg.models.threads = 4
    params = json.loads((RUN / "tuning.json").read_text())["xgboost"]["selected"]
    fit = pd.concat([table(f"{y}_train") for y in range(2015, 2022)], ignore_index=True)
    cal = table("2022_evaluation")
    test = pd.concat([table("2023_evaluation"), table("2024_evaluation")], ignore_index=True)
    y, w = test.label.to_numpy(), test.weight.to_numpy()
    reference = fit_seasonal(fit, cfg.models.seasonal_smoothing).predict(test)
    cols, rows = [], []
    for name, group in STEPS:
        cols = cols + group
        model = fit_model("xgboost", fit, cols, cfg, params, sampled=True)
        calibration, threshold = fit_sigmoid(cal, model.predict(cal), 2022)
        p = calibration.predict(model.predict(test))
        m = metrics(y, p, w, threshold, reference)
        capture = float(top_capture(test, p, [0.05]).capture_rate.iloc[0])
        rows.append(
            {
                "step": name,
                "features": len(cols),
                "average_precision": m["average_precision"],
                "roc_auc": m["roc_auc"],
                "top5_capture": capture,
                "bss": m["bss"],
            }
        )
        print(
            f"{name:20s} n={len(cols):2d} ap={m['average_precision']:.4f} "
            f"auc={m['roc_auc']:.3f} top5={capture:.3f}",
            flush=True,
        )
        pd.DataFrame(rows).to_csv(OUT / "forward_additions.csv", index=False)
    print("done", flush=True)


if __name__ == "__main__":
    main()
