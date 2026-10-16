"""Logging, determinism, hashing and stage caching shared by all pipeline stages."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import random
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from wildfire_kz import __version__

LOGGER_NAME = "wildfire_kz"


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def setup_logging(level: str = "INFO", log_file: Path | None = None) -> logging.Logger:
    """Configure the package logger (console + optional file); idempotent."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    if not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in logger.handlers
    ):
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        resolved = str(log_file.resolve())
        if not any(
            isinstance(h, logging.FileHandler) and h.baseFilename == resolved
            for h in logger.handlers
        ):
            fh = logging.FileHandler(log_file)
            fh.setFormatter(fmt)
            logger.addHandler(fh)
    logger.propagate = False
    return logger


def set_global_seed(seed: int) -> None:
    """Seed python, numpy and hash randomisation. Model seeds are passed explicitly."""
    random.seed(seed)
    np.random.seed(seed % (2**32))  # noqa: NPY002 - legacy global RNG used by some libraries
    os.environ["PYTHONHASHSEED"] = str(seed)


def derive_seed(seed: int, *tags: object) -> int:
    """Deterministically derive a sub-seed from the global seed and string tags."""
    h = hashlib.sha256(json.dumps([seed, *map(str, tags)]).encode()).hexdigest()
    return int(h[:8], 16)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True, default=_json_default)
    tmp.replace(path)


def read_json(path: Path) -> Any:
    with path.open() as fh:
        return json.load(fh)


def _json_default(o: Any) -> Any:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, Path):
        return str(o)
    return str(o)


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- stage cache
@dataclass
class StageRecord:
    """Metadata written next to every stage output (``_stage.json``)."""

    stage: str
    fingerprint: str
    seed: int
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)
    started: str = ""
    finished: str = ""
    package_version: str = __version__
    extra: dict[str, Any] = field(default_factory=dict)


class StageCache:
    """Idempotent stage execution: skip when the fingerprint and outputs are unchanged."""

    def __init__(
        self, stage_dir: Path, stage: str, fingerprint_payload: dict[str, Any], seed: int
    ) -> None:
        self.stage_dir = stage_dir
        self.stage = stage
        self.seed = seed
        self.fingerprint = sha256_json(
            {"stage": stage, "seed": seed, "version": __version__, **fingerprint_payload}
        )
        self.record_path = stage_dir / "_stage.json"

    def is_fresh(self) -> bool:
        if not self.record_path.exists():
            return False
        rec = read_json(self.record_path)
        if rec.get("fingerprint") != self.fingerprint:
            return False
        return all((self.stage_dir / o).exists() for o in rec.get("outputs", []))

    @contextmanager
    def run(self, force: bool = False) -> Iterator[StageRecord | None]:
        """Yield a record to fill, or ``None`` if the cached result is fresh."""
        log = get_logger(self.stage)
        if not force and self.is_fresh():
            log.info(
                "stage '%s' is up to date (fingerprint %s…) — skipping",
                self.stage,
                self.fingerprint[:12],
            )
            yield None
            return
        self.stage_dir.mkdir(parents=True, exist_ok=True)
        rec = StageRecord(
            stage=self.stage, fingerprint=self.fingerprint, seed=self.seed, started=utc_now()
        )
        log.info("running stage '%s' (seed=%d)", self.stage, self.seed)
        yield rec
        rec.finished = utc_now()
        write_json(self.record_path, rec.__dict__)
        log.info("stage '%s' finished", self.stage)


def stage_fingerprint(stage_dir: Path) -> str:
    """Fingerprint of a completed upstream stage (raises if it has not been run)."""
    path = stage_dir / "_stage.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Upstream stage output missing: {stage_dir}. Run the preceding pipeline stage first."
        )
    return str(read_json(path)["fingerprint"])
