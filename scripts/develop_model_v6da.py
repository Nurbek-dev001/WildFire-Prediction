"""v6da: the v6 recipe for a forecast issued the day before (day ahead).

v6 reads ERA5 for D-7, which the archive publishes only around the night before D; issued
during D-1 (from 12:00 UTC) the latest ERA5 day is D-8. v6da changes only that: the ten ERA5
predictors (daily values and the 7/14-day windows) end on D-8 instead of D-7. Features, rows,
hyperparameters, training years, calibration year and the threshold rule are v6's. v6's fire
history already ends on D-2, so it needs no change.

Commands:
  check     the lag-7 weather rebuilt here equals the v6 tables (the code reproduces v6)
  evaluate  v6's rolling validation (2020, 2021, 2022; fit on earlier years) for lag 7 and 8
  freeze    fit 2015-2021, sigmoid on 2022, v6's precision floor; writes runs/model_v6da
No test-year label is read: 2023 onward stays untouched, as in v6's protocol.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import develop_model_v6 as v6  # noqa: E402

from wildfire_kz import model_upgrade as mu  # noqa: E402
from wildfire_kz.data import checksum, dump_json  # noqa: E402
from wildfire_kz.data import public_study as study  # noqa: E402

RUN = ROOT / "runs/model_v6da"
LAG = 8
WEATHER_COLUMNS = study.WEATHER + [f"{v}_{w}d" for v in ["precip", "temperature"] for w in [7, 14]]


def log(message: str) -> None:
    print(f"{datetime.now(UTC).isoformat(timespec='seconds')} {message}", flush=True)


def meteorology(indices: np.ndarray, dates: pd.DatetimeIndex, lag: int) -> dict[str, np.ndarray]:
    """public_study.meteorology with the lag as a parameter (v6: 7, v6da: 8)."""
    source_days = dates - pd.Timedelta(days=lag)
    result = {n: np.full(len(indices), np.nan, dtype="float32") for n in WEATHER_COLUMNS}
    for year in sorted(set(source_days.year)):
        selected = np.flatnonzero(source_days.year == year)
        arrays, start, iy, ix = study.weather_arrays(int(year))
        ci = indices[selected]
        d = ((source_days[selected] - start).days).to_numpy()
        for name in study.WEATHER:
            result[name][selected] = arrays[name][iy[ci], ix[ci], d]
    for window in [7, 14]:
        for name in ["precip", "temperature"]:
            accumulator = np.zeros(len(indices), dtype="float32")
            missing = np.zeros(len(indices), dtype=bool)
            for k in range(window):
                lagged = source_days - pd.Timedelta(days=k)
                for year in sorted(set(lagged.year)):
                    selected = np.flatnonzero(lagged.year == year)
                    arrays, start, iy, ix = study.weather_arrays(int(year))
                    ci = indices[selected]
                    d = (lagged[selected] - start).days.to_numpy()
                    values = arrays[name][iy[ci], ix[ci], d]
                    accumulator[selected] += np.nan_to_num(values)
                    missing[selected] |= ~np.isfinite(values)
            if name == "temperature":
                accumulator /= window
            accumulator[missing] = np.nan
            result[f"{name}_{window}d"] = accumulator
    # As public_study.feature_frame stores it.
    result["soil_moisture"] = np.clip(result["soil_moisture"], 0, 1)
    return result


def table(name: str, lag: int) -> pd.DataFrame:
    """v6's table (base + cell features) with the ERA5 predictors at the given lag."""
    f = v6.load(name)
    if lag != 7:
        w = meteorology(f.cell_index.to_numpy(), pd.DatetimeIndex(f.day), lag)
        for c in WEATHER_COLUMNS:
            f[c] = w[c]
    return f


def features() -> list[str]:
    return json.loads((v6.RUN / "frozen.json").read_text())["features"]


def fit(train: pd.DataFrame, cols: list[str]) -> XGBClassifier:
    clf = XGBClassifier(
        **v6.PARAMS, objective="binary:logistic", tree_method="hist", random_state=42, n_jobs=8
    )
    clf.fit(train[cols], train.label, sample_weight=train.weight.to_numpy())
    return clf


def check() -> None:
    """Rebuilt lag-7 weather must equal the stored v6 values, row by row."""
    for name in ["2015_train", "2022_evaluation"]:
        f = v6.load(name)
        w = meteorology(f.cell_index.to_numpy(), pd.DatetimeIndex(f.day), 7)
        for c in WEATHER_COLUMNS:
            same = np.allclose(f[c].to_numpy(), w[c], equal_nan=True, atol=1e-5)
            if not same:
                raise ValueError(f"{name} {c}: rebuilt lag-7 weather differs from v6")
        log(f"{name}: lag-7 weather reproduces v6 ({len(f)} rows)")


def evaluate() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    industrial = set(json.loads((v6.OLD / "industrial_cells.json").read_text())["cell_ids"])
    cols, rows = features(), []
    for lag in (7, LAG):
        cache = {n: table(n, lag) for n in [f"{y}_train" for y in v6.TRAIN_YEARS]}
        for v in v6.VALIDATION_YEARS:
            train = pd.concat(
                [cache[f"{y}_train"] for y in v6.TRAIN_YEARS if y < v], ignore_index=True
            )
            valid = table(f"{v}_evaluation", lag)
            valid = valid.loc[~valid.cell_id.isin(industrial)].reset_index(drop=True)
            p = fit(train, cols).predict_proba(valid[cols])[:, 1]
            rows.append({"year": v, "era5_lag_days": lag, **v6.score_metrics(valid, p)})
            log(f"{v} lag {lag}: {rows[-1]}")
    out = pd.DataFrame(rows)
    out.to_csv(RUN / "lag_comparison.csv", index=False)
    log("\n" + out.to_string(index=False))


def freeze() -> None:
    from wildfire_kz.calibration import fit_sigmoid

    if (RUN / "release.json").exists():
        raise FileExistsError("The v6da release is frozen and immutable")
    cols = features()
    train = pd.concat([table(f"{y}_train", LAG) for y in v6.TRAIN_YEARS], ignore_index=True)
    clf = fit(train, cols)
    joblib.dump(
        {"estimator": clf, "features": cols, "candidate": "v6_recipe_era5_lag8"},
        RUN / "model.joblib",
        compress=3,
    )
    industrial = set(json.loads((v6.OLD / "industrial_cells.json").read_text())["cell_ids"])
    cal = table("2022_evaluation", LAG)
    cal = cal.loc[~cal.cell_id.isin(industrial)].reset_index(drop=True)
    raw = clf.predict_proba(cal[cols])[:, 1]
    calibration, _ = fit_sigmoid(cal, raw, 2022)
    joblib.dump(calibration, RUN / "calibrator.joblib", compress=3)
    p = mu.published_probability(calibration.predict(raw))
    v6_frozen = json.loads((v6.RUN / "frozen.json").read_text())
    floor = v6_frozen["precision_floor"]
    point = mu.operating_point(cal.label.to_numpy(), p, cal.weight.to_numpy(), floor)
    dump_json(
        RUN / "frozen.json",
        {
            "synthetic": False,
            "model": "xgboost_v6da",
            "features": cols,
            "era5_lag_days": LAG,
            "threshold": point["threshold"],
            "calibration_metrics": point,
            "precision_floor": floor,
            "v6_2022_operating_point": v6_frozen["calibration_metrics"],
            "calibration_year": 2022,
            "issue": "day ahead: from 12:00 UTC of D-1, ERA5 through D-8",
            "test_used_for_selection": False,
            "operational_validation": False,
            "transport": "float16 before metrics",
        },
    )
    dump_json(
        RUN / "training.json",
        {
            "synthetic": False,
            "training_years": [v6.TRAIN_YEARS[0], v6.TRAIN_YEARS[-1]],
            "rows": len(train),
            "positives": int(train.label.sum()),
            "params": v6.PARAMS,
        },
    )
    artifacts = [
        "model.joblib",
        "calibrator.joblib",
        "frozen.json",
        "training.json",
        "lag_comparison.csv",
    ]
    dump_json(
        RUN / "release.json",
        {
            "synthetic": False,
            "frozen_utc": datetime.now(UTC).isoformat(),
            "recipe": "v6 (runs/model_v6) with ERA5 predictors ending on D-8",
            "v6_release_sha256": checksum(v6.RUN / "release.json"),
            "artifacts": {a: checksum(RUN / a) for a in artifacts},
            "code": {str(Path(__file__).relative_to(ROOT)): checksum(Path(__file__))},
        },
    )
    log(f"v6da frozen: threshold {point['threshold']:.6f}, 2022 {point}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["check", "evaluate", "freeze"])
    {"check": check, "evaluate": evaluate, "freeze": freeze}[parser.parse_args().command]()
