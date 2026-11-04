"""Predictor-group ablation for the article (RQ1): does each group of inputs add value?

Same data, splits, frozen XGBoost hyperparameters, sigmoid calibration on 2022 and test years
2023-2024 as the public hindcast (runs/public_hindcast). Each variant drops one predictor group;
"weather_only" keeps same-day and antecedent weather only, so model class and information are
separated. Rolling-origin validation (fit through Y-1, validate on Y, Y = 2019-2021) gives the
selection-safe view; the test years give the reported one. Paired 95% intervals use the same
1000 space-time block resamples (100 km x 30 days) for every variant.
Post hoc: the test years were already opened for the final evaluation, so this analysis
explains the result and selects nothing.
Usage: paper_ablation.py   -> docs/paper/results/tables/ablation*.csv
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from wildfire_kz.calibration import fit_sigmoid  # noqa: E402
from wildfire_kz.evaluation import cluster_draws, metrics, paired_intervals  # noqa: E402
from wildfire_kz.models import fit_model, fit_seasonal  # noqa: E402
from wildfire_kz.public_experiment import config  # noqa: E402

RUN = ROOT / "runs/public_hindcast"
OUT = ROOT / "docs/paper/results/tables"
FEATURES = json.loads((RUN / "design.json").read_text())["features"]
GROUPS = {
    "same_day_weather": ["tmax", "tmin", "wind", "rh", "precip", "soil_moisture"],
    "antecedent_weather": ["precip_7d", "precip_14d", "temperature_7d", "temperature_14d"],
    "vegetation": ["ndvi", "ndvi_missing", "ndvi_age_days"],
    "land_cover": ["forest", "grassland", "shrubland", "cropland", "other"],
    "terrain": ["elevation", "slope", "aspect_sin", "aspect_cos"],
    "human": ["population_density", "settlement_distance"],
    "season": ["month_sin", "month_cos"],
}
VARIANTS = {"full": FEATURES}
VARIANTS |= {f"without_{g}": [f for f in FEATURES if f not in cols] for g, cols in GROUPS.items()}
VARIANTS["weather_only"] = GROUPS["same_day_weather"] + GROUPS["antecedent_weather"]


def table(name: str) -> pd.DataFrame:
    return pd.read_parquet(RUN / f"features/{name}.parquet")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = config(5)
    cfg.models.threads = 2
    params = json.loads((RUN / "tuning.json").read_text())["xgboost"]["selected"]
    train = {y: table(f"{y}_train") for y in range(2015, 2022)}
    evaluation = {y: table(f"{y}_evaluation") for y in range(2019, 2025)}

    # Rolling origin: the selection-safe view of each group's value.
    rows = []
    for year in (2019, 2020, 2021):
        fit = pd.concat([train[y] for y in range(2015, year)], ignore_index=True)
        valid = evaluation[year]
        y, w = valid.label.to_numpy(), valid.weight.to_numpy()
        for name, cols in VARIANTS.items():
            p = fit_model("xgboost", fit, cols, cfg, params, sampled=True).predict(valid)
            from sklearn.metrics import average_precision_score

            rows.append(
                {
                    "year": year,
                    "variant": name,
                    "ap": average_precision_score(y, p, sample_weight=w),
                }
            )
            print(f"rolling {year} {name} {rows[-1]['ap']:.5f}", flush=True)
    pd.DataFrame(rows).to_csv(OUT / "ablation_rolling.csv", index=False)

    # Test years with the hindcast's calibration and reference.
    fit = pd.concat(train.values(), ignore_index=True)
    cal = evaluation[2022]
    test = pd.concat([evaluation[2023], evaluation[2024]], ignore_index=True)
    y, w = test.label.to_numpy(), test.weight.to_numpy()
    reference = fit_seasonal(fit, cfg.models.seasonal_smoothing).predict(test)
    predictions, thresholds, out = {}, {}, []
    for name, cols in VARIANTS.items():
        model = fit_model("xgboost", fit, cols, cfg, params, sampled=True)
        calibration, threshold = fit_sigmoid(cal, model.predict(cal), 2022)
        p = calibration.predict(model.predict(test))
        predictions[name], thresholds[name] = p, threshold
        m = metrics(y, p, w, threshold, reference)
        out.append({"variant": name, "features": len(cols), **m})
        print(f"test {name} ap={m['average_precision']:.5f} bss={m['bss']:.5f}", flush=True)
    pd.DataFrame(out).to_csv(OUT / "ablation_test.csv", index=False)
    draws = cluster_draws(test, 1000, 100_000, 30, 42)
    pairs = paired_intervals(y, predictions, w, thresholds, reference, draws, 0.95)
    pairs.to_csv(OUT / "ablation_intervals.csv", index=False)
    print("done", flush=True)


if __name__ == "__main__":
    main()
