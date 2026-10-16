"""Declarative stage registry: dependencies, config sections that affect each stage, runners.

Every stage is idempotent: its fingerprint combines the relevant configuration sections, the
fingerprints of its upstream stages and the global seed. A stage whose fingerprint and outputs
are unchanged is skipped (unless forced).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from wildfire_kz.config.loader import dump_config
from wildfire_kz.config.schema import Config
from wildfire_kz.paths import RunPaths
from wildfire_kz.utils.runtime import (
    StageCache,
    get_logger,
    set_global_seed,
    setup_logging,
    stage_fingerprint,
)

log = get_logger("pipeline")

Runner = Callable[[Config, RunPaths], dict[str, Any]]


@dataclass(frozen=True)
class Stage:
    name: str
    sections: tuple[str, ...]
    upstream: tuple[str, ...]
    outputs: tuple[str, ...]
    runner: Runner


def _subset(cfg: Config, keys: tuple[str, ...]) -> dict[str, Any]:
    dumped = cfg.model_dump(mode="json")
    out: dict[str, Any] = {}
    for key in keys:
        node: Any = dumped
        for part in key.split("."):
            node = node[part]
        out[key] = node
    return out


# --------------------------------------------------------------------------- runners
def _ingest(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.data.manifest import run_ingest

    path = run_ingest(cfg, p.stage("ingest"))
    return {"manifest": str(path)}


def _grid(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.grid.grid import run_grid

    return run_grid(cfg, p.stage("grid"))


def _events(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.events.build import run_events

    return run_events(cfg, p.grid_file, p.grid_meta, p.stage("events"))


def _risk_set(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.sampling.risk_set import run_risk_set

    return run_risk_set(cfg, p.grid_file, p.stage("events"), p.stage("risk_set"))


def _sampling(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.sampling.design import run_sampling

    return run_sampling(cfg, p.grid_file, p.grid_meta, p.stage("risk_set"), p.stage("sampling"))


def _features(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.features.build import run_features

    return run_features(cfg, p)


def _splits(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.splits.build import run_splits

    return run_splits(cfg, p)


def _train(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.models.train import run_train

    return run_train(cfg, p)


def _calibrate(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.calibration.calibrate import run_calibrate

    return run_calibrate(cfg, p)


def _ablate(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.models.ablation import run_ablation

    return run_ablation(cfg, p)


def _evaluate(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.evaluation.evaluate import run_evaluate

    return run_evaluate(cfg, p)


def _explain(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.explain.shap_analysis import run_explain

    return run_explain(cfg, p)


def _map(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.mapping.export import run_map

    return run_map(cfg, p)


def _report(cfg: Config, p: RunPaths) -> dict[str, Any]:
    from wildfire_kz.report.build import run_report

    return run_report(cfg, p)


STAGE_LIST: tuple[Stage, ...] = (
    Stage(
        "ingest",
        ("sources", "study", "crs", "project.raw_dir"),
        (),
        ("data_manifest.json",),
        _ingest,
    ),
    Stage(
        "grid",
        ("crs", "grid", "sources.boundary"),
        ("ingest",),
        ("grid.parquet", "grid_meta.json"),
        _grid,
    ),
    Stage(
        "events",
        (
            "events",
            "sources.firms",
            "sources.boundary",
            "sources.mcd12q1",
            "study",
            "splits.development_years",
        ),
        ("grid",),
        ("detections_qc.parquet", "events.parquet", "positives.parquet"),
        _events,
    ),
    Stage("risk_set", ("risk_set", "study"), ("events",), ("risk_set_summary.json",), _risk_set),
    Stage(
        "sampling",
        ("sampling", "sources.mcd12q1", "study"),
        ("risk_set",),
        ("sampling_summary.json", "landcover_fractions.parquet"),
        _sampling,
    ),
    Stage(
        "features",
        ("features", "sources", "study"),
        ("sampling",),
        ("feature_registry.json", "leakage_report.json"),
        _features,
    ),
    Stage(
        "splits",
        ("splits", "evaluation.bootstrap"),
        ("features",),
        ("temporal_splits.json", "spatial_blocks.parquet"),
        _splits,
    ),
    Stage(
        "train",
        ("models", "splits", "sampling.training_weighting", "features"),
        ("splits",),
        ("selection.json",),
        _train,
    ),
    Stage(
        "calibrate",
        ("calibration", "mapping.class_quantiles", "splits.calibration_years"),
        ("train",),
        ("calibration_artifacts.json",),
        _calibrate,
    ),
    Stage(
        "ablate",
        ("ablation", "features.groups"),
        ("calibrate",),
        ("ablation_validation.csv",),
        _ablate,
    ),
    Stage(
        "evaluate",
        ("evaluation", "splits.test_years"),
        ("calibrate", "ablate"),
        ("metrics_overall.csv",),
        _evaluate,
    ),
    Stage("explain", ("explain",), ("evaluate",), ("shap_global_importance.csv",), _explain),
    Stage("map", ("mapping",), ("evaluate",), ("map_index.csv",), _map),
    Stage("report", (), ("evaluate", "explain", "map"), ("REPORT.md",), _report),
)
STAGES = {s.name: s for s in STAGE_LIST}


def _source_listing(cfg: Config) -> list[tuple[str, int, float]]:
    from wildfire_kz.data.manifest import enumerate_sources

    out = []
    for sf in enumerate_sources(cfg):
        for f in sf.files:
            if f.exists():
                st = f.stat()
                out.append((str(f), st.st_size, st.st_mtime))
    return out


def run_stage(name: str, cfg: Config, force: bool = False) -> dict[str, Any] | None:
    stage = STAGES[name]
    paths = RunPaths.from_config(cfg)
    setup_logging(cfg.project.log_level, paths.log_dir / "pipeline.log")
    set_global_seed(cfg.project.seed)
    payload: dict[str, Any] = {
        "config": _subset(cfg, stage.sections),
        "grid_variant": cfg.grid.active,
    }
    payload["upstream"] = {u: stage_fingerprint(paths.stage(u)) for u in stage.upstream}
    if name == "ingest":
        payload["files"] = _source_listing(cfg)
    cache = StageCache(paths.stage(name), name, payload, cfg.project.seed)
    with cache.run(force=force) as rec:
        if rec is None:
            return None
        dump_config(cfg, paths.stage(name) / "config_resolved.yaml")
        summary = stage.runner(cfg, paths)
        rec.outputs = list(stage.outputs)
        rec.inputs = payload["upstream"]
        rec.extra = {"summary": summary}
        missing = [o for o in stage.outputs if not (paths.stage(name) / o).exists()]
        if missing:
            raise RuntimeError(f"stage '{name}' did not produce expected outputs {missing}")
        return summary


def run_all(cfg: Config, until: str | None = None, force: bool = False) -> None:
    for stage in STAGE_LIST:
        run_stage(stage.name, cfg, force=force)
        if until == stage.name:
            break
