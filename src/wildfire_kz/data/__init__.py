"""Checksummed source registration, partitioned tables, and sealed test access."""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.dataset as ds

from wildfire_kz.config import Config


def checksum(path: Path) -> str:
    """Hash file content with bounded memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump_json(path: Path, value: Any) -> None:
    """Write JSON atomically, rejecting non-standard NaN values."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def ingest(cfg: Config, out: Path) -> None:
    """Register supplied sources; never fabricate or silently download missing data."""
    required = {"boundary", "detections", "weather", "vegetation", "landcover", "static", "human"}
    if not cfg.data.synthetic:
        required.add("regions")
    missing = required - cfg.data.sources.keys()
    if missing:
        raise FileNotFoundError(f"Register required source tables first: {sorted(missing)}")
    records = []
    for kind, source in cfg.data.sources.items():
        if not source.path.is_file():
            raise FileNotFoundError(f"{kind}: source unavailable: {source.path}")
        actual = checksum(source.path)
        if source.sha256 and actual != source.sha256:
            raise ValueError(f"Checksum mismatch: {source.path}")
        records.append({"kind": kind, **source.model_dump(mode="json"), "sha256": actual})
    dump_json(
        out / "manifest.json",
        {
            "created_utc": datetime.now(UTC).isoformat(),
            "seed": cfg.seed,
            "synthetic": cfg.data.synthetic,
            "sources": records,
            "python": platform.python_version(),
            "exclusions": []
            if cfg.data.historical_roads
            else ["Historical roads unavailable: omitted"],
        },
    )


class AccessGuard:
    """Require an explicit final-stage capability before reading held-out rows.

    This prevents accidental pipeline access; it is not an OS security boundary.
    """

    def __init__(self, cfg: Config, *, final: bool = False) -> None:
        self.cfg = cfg
        self.final = final

    def check(self, years: list[int]) -> None:
        if set(years) & set(self.cfg.splits.test_years) and not self.final:
            raise PermissionError("2023-2024 are sealed until the final evaluate stage")

    def read(self, path: Path, years: list[int]) -> pd.DataFrame:
        """Filter partition metadata before materializing a table."""
        self.check(years)
        return (
            ds.dataset(path, format="parquet", partitioning="hive")
            .to_table(filter=ds.field("year").isin(years))
            .to_pandas()
        )


def write_partitioned(frame: pd.DataFrame, path: Path) -> None:
    """Write one partition per year/month, overwriting only visited partitions."""
    frame = frame.copy()
    frame["year"] = pd.to_datetime(frame.day).dt.year
    frame["month"] = pd.to_datetime(frame.day).dt.month
    path.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False, partition_cols=["year", "month"])


def read_source(cfg: Config, name: str, *, end_year: int, final: bool = False) -> pd.DataFrame:
    """Read only requested observation years using Arrow predicate pushdown."""
    years = list(range(cfg.splits.start_year - 2, end_year + 1))
    AccessGuard(cfg, final=final).check(years)
    return pd.read_parquet(cfg.data.sources[name].path, filters=[("year", "<=", end_year)])
