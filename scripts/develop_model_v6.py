"""Model v6 development: new cell-level fire history, fire climatology and fire weather.

Development uses only 2015–2022. Commands run in order:
  protocol  - write and hash the pre-declared plan before any experiment
  features  - build the new features for train 2015–2021 and evaluation 2020–2022 tables
  evaluate  - rolling-origin comparison of fixed candidates against the references
The final 2026 test is a separate step that requires the frozen release this plan defines.
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
from scipy.ndimage import maximum_filter
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from wildfire_kz import model_upgrade as mu  # noqa: E402
from wildfire_kz.data import checksum, dump_json  # noqa: E402
from wildfire_kz.data.public_study import FEATURES  # noqa: E402
from wildfire_kz.fire_weather import NAMES as FIREWX_NAMES  # noqa: E402
from wildfire_kz.fire_weather import FireWeather  # noqa: E402

RUN = ROOT / "runs/model_v6"
OLD = ROOT / "runs/public_hindcast"
V5 = ROOT / "runs/model_stack_v5"
WEATHER = ROOT / "data/real/public_predictors/weather"
TRAIN_YEARS = list(range(2015, 2022))
VALIDATION_YEARS = [2020, 2021, 2022]
CELL = [
    "cell_fire_30d",
    "cell_fire_365d",
    "cell_days_since_fire",
    "cell_month_climatology",
    "nbr15_month_climatology",
]
FIREWX = [f"fw_{n}" for n in FIREWX_NAMES]
CANDIDATES = {
    "R0_base": FEATURES,
    "R1_history": FEATURES + mu.HISTORY,
    "R2_cell": FEATURES + mu.HISTORY + CELL,
    "R3_cell_weather": FEATURES + mu.HISTORY + CELL + FIREWX,
    "R4_weather": FEATURES + mu.HISTORY + FIREWX,
}
# The original release's tuned XGBoost settings, kept fixed so candidates differ only in inputs.
PARAMS = {
    "learning_rate": 0.06252287916406217,
    "max_depth": 5,
    "min_child_weight": 6.440260565429631,
    "n_estimators": 314,
    "reg_alpha": 0.006789053271698486,
    "reg_lambda": 0.14742753159914673,
}
TOPK = {"top_0.1pct": 0.001, "top_1pct": 0.01}


def log(message: str) -> None:
    print(datetime.now(UTC).isoformat(), message, flush=True)


def guard(years) -> None:
    if max(years) > 2022:
        raise PermissionError(
            "Development is restricted to 2015–2022; 2023+ needs the frozen v6 release"
        )


def protocol() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    path = RUN / "protocol.json"
    if path.exists():
        raise FileExistsError("The v6 protocol is already registered and immutable")
    dump_json(
        path,
        {
            "synthetic": False,
            "registered_utc": datetime.now(UTC).isoformat(),
            "purpose": "Improve next-day new-fire ranking with cell-level fire history, multi-year fire climatology and Canadian FWI codes",
            "development_years": [2015, 2022],
            "years_never_used_for_development": [2023, 2024, 2025, 2026],
            "previous_tests_already_used": {
                "2023-2024": "reassessment benchmark",
                "2025": "independent test, used 2026-10-25",
            },
            "new_features": {
                "cell_history": "active cell-days in the same 5 km cell, windows ending at target minus 2 days: 30 d, 365 d, days since last active (capped 3650)",
                "climatology": "share of complete prior years since 2014 with activity in the same calendar month: same cell, and any cell in the 15 km square",
                "fire_weather": "Van Wagner FFMC, DMC, DC, ISI, BUI, FWI, dry days (<1 mm), 30 and 60 day precipitation; state through target minus 7 days, the same lag as existing weather features",
            },
            "candidates": {k: len(v) for k, v in CANDIDATES.items()},
            "model": {
                "type": "XGBoost hist, NaN native, design weights",
                "params": PARAMS,
                "seed": 42,
            },
            "rolling_validation": {
                str(
                    v
                ): f"train {TRAIN_YEARS[0]}-{v - 1} train tables, evaluate {v} evaluation table"
                for v in VALIDATION_YEARS
            },
            "references": {
                "2020": "original XGBoost out-of-fold",
                "2021": "original XGBoost out-of-fold",
                "2022": "current release v5 (base and meta trained before 2022)",
            },
            "metrics": [
                "weighted average precision",
                "weighted ROC-AUC",
                "estimated daily capture in top 0.1% and 1% of cells",
            ],
            "selection_rule": "A candidate qualifies only if, in each of 2020, 2021 and 2022, its AP exceeds the reference AP and its top-1% capture is at least the reference's. The qualifier with the highest mean AP is selected. If none qualifies, no new model is released.",
            "release_rule": "Selected features: XGBoost refit on 2015–2021 train tables, sigmoid calibration on 2022 excluding industrial cells, threshold = maximum 2022 recall at precision not below the current release's 2022 calibration precision; float16 transport; artifacts hashed before any 2026 label is read.",
            "final_test": "2026 from 1 January to the last date with complete predictors and labels, fixed at freeze; labels from FIRMS SNPP (standard processing where published, otherwise NRT, declared before access); all positive cell-days and sampled negatives with known probabilities; v6 versus v5 on the same rows: precision and recall at frozen thresholds, AP, daily top-1% capture, 1000 paired 100 km x 30 day block bootstrap draws.",
        },
    )
    dump_json(RUN / "protocol.sha256.json", {"sha256": checksum(path)})
    log(f"protocol registered {checksum(path)}")


def tables() -> dict[str, pd.DataFrame]:
    names = [f"{y}_train" for y in TRAIN_YEARS] + [f"{y}_evaluation" for y in VALIDATION_YEARS]
    guard([int(n[:4]) for n in names])
    return {n: pd.read_parquet(OLD / f"features/{n}.parquet") for n in names}


def grid():
    g = pd.read_parquet(ROOT / "data/real/normalized/grid_5km.parquet", columns=["cell_id"])
    parts = g.cell_id.str.split("_", expand=True)
    rows, cols = parts[1].astype(int).to_numpy(), parts[2].astype(int).to_numpy()
    return (
        g.cell_id,
        rows - rows.min(),
        cols - cols.min(),
        (rows.max() - rows.min() + 1, cols.max() - cols.min() + 1),
    )


def build_features() -> None:
    if not (RUN / "protocol.json").is_file():
        raise PermissionError("Register the protocol first")
    frames = tables()
    keys = pd.concat(
        [
            f[["cell_index", "cell_id", "day"]].assign(table=n, row=np.arange(len(f)))
            for n, f in frames.items()
        ],
        ignore_index=True,
    )
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    keys["day_no"] = (keys.day - epoch).dt.days.astype(np.int64)
    n_cells = 110129
    cell_ids, gr, gc, shape = grid()
    index = pd.Series(np.arange(n_cells), index=cell_ids)

    history = mu.load_history(2022)
    history["cell"] = history.cell_id.map(index)
    history = history.dropna(subset=["cell"])
    history["day_no"] = (history.day - epoch).dt.days.astype(np.int64)
    active = {int(d): g.cell.to_numpy(dtype=np.int64) for d, g in history.groupby("day_no")}

    # Climatology: activity per (year, month), as a cell vector and its 15 km neighbourhood maximum.
    years = range(2014, 2023)
    month_cell = {}
    for y in years:
        for m in range(1, 13):
            sel = history[(history.day.dt.year == y) & (history.day.dt.month == m)].cell.to_numpy(
                dtype=np.int64
            )
            v = np.zeros(n_cells, dtype=np.float32)
            v[np.unique(sel)] = 1
            img = np.zeros(shape, dtype=np.float32)
            img[gr, gc] = v
            month_cell[(y, m)] = (v, maximum_filter(img, size=3, mode="constant")[gr, gc])
    out = {c: np.full(len(keys), np.nan, dtype=np.float32) for c in CELL + FIREWX}
    target_year, target_month = keys.day.dt.year.to_numpy(), keys.day.dt.month.to_numpy()
    for (y, m), idx in (
        pd.Series(np.arange(len(keys))).groupby([target_year, target_month]).groups.items()
    ):
        prior = [p for p in years if p < y]
        ci = keys.cell_index.to_numpy()[idx]
        out["cell_month_climatology"][idx] = np.mean(
            [month_cell[(p, m)][0][ci] for p in prior], axis=0
        )
        out["nbr15_month_climatology"][idx] = np.mean(
            [month_cell[(p, m)][1][ci] for p in prior], axis=0
        )

    by_fire_day = keys.groupby(keys.day_no - 2).indices
    by_weather_day = keys.groupby(keys.day_no - 7).indices
    first, last = (
        int(pd.Timestamp("2014-01-01").value // 86_400_000_000_000),
        int(keys.day_no.max()),
    )
    last_active = np.full(n_cells, -(10**6), dtype=np.int64)
    c30 = np.zeros(n_cells, dtype=np.int32)
    c365 = np.zeros(n_cells, dtype=np.int32)
    fw, wx, wx_year = None, None, None
    for d in range(first, last + 1):
        date = pd.Timestamp(d * 86_400_000_000_000)
        if date.year != wx_year:
            with np.load(WEATHER / f"{date.year}.npz") as z:
                wx = {k: z[k].copy() for k in ["tmax", "rh", "wind", "precip"]}
                ny, nx = z["native_cell_y"].copy(), z["native_cell_x"].copy()
                wx_first = pd.Timestamp(str(z["first_day"]))
            wx_year = date.year
        # Weather starts 2014-11-01, so the fire weather codes spin up from there.
        offset = (date - wx_first).days
        if 0 <= offset < wx["tmax"].shape[2]:
            if fw is None:
                fw = FireWeather(wx["tmax"].shape[:2])
            fw.step(
                wx["tmax"][:, :, offset],
                wx["rh"][:, :, offset],
                wx["wind"][:, :, offset],
                wx["precip"][:, :, offset],
                date.month,
            )
        if d in by_weather_day and fw is not None:
            idx = by_weather_day[d]
            ci = keys.cell_index.to_numpy()[idx]
            for name, grid_values in fw.state().items():
                out[f"fw_{name}"][idx] = grid_values[ny[ci], nx[ci]]
        today = active.get(d, np.empty(0, dtype=np.int64))
        c30[today] += 1
        c365[today] += 1
        c30[active.get(d - 30, np.empty(0, dtype=np.int64))] -= 1
        c365[active.get(d - 365, np.empty(0, dtype=np.int64))] -= 1
        last_active[today] = d
        if d in by_fire_day:
            idx = by_fire_day[d]
            ci = keys.cell_index.to_numpy()[idx]
            target = keys.day_no.to_numpy()[idx]
            out["cell_fire_30d"][idx] = np.log1p(c30[ci])
            out["cell_fire_365d"][idx] = np.log1p(c365[ci])
            out["cell_days_since_fire"][idx] = np.minimum(target - last_active[ci], 3650)
        if date.day == 1 and date.month == 1:
            log(f"features through {date.date()}")

    # The release's own 6 neighbourhood history features, built exactly as v5 built them.
    hist = mu.FireHistory(mu.load_history(2022))
    for name in mu.HISTORY:
        out[name] = np.zeros(len(keys), dtype=np.float32)
    for day, idx in keys.groupby("day", sort=True).indices.items():
        for name, values in hist.get(day, keys.cell_id.iloc[idx]).items():
            out[name][idx] = values

    RUN.joinpath("features").mkdir(parents=True, exist_ok=True)
    for name in frames:
        sel = (keys.table == name).to_numpy()
        frame = pd.DataFrame({c: v[sel] for c, v in out.items()})
        frame.insert(0, "day", keys.day[sel].to_numpy())
        frame.insert(0, "cell_index", keys.cell_index[sel].to_numpy())
        path = RUN / f"features/{name}.parquet"
        frame.to_parquet(path, index=False)
        dump_json(
            path.with_suffix(".sha256.json"),
            {
                "sha256": checksum(path),
                "base_table_sha256": checksum(OLD / f"features/{name}.parquet"),
            },
        )
    log("features written")


def load(name: str) -> pd.DataFrame:
    base = pd.read_parquet(OLD / f"features/{name}.parquet")
    extra = pd.read_parquet(RUN / f"features/{name}.parquet")
    if not (base.cell_index.to_numpy() == extra.cell_index.to_numpy()).all():
        raise ValueError(f"Row order differs for {name}")
    return pd.concat([base, extra.drop(columns=["cell_index", "day"])], axis=1)


def capture(frame: pd.DataFrame, score: np.ndarray) -> dict[str, float]:
    """Estimated share of positives inside each day's top k% of eligible cells (design-weighted)."""
    result = {}
    f = frame[["day", "label", "weight"]].assign(score=score)
    for name, share in TOPK.items():
        hit = 0.0
        for _, g in f.groupby("day"):
            g = g.sort_values("score", ascending=False)
            budget = share * g.weight.sum()
            inside = g.weight.cumsum().to_numpy() <= budget
            hit += g.label.to_numpy()[inside].sum()
        result[name] = float(hit / f.label.sum())
    return result


def score_metrics(frame: pd.DataFrame, score: np.ndarray) -> dict[str, float]:
    y, w = frame.label.to_numpy(), frame.weight.to_numpy()
    return {
        "ap": float(average_precision_score(y, score, sample_weight=w)),
        "roc_auc": float(roc_auc_score(y, score, sample_weight=w)),
        **capture(frame, score),
    }


def evaluate() -> None:
    proof = json.loads((RUN / "protocol.sha256.json").read_text())
    if checksum(RUN / "protocol.json") != proof["sha256"]:
        raise PermissionError("Protocol changed after registration")
    industrial = set(json.loads((OLD / "industrial_cells.json").read_text())["cell_ids"])
    rows = []
    for v in VALIDATION_YEARS:
        guard([v])
        train = pd.concat([load(f"{y}_train") for y in TRAIN_YEARS if y < v], ignore_index=True)
        valid = load(f"{v}_evaluation")
        valid = valid.loc[~valid.cell_id.isin(industrial)].reset_index(drop=True)
        if v < 2022:
            ref = pd.read_parquet(OLD / f"validation/xgboost_{v}.parquet")
            valid = valid.merge(
                ref[["cell_id", "day", "probability"]],
                on=["cell_id", "day"],
                how="inner",
                validate="one_to_one",
            )
            reference, ref_name = valid.probability.to_numpy(), "original_xgboost_oof"
        else:
            model = joblib.load(V5 / "model.joblib")
            reference, ref_name = (
                model["estimator"].predict_proba(valid[model["features"]])[:, 1],
                "release_v5",
            )
        rows.append(
            {
                "year": v,
                "model": ref_name,
                "rows": len(valid),
                "positives": int(valid.label.sum()),
                **score_metrics(valid, reference),
            }
        )
        log(f"{v} {ref_name} {rows[-1]}")
        for name, features in CANDIDATES.items():
            clf = XGBClassifier(
                **PARAMS, objective="binary:logistic", tree_method="hist", random_state=42, n_jobs=8
            )
            clf.fit(train[features], train.label, sample_weight=train.weight.to_numpy())
            p = clf.predict_proba(valid[features])[:, 1]
            rows.append(
                {
                    "year": v,
                    "model": name,
                    "rows": len(valid),
                    "positives": int(valid.label.sum()),
                    **score_metrics(valid, p),
                }
            )
            log(f"{v} {name} {rows[-1]}")
    table = pd.DataFrame(rows)
    table.to_csv(RUN / "development_comparison.csv", index=False)
    qualified = []
    for name in CANDIDATES:
        ok = True
        for v in VALIDATION_YEARS:
            c = table[(table.year == v) & (table.model == name)].iloc[0]
            r = table[
                (table.year == v) & table.model.isin(["original_xgboost_oof", "release_v5"])
            ].iloc[0]
            ok &= bool(c.ap > r.ap and c.top_1pct >= r.top_1pct)
        if ok:
            qualified.append((table[table.model == name].ap.mean(), name))
    selection = {
        "qualified": [n for _, n in sorted(qualified, reverse=True)],
        "selected": max(qualified)[1] if qualified else None,
        "rule": json.loads((RUN / "protocol.json").read_text())["selection_rule"],
        "test_years_accessed": False,
    }
    dump_json(RUN / "development_selection.json", selection)
    log(f"selection {selection}")


def freeze() -> None:
    """Release rule from the protocol: refit 2015–2021, calibrate and set the threshold on 2022."""
    from wildfire_kz.calibration import fit_sigmoid

    if (RUN / "release.json").exists():
        raise FileExistsError("The v6 release is frozen and immutable")
    selection = json.loads((RUN / "development_selection.json").read_text())
    name = selection["selected"]
    if not name:
        raise ValueError("No candidate qualified; the protocol forbids a release")
    features = CANDIDATES[name]
    train = pd.concat([load(f"{y}_train") for y in TRAIN_YEARS], ignore_index=True)
    clf = XGBClassifier(
        **PARAMS, objective="binary:logistic", tree_method="hist", random_state=42, n_jobs=8
    )
    clf.fit(train[features], train.label, sample_weight=train.weight.to_numpy())
    joblib.dump(
        {"estimator": clf, "features": features, "candidate": name},
        RUN / "model.joblib",
        compress=3,
    )

    industrial = set(json.loads((OLD / "industrial_cells.json").read_text())["cell_ids"])
    cal = load("2022_evaluation")
    cal = cal.loc[~cal.cell_id.isin(industrial)].reset_index(drop=True)
    raw = clf.predict_proba(cal[features])[:, 1]
    calibration, _ = fit_sigmoid(cal, raw, 2022)
    joblib.dump(calibration, RUN / "calibrator.joblib", compress=3)
    p = mu.published_probability(calibration.predict(raw))
    floor = json.loads((V5 / "frozen.json").read_text())["calibration_metrics"]["precision"]
    point = mu.operating_point(cal.label.to_numpy(), p, cal.weight.to_numpy(), floor)
    if (
        point["recall"]
        <= json.loads((V5 / "frozen.json").read_text())["calibration_metrics"]["recall"]
    ):
        raise ValueError("2022 recall at the v5 precision floor did not improve; no release")
    dump_json(
        RUN / "frozen.json",
        {
            "synthetic": False,
            "model": f"xgboost_v6_{name}",
            "features": features,
            "threshold": point["threshold"],
            "calibration_metrics": point,
            "precision_floor": floor,
            "v5_2022_operating_point": json.loads((V5 / "frozen.json").read_text())[
                "calibration_metrics"
            ],
            "calibration_year": 2022,
            "selection_max_year": 2022,
            "test_used_for_selection": False,
            "operational_validation": False,
            "transport": "float16 before metrics",
        },
    )
    dump_json(
        RUN / "training.json",
        {
            "synthetic": False,
            "training_years": [TRAIN_YEARS[0], TRAIN_YEARS[-1]],
            "rows": len(train),
            "positives": int(train.label.sum()),
            "params": PARAMS,
            "candidate": name,
        },
    )
    artifacts = [
        "model.joblib",
        "calibrator.joblib",
        "frozen.json",
        "training.json",
        "protocol.json",
        "development_comparison.csv",
        "development_selection.json",
    ]
    dump_json(
        RUN / "release.json",
        {
            "synthetic": False,
            "selection_max_year": 2022,
            "frozen_utc": datetime.now(UTC).isoformat(),
            "labels_after_2022_accessed": False,
            "artifacts": {a: checksum(RUN / a) for a in artifacts},
            "code": {
                str(Path(f).relative_to(ROOT)): checksum(Path(f))
                for f in [__file__, ROOT / "src/wildfire_kz/fire_weather.py", Path(mu.__file__)]
            },
        },
    )
    log(
        f"frozen {name}: threshold {point['threshold']:.6f}, 2022 precision {point['precision']:.4f}, recall {point['recall']:.4f}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["protocol", "features", "evaluate", "freeze"])
    command = parser.parse_args().command
    {"protocol": protocol, "features": build_features, "evaluate": evaluate, "freeze": freeze}[
        command
    ]()
