"""Retrieve documented free predictor alternatives without changing the primary study."""

import argparse
import asyncio
import sys
from pathlib import Path

from wildfire_kz.data.public_predictors import (
    human,
    landcover,
    terrain,
    vegetation,
    weather_year,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("part", choices=["weather", "vegetation", "landcover", "terrain", "human"])
parser.add_argument("--start-year", type=int, default=2014)
parser.add_argument("--end-year", type=int, default=2022)
parser.add_argument("--workers", type=int, default=2)
parser.add_argument("--release", type=Path)
args = parser.parse_args()
years = list(range(args.start_year, args.end_year + 1))
if args.part == "weather":
    # Each Rust/Python async reader must own its event loop and S3 client.
    # Avoid Windows Proactor cancellation storms and cross-thread loop reuse.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    for year in years:
        weather_year(year, release=args.release)
elif args.part == "vegetation":
    vegetation(years, args.workers, args.release)
elif args.part == "landcover":
    landcover(years, args.workers, args.release)
elif args.part == "terrain":
    terrain(args.workers)
else:
    human()
