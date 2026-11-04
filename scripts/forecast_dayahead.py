"""Day-ahead forecast for UTC day D with v6da, issued during D-1 from 12:00 UTC.

v6da (runs/model_v6da, scripts/develop_model_v6da.py) is the v6 recipe with ERA5 ending on
D-8, the latest day the archive has published by then. Inputs are what exists at 12:00 UTC of
D-1: S-NPP detections through 12:00 UTC of D-1 (its day pass; every attempt and replay cuts
there, so all see the same points), ERA5 through D-8, NDVI through D-12. v6's fire history ends
on D-2, so it is unchanged. An issue before 19:00 UTC of D-1 (midnight in Kazakhstan) is on
time; a later one is logged as late.

The entries go to their own hash-chained log, runs/forecast_live/dayahead.jsonl: the frozen v6
and v7 log (log.jsonl) and its 2027 prospective test stay exactly as registered, and their
morning issue for D refines this forecast on the site.
Usage: forecast_dayahead.py [--day YYYY-MM-DD] [--replay]   (default: the UTC day 12 hours ahead)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import FunctionType

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import develop_model_v6da as v6da  # noqa: E402
import develop_model_v7 as v7  # noqa: E402
import forecast_daily as fd  # noqa: E402
import test_2026 as t26  # noqa: E402

from wildfire_kz import forecast_log as fl  # noqa: E402
from wildfire_kz import model_upgrade as mu  # noqa: E402
from wildfire_kz.data import checksum  # noqa: E402
from wildfire_kz.data import public_predictors as pp  # noqa: E402
from wildfire_kz.data import public_study as study  # noqa: E402

LIVE = fd.LIVE
LOG = LIVE / "dayahead.jsonl"
MODEL = v6da.RUN
EARLIEST = timedelta(hours=12)  # before 00:00 UTC of D: 12:00 UTC of D-1
DEADLINE = timedelta(hours=5)  # before 00:00 UTC of D: 19:00 UTC of D-1, midnight in Kazakhstan
# The last scheduled attempt starts at 23:35 UTC of D-1; a failure from then on is recorded.
LAST_ATTEMPT = timedelta(minutes=30)


def log(message: str) -> None:
    print(f"{datetime.now(UTC).isoformat(timespec='seconds')} {message}", flush=True)


def feature_frame(keys: pd.DataFrame) -> pd.DataFrame:
    """test_2026.feature_frame with the ERA5 predictors at v6da's lag (8 days)."""
    env = dict(study.__dict__)
    env.update(
        permitted=t26.independent.cached_guard,
        vegetation_features=t26.independent.vegetation_features,
        cover_year=fd.cover_override,
        meteorology=lambda indices, dates, release=None: v6da.meteorology(indices, dates, v6da.LAG),
    )
    adapted = FunctionType(
        study.feature_frame.__code__, env, "feature_frame", study.feature_frame.__defaults__
    )
    return adapted(keys, t26.RELEASE)


def forecast(target: date, replay: bool = False) -> None:
    issued = datetime.now(UTC)
    if not replay and any(e["target_day"] == str(target) for e in fl.read(LOG)):
        log(f"{target}: already in the day-ahead log, the first entry stands")
        return
    earliest, deadline = fl.midnight(target) - EARLIEST, fl.midnight(target) - DEADLINE
    if not replay and issued < earliest:
        raise RuntimeError(f"Too early: the day-ahead forecast is issued from {earliest}")
    fd.check_versions()
    release = fd.verify(MODEL)
    mu.verify_release(t26.V5 / "release.json")

    log(f"{target}: day-ahead inputs")
    detections, det_meta = fd.live_detections(target - timedelta(days=1))
    cutoff = pd.Timestamp(fl.midnight(target) - EARLIEST)
    detections = detections[detections.timestamp < cutoff].reset_index(drop=True)
    det_meta["cutoff_utc"] = str(cutoff)
    det_meta["last_detection_utc"] = str(detections.timestamp.max())
    lag = timedelta(days=v6da.LAG)
    lasts = {
        y: fd.extend_weather(y, target - lag)
        for y in sorted({(target - lag - timedelta(days=13)).year, (target - lag).year})
    }
    era5_last = lasts[(target - lag).year]
    if era5_last is None or era5_last < target - lag:
        raise FileNotFoundError(f"ERA5 published only through {era5_last}; v6da needs D-8")
    ndvi_last = fd.ndvi(target)

    log(f"{target}: features")
    study.weather_arrays = fd.live_weather_arrays
    t26.cover_override = fd.cover_override
    grid = pp.geography()[0]
    ids = pd.Index(grid.cell_id)
    n = len(ids)
    cells = pd.Series(np.arange(n), index=ids)
    binary = (ROOT / "platform/dist/assets/cells.bin").read_bytes()
    order = ids.get_indexer(
        pd.Index([f"g5000_{r[0]}_{r[1]}" for r in struct.iter_unpack("<hhfffH8H", binary)])
    )
    industrial = ids.isin(json.loads((mu.OLD / "industrial_cells.json").read_text())["cell_ids"])
    history = mu.load_history(2024, t26.V5 / "release.json")
    raw25 = pd.read_parquet(
        t26.independent.RUN / "detections_2025.parquet", columns=["cell_id", "timestamp"]
    )
    extra = pd.concat([raw25, detections[["cell_id", "timestamp"]]], ignore_index=True)
    extra["day"] = extra.timestamp.dt.floor("D")
    history = pd.concat([history, extra[["cell_id", "day"]]], ignore_index=True).drop_duplicates()
    day = pd.Timestamp(target, tz="UTC")
    keys = pd.DataFrame({"cell_index": np.arange(n, dtype="int32"), "day": day})
    f = feature_frame(keys)
    f = mu.augment(f, mu.FireHistory(history), t26.V5 / "release.json")
    history_cells = fd.CellHistory(
        history.assign(cell=history.cell_id.map(cells))
        .dropna(subset=["cell"])
        .astype({"cell": np.int64}),
        n,
        target.year - 1,
    )
    for name, values in history_cells.features(f).items():
        f[name] = values
    recent = set(
        detections.loc[
            (detections.timestamp >= day - pd.Timedelta(hours=48)) & (detections.timestamp < day),
            "cell_id",
        ]
    )
    eligible = f.required_features_valid.to_numpy() & ~industrial & ~ids.isin(recent)
    heat = v7.HeatRule(fd.strong_detections(detections), cells).flag(keys)

    log(f"{target}: scoring")
    out_dir = LIVE / (f"dayahead/replay/{target}" if replay else f"dayahead/{target}")
    model = joblib.load(MODEL / "model.joblib")
    model["estimator"].set_params(n_jobs=2)
    calibration = joblib.load(MODEL / "calibrator.joblib")
    frozen = json.loads((MODEL / "frozen.json").read_text())
    p = np.full(n, np.nan, dtype="float32")
    raw = model["estimator"].predict_proba(f.loc[eligible, model["features"]])[:, 1]
    p[eligible] = mu.published_probability(calibration.predict(raw))
    alert = p >= frozen["threshold"]
    payload = f"dayahead/{target}/v6da.f16.gz"
    payload_sha256 = fd.write_payload(out_dir / "v6da.f16.gz", p[order])
    heat_cells = np.flatnonzero(heat[order]).astype(int).tolist()
    (out_dir / "heat_cells.json").write_text(json.dumps(heat_cells))
    land = f[fd.LAND].to_numpy().argmax(axis=1).astype("uint8")[order]
    (out_dir / "land.u8").write_bytes(land.tobytes())
    checks = {
        "detections_d1_to_cutoff": int((detections.timestamp >= day - pd.Timedelta(days=1)).sum()),
        "era5_lag_days": (target - era5_last).days,
        "ndvi_age_days": (target - date.fromisoformat(ndvi_last)).days if ndvi_last else None,
        "eligible_share": round(float(eligible.mean()), 4),
    }
    warnings = fd.feed_gap(target, det_meta)
    if det_meta.get("firms_days"):
        warnings.append(f"FIRMS fallback used for {det_meta['firms_days']}")
    if checks["ndvi_age_days"] is None or checks["ndvi_age_days"] > 26:
        warnings.append(f"NDVI is {checks['ndvi_age_days']} days old (normal 12-19)")
    log(f"{target}: health {checks}" + (f"; warnings: {warnings}" if warnings else ""))
    if replay:
        log(f"replay {target}: {int(alert.sum())} alert cells, values in {out_dir}")
        return
    entry = fl.append(
        LOG,
        {
            "target_day": str(target),
            "status": "issued",
            "issue": "day_ahead",
            "issued_utc": issued.isoformat(timespec="seconds"),
            "on_time": issued < deadline,
            "models": {
                "v6da": {
                    "release_sha256": checksum(MODEL / "release.json"),
                    "payload": payload,
                    "payload_sha256": payload_sha256,
                    "values_sha256": hashlib.sha256(
                        np.asarray(p[order], dtype="<f2").tobytes()
                    ).hexdigest(),
                    "format": fl.FORMAT,
                    "finite_cells": int(np.isfinite(p).sum()),
                    "threshold": frozen["threshold"],
                    "alert_cells": int(alert.sum()),
                    "alert_cells_outside_heat_sources": int((alert & ~heat).sum()),
                    "mean_probability": float(np.nanmean(p)),
                }
            },
            "heat_cells": len(heat_cells),
            "heat_cells_sha256": checksum(out_dir / "heat_cells.json"),
            "land_sha256": checksum(out_dir / "land.u8"),
            "health": checks,
            "warnings": warnings,
            "inputs": {
                "detections": det_meta,
                "era5_last_day": str(era5_last),
                "ndvi_last_week": ndvi_last,
                "land_cover_year": t26.COVER_YEAR,
                "v6da_frozen_utc": release["frozen_utc"],
            },
            "code_sha256": checksum(Path(__file__)),
        },
    )
    log(
        f"{target}: day-ahead issued, on time {entry['on_time']}; v6da alerts "
        f"{entry['models']['v6da']['alert_cells']} of {entry['models']['v6da']['finite_cells']} cells"
    )
    import publish_forecasts

    publish_forecasts.publish()


def missed(target: date, error: BaseException) -> None:
    if any(e["target_day"] == str(target) for e in fl.read(LOG)):
        return
    fl.append(
        LOG,
        {
            "target_day": str(target),
            "status": "missed",
            "issue": "day_ahead",
            "issued_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "on_time": False,
            "reason": f"{type(error).__name__}: {error}"[:500],
            "code_sha256": checksum(Path(__file__)),
        },
    )
    log(f"{target}: day-ahead recorded as missed ({error})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default=str(fl.target_day(datetime.now(UTC))))
    parser.add_argument("--replay", action="store_true", help="recompute a day, no log entry")
    args = parser.parse_args()
    target = date.fromisoformat(args.day)
    try:
        forecast(target, args.replay)
    except Exception as error:
        if not args.replay and datetime.now(UTC) >= fl.midnight(target) - LAST_ATTEMPT:
            missed(target, error)
            fd.notify(f"Прогноз на завтра {target} не выпущен", f"{type(error).__name__}: {error}")
        raise
