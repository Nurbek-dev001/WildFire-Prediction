"""Register the actual final-run source inventory, including lossless raw archives."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from wildfire_kz.config import load_config
from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import PUBLIC, ROOT, SOURCES, permitted
from wildfire_kz.data.public_study import RUN


def register_final_sources() -> dict[str, Any]:
    permitted([2023, 2024], RUN / "release.json")
    inventory = []
    for path in sorted(PUBLIC.rglob("*")):
        if (
            not path.is_file()
            or path.suffix in [".working", ".tmp"]
            or any(part.startswith("rows_") for part in path.relative_to(PUBLIC).parts)
        ):
            continue
        entry: dict[str, Any] = {
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": checksum(path),
            "file_modified_utc": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        }
        if path.name.endswith((".sha256.json", ".provenance.json", ".unavailable.json")):
            entry["metadata"] = json.loads(path.read_text(encoding="utf-8"))
        inventory.append(entry)
    cfg = load_config(ROOT / "configs/real_public.yaml")
    contracts = {}
    for name, source in {
        **cfg.data.sources,
        **{f"sealed_archive_{y}": s for y, s in cfg.data.sealed_detection_archives.items()},
    }.items():
        record = source.model_dump(mode="json")
        record["path"] = source.path.relative_to(ROOT).as_posix()
        if checksum(source.path) != source.sha256:
            raise ValueError(f"Registered geometry/detection source changed: {name}")
        contracts[name] = record
    detections = []
    for year in range(2014, 2025):
        path = ROOT / f"data/real/normalized/detections_{year}.parquet"
        detections.append(
            {
                "year": year,
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": checksum(path),
                "bytes": path.stat().st_size,
            }
        )
    result = {
        "synthetic": False,
        "variant": "public_reprocessed_hindcast",
        "created_utc": datetime.now(UTC).isoformat(),
        "release_sha256": checksum(RUN / "release.json"),
        "source_groups": SOURCES,
        "native_metadata_evidence": [
            json.loads(p.read_text())
            for p in sorted((ROOT / "docs/source_metadata").glob("*.json"))
        ],
        "geometry_and_detection_contracts": contracts,
        "normalized_detection_partitions": detections,
        "predictor_inventory": inventory,
        "inventory_scope": "all acquired inputs, including unused boundary snapshots and preparation caches",
        "time_evidence": "provider metadata and actual download timestamps where recorded; file mtime is labelled separately, never claimed as historical publication time",
        "compressed_sources": "gzip archives retain exact original bytes, with compressed and uncompressed SHA-256 records",
        "training_sources": "training_sources.json frozen before final access; only development tables influence model selection",
        "final_weather_boundary": json.loads((RUN / "final_weather_boundary.json").read_text())
        if (RUN / "final_weather_boundary.json").is_file()
        else None,
    }
    dump_json(RUN / "acquisition_manifest.json", result)
    return result
