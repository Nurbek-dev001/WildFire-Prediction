"""Canonical artifact layout for a run (``<work_dir>/<run_label>/<stage>/...``)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wildfire_kz.config.schema import Config

STAGES = (
    "ingest",
    "grid",
    "events",
    "risk_set",
    "sampling",
    "features",
    "splits",
    "train",
    "calibrate",
    "ablate",
    "evaluate",
    "explain",
    "map",
    "report",
    "forecast",
)


@dataclass(frozen=True)
class RunPaths:
    root: Path
    grid_variant: str

    @classmethod
    def from_config(cls, cfg: Config) -> RunPaths:
        return cls(root=cfg.run_dir, grid_variant=cfg.grid.active)

    def stage(self, name: str) -> Path:
        if name not in STAGES:
            raise KeyError(name)
        # grid-dependent stages are namespaced by grid variant so that the 1 km
        # sensitivity grid never overwrites primary 5 km artifacts.
        if name in ("ingest",):
            return self.root / name
        return self.root / self.grid_variant / name

    # ---- frequently used files
    @property
    def manifest(self) -> Path:
        return self.stage("ingest") / "data_manifest.json"

    @property
    def grid_file(self) -> Path:
        return self.stage("grid") / "grid.parquet"

    @property
    def grid_meta(self) -> Path:
        return self.stage("grid") / "grid_meta.json"

    @property
    def detections(self) -> Path:
        return self.stage("events") / "detections_qc.parquet"

    @property
    def events_table(self) -> Path:
        return self.stage("events") / "events.parquet"

    @property
    def positives(self) -> Path:
        return self.stage("events") / "positives.parquet"

    @property
    def risk_set(self) -> Path:
        return self.stage("risk_set") / "risk_set"

    @property
    def sample(self) -> Path:
        return self.stage("sampling") / "sample"

    @property
    def features(self) -> Path:
        return self.stage("features") / "features"

    @property
    def log_dir(self) -> Path:
        return self.root / "logs"
