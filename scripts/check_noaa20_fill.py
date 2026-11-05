"""Check of amendment 2026-11-05-01 (docs/model-v7-progress.md).

Usage: check_noaa20_fill.py N20_DIR OUT_DIR  (N20_DIR: GIBS NOAA-20 days as parquet)

Replay past days three ways: S-NPP as issued (A), the last 3 days from NOAA-20 (B),
the last 3 days missing as in the outage (C). Compare B and C with A, and with that day's fires."""

import json
import shutil
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(r"C:\Users\nured\Documents\ChatGPT\WildFire")
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
import forecast_daily as fd  # noqa: E402
import test_2026 as t26  # noqa: E402

from wildfire_kz import forecast_log as fl  # noqa: E402

N20 = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(exist_ok=True)
original = fd.live_detections


def n20_points(d):
    p = N20 / f"{d}.parquet"
    raw = pd.read_parquet(p).astype(str).drop_duplicates(["LATITUDE", "LONGITUDE", "ACQ_TIME"])
    return t26.normalise(raw).assign(satellite="N20")


def scenario(kind, target):
    def patched(last):
        det, meta = original(last)
        gap = [target - timedelta(days=k) for k in (3, 2, 1)]
        keep = ~det.timestamp.dt.date.isin(gap)
        det = det[keep]
        if kind == "B":
            det = pd.concat([det] + [n20_points(d) for d in gap], ignore_index=True)
        return det.reset_index(drop=True), meta

    return patched


res = []
for target in [date(2026, 10, 31), date(2026, 11, 1)]:
    maps = {}
    for kind in "ABC":
        fd.live_detections = original if kind == "A" else scenario(kind, target)
        try:
            fd.forecast(target, replay=True)
        except Exception as e:
            print("check note", kind, e)
        src = fd.LIVE / f"replay/{target}"
        maps[kind] = {m: fl.decode((src / f"{m}.f16.gz").read_bytes()) for m in ("v6", "v7")}
        shutil.copy(src / "v7.f16.gz", OUT / f"{target}_{kind}_v7.f16.gz")
    # fires on the target day (S-NPP, nominal/high), in cells.bin order through the payload grid
    for m in ("v6", "v7"):
        thr = json.loads(((t26.V6 if m == "v6" else fd.v7.RUN) / "frozen.json").read_text())[
            "threshold"
        ]
        a = maps["A"][m]
        for kind in "BC":
            b = maps[kind][m]
            ok = np.isfinite(a) & np.isfinite(b)
            rank = pd.Series(a[ok]).rank().corr(pd.Series(b[ok]).rank())
            k = int(ok.sum() * 0.01)
            ta = set(np.argsort(-np.where(ok, a, -1))[:k])
            tb = set(np.argsort(-np.where(ok, b, -1))[:k])
            al_a = set(np.flatnonzero(a >= thr))
            al_b = set(np.flatnonzero(b >= thr))
            res.append(
                dict(
                    day=target,
                    model=m,
                    vs_A=kind,
                    spearman=round(rank, 4),
                    top1pct_same=round(len(ta & tb) / k, 3),
                    alerts_A=len(al_a),
                    alerts=len(al_b),
                    alerts_same=round(len(al_a & al_b) / max(1, len(al_a | al_b)), 3),
                )
            )
        print(pd.DataFrame(res).to_string(index=False), flush=True)
pd.DataFrame(res).to_csv(OUT / "n20_replay.csv", index=False)
