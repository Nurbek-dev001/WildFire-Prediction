"""Access layer for feature tables with a hard guard on the test years.

Model-facing code reads features exclusively through :class:`FeatureStore`. Requests that
touch a test year raise :class:`TestSetAccessError` unless the final-evaluation ledger has
been opened by :func:`unlock_final_evaluation`, which in turn requires the calibration
artifacts (Platt parameters, decision threshold and map class boundaries) to exist and be
frozen. The ledger stores their hash; any later change to them re-locks the test data.
"""

from __future__ import annotations

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
            f"can be opened (missing {calib})")
    digest = sha256_file(calib)
    ledger_path = _ledger(paths)
    if ledger_path.exists():
        ledger = read_json(ledger_path)
        if ledger["calibration_sha256"] != digest:
            raise TestSetAccessError("calibration artifacts changed after the test years were "
                                     "opened; results would be tuned on test data")
        ledger.setdefault("accessed_by", []).append({"stage": stage, "at": utc_now()})
    else:
        ledger = {"unlocked_at": utc_now(), "unlocked_by": stage,
                  "calibration_sha256": digest, "test_years": cfg.splits.test_years,
                  "accessed_by": [{"stage": stage, "at": utc_now()}]}
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

    def load(self, years: list[int], purpose: Purpose,
             columns: list[str] | None = None) -> pd.DataFrame:
        test = set(years) & set(self.cfg.splits.test_years)
        if test:
            if purpose not in ("test", "explain", "map"):
                raise TestSetAccessError(
                    f"test years {sorted(test)} requested for purpose '{purpose}'. Test data "
                    "may never be used for training, tuning, calibration or thresholds.")
            if not test_years_unlocked(self.cfg, self.paths):
                raise TestSetAccessError(
                    f"test years {sorted(test)} are locked until the final evaluation stage")
        cal = set(years) & set(self.cfg.splits.calibration_years)
        if cal and purpose == "train":
            raise TestSetAccessError(f"calibration years {sorted(cal)} may not be used for "
                                     "model fitting or tuning")
        df = read_partitions(self.root, "year", years, columns=columns)
        if df.empty:
            raise FileNotFoundError(f"no feature rows for years {years} in {self.root}")
        return df
