"""Retrieve test predictors only; never opens the independent outcome archive."""

import argparse
import json

import pandas as pd

from wildfire_kz.data.public_predictors import ROOT, landcover, parallel, permitted, vegetation_day

p = argparse.ArgumentParser()
p.add_argument("part", choices=["vegetation", "landcover"])
a = p.parse_args()
protocol = ROOT / "runs/independent_2025/protocol.json"
if not protocol.is_file() or json.loads(protocol.read_text())["test_year"] != 2025:
    raise PermissionError("Registered 2025 protocol is required")
release = ROOT / "runs/public_hindcast/release.json"
permitted([2025], release)
if a.part == "vegetation":
    days = [
        d.strftime("%Y-%m-%d")
        for d in pd.date_range("2014-11-01", "2025-12-31", freq="7D")
        if d.year == 2025
    ]
    parallel(vegetation_day, days, 2)
else:
    landcover([2024], 2, release)
