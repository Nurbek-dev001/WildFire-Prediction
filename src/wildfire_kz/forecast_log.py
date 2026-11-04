"""Issue window, map payloads and the hash-chained log of the daily forecasts.

A forecast for UTC day D is issued between 23:00 UTC of D-1 (S-NPP detections of D-1 to
21 UTC and the GFS 18 UTC run of D-1 exist) and 06:00 UTC of D (the first S-NPP pass over
Kazakhstan). Each log line carries the hash of the previous line, so no entry can be changed
or removed without breaking every later one. One entry per target day; the first stands.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

GENESIS = "0" * 64
FORMAT = "little_endian_float16_byte_shuffle_gzip"
EARLIEST_BEFORE_MIDNIGHT = timedelta(hours=1)
DEADLINE_AFTER_MIDNIGHT = timedelta(hours=6)
# The last scheduled attempt starts at 05:35 UTC; a failure from 05:30 UTC on is recorded.
LAST_ATTEMPT_AFTER_MIDNIGHT = timedelta(hours=5, minutes=30)


def midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), UTC)


def target_day(now: datetime) -> date:
    """23:00 UTC of D-1 to 06:00 UTC of D (and up to noon) all map to D."""
    return (now + timedelta(hours=12)).date()


def window(day: date) -> tuple[datetime, datetime]:
    return midnight(day) - EARLIEST_BEFORE_MIDNIGHT, midnight(day) + DEADLINE_AFTER_MIDNIGHT


def last_attempt(day: date, now: datetime) -> bool:
    return now >= midnight(day) + LAST_ATTEMPT_AFTER_MIDNIGHT


def encode(p: np.ndarray) -> bytes:
    """float16, bytes split into two planes, gzip without a timestamp (byte-reproducible)."""
    bits = np.asarray(p, dtype="<f2").view("uint8").reshape(-1, 2)
    return gzip.compress(bits.T.tobytes(), mtime=0)


def decode(payload: bytes) -> np.ndarray:
    planes = np.frombuffer(gzip.decompress(payload), dtype="uint8").reshape(2, -1)
    return np.frombuffer(planes.T.tobytes(), dtype="<f2").astype("float32")


def digest(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def read(path: Path) -> list[dict]:
    """All entries, after checking every link of the chain."""
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    previous = GENESIS
    for row in rows:
        body = {k: v for k, v in row.items() if k != "entry_sha256"}
        if row["previous_sha256"] != previous or digest(body) != row["entry_sha256"]:
            raise ValueError(f"Forecast log chain broken at {row.get('target_day')}")
        previous = row["entry_sha256"]
    days = [r["target_day"] for r in rows]
    if len(set(days)) != len(days):
        raise ValueError("Two entries for one target day")
    return rows


def append(path: Path, body: dict) -> dict:
    rows = read(path)
    if any(r["target_day"] == body["target_day"] for r in rows):
        raise FileExistsError(f"{body['target_day']} is already in the log")
    entry = {**body, "previous_sha256": rows[-1]["entry_sha256"] if rows else GENESIS}
    entry["entry_sha256"] = digest(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def summary(rows: list[dict], test: tuple[date, date]) -> dict:
    """What the prospective test will have: issued on time, late and missed days."""
    inside = [r for r in rows if test[0] <= date.fromisoformat(r["target_day"]) <= test[1]]
    issued = [r for r in inside if r["status"] == "issued"]
    return {
        "entries": len(rows),
        "test_days_total": (test[1] - test[0]).days + 1,
        "test_days_on_time": sum(r["on_time"] for r in issued),
        "test_days_late": sum(not r["on_time"] for r in issued),
        "test_days_missed": sum(r["status"] == "missed" for r in inside),
        "last": rows[-1]["target_day"] if rows else None,
    }
