"""Run the documented public-data variant, preserving the sealed-test boundary."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from wildfire_kz.data.public_predictors import ROOT, log, permitted
from wildfire_kz.data.public_study import RUN, table
from wildfire_kz.public_evaluation import evaluate
from wildfire_kz.public_experiment import comparison, freeze
from wildfire_kz.public_maps import export


def prepare(wait: bool) -> None:
    jobs = [(year, True) for year in range(2015, 2022)] + [
        (y, False) for y in [2019, 2020, 2021, 2022]
    ]
    for year, training in jobs:
        while True:
            try:
                table(year, training=training)
                break
            except FileNotFoundError as exc:
                if not wait:
                    raise
                log(f"Waiting for predictor acquisition: {str(exc).splitlines()[0]}")
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
            ],
            cwd=ROOT,
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=["prepare", "compare", "freeze", "acquire-final", "evaluate", "export"]
    )
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--trials", type=int, default=50)
    parser.add_argument("--destination", type=Path, default=ROOT / "platform/dist/assets")
    parser.add_argument("--day", action="append")
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.wait)
    elif args.stage == "compare":
        comparison(args.trials)
    elif args.stage == "freeze":
        freeze()
    elif args.stage == "acquire-final":
        acquire_final()
    elif args.stage == "evaluate":
        evaluate()
    else:
        export(args.destination, dates=args.day)
        shutil.copyfile(
            ROOT / "docs/public-hindcast-method.md", args.destination / "model-method.txt"
        )
        shutil.copyfile(RUN / "evaluate/complete.json", args.destination / "model-evaluation.json")
        shutil.copyfile(
            RUN / "evaluate/cluster_intervals.csv", args.destination / "cluster_intervals.csv"
        )


if __name__ == "__main__":
    main()
