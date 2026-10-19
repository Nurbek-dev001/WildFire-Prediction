"""Retrieve documented free predictor alternatives without changing the primary study."""

import argparse
import asyncio
import sys
import time
from pathlib import Path

from wildfire_kz.data.public_predictors import (
    human,
    landcover,
    log,
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
parser.add_argument("--attempts", type=int, default=1)
args = parser.parse_args()
years = list(range(args.start_year, args.end_year + 1))
for attempt in range(args.attempts):
    try:
        if args.part == "weather":
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
        break
    except PermissionError:
        raise
    except Exception as exc:
        if attempt == args.attempts - 1:
            raise
        log(
            f"{args.part}: resumable attempt {attempt + 1} failed ({type(exc).__name__}); retry in 30 seconds"
        )
        time.sleep(30)
