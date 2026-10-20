"""Run the documented public-data variant, preserving the sealed-test boundary."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import PUBLIC, ROOT, log, permitted
from wildfire_kz.data.public_study import RUN, table


def prepare(wait: bool) -> None:
    jobs = [(year, True) for year in range(2015, 2022)] + [
        (y, False) for y in [2019, 2020, 2021, 2022]
    ]
    for year, training in jobs:
        last_reason = None
        while True:
            try:
                table(year, training=training)
                break
            except FileNotFoundError as exc:
                if not wait:
                    raise
                reason = str(exc).splitlines()[0]
                if reason != last_reason:
                    log(f"Waiting for predictor acquisition: {reason}")
                    last_reason = reason
                time.sleep(30)


def acquire_final() -> None:
    release = RUN / "release.json"
    permitted([2023, 2024], release)
    # Only this function may request held-out predictor years. It verifies the
    # actual models, calibrators, thresholds and design before every acquisition.
    for part, first, last in [
        ("weather", 2023, 2024),
        ("vegetation", 2023, 2024),
        ("landcover", 2022, 2023),
    ]:
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/acquire_public_predictors.py"),
                part,
                "--start-year",
                str(first),
                "--end-year",
                str(last),
                "--workers",
                "2" if part != "weather" else "1",
                "--release",
                str(release),
                "--attempts",
                "6",
            ],
            cwd=ROOT,
            check=True,
        )


def seal_evaluation_protocol() -> None:
    """Seal final metrics and explanation code before test materialisation."""
    release = RUN / "release.json"
    permitted([2023, 2024], release)
    path = RUN / "source_registry.json"
    registry = json.loads(path.read_text())
    if "evaluation_code_sealed_utc" in registry:
        return
    for year in [2023, 2024]:
        if (
            (ROOT / f"data/real/normalized/detections_{year}.parquet").exists()
            or (PUBLIC / f"weather/{year}.npz").exists()
            or any((PUBLIC / f"weather/rows_{year}").glob("*.npz"))
            or any((PUBLIC / "vegetation").glob(f"{year}-*.npz"))
        ):
            raise PermissionError(
                "Final metric protocol must be sealed before test materialisation"
            )
    for file in [
        ROOT / "src/wildfire_kz/public_evaluation.py",
        ROOT / "src/wildfire_kz/evaluation/__init__.py",
        ROOT / "src/wildfire_kz/public_explanation.py",
    ]:
        registry["code_sha256"][str(file.relative_to(ROOT))] = checksum(file)
    registry["evaluation_code_sealed_utc"] = datetime.now(UTC).isoformat()
    dump_json(path, registry)
    record = json.loads(release.read_text())
    record["artifact_hashes"]["source_registry.json"] = checksum(path)
    record["evaluation_code_sealed_utc"] = registry["evaluation_code_sealed_utc"]
    dump_json(release, record)
    permitted([2023, 2024], release)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        choices=[
            "prepare",
            "compare",
            "freeze",
            "acquire-final",
            "evaluate",
            "explain",
            "report",
            "export",
        ],
    )
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--trials", type=int, default=50)
    parser.add_argument("--destination", type=Path, default=ROOT / "platform/dist/assets")
    parser.add_argument("--day", action="append")
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.wait)
    elif args.stage == "compare":
        from wildfire_kz.public_experiment import comparison

        comparison(args.trials)
    elif args.stage == "freeze":
        from wildfire_kz.public_experiment import freeze

        freeze()
        seal_evaluation_protocol()
    elif args.stage == "acquire-final":
        acquire_final()
    elif args.stage == "evaluate":
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/reclaim_public_cache.py"), "--include-final"],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/finalize_weather_boundary.py")],
            cwd=ROOT,
            check=True,
        )
        from wildfire_kz.public_evaluation import evaluate

        evaluate()
    elif args.stage == "report":
        from wildfire_kz.public_report import report

        report()
    elif args.stage == "explain":
        from wildfire_kz.public_explanation import explain

        explain()
    else:
        from wildfire_kz.public_maps import export

        export(args.destination, dates=args.day)
        shutil.copyfile(
            ROOT / "docs/public-hindcast-method.md", args.destination / "model-method.txt"
        )
        shutil.copyfile(RUN / "evaluate/complete.json", args.destination / "model-evaluation.json")
        shutil.copyfile(
            RUN / "evaluate/cluster_intervals.csv", args.destination / "cluster_intervals.csv"
        )
        report_directory = RUN / "report"
        if (report_directory / "complete.json").is_file():
            proof = json.loads((report_directory / "complete.json").read_text())
            if proof["release_sha256"] != checksum(RUN / "release.json"):
                raise ValueError("Report belongs to a different frozen experiment")
            for filename, digest in proof["outputs"].items():
                if checksum(report_directory / filename) != digest:
                    raise ValueError(f"Report output changed: {filename}")
            site = args.destination.parent
            shutil.copytree(report_directory, site / "results", dirs_exist_ok=True)
            (site / "evaluate").mkdir(exist_ok=True)
            for path in (RUN / "evaluate").glob("*.csv"):
                shutil.copyfile(path, site / "evaluate" / path.name)
            for name in ["comparison.csv", "source_registry.json", "frozen.json"]:
                shutil.copyfile(RUN / name, site / name)
        if args.day is None:
            from wildfire_kz.public_verification import verify

            verify(args.destination)


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes

        # Prevent automatic idle sleep during this computation only. This does
        # not keep the display on or override a user's explicit sleep action.
        execution_state = ctypes.windll.kernel32.SetThreadExecutionState
        execution_state.argtypes = [ctypes.c_uint]
        execution_state.restype = ctypes.c_uint
        execution_state(0x80000001)
    try:
        main()
    finally:
        if sys.platform == "win32":
            execution_state(0x80000000)
