"""Put every issued daily forecast on the map and write the alert bulletin of the latest day.

Reads the hash-chained log (runs/forecast_live/log.jsonl), copies each issued v6 and v7
payload next to the site and writes platform/dist/assets/forecast-live.json, which binds
each map to its log entry by SHA-256. The site merges these days into the v6 timeline and
shows v7 as a third model. The registered v6 manifest and its records are not changed.
Day-ahead v6da forecasts (runs/forecast_live/dayahead.jsonl) go to the record's `dayahead`
block; while the latest of them is for a later day than the latest morning issue, the bot's
bulletin is the day-ahead one.
Usage: publish_forecasts.py   (forecast_daily.py and forecast_dayahead.py run it after an issue)
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from wildfire_kz import forecast_log as fl  # noqa: E402
from wildfire_kz.data import checksum, dump_json  # noqa: E402

LIVE = ROOT / "runs/forecast_live"
SITE = ROOT / "platform/dist"
ASSETS = SITE / "assets"
TEST = ("2027-03-01", "2027-10-31")
MODELS = {"v6": ROOT / "runs/model_v6", "v7": ROOT / "runs/model_v7"}


def development_v7() -> dict:
    """v7's rolling-origin development results and their bootstrap, for the report."""
    folder = MODELS["v7"] / "experiments/v7_candidate"
    with (folder / "metrics.csv").open(encoding="utf-8") as stream:
        rows = [
            {
                k: (v if k in {"model", "inputs"} else float(v))
                for k, v in r.items()
                if k
                in {
                    "origin",
                    "model",
                    "inputs",
                    "ap",
                    "bss",
                    "recall_at_v6_recipe_precision",
                    "reliability_spread",
                }
            }
            for r in csv.DictReader(stream)
        ]
    boot = folder / "bootstrap.json"
    return {
        "origins": rows,
        "paired_bootstrap_95": json.loads(boot.read_text()) if boot.exists() else None,
        "selection_rule_met": False,
        "decision": "challenger: the prospective 2027 test decides the default",
    }


LAND = ["лес", "степь", "кустарник", "пашня", "прочее"]
# Region names in Kazakh, by the English name of geography.json (as the site's i18n.js).
KAZAKH = {
    "Pavlodar Region": "Павлодар",
    "Jambyl Region": "Жамбыл",
    "Kostanay Region": "Қостанай",
    "Mangystau Region": "Маңғыстау",
    "Karaganda Region": "Қарағанды",
    "Kyzylorda Region": "Қызылорда",
    "East Kazakhstan Region": "Шығыс Қазақстан",
    "Aktobe Region": "Ақтөбе",
    "Atyrau Region": "Атырау",
    "South Kazakhstan Region": "Оңтүстік Қазақстан",
    "Akmola Region": "Ақмола",
    "Almaty Region": "Алматы облысы",
    "North Kazakhstan Region": "Солтүстік Қазақстан",
    "Almaty": "Алматы",
    "West Kazakhstan Region": "Батыс Қазақстан",
    "Astana": "Астана",
}


def bulletin(
    day: str, values: dict[str, np.ndarray], thresholds: dict, heat: set[int], entry: dict
) -> Path:
    """Cells on alert by either model, outside persistent heat sources, highest v7 first."""
    raw = np.frombuffer((ASSETS / "cells.bin").read_bytes(), dtype=np.uint8).reshape(-1, 34)
    lon = raw[:, 8:12].copy().view("<f4").ravel()
    lat = raw[:, 12:16].copy().view("<f4").ravel()
    region = raw[:, 16:18].copy().view("<u2").ravel()
    regions = json.loads((ASSETS / "geography.json").read_text(encoding="utf-8"))["regions"]
    labels = [r["label"] for r in regions]
    alert = {k: values[k] >= thresholds[k] for k in values}
    path_land = LIVE / f"forecasts/{day}/land.u8"
    codes = np.frombuffer(path_land.read_bytes(), dtype=np.uint8) if path_land.exists() else None
    land = [LAND[c] for c in codes] if codes is not None else [""] * len(lon)
    cells = [i for i in np.flatnonzero(alert["v6"] | alert["v7"]) if int(i) not in heat]
    cells.sort(key=lambda i: -float(np.nan_to_num(values["v7"][i])))
    path = LIVE / f"bulletins/{day}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    # BOM so that Excel opens the Cyrillic region names correctly.
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        w = csv.writer(stream)
        w.writerow(
            ["target_day", "region", "lat", "lon", "land", "p_v7", "p_v6", "alert_v7", "alert_v6"]
        )
        for i in cells:
            w.writerow(
                [
                    day,
                    labels[region[i]],
                    f"{lat[i]:.4f}",
                    f"{lon[i]:.4f}",
                    land[i],
                    f"{values['v7'][i]:.5f}",
                    f"{values['v6'][i]:.5f}",
                    int(alert["v7"][i]),
                    int(alert["v6"][i]),
                ]
            )
    # The same alerts for the Telegram bot, with region names in three languages.
    dump_json(
        ASSETS / "bulletin-latest.json",
        {
            "synthetic": False,
            "kind": "morning",
            "target_day": day,
            "issued_utc": entry["issued_utc"],
            "on_time": entry["on_time"],
            "warnings": entry.get("warnings", []),
            "thresholds": thresholds,
            "eligible_cells": entry["models"]["v6"]["finite_cells"],
            "regions": [
                {
                    "ru": r["label"],
                    "en": r["name"].replace(" Region", ""),
                    "kk": KAZAKH.get(r["name"], r["label"]),
                }
                for r in regions
            ],
            "alerts": [
                {
                    "region": int(region[i]),
                    "lat": round(float(lat[i]), 4),
                    "lon": round(float(lon[i]), 4),
                    "land": land[i],
                    "p_v7": round(float(values["v7"][i]), 5),
                    "p_v6": round(float(values["v6"][i]), 5),
                    "v7": bool(alert["v7"][i]),
                    "v6": bool(alert["v6"][i]),
                    # One scale for the bot whatever the bulletin's kind.
                    "p": round(float(values["v7"][i]), 5),
                    "strong": bool(alert["v7"][i]),
                }
                for i in cells
            ],
        },
    )
    return path


def publish() -> dict:
    rows = fl.read(LIVE / "log.jsonl")
    issued = [r for r in rows if r["status"] == "issued"]
    registered_v6 = checksum(SITE / "v6/release.json")
    count = (ASSETS / "cells.bin").stat().st_size // 34
    assets: dict[str, dict] = {"v6": {}, "v7": {}}
    for r in issued:
        day = r["target_day"]
        for name in assets:
            m = r["models"][name]
            source = LIVE / m["payload"]
            if checksum(source) != m["payload_sha256"]:
                raise ValueError(f"{day} {name}: payload differs from its log entry")
            if name == "v6" and m["release_sha256"] != registered_v6:
                raise ValueError("Live v6 release differs from the one on the site")
            target = ASSETS / f"predictions-{name}/{day}.f16.gz"
            if not target.exists() or checksum(target) != m["payload_sha256"]:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            assets[name][day] = {
                "target_day": day,
                "synthetic": False,
                "model": f"xgboost_{name}",
                "format": m["format"],
                "count": count,
                "finite_cells": m["finite_cells"],
                "alert_cells": m["alert_cells"],
                "payload_sha256": m["payload_sha256"],
                "release_sha256": m["release_sha256"],
                "retrospective": False,
                "issued_utc": r["issued_utc"],
                "on_time": r["on_time"],
                "log_entry_sha256": r["entry_sha256"],
            }
    frozen = {k: json.loads((v / "frozen.json").read_text()) for k, v in MODELS.items()}
    v7_release = json.loads((MODELS["v7"] / "release.json").read_text())
    heat: list[int] = []
    if issued:
        last = issued[-1]
        heat_path = LIVE / f"forecasts/{last['target_day']}/heat_cells.json"
        if checksum(heat_path) != last["heat_cells_sha256"]:
            raise ValueError("Heat-source list differs from its log entry")
        heat = json.loads(heat_path.read_text())
    record = {
        "synthetic": False,
        "kind": "daily_forecasts",
        "updated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "test_period": list(TEST),
        "log_last_entry_sha256": rows[-1]["entry_sha256"] if rows else fl.GENESIS,
        "summary": fl.summary(rows, tuple(datetime.fromisoformat(d).date() for d in TEST)),
        "missed_days": [r["target_day"] for r in rows if r["status"] == "missed"],
        "days": [r["target_day"] for r in issued],
        "models": {
            "v6": {
                "model": "xgboost_v6",
                "release_sha256": registered_v6,
                "threshold": frozen["v6"]["threshold"],
                "prediction_path": "./assets/predictions-v6/",
            },
            "v7": {
                "model": "xgboost_v7",
                "release_sha256": checksum(MODELS["v7"] / "release.json"),
                "frozen_utc": v7_release["frozen_utc"],
                "threshold": frozen["v7"]["threshold"],
                "input_features": frozen["v7"]["features"],
                "calibration": frozen["v7"]["calibration"],
                "calibration_metrics": frozen["v7"]["calibration_metrics"],
                "prediction_path": "./assets/predictions-v7/",
                "development": development_v7(),
            },
        },
        "assets": assets,
        "heat_cells": heat,
    }
    last = issued[-1]["target_day"] if issued else ""
    ahead = dayahead(count, last)
    if ahead:
        record["dayahead"] = ahead
    dump_json(ASSETS / "forecast-live.json", record)
    if issued:
        values = {
            k: fl.decode((ASSETS / f"predictions-{k}/{last}.f16.gz").read_bytes()) for k in assets
        }
        thresholds = {k: frozen[k]["threshold"] for k in assets}
        shutil.copyfile(
            bulletin(last, values, thresholds, set(heat), issued[-1]),
            ASSETS / "bulletin-latest.csv",
        )
    # The day-ahead forecast of a later day is the latest news until that day's morning issue.
    if ahead and ahead["tomorrow"]:
        bulletin_dayahead(ahead["tomorrow"])
    return record


def dayahead(count: int, last_main: str) -> dict | None:
    """Day-ahead v6da forecasts from their own log (forecast_dayahead.py), bound to the site the
    same way; `tomorrow` is the latest one when its day has no morning issue yet."""
    path = LIVE / "dayahead.jsonl"
    rows = fl.read(path) if path.exists() else []
    issued = [r for r in rows if r["status"] == "issued"]
    if not issued:
        return None
    folder = ROOT / "runs/model_v6da"
    release = checksum(folder / "release.json")
    frozen = json.loads((folder / "frozen.json").read_text())
    assets = {}
    for r in issued:
        day, m = r["target_day"], r["models"]["v6da"]
        if m["release_sha256"] != release:
            raise ValueError(f"{day}: day-ahead release differs from runs/model_v6da")
        source = LIVE / m["payload"]
        if checksum(source) != m["payload_sha256"]:
            raise ValueError(f"{day} v6da: payload differs from its log entry")
        target = ASSETS / f"predictions-v6da/{day}.f16.gz"
        if not target.exists() or checksum(target) != m["payload_sha256"]:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        assets[day] = {
            "target_day": day,
            "synthetic": False,
            "model": "xgboost_v6da",
            "format": m["format"],
            "count": count,
            "finite_cells": m["finite_cells"],
            "alert_cells": m["alert_cells"],
            "payload_sha256": m["payload_sha256"],
            "release_sha256": release,
            "retrospective": False,
            "issued_utc": r["issued_utc"],
            "on_time": r["on_time"],
            "log_entry_sha256": r["entry_sha256"],
        }
    latest = issued[-1]["target_day"]
    return {
        "model": "xgboost_v6da",
        "release_sha256": release,
        "threshold": frozen["threshold"],
        "era5_lag_days": frozen["era5_lag_days"],
        "prediction_path": "./assets/predictions-v6da/",
        "log_last_entry_sha256": rows[-1]["entry_sha256"],
        "days": [r["target_day"] for r in issued],
        "missed_days": [r["target_day"] for r in rows if r["status"] == "missed"],
        "assets": assets,
        "tomorrow": latest if latest > last_main else None,
    }


def bulletin_dayahead(day: str) -> None:
    """The bot's bulletin for a day-ahead forecast: v6da alerts outside heat sources."""
    entry = next(r for r in fl.read(LIVE / "dayahead.jsonl") if r["target_day"] == day)
    folder = LIVE / f"dayahead/{day}"
    if checksum(folder / "heat_cells.json") != entry["heat_cells_sha256"]:
        raise ValueError("Day-ahead heat-source list differs from its log entry")
    heat = set(json.loads((folder / "heat_cells.json").read_text()))
    p = fl.decode((ASSETS / f"predictions-v6da/{day}.f16.gz").read_bytes())
    threshold = entry["models"]["v6da"]["threshold"]
    raw = np.frombuffer((ASSETS / "cells.bin").read_bytes(), dtype=np.uint8).reshape(-1, 34)
    lon = raw[:, 8:12].copy().view("<f4").ravel()
    lat = raw[:, 12:16].copy().view("<f4").ravel()
    region = raw[:, 16:18].copy().view("<u2").ravel()
    regions = json.loads((ASSETS / "geography.json").read_text(encoding="utf-8"))["regions"]
    codes = np.frombuffer((folder / "land.u8").read_bytes(), dtype=np.uint8)
    cells = [i for i in np.flatnonzero(p >= threshold) if int(i) not in heat]
    cells.sort(key=lambda i: -float(p[i]))
    dump_json(
        ASSETS / "bulletin-latest.json",
        {
            "synthetic": False,
            "kind": "dayahead",
            "model": "v6da",
            "target_day": day,
            "issued_utc": entry["issued_utc"],
            "on_time": entry["on_time"],
            "warnings": entry.get("warnings", []),
            "thresholds": {"v6da": threshold},
            "eligible_cells": entry["models"]["v6da"]["finite_cells"],
            "regions": [
                {
                    "ru": r["label"],
                    "en": r["name"].replace(" Region", ""),
                    "kk": KAZAKH.get(r["name"], r["label"]),
                }
                for r in regions
            ],
            "alerts": [
                {
                    "region": int(region[i]),
                    "lat": round(float(lat[i]), 4),
                    "lon": round(float(lon[i]), 4),
                    "land": LAND[codes[i]],
                    "p": round(float(p[i]), 5),
                    "strong": False,
                }
                for i in cells
            ],
        },
    )


if __name__ == "__main__":
    r = publish()
    print(json.dumps({"days": len(r["days"]), "summary": r["summary"]}))
