"""Pre-2023 model training, frozen release, then one benchmark reassessment."""

from __future__ import annotations

import argparse
import gc
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from wildfire_kz import model_upgrade as mu
from wildfire_kz.calibration import fit_sigmoid, map_boundaries
from wildfire_kz.data import checksum, dump_json
from wildfire_kz.evaluation import cluster_draws, metrics

RUN, OLD = mu.RUN, mu.OLD
CANDIDATES = [
    {
        "name": "causal_history",
        "features": mu.FEATURES + mu.HISTORY,
        "depth": 5,
        "positive_weight": 1,
    },
    {
        "name": "causal_spatial_history",
        "features": mu.ALL_FEATURES,
        "depth": 5,
        "positive_weight": 1,
    },
]


def log(message: str) -> None:
    print(datetime.now(UTC).isoformat(), message, flush=True)


def prepare() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    plan = RUN / "plan.json"
    if not plan.exists():
        dump_json(
            plan,
            {
                "synthetic": False,
                "created_utc": datetime.now(UTC).isoformat(),
                "selection_max_year": 2022,
                "train_years": list(range(2015, 2021)),
                "validation_year": 2021,
                "final_refit_years": list(range(2015, 2022)),
                "calibration_year": 2022,
                "candidate_budget": len(CANDIDATES),
                "candidates": CANDIDATES,
                "precision_floor": mu.PRECISION_FLOOR,
                "objective": "maximum validation recall at design-weighted precision >=0.10; AP breaks ties",
                "threshold_rule": "maximum 2022 weighted recall with precision >=0.10",
                "history_lag_days": 2,
                "history_windows": mu.FIRE_WINDOWS,
                "transport": "float16 rounded before threshold selection, evaluation and map export",
                "test_previously_reported": True,
                "test_used_for_selection": False,
            },
        )
    history = mu.FireHistory(mu.load_history(2022))
    directory = RUN / "features"
    directory.mkdir(exist_ok=True)
    for year in range(2015, 2023):
        paths = [
            p
            for p in [
                OLD / f"features/{year}_train.parquet",
                OLD / f"features/{year}_evaluation.parquet",
            ]
            if p.exists()
        ]
        if all((directory / p.name).exists() for p in paths):
            continue
        pieces = []
        sources = {}
        for p in paths:
            proof = json.loads(p.with_suffix(".sha256.json").read_text())
            if checksum(p) != proof["sha256"]:
                raise ValueError(f"Original table changed: {p.name}")
            f = pd.read_parquet(p)
            if not f.day.dt.year.eq(year).all() or year >= 2023:
                raise PermissionError("Only pre-2023 training/calibration inputs allowed")
            sources[p.name] = checksum(p)
            pieces.append(f.assign(_table=p.name))
        augmented = mu.augment(pd.concat(pieces, ignore_index=True), history)
        for name, g in augmented.groupby("_table", sort=False):
            g.drop(columns="_table").to_parquet(directory / name, index=False)
            dump_json(
                (directory / name).with_suffix(".json"),
                {
                    "synthetic": False,
                    "original_sha256": sources[name],
                    "sha256": checksum(directory / name),
                    "feature_code_sha256": checksum(Path(mu.__file__)),
                    "rows": len(g),
                },
            )
        log(f"prepared {year}: {len(augmented):,} actual rows, {len(mu.ALL_FEATURES)} features")
        del pieces, augmented
        gc.collect()


def load(years: list[int], training: bool, mask_year: int = 2021) -> pd.DataFrame:
    if max(years) > 2022:
        raise PermissionError("Development loader refuses 2023/2024")
    columns = mu.ALL_FEATURES + ["day", "label", "weight", "cell_id"]
    result = []
    for year in years:
        p = RUN / f"features/{year}_{'train' if training else 'evaluation'}.parquet"
        proof = json.loads(p.with_suffix(".json").read_text())
        if (
            checksum(p) != proof["sha256"]
            or checksum(Path(mu.__file__)) != proof["feature_code_sha256"]
        ):
            raise ValueError("Prepared development table changed")
        result.append(pd.read_parquet(p, columns=columns))
    f = pd.concat(result, ignore_index=True)
    mask = OLD / (
        "industrial_cells.json" if mask_year == 2021 else f"industrial_cells_{mask_year}.json"
    )
    industrial = json.loads(mask.read_text())["cell_ids"]
    f = f.loc[~f.cell_id.isin(industrial)].reset_index(drop=True)
    f["cell_id"] = f.cell_id.astype("category")
    return f


def estimator(spec: dict, iterations: int = 800, early: bool = False) -> XGBClassifier:
    return XGBClassifier(
        n_estimators=iterations,
        max_depth=spec["depth"],
        learning_rate=0.045,
        min_child_weight=20,
        reg_lambda=10,
        reg_alpha=1,
        subsample=0.9,
        colsample_bytree=0.9,
        scale_pos_weight=spec["positive_weight"],
        objective="binary:logistic",
        eval_metric="aucpr",
        tree_method="hist",
        max_bin=128,
        n_jobs=4,
        random_state=42,
        **({"early_stopping_rounds": 60} if early else {}),
    )


def train() -> None:
    from wildfire_kz.config import load_config
    from wildfire_kz.models import fit_model

    if (RUN / "release.json").exists():
        raise PermissionError("Frozen training is immutable")
    cfg = load_config(mu.ROOT / "configs/real_public.yaml")
    cfg.models.threads = 4
    params = json.loads((OLD / "tuning.json").read_text())["xgboost"]["selected"]
    training = load(list(range(2015, 2021)), True, 2020)
    valid = load([2021], False, 2020)
    old = pd.read_parquet(OLD / "validation/xgboost_2021.parquet")
    if (
        not old[["cell_id", "day"]]
        .astype({"cell_id": "string"})
        .equals(valid[["cell_id", "day"]].astype({"cell_id": "string"}))
    ):
        raise ValueError("Validation keys differ")
    records = [
        {
            "name": "original_xgboost",
            **mu.operating_point(
                old.label.to_numpy(), old.probability.to_numpy(), old.weight.to_numpy()
            ),
        }
    ]
    for spec in CANDIDATES:
        started = time.perf_counter()
        model = fit_model("xgboost", training, spec["features"], cfg, params, sampled=True)
        p = model.predict(valid)
        pd.DataFrame({"probability": p}).to_parquet(
            RUN / f"validation_{spec['name']}.parquet", index=False
        )
        for weight in [1.0, 0.75, 0.5, 0.25]:
            blended = weight * p + (1 - weight) * old.probability.to_numpy()
            point = mu.operating_point(valid.label.to_numpy(), blended, valid.weight.to_numpy())
            record = {
                **spec,
                "name": spec["name"] + f"_w{weight}",
                "base_candidate": spec["name"],
                "new_weight": weight,
                **point,
                "iterations": params["n_estimators"],
                "seconds": time.perf_counter() - started,
            }
            records.append(record)
            log(
                f"{record['name']}: AP={point['average_precision']:.5f}, recall@P10={point['recall']:.3%}"
            )
        del model
        gc.collect()
    pd.DataFrame([{k: v for k, v in r.items() if k != "features"} for r in records]).to_csv(
        RUN / "comparison.csv", index=False
    )
    winner = max(records[1:], key=lambda r: (r["recall"], r["average_precision"]))
    dump_json(
        RUN / "selection.json",
        {
            "selected": winner,
            "baseline": records[0],
            "selection_max_year": 2021,
            "test_accessed": False,
            "objective": "recall at precision >=0.10, then AP",
            "model_fits": 2,
            "cheap_blend_weights": [1.0, 0.75, 0.5, 0.25],
        },
    )
    if winner["recall"] <= records[0]["recall"]:
        raise ValueError("No candidate improved development recall; no release is permitted")
    del training, valid
    gc.collect()
    final = load(list(range(2015, 2022)), True)
    fitted = fit_model("xgboost", final, winner["features"], cfg, params, sampled=True)
    components = [(fitted, winner["new_weight"])]
    if winner["new_weight"] < 1:
        components.append((joblib.load(OLD / "models.joblib")["xgboost"], 1 - winner["new_weight"]))
    model = mu.ModelBlend(components)
    joblib.dump(
        {"estimator": model, "features": winner["features"], "spec": winner},
        RUN / "model.joblib",
        compress=3,
    )
    dump_json(
        RUN / "training.json",
        {
            "synthetic": False,
            "training_end": 2021,
            "rows": len(final),
            "positives": int(final.label.sum()),
            "model_sha256": checksum(RUN / "model.joblib"),
            "parameters": params,
            "preprocessing": "fold-local median imputation and standard scaling; same as original baseline",
        },
    )
    log(f"final refit complete: {winner['name']}, {len(final):,} rows")


def freeze() -> None:
    if (RUN / "release.json").exists():
        mu.verify_release(RUN / "release.json")
        return
    selected = joblib.load(RUN / "model.joblib")
    f = load([2022], False)
    raw = selected["estimator"].predict_proba(f[selected["features"]])[:, 1]
    calibration, _ = fit_sigmoid(f, raw, 2022)
    p = mu.published_probability(calibration.predict(raw))
    point = mu.operating_point(f.label.to_numpy(), p, f.weight.to_numpy())
    joblib.dump(calibration, RUN / "calibrator.joblib", compress=3)
    dump_json(
        RUN / "frozen.json",
        {
            "synthetic": False,
            "model": "xgboost_spatiotemporal",
            "features": selected["features"],
            "threshold": point["threshold"],
            "calibration_metrics": point,
            "calibration_year": 2022,
            "boundaries": map_boundaries(p, [0.5, 0.8, 0.95], f.weight.to_numpy()),
            "precision_floor": mu.PRECISION_FLOOR,
            "selection_max_year": 2022,
            "test_used_for_selection": False,
            "operational_validation": False,
        },
    )
    files = [
        "model.joblib",
        "calibrator.joblib",
        "frozen.json",
        "selection.json",
        "training.json",
        "plan.json",
        "comparison.csv",
    ]
    dump_json(
        RUN / "release.json",
        {
            "synthetic": False,
            "selection_max_year": 2022,
            "frozen_utc": datetime.now(UTC).isoformat(),
            "test_previously_reported": True,
            "artifacts": {n: checksum(RUN / n) for n in files},
            "feature_code_sha256": checksum(Path(mu.__file__)),
            "runner_code_sha256": checksum(Path(__file__)),
            "training_table_hashes": {
                p.name: checksum(p) for p in (RUN / "features").glob("*.parquet")
            },
        },
    )
    log(
        f"new model frozen: 2022 precision={point['precision']:.2%}, recall={point['recall']:.2%}, AP={point['average_precision']:.5f}"
    )


def evaluate() -> None:
    release = RUN / "release.json"
    record = mu.verify_release(release)
    if checksum(Path(__file__)) != record["runner_code_sha256"]:
        raise PermissionError("Evaluation runner changed after freeze")
    if (RUN / "evaluation.json").exists():
        raise FileExistsError("Preserve completed one-shot reassessment")
    history = mu.FireHistory(mu.load_history(2024, release))
    selected = joblib.load(RUN / "model.joblib")
    calibrator = joblib.load(RUN / "calibrator.joblib")
    frozen = json.loads((RUN / "frozen.json").read_text())
    pieces = []
    for year in [2023, 2024]:
        f = pd.read_parquet(OLD / f"features/{year}_evaluation.parquet")
        f = mu.augment(f, history, release)
        industrial = json.loads((OLD / "industrial_cells.json").read_text())["cell_ids"]
        f = f.loc[~f.cell_id.isin(industrial)].reset_index(drop=True)
        p = mu.published_probability(
            calibrator.predict(selected["estimator"].predict_proba(f[selected["features"]])[:, 1])
        )
        columns = ["cell_id", "day", "label", "weight", "x", "y_coord", "area_km2", "landcover"]
        pieces.append(f[columns].assign(probability=p))
        log(f"post-freeze benchmark inference {year}: {len(f):,} rows")
    f = pd.concat(pieces, ignore_index=True)
    f.to_parquet(RUN / "predictions.parquet", index=False)
    old = pd.read_parquet(OLD / "evaluate/predictions_xgboost.parquet")
    if not old[["cell_id", "day"]].equals(f[["cell_id", "day"]]):
        raise ValueError("Benchmark keys differ from original experiment")
    reference = pd.read_parquet(
        OLD / "evaluate/predictions_seasonal.parquet"
    ).probability.to_numpy()
    old_threshold = json.loads((OLD / "frozen.json").read_text())["thresholds"]["xgboost"]
    rows = []
    for name, p, t in [
        ("xgboost_original", old.probability.to_numpy(), old_threshold),
        ("xgboost_spatiotemporal", f.probability.to_numpy(), frozen["threshold"]),
    ]:
        for period in ["2023–2024", "2023", "2024"]:
            mask = (
                np.ones(len(f), bool) if "–" in period else f.day.dt.year.eq(int(period)).to_numpy()
            )
            rows.append(
                {
                    "model": name,
                    "period": period,
                    "threshold": t,
                    **metrics(
                        f.label.to_numpy()[mask],
                        p[mask],
                        f.weight.to_numpy()[mask],
                        t,
                        reference[mask],
                    ),
                }
            )
    pd.DataFrame(rows).to_csv(RUN / "metrics.csv", index=False)
    draws = cluster_draws(f, 1000, 100000, 30, 42)

    def aggregate(a):
        return np.bincount(draws.codes, weights=a, minlength=draws.multiplicities.shape[1])

    w, y = f.weight.to_numpy(), f.label.to_numpy()
    positive = draws.multiplicities @ aggregate(w * y)
    estimates = {}
    intervals = []
    for name, p, t in [
        ("original", old.probability.to_numpy(), old_threshold),
        ("new", f.probability.to_numpy(), frozen["threshold"]),
    ]:
        alert = p >= t
        tp = draws.multiplicities @ aggregate(w * y * alert)
        mass = draws.multiplicities @ aggregate(w * alert)
        precision = np.divide(tp, mass, out=np.zeros_like(tp), where=mass > 0)
        recall = tp / positive
        estimates[name] = {"precision": precision, "recall": recall}
    for name in ["original", "new", "new minus original"]:
        for metric in ["precision", "recall"]:
            v = (
                estimates[name][metric]
                if name in estimates
                else estimates["new"][metric] - estimates["original"][metric]
            )
            intervals.append(
                {
                    "model": name,
                    "metric": metric,
                    "lower": float(np.quantile(v, 0.025)),
                    "upper": float(np.quantile(v, 0.975)),
                    "resamples": 1000,
                }
            )
    pd.DataFrame(intervals).to_csv(RUN / "cluster_intervals.csv", index=False)
    dump_json(
        RUN / "evaluation.json",
        {
            "synthetic": False,
            "release_sha256": checksum(release),
            "completed_utc": datetime.now(UTC).isoformat(),
            "selection_max_year": 2022,
            "test_previously_reported": True,
            "model_frozen_before_reassessment": True,
            "rows": len(f),
            "positives": int(f.label.sum()),
            "metrics": rows,
            "outputs": {
                name: checksum(RUN / name)
                for name in ["predictions.parquet", "metrics.csv", "cluster_intervals.csv"]
            },
        },
    )
    log(json.dumps([r for r in rows if r["period"] == "2023–2024"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "train", "freeze", "evaluate"])
    args = parser.parse_args()
    {"prepare": prepare, "train": train, "freeze": freeze, "evaluate": evaluate}[args.phase]()
