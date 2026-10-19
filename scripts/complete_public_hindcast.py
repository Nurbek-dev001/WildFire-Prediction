"""Continue an owned training run through guarded final evaluation and map exports."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "data/real/public_predictors"
RUN = ROOT / "runs/public_hindcast"


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dump_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def log(message: str) -> None:
    print(f"{datetime.now(UTC).isoformat()} {message}", flush=True)


def stage(name: str, *extra: str) -> None:
    dump_json(RUN / "progress.json", {"stage": name, "started_utc": datetime.now(UTC).isoformat()})
    log(f"Public completion stage: {name}")
    subprocess.run(
        [sys.executable, "-u", str(ROOT / "scripts/run_public_hindcast.py"), name, *extra],
        cwd=ROOT,
        check=True,
    )


def verify_training_sources() -> None:
    registry = json.loads((RUN / "training_sources.json").read_text())
    for record in registry["sources"]:
        if checksum(PUBLIC / record["path"]) != record["sha256"]:
            raise ValueError(f"Training source changed: {record['path']}")
    for record in registry["feature_tables"]:
        if int(Path(record["path"]).name[:4]) > 2021:
            raise PermissionError("Training registry includes a non-development feature table")
        if checksum(RUN / record["path"]) != record["sha256"]:
            raise ValueError(f"Training feature table changed: {record['path']}")
    for name, digest in registry["geometry_sha256"].items():
        if checksum(ROOT / f"data/real/normalized/{name}.parquet") != digest:
            raise ValueError(f"Training geometry changed: {name}")


def wait_training(pid: int) -> None:
    process = psutil.Process(pid)
    if process.cwd() != str(ROOT) or "compare" not in process.cmdline():
        raise ValueError("The supplied PID is not this workspace's comparison worker")
    previous = None
    log("Waiting for the owned development-only comparison; final observations remain sealed")
    while not (RUN / "training_complete.json").is_file():
        if not process.is_running():
            raise RuntimeError("Training process stopped before verified completion")
        try:
            database = "file:" + (RUN / "tuning.sqlite3").as_posix() + "?mode=ro"
            with sqlite3.connect(database, uri=True, timeout=2) as connection:
                state = connection.execute(
                    "SELECT study_name,state,count(*) FROM trials JOIN studies USING(study_id) GROUP BY study_name,state ORDER BY study_name,state"
                ).fetchall()
                folds = connection.execute(
                    "SELECT trial_id,value_json FROM trial_user_attributes WHERE key='fold_scores' ORDER BY trial_id DESC LIMIT 1"
                ).fetchall()
            summary = repr((state, folds))
            if summary != previous:
                log(f"Development tuning progress: {summary}")
                previous = summary
        except sqlite3.OperationalError:
            pass
        time.sleep(30)
    verify_training_sources()


def acquire_final() -> None:
    release = RUN / "release.json"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; from wildfire_kz.data.public_predictors import permitted; "
            "permitted([2023,2024],Path('runs/public_hindcast/release.json'))",
        ],
        cwd=ROOT,
        check=True,
    )
    jobs = [
        ("weather", 2023, 2023, 1),
        ("weather", 2024, 2024, 1),
        ("vegetation", 2023, 2024, 2),
        ("landcover", 2022, 2023, 2),
    ]
    dump_json(
        RUN / "progress.json",
        {"stage": "acquire-final", "started_utc": datetime.now(UTC).isoformat()},
    )
    log(
        "Frozen release verified; acquiring final-year predictors in two bounded independent processes"
    )

    def acquire(job: tuple[str, int, int, int]) -> None:
        part, first, last, workers = job
        subprocess.run(
            [
                sys.executable,
                "-u",
                str(ROOT / "scripts/acquire_public_predictors.py"),
                part,
                "--start-year",
                str(first),
                "--end-year",
                str(last),
                "--workers",
                str(workers),
                "--attempts",
                "6",
                "--release",
                str(release),
            ],
            cwd=ROOT,
            check=True,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(acquire, jobs))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-training-pid", type=int)
    args = parser.parse_args()
    if args.wait_training_pid:
        wait_training(args.wait_training_pid)
    elif not (RUN / "training_complete.json").is_file():
        stage("prepare")
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/audit_public_development.py")],
            cwd=ROOT,
            check=True,
        )
        stage("compare", "--trials", "50")
    verify_training_sources()
    stage("freeze")
    acquire_final()
    stage("evaluate")
    stage("explain")
    stage("report")
    stage("export", "--day", "2024-07-15")
    stage("export")
    dump_json(
        RUN / "progress.json",
        {"stage": "backend_complete", "completed_utc": datetime.now(UTC).isoformat()},
    )
    log("Actual final metrics, explanations, report and 731 daily map assets are complete")


if __name__ == "__main__":
    if sys.platform == "win32":
        execution_state = ctypes.windll.kernel32.SetThreadExecutionState
        execution_state.argtypes = [ctypes.c_uint]
        execution_state.restype = ctypes.c_uint
        execution_state(0x80000001)
    try:
        main()
    finally:
        if sys.platform == "win32":
            execution_state(0x80000000)
