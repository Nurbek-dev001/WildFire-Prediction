"""Real-data preparation with an opaque held-out detection archive boundary."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import yaml

from wildfire_kz.config import Config
from wildfire_kz.data import AccessGuard, checksum, dump_json
from wildfire_kz.data.adapters import firms_csv
from wildfire_kz.grid import build_grid

REQUIRED_SOURCES = {
    "boundary",
    "regions",
    "detections",
    "weather",
    "vegetation",
    "landcover",
    "static",
    "human",
}


def normalize_detection_archive(
    path: Path, grid: gpd.GeoDataFrame, year: int, cfg: Config, *, final: bool = False
) -> pd.DataFrame:
    """Check access BEFORE opening a country CSV; reject mislabeled or NRT archives."""
    AccessGuard(cfg, final=final).check([year])
    frame = firms_csv(path, grid, standard_processed=True)
    if not frame.year.eq(year).all():
        raise ValueError(f"Acquisition-year mismatch in {path.name}")
    return frame


def real_preflight(cfg: Config) -> dict[str, Any]:
    """Inspect configuration and hashes only; never read held-out observations."""
    missing = sorted(REQUIRED_SOURCES - cfg.data.sources.keys())
    invalid = []
    for name, source in cfg.data.sources.items():
        if not source.path.is_file():
            invalid.append(f"{name}: file absent")
        elif source.sha256 is None or checksum(source.path) != source.sha256:
            invalid.append(f"{name}: checksum absent or mismatched")
    sealed = {}
    released = (cfg.output_dir / "evaluate" / "test_release.json").is_file()
    for year, source in cfg.data.sealed_detection_archives.items():
        verified = (
            source.path.is_file()
            and source.sha256 is not None
            and checksum(source.path) == source.sha256
        )
        sealed[str(year)] = {
            "state": "released_by_final_stage" if released else "sealed_opaque",
            "sha256_verified": verified,
            "observations_parsed_by_preflight": False,
        }
        if not verified or year not in cfg.splits.test_years:
            invalid.append(f"sealed detections {year}: invalid registration")
    return {
        "ready": not cfg.data.synthetic and not missing and not invalid,
        "synthetic": cfg.data.synthetic,
        "missing_sources": missing,
        "invalid_sources": invalid,
        "free_disk_bytes": shutil.disk_usage(cfg.output_dir.parent).free,
        "holdout": sealed,
        "checks_performed": "paths, hashes, declared partitions only",
        "training_artifact_present": (cfg.output_dir / "train" / "_stage.json").is_file(),
        "final_release_record_present": released,
    }


def register_public_kazakhstan(
    config_path: Path, raw_root: Path, registry_path: Path
) -> dict[str, Any]:
    """Normalize verified development assets and register opaque test archives.

    The resulting config remains explicitly incomplete until every required source
    has actually been prepared. It cannot pass ingest or start model training.
    """
    manifest = json.loads(registry_path.read_text(encoding="utf-8"))
    records = manifest["sources"]
    for record in records:
        if checksum(Path(record["path"])) != record["sha256"]:
            raise ValueError(f"Downloaded asset changed: {record['path']}")
    cfg = Config()
    cfg.output_dir = config_path.resolve().parent.parent / "runs" / "primary"
    normalized = raw_root.parent / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)
    boundary = gpd.read_file(raw_root / "kaz_adm0.geojson")
    regions = gpd.read_file(raw_root / "kaz_adm1.geojson").rename(columns={"shapeName": "region"})
    boundary.to_parquet(normalized / "boundary.parquet", index=False)
    regions.to_parquet(normalized / "regions.parquet", index=False)
    print("Preparing the real national equal-area lattice", flush=True)
    grid = build_grid(boundary, cfg.grid.crs, cfg.grid.resolution_m)
    grid.to_parquet(normalized / "grid_5km.parquet", index=False)
    print(f"Grid complete: {len(grid)} clipped cells", flush=True)
    frames, audit = [], []
    for record in sorted(
        [r for r in records if r["kind"] == "detections_archive"], key=lambda r: r["year"]
    ):
        year = record["year"]
        if year in cfg.splits.test_years:
            continue  # Hashes above are the ONLY access to these bytes.
        frame = normalize_detection_archive(Path(record["path"]), grid, year, cfg)
        frame.to_parquet(normalized / f"detections_{year}.parquet", index=False)
        frames.append(frame)
        audit.append(
            {
                "year": year,
                "rows_in_boundary": len(frame),
                "nominal_high_rows": int(frame.confidence.isin(["n", "h"]).sum()),
                "observed_product_versions": sorted(frame.product_version.unique().tolist()),
                "sha256": checksum(normalized / f"detections_{year}.parquet"),
                "raw_sha256": record["sha256"],
            }
        )
        print(f"Validated and normalized {year}; holdout files remain unopened", flush=True)
    pd.concat(frames, ignore_index=True).to_parquet(
        normalized / "detections_development_calibration.parquet", index=False
    )
    data = cfg.model_dump(mode="json")
    sources = {}
    for kind, filename in {
        "boundary": "boundary.parquet",
        "regions": "regions.parquet",
        "detections": "detections_development_calibration.parquet",
    }.items():
        parent = next(
            r
            for r in records
            if r["kind"] == ("detections_archive" if kind == "detections" else kind)
        )
        path = normalized / filename
        sources[kind] = {
            "path": str(path.relative_to(config_path.resolve().parent.parent)).replace("\\", "/"),
            "source_id": parent["source_id"],
            "version": "VIIRS standard processing; versions "
            + str(sorted({v for r in audit for v in r["observed_product_versions"]}))
            if kind == "detections"
            else parent["version"],
            "downloaded_at": parent["downloaded_at"],
            "sha256": checksum(path),
            "url": parent["url"],
        }
        sources[kind]["path"] = "../" + sources[kind]["path"]
    data["output_dir"] = "../runs/primary"
    data["data"]["sources"] = sources
    data["data"]["sealed_detection_archives"] = {
        r["year"]: {
            "path": "../"
            + str(Path(r["path"]).relative_to(config_path.resolve().parent.parent)).replace(
                "\\", "/"
            ),
            "source_id": r["source_id"],
            "version": "provider annual archive; content validation deferred to final evaluation",
            "downloaded_at": r["downloaded_at"],
            "sha256": r["sha256"],
            "url": r["url"],
        }
        for r in records
        if r["kind"] == "detections_archive" and r["year"] in cfg.splits.test_years
    }
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    years = pd.date_range("2015-01-01", "2024-12-31")
    result = {
        "seed": cfg.seed,
        "synthetic": False,
        "status": "partial registration",
        "grid_cells": len(grid),
        "clipped_area_km2": float(grid.area_km2.sum()),
        "target_cell_days_before_exclusions": len(grid) * len(years),
        "dense_25_predictors_and_25_timestamps_uncompressed_bytes": len(grid) * len(years) * 50 * 8,
        "storage_estimate_note": "Arithmetic footprint, not a compressed-size prediction; excludes indexes, staging and raw rasters",
        "labels_normalized": audit,
        "holdout_state": "sealed_opaque; no CSV parsing",
        "normalization_note": "No event counts or model scores; industrial screening awaits development land-cover evidence",
        "boundary_note": "Fixed geoBoundaries OSM-derived 2017 geometry at pinned revision; not claimed to be a government boundary",
        "required_sources_still_missing": sorted(REQUIRED_SOURCES - sources.keys()),
    }
    dump_json(registry_path.parent / "registration.json", result)
    return result
