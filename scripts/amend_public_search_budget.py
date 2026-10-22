"""Reduce only the search budget, preserving and verifying pre-test trial history."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import optuna
import psutil

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import PUBLIC, ROOT
from wildfire_kz.data.public_study import FEATURES, RUN
from wildfire_kz.public_experiment import config, source_registry


def assert_pretest(root: Path, run: Path) -> None:
    """Fail before changing a study if fitting, release or test access already occurred."""
    forbidden = [
        run / name
        for name in ["release.json", "models.joblib", "training_complete.json", "selection.json"]
    ]
    forbidden += list((run / "validation").glob("*.parquet"))
    for year in [2023, 2024]:
        forbidden += [
            root / f"data/real/normalized/detections_{year}.parquet",
            root / f"data/real/public_predictors/weather/{year}.npz",
        ]
        forbidden += list((root / f"data/real/public_predictors/weather/rows_{year}").glob("*.npz"))
        forbidden += list((root / "data/real/public_predictors/vegetation").glob(f"{year}-*"))
    if any(path.exists() for path in forbidden):
        raise PermissionError("Budget amendment must precede fitted selection and test access")


def fingerprint(snapshot: dict[str, Any], configuration: dict[str, Any]) -> str:
    """The exact fingerprint formula used by the unchanged comparison worker."""
    payload = {
        "tables": [p for p in snapshot["feature_tables"] if int(Path(p["path"]).name[:4]) <= 2021],
        "code": snapshot["code_sha256"],
        "features": FEATURES,
        "config": configuration,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def assert_only_budget_changed(old: dict[str, Any], new: dict[str, Any]) -> None:
    old_without_budget = {**old, "models": {**old["models"], "trials": new["models"]["trials"]}}
    if old_without_budget != new:
        raise PermissionError("Only models.trials may change; data and model settings must match")
    if not 1 <= new["models"]["trials"] < old["models"]["trials"]:
        raise ValueError("The new budget must be positive and smaller than the old budget")


def amend(trials: int) -> None:
    assert_pretest(ROOT, RUN)
    for process in psutil.process_iter(["name", "cmdline"]):
        args = process.info["cmdline"] or []
        if (
            (process.info["name"] or "").lower().startswith("python")
            and "compare" in args
            and any(Path(arg).name == "run_public_hindcast.py" for arg in args)
        ):
            try:
                if Path(process.cwd()).resolve() == ROOT:
                    raise RuntimeError("Stop the owned comparison before changing its study budget")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    archive = RUN / "protocol_before_budget_amendment"
    archived_registry = archive / "runs/public_hindcast/training_sources.json"
    previous = json.loads(archived_registry.read_text())
    design = json.loads((archive / "runs/public_hindcast/design.json").read_text())
    for record in json.loads((archive / "archive.json").read_text())["files"]:
        if checksum(archive / record["path"]) != record["sha256"]:
            raise PermissionError("An archived original input changed")
    current = source_registry(max_year=2021)
    # Runtime and method documentation can change; every scientific input and all
    # feature/model code must remain byte-identical. No trial results are rewritten.
    for key in [
        "sources",
        "geometry_sha256",
        "feature_tables",
        "development_outcome_tables",
        "code_sha256",
    ]:
        if previous[key] != current[key]:
            raise PermissionError(f"Scientific inputs changed: {key}")
    for record in current["sources"]:
        if checksum(PUBLIC / record["path"]) != record["sha256"]:
            raise PermissionError("A predictor checksum changed")
    old_config = design["config"]
    new_config = config(trials).model_dump(mode="json")
    assert_only_budget_changed(old_config, new_config)
    old_fingerprint = fingerprint(previous, old_config)
    new_fingerprint = fingerprint(current, new_config)
    database = RUN / "tuning.sqlite3"
    storage = "sqlite:///" + database.as_posix()
    summaries = optuna.get_all_study_summaries(storage=storage)
    if not summaries:
        raise ValueError("There is no prior tuning history to preserve")
    studies = [optuna.load_study(study_name=s.study_name, storage=storage) for s in summaries]
    for study in studies:
        if study.user_attrs.get("experiment_fingerprint") != old_fingerprint:
            raise PermissionError("The existing study is not the archived original experiment")
    with sqlite3.connect(database) as connection:
        with sqlite3.connect(archive / "tuning_at_amendment.sqlite3") as backup:
            connection.backup(backup)
    record = {
        "recorded_utc": datetime.now(UTC).isoformat(),
        "reason": "User explicitly waived 50 attempts on 2026-10-22 before test access",
        "user_request": "50 попыток не надо, в этом проекта до идела что не хватает",
        "old_fingerprint": old_fingerprint,
        "new_fingerprint": new_fingerprint,
        "old_budget": old_config["models"]["trials"],
        "new_budget": trials,
        "retained_history": {
            s.study_name: {
                state: sum(t.state.name == state for t in s.trials)
                for state in ["COMPLETE", "PRUNED", "RUNNING", "FAIL"]
            }
            for s in studies
        },
        "prior_registry_sha256": checksum(archived_registry),
        "prior_history_sha256": checksum(archive / "tuning_at_amendment.sqlite3"),
        "amendment_script_sha256": checksum(Path(__file__)),
        "test_accessed": False,
        "scientific_inputs_and_model_code_unchanged": True,
        "note": "Retain excess RF trials; interrupted trials become FAIL on normal resume. "
        "Unequal search effort is reported; this is a limited practical comparison.",
    }
    path = RUN / "budget_amendment.json"
    if path.exists():
        raise FileExistsError("A budget amendment already exists; inspect it before any retry")
    dump_json(path, record)
    for study in studies:
        study.set_user_attr("budget_amendment_sha256", checksum(path))
        study.set_user_attr("previous_experiment_fingerprint", old_fingerprint)
        study.set_user_attr("experiment_fingerprint", new_fingerprint)
    print(json.dumps(record, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=5)
    amend(parser.parse_args().trials)
