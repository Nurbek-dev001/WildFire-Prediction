"""Access layer for feature tables with a hard guard on the test years.

Model-facing code reads features exclusively through :class:`FeatureStore`. Requests that
touch a test year raise :class:`TestSetAccessError` unless the final-evaluation ledger has
been opened by :func:`unlock_final_evaluation`, which in turn requires the calibration
artifacts (Platt parameters, decision threshold and map class boundaries) to exist and be
frozen. The ledger stores their hash; any later change to them re-locks the test data.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

import pandas as pd

from wildfire_kz.config.schema import Config
from wildfire_kz.paths import RunPaths
from wildfire_kz.utils.io import read_partitions
from wildfire_kz.utils.runtime import get_logger, read_json, sha256_file, utc_now, write_json

log = get_logger("splits.guard")

Purpose = Literal["train", "validation", "calibration", "test", "explain", "map"]
FINAL_STAGES = ("evaluate", "explain", "map", "report")


class TestSetAccessError(PermissionError):
    """Test-year data requested before the final evaluation stage."""

    __test__ = False  # not a pytest test class


def _ledger(paths: RunPaths) -> Path:
    return paths.stage("evaluate") / "final_evaluation_ledger.json"


def _calibration_file(paths: RunPaths) -> Path:
    return paths.stage("calibrate") / "calibration_artifacts.json"


def unlock_final_evaluation(cfg: Config, paths: RunPaths, stage: str) -> dict[str, str]:
    """Open the test years for a final-stage consumer (evaluate/explain/map/report)."""
    if stage not in FINAL_STAGES:
        raise TestSetAccessError(f"stage '{stage}' may not unlock the test years")
    calib = _calibration_file(paths)
    if not calib.exists():
        raise TestSetAccessError(
            "calibration, threshold and class boundaries must be frozen before the test years "
            f"can be opened (missing {calib})"
        )
    digest = sha256_file(calib)
    ledger_path = _ledger(paths)
    if ledger_path.exists():
        ledger = read_json(ledger_path)
        if ledger["calibration_sha256"] != digest:
            raise TestSetAccessError(
                "calibration artifacts changed after the test years were "
                "opened; results would be tuned on test data"
            )
        ledger.setdefault("accessed_by", []).append({"stage": stage, "at": utc_now()})
    else:
        ledger = {
            "unlocked_at": utc_now(),
            "unlocked_by": stage,
            "calibration_sha256": digest,
            "test_period": cfg.splits.resolved().test.model_dump(mode="json"),
            "accessed_by": [{"stage": stage, "at": utc_now()}],
        }
    write_json(ledger_path, ledger)
    return ledger


def test_years_unlocked(cfg: Config, paths: RunPaths) -> bool:
    ledger_path = _ledger(paths)
    calib = _calibration_file(paths)
    if not (ledger_path.exists() and calib.exists()):
        return False
    return bool(read_json(ledger_path)["calibration_sha256"] == sha256_file(calib))


class FeatureStore:
    """Guarded reader of the per-year feature partitions."""

    def __init__(self, cfg: Config, paths: RunPaths) -> None:
        self.cfg = cfg
        self.paths = paths
        self.root = paths.features

    def _check(self, touches_test: bool, touches_cal: bool, purpose: Purpose, what: str) -> None:
        if touches_test:
            if purpose not in ("test", "explain", "map"):
                raise TestSetAccessError(
                    f"{what} overlaps the test period but was requested for purpose "
                    f"'{purpose}'. Test data may never be used for training, tuning, "
                    "calibration or thresholds."
                )
            if not test_years_unlocked(self.cfg, self.paths):
                raise TestSetAccessError(
                    f"{what} overlaps the test period, which is locked until the final "
                    "evaluation stage"
                )
        if touches_cal and purpose == "train":
            raise TestSetAccessError(
                f"{what} overlaps the calibration period and may not be used for model "
                "fitting or tuning"
            )

    def load(
        self, years: list[int], purpose: Purpose, columns: list[str] | None = None
    ) -> pd.DataFrame:
        """Whole calendar years (strict: any overlap with the test period counts as test)."""
        r = self.cfg.splits.resolved()
        ys = set(years)
        self._check(
            bool(ys & set(r.test.years)),
            bool(ys & set(r.calibration.years)),
            purpose,
            f"years {sorted(ys)}",
        )
        df = read_partitions(self.root, "year", years, columns=columns)
        if df.empty:
            raise FileNotFoundError(f"no feature rows for years {years} in {self.root}")
        return df

    def load_partition(
        self,
        name: Literal["development", "calibration", "test"],
        purpose: Purpose,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        """Rows of one partition only (date-filtered; other partitions' rows are dropped)."""
        r = self.cfg.splits.resolved()
        per = getattr(r, name)
        self._check(name == "test", name == "calibration", purpose, f"partition '{name}'")
        cols = None if columns is None else list(dict.fromkeys([*columns, "date"]))
        df = read_partitions(self.root, "year", per.years, columns=cols)
        if df.empty:
            raise FileNotFoundError(f"no feature rows for partition {name} in {self.root}")
        d = pd.to_datetime(df["date"])
        df = df[(d >= pd.Timestamp(per.start)) & (d <= pd.Timestamp(per.end))]
        return df.reset_index(drop=True)


def partition_of(cfg: Config, day: pd.Timestamp | dt.date) -> str:
    """'development' | 'calibration' | 'test' | 'operational' (outside all partitions)."""
    r = cfg.splits.resolved()
    d = pd.Timestamp(day).date()
    for name in ("test", "calibration", "development"):
        if getattr(r, name).contains(d):
            return name
    return "operational"
