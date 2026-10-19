"""Resumable model comparison for the separately documented public hindcast."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import joblib
import numpy as np
import optuna
import pandas as pd
from sklearn.metrics import average_precision_score

from wildfire_kz.calibration import fit_sigmoid, map_boundaries
from wildfire_kz.config import Config, load_config
from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import PUBLIC, ROOT, complete, log, permitted, reserve
from wildfire_kz.data.public_study import (
    FEATURES,
    RUN,
    WEATHER,
    industrial_cells,
    record_table,
    table,
)
from wildfire_kz.models import fit_model, fit_seasonal, suggest

NAMES = ["logistic", "random_forest", "xgboost", "catboost", "weather_logistic", "seasonal"]


def config(trials: int = 50) -> Config:
    cfg = load_config(ROOT / "configs/real_public.yaml")
    cfg.output_dir = RUN
    cfg.models.trials = trials
    cfg.models.threads = 4
    return cfg


def source_registry() -> dict[str, Any]:
    """Register verified sources actually used by training; never scan sealed CSVs."""
    records = []
    for path in sorted(PUBLIC.rglob("*.npz")):
        # An explicit list of development/calibration products, not any future cache.
        if path.parent.name.startswith("rows_"):
            continue
        relative = path.relative_to(PUBLIC).as_posix()
        if relative.startswith("weather/") and int(path.stem) > 2022:
            continue
        if relative.startswith("vegetation/") and path.stem[:4] > "2022":
            continue
        if relative.startswith("landcover/") and not path.name.startswith("annual_2014_2021"):
            continue
        if relative.startswith(("terrain/", "human/")) and path.name != "national.npz":
            continue
        if not complete(path):
            raise ValueError(f"Unverified predictor: {path}")
        records.append({"path": relative, "sha256": checksum(path), "bytes": path.stat().st_size})
    return {
        "synthetic": False,
        "variant": "public_reprocessed_hindcast",
        "sources": records,
        "geometry_sha256": {
            name: checksum(ROOT / f"data/real/normalized/{name}.parquet")
            for name in ["boundary", "regions", "grid_5km"]
        },
        "feature_tables": [
            {"path": str(p.relative_to(RUN)), "sha256": checksum(p)}
            for p in sorted((RUN / "features").glob("*.parquet"))
            if int(p.name[:4]) <= 2022
        ],
        "development_outcome_tables": [
            {"path": str(p.relative_to(RUN)), "sha256": checksum(p)}
            for p in sorted((RUN / "outcomes").glob("events_through_*.parquet"))
            if int(p.stem.rsplit("_", 1)[1]) <= 2022
        ],
        "method_sha256": checksum(ROOT / "docs/public-hindcast-method.md"),
        "code_sha256": {
            str(p.relative_to(ROOT)): checksum(p)
            for p in [
                ROOT / "src/wildfire_kz/data/public_study.py",
                ROOT / "src/wildfire_kz/data/public_predictors.py",
                ROOT / "src/wildfire_kz/public_experiment.py",
                ROOT / "src/wildfire_kz/models/__init__.py",
                ROOT / "src/wildfire_kz/calibration/__init__.py",
                ROOT / "src/wildfire_kz/events/__init__.py",
                ROOT / "src/wildfire_kz/data/range_cache.py",
            ]
        },
    }


def fit(
    name: str,
    train: pd.DataFrame,
    cfg: Config,
    params: dict[str, Any],
    valid: pd.DataFrame | None = None,
) -> Any:
    if name == "seasonal":
        return fit_seasonal(train, cfg.models.seasonal_smoothing)
    columns = (
        [f for f in FEATURES if f in WEATHER or f.startswith(("precip_", "temperature_"))]
        if name == "weather_logistic"
        else FEATURES
    )
    return fit_model(name, train, columns, cfg, params, valid, sampled=True)


def comparison(trials: int = 50) -> None:
    """Tuning sees development only; SQLite allows exact continuation after interruption."""
    if (RUN / "release.json").exists():
        raise PermissionError("A released experiment is immutable; use a new run for new tuning")
    cfg = config(trials)
    train = pd.concat(
        [pd.read_parquet(table(y, training=True)) for y in range(2015, 2022)], ignore_index=True
    )
    valid = {y: pd.read_parquet(table(y, training=False)) for y in [2019, 2020, 2021]}
    RUN.mkdir(exist_ok=True, parents=True)
    dump_json(RUN / "source_registry.json", source_registry())
    dump_json(
        RUN / "design.json",
        {
            "synthetic": False,
            "features": FEATURES,
            "development_years": list(range(2015, 2022)),
            "validation_years": [2019, 2020, 2021],
            "selection_metric": "mean rolling weighted average precision",
            "calibration_year": 2022,
            "test_years": [2023, 2024],
            "optuna_attempts_per_ensemble": trials,
            "pruner": "MedianPruner after first rolling fold, 5 startup trials",
            "primary_study_completed": False,
            "config": cfg.model_dump(mode="json"),
        },
    )
    years = train.day.dt.year.to_numpy()
    prepared = [
        (
            train.loc[(years < y) & ~train.cell_id.isin(industrial_cells(y - 1))],
            valid[y].loc[~valid[y].cell_id.isin(industrial_cells(y - 1))],
        )
        for y in [2019, 2020, 2021]
    ]
    tuning: dict[str, Any] = {}
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    for name in NAMES:
        if name in ["random_forest", "xgboost", "catboost"]:
            database = RUN / "tuning.sqlite3"
            study = optuna.create_study(
                study_name=name,
                storage="sqlite:///" + database.as_posix(),
                load_if_exists=True,
                direction="maximize",
                sampler=optuna.samplers.TPESampler(seed=42),
                pruner=optuna.pruners.MedianPruner(n_startup_trials=5),
            )

            def objective(trial: optuna.Trial, name: str = name) -> float:
                started = time.perf_counter()
                params = suggest(trial, name, cfg)
                scores, lengths, iterations = [], [], []
                for fold, (training, validation) in enumerate(prepared):
                    model = fit(name, training, cfg, params, validation)
                    scores.append(
                        float(
                            average_precision_score(
                                validation.label,
                                model.predict(validation),
                                sample_weight=validation.weight,
                            )
                        )
                    )
                    lengths.append(float(validation.weight.sum()))
                    estimator = model.pipeline.named_steps["estimator"]
                    if name == "xgboost":
                        iterations.append(int(estimator.best_iteration) + 1)
                    elif name == "catboost":
                        iterations.append(int(estimator.tree_count_))
                    score = float(np.average(scores, weights=lengths))
                    trial.report(score, fold)
                    trial.set_user_attr("fold_scores", scores)
                    trial.set_user_attr("best_iterations", iterations)
                    if trial.should_prune():
                        log(
                            f"tune {name}: trial {trial.number} pruned after fold {fold + 1}; AP={score:.6f}"
                        )
                        raise optuna.TrialPruned()
                log(
                    f"tune {name}: trial {trial.number} AP={score:.6f}, {time.perf_counter() - started:.1f}s"
                )
                return score

            attempted = sum(t.state.is_finished() for t in study.trials)
            for unfinished in study.get_trials(states=(optuna.trial.TrialState.RUNNING,)):
                study.tell(unfinished.number, state=optuna.trial.TrialState.FAIL)
            attempted = sum(t.state.is_finished() for t in study.trials)
            if attempted < trials:
                study.optimize(objective, n_trials=trials - attempted, gc_after_trial=True)
            selected = dict(study.best_params)
            iterations = study.best_trial.user_attrs.get("best_iterations", [])
            if iterations:
                selected["n_estimators"] = max(2, int(np.median(iterations)))
            tuning[name] = {
                "selected": selected,
                "development_selection_ap": study.best_value,
                "completed": sum(t.state == optuna.trial.TrialState.COMPLETE for t in study.trials),
                "pruned": sum(t.state == optuna.trial.TrialState.PRUNED for t in study.trials),
                "trials": [
                    {
                        "number": t.number,
                        "state": t.state.name,
                        "value": t.value,
                        "params": t.params,
                        "attributes": t.user_attrs,
                    }
                    for t in study.trials
                ],
            }
        else:
            tuning[name] = {"selected": {}}
        dump_json(RUN / "tuning.json", tuning)
    rows = []
    for name in NAMES:
        params = tuning[name]["selected"]
        for y, (training, validation) in zip([2019, 2020, 2021], prepared, strict=True):
            cache = RUN / f"validation/{name}_{y}.parquet"
            if complete(cache):
                prediction = pd.read_parquet(cache)
            else:
                model = fit(name, training, cfg, params)
                prediction = validation[["cell_id", "day", "label", "weight"]].copy()
                prediction["probability"] = model.predict(validation)
                record_table(
                    cache, prediction, {"model": name, "params": params, "synthetic": False}
                )
            score = float(
                average_precision_score(
                    prediction.label, prediction.probability, sample_weight=prediction.weight
                )
            )
            rows.append(
                {
                    "model": name,
                    "year": y,
                    "weighted_ap": score,
                    "weight_mass": float(prediction.weight.sum()),
                    "rows": len(prediction),
                }
            )
            log(f"validation {name} {y}: weighted AP={score:.6f}")
    scores = pd.DataFrame(rows)
    score_path = RUN / "comparison.csv"
    scores.to_csv(score_path, index=False)
    weighted = {
        name: float(np.average(g.weighted_ap, weights=g.weight_mass))
        for name, g in scores.groupby("model")
    }
    winner = max(weighted, key=lambda name: (weighted[name], name))
    dump_json(
        RUN / "selection.json",
        {
            "winner": winner,
            "weighted_validation_ap": weighted,
            "selection_data_end": 2021,
            "test_accessed": False,
            "comparison_sha256": checksum(score_path),
        },
    )
    fitted = {}
    train = train.loc[~train.cell_id.isin(industrial_cells())]
    for name in NAMES:
        reserve()
        fitted[name] = fit(name, train, cfg, tuning[name]["selected"])
        log(f"final development fit complete: {name}")
    joblib.dump(fitted, RUN / "models.joblib", compress=3)
    dump_json(
        RUN / "training_complete.json",
        {
            "models_sha256": checksum(RUN / "models.joblib"),
            "selected": winner,
            "train_rows": len(train),
            "positive_rows": int(train.label.sum()),
            "synthetic": False,
            "end_year": 2021,
            "source_registry_sha256": checksum(RUN / "source_registry.json"),
        },
    )


def freeze() -> None:
    if (RUN / "release.json").exists():
        permitted([2023, 2024], RUN / "release.json")
        log("Verified existing immutable model freeze")
        return
    models = joblib.load(RUN / "models.joblib")
    training = json.loads((RUN / "training_complete.json").read_text())
    if training["models_sha256"] != checksum(RUN / "models.joblib"):
        raise ValueError("Training model changed")
    if training["source_registry_sha256"] != checksum(RUN / "source_registry.json"):
        raise ValueError("Training source registry changed")
    registry = json.loads((RUN / "source_registry.json").read_text())
    for relative, digest in registry["code_sha256"].items():
        if checksum(ROOT / relative) != digest:
            raise ValueError(f"Training code changed before freeze: {relative}")
    selection = json.loads((RUN / "selection.json").read_text())
    frame = pd.read_parquet(table(2022, training=False))
    frame = frame.loc[~frame.cell_id.isin(industrial_cells())]
    calibrators, thresholds, boundaries, reliability_boundaries = {}, {}, {}, {}
    for name, model in models.items():
        calibrator, threshold = fit_sigmoid(frame, model.predict(frame), 2022)
        probabilities = calibrator.predict(model.predict(frame))
        calibrators[name], thresholds[name] = calibrator, threshold
        boundaries[name] = map_boundaries(probabilities, [0.5, 0.8, 0.95], frame.weight.to_numpy())
        reliability_boundaries[name] = (
            [0.0]
            + map_boundaries(probabilities, list(np.arange(0.1, 1, 0.1)), frame.weight.to_numpy())
            + [1.0]
        )
    joblib.dump(calibrators, RUN / "calibrators.joblib", compress=3)
    # Registry now also records the actual completed calibration-year inputs.
    dump_json(RUN / "source_registry.json", source_registry())
    dump_json(
        RUN / "frozen.json",
        {
            "synthetic": False,
            "variant": "public_reprocessed_hindcast",
            "selected_model": selection["winner"],
            "features": FEATURES,
            "thresholds": thresholds,
            "map_boundaries": boundaries,
            "reliability_boundaries": reliability_boundaries,
            "calibration_year": 2022,
            "development_end": 2021,
            "test_used_for_selection": False,
            "population": "fixed retrospective WorldPop 2010 proxy",
            "operational_validation": False,
        },
    )
    files = [
        "models.joblib",
        "calibrators.joblib",
        "frozen.json",
        "selection.json",
        "design.json",
        "source_registry.json",
        "training_complete.json",
        "tuning.json",
        "comparison.csv",
        "industrial_cells.json",
    ]
    hashes = {name: checksum(RUN / name) for name in files}
    dump_json(
        RUN / "release.json",
        {
            "status": "frozen_before_final_evaluation",
            "synthetic": False,
            "frozen_utc": datetime.now(UTC).isoformat(),
            "model_file": "models.joblib",
            "model_sha256": hashes["models.joblib"],
            "artifact_hashes": hashes,
        },
    )
    log(f"Model and calibration frozen. Selected by development AP: {selection['winner']}")
