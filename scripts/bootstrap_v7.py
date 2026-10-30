"""Paired block bootstrap (95%) of the v7 candidate against the v6 recipe at every origin.

Recomputes the scores of develop_model_v7.v7_candidate exactly (same fits, calibration and
thresholds) and resamples 100 km x 30 day blocks, as every earlier test did. Development
evidence only; the frozen release is not touched.
Usage: bootstrap_v7.py   (V7_DRAWS sets the number of draws, default 1000)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import develop_model_v7 as v7  # noqa: E402

from wildfire_kz import model_upgrade as mu  # noqa: E402
from wildfire_kz.data import dump_json  # noqa: E402


def scores(origin: int) -> tuple[pd.DataFrame, np.ndarray, float, np.ndarray]:
    """Test rows, v6 recipe scores and threshold, v7 scores; as in v7_candidate."""
    features = v7.v7_features()
    v6_features = json.loads((v7.V6 / "frozen.json").read_text())["features"]
    test = v7.primary(v7.loaded(v7.evaluation_name(origin), v7.weather_inputs(origin)))
    fit_ref = pd.concat(
        [v7.loaded(v7.fit_table(t), ("h3",)) for t in range(2015, origin - 1)], ignore_index=True
    )
    ref = v7.train(fit_ref, v6_features)
    cal_ref = v7.primary(v7.loaded(v7.evaluation_name(origin - 1), ("h3",)))
    calibration, ref_t = v7.calibrate(ref, cal_ref, v6_features, origin - 1)
    ref_p = mu.published_probability(
        calibration.predict(ref.predict_proba(test[v6_features])[:, 1])
    )
    fit = pd.concat(
        [v7.loaded(v7.fit_table(t), ("h3", "h2era5")) for t in range(2015, origin - 2)],
        ignore_index=True,
    )
    clf = v7.train(fit, features)
    cal = pd.concat(
        [v7.calibration_rows(t, v7.weather_inputs(t)) for t in (origin - 2, origin - 1)],
        ignore_index=True,
    )
    iso, _ = v7.isotonic_two_years(clf.predict_proba(cal[features])[:, 1], cal)
    p = mu.published_probability(iso.predict(clf.predict_proba(test[features])[:, 1]))
    return test, ref_p, ref_t, p


def main() -> None:
    v7.check_protocol()
    out = v7.RUN / "experiments/v7_candidate/bootstrap.json"
    result = json.loads(out.read_text()) if out.exists() else {}
    for origin in v7.ORIGINS:
        if str(origin) in result:
            continue
        test, ref_p, ref_t, p = scores(origin)
        y, w = test.label.to_numpy() == 1, test.weight.to_numpy()
        group = v7.clusters(test)
        n_groups = group.max() + 1
        rng = np.random.default_rng(42)
        draws: dict[str, list[float]] = {"ap": [], "recall_at_v6_recipe_precision": []}
        for _ in range(v7.DRAWS):
            m = np.bincount(rng.integers(0, n_groups, n_groups), minlength=n_groups)[group] * w
            keep = m > 0
            yy, mm = y[keep], m[keep]
            if yy.sum() == 0:
                continue
            draws["ap"].append(
                average_precision_score(yy, p[keep], sample_weight=mm)
                - average_precision_score(yy, ref_p[keep], sample_weight=mm)
            )
            floor, _ = v7.at_threshold(yy, ref_p[keep], mm, ref_t)
            draws["recall_at_v6_recipe_precision"].append(
                v7.recall_at(yy, p[keep], mm, floor) - v7.recall_at(yy, ref_p[keep], mm, floor)
            )
        result[str(origin)] = {
            "draws": len(draws["ap"]),
            **{
                k: [float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))]
                for k, v in draws.items()
            },
            "share_ap_higher": float(np.mean(np.array(draws["ap"]) > 0)),
        }
        dump_json(out, result)
        v7.log(f"bootstrap v7 {origin} {result[str(origin)]}")


if __name__ == "__main__":
    main()
