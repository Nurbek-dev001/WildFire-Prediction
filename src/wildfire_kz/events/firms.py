"""Reading and quality control of FIRMS Suomi-NPP VIIRS 375 m archive detections."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from wildfire_kz.config.schema import FirmsSource
from wildfire_kz.utils.runtime import get_logger

log = get_logger("events.firms")

REQUIRED_COLUMNS = ("latitude", "longitude", "acq_date", "acq_time", "confidence")
CONFIDENCE_RANK = {"h": 0, "n": 1, "l": 2}  # lower = preferred in tie-breaking


@dataclass
class QCCounts:
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, key: str, n: int) -> None:
        self.counts[key] = self.counts.get(key, 0) + int(n)


def parse_acq_datetime(acq_date: pd.Series, acq_time: pd.Series) -> pd.Series:
    """Combine FIRMS ``acq_date`` (YYYY-MM-DD, UTC) and ``acq_time`` (HHMM, UTC)."""
    hhmm = pd.to_numeric(acq_time, errors="coerce").fillna(-1).astype(int)
    if (hhmm < 0).any() or (hhmm % 100 >= 60).any() or (hhmm // 100 >= 24).any():
        raise ValueError("invalid FIRMS acq_time values (expected HHMM in UTC)")
    base = pd.to_datetime(acq_date, format="%Y-%m-%d", utc=False)
    return base + pd.to_timedelta(hhmm // 100, unit="h") + pd.to_timedelta(hhmm % 100, unit="m")


def read_firms(files: list[Path], src: FirmsSource, qc: QCCounts) -> pd.DataFrame:
    """Read archive CSVs, validate schema and apply confidence / sensor filters.

    VIIRS confidence is the categorical l/n/h flag. It is NEVER mapped to MODIS-style
    percentages; numeric confidence values are rejected.
    """
    if not files:
        raise FileNotFoundError("no FIRMS files registered")
    frames = []
    for f in files:
        df = pd.read_csv(f, dtype={"confidence": str, "acq_date": str, "satellite": str})
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"{f}: missing FIRMS columns {missing}")
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    qc.add("raw_rows", len(df))
    conf = df["confidence"].astype(str).str.strip().str.lower()
    unknown = ~conf.isin(list(CONFIDENCE_RANK))
    if unknown.any():
        sample = conf[unknown].unique()[:5].tolist()
        raise ValueError(
            "VIIRS confidence must be categorical l/n/h (not MODIS percentages); found "
            f"{sample}. Check that the file is a VIIRS (not MODIS) product."
        )
    df["confidence"] = conf
    if "satellite" in df.columns:
        sat_ok = (
            df["satellite"]
            .astype(str)
            .str.upper()
            .isin([src.expected_satellite.upper(), "SUOMI NPP", "NPP"])
        )
        qc.add("dropped_other_satellite", int((~sat_ok).sum()))
        df = df[sat_ok]
    if "instrument" in df.columns:
        ins_ok = df["instrument"].astype(str).str.upper() == src.expected_instrument.upper()
        qc.add("dropped_other_instrument", int((~ins_ok).sum()))
        df = df[ins_ok]
    low = df["confidence"].isin(src.drop_confidence)
    qc.add("dropped_low_confidence", int(low.sum()))
    df = df[~low & df["confidence"].isin(src.keep_confidence)].copy()
    df["acq_datetime"] = parse_acq_datetime(df["acq_date"], df["acq_time"])
    df["confidence_rank"] = df["confidence"].map(CONFIDENCE_RANK).astype(np.int8)
    if "frp" not in df.columns:
        df["frp"] = np.nan
    if "type" not in df.columns:
        df["type"] = -1  # unknown; source-type screening falls back to the industrial mask
        log.warning("FIRMS files lack the `type` field; relying on industrial mask only")
    return df.reset_index(drop=True)


def deduplicate(df: pd.DataFrame, decimals: int, qc: QCCounts) -> pd.DataFrame:
    """Remove exact duplicates (same rounded location and acquisition time)."""
    key = pd.DataFrame(
        {
            "lat": df["latitude"].round(decimals),
            "lon": df["longitude"].round(decimals),
            "t": df["acq_datetime"],
        }
    )
    dup = key.duplicated(keep="first")
    qc.add("dropped_duplicates", int(dup.sum()))
    return df.loc[~dup].reset_index(drop=True)
