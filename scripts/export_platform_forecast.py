"""Publish completed REAL pipeline map artifacts into the map platform.

Reads output rasters, never raw detection archives. Refuses the synthetic smoke
model and requires a completed, hash-consistent final evaluation and map stage.
"""

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def export(run, day, destination):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("Expected an ISO target date")
    for stage in ["ingest", "train", "calibrate", "evaluate", "map"]:
        stamp = json.loads((run / stage / "_stage.json").read_text())
        if stamp.get("synthetic") is not False:
            raise ValueError("Synthetic model output cannot be registered as a real forecast")
        for filename, digest in stamp["outputs"].items():
            # Verify selected necessary artifacts without reading labels/features.
            if filename in [
                "manifest.json",
                "models.joblib",
                "frozen.json",
                "test_release.json",
                f"probability_{day}.tif",
            ]:
                if sha(run / stage / filename) != digest:
                    raise ValueError(f"Modified pipeline artifact: {stage}/{filename}")
    source = json.loads((run / "ingest/manifest.json").read_text())
    if source.get("synthetic") is not False:
        raise ValueError("Real source manifest required")
    release = json.loads((run / "evaluate/test_release.json").read_text())
    for key, filename in [
        ("frozen_sha256", "calibrate/frozen.json"),
        ("train_sha256", "train/models.joblib"),
        ("ablation_sha256", "ablate/ablations.joblib"),
    ]:
        if release[key] != sha(run / filename):
            raise ValueError("Final evaluation release does not match frozen model artifacts")
    payload = (destination / "cells.bin").read_bytes()
    records = list(struct.iter_unpack("<hhfffH8H", payload))
    cell_ids = [f"g5000_{r[0]}_{r[1]}" for r in records]
    grid = gpd.read_parquet(run / "grid/grid.parquet")
    if set(grid.cell_id) != set(cell_ids):
        raise ValueError("Forecast must use the platform's complete actual national 5 km grid")
    raster_path = run / f"map/probability_{day}.tif"
    map_stamp = json.loads((run / "map/_stage.json").read_text())
    if map_stamp["outputs"].get(raster_path.name) != sha(raster_path):
        raise ValueError("Raster is not registered in the completed map stage")
    with rasterio.open(raster_path) as raster:
        tags = raster.tags()
        if tags.get("synthetic") != "False" or tags.get("manifest_sha256") != sha(
            run / "ingest/manifest.json"
        ):
            raise ValueError("Raster provenance is not an actual matching real-data run")
        if raster.crs != grid.crs or raster.res != (5000, 5000):
            raise ValueError("Projection or resolution differs from national grid")
        probabilities = []
        for sampled in raster.sample(
            [((r[1] + 0.5) * 5000, (r[0] + 0.5) * 5000) for r in records], indexes=1, masked=True
        ):
            p = sampled[0]
            if np.ma.is_masked(p):
                probabilities.append(None)
            elif not np.isfinite(p) or not 0 <= p <= 1:
                raise ValueError("Invalid calibrated probability")
            else:
                probabilities.append(round(float(p), 8))
    predictions = destination / "predictions"
    predictions.mkdir(exist_ok=True)
    output = {
        "target_day": day,
        "synthetic": False,
        "probabilities": probabilities,
        "model": tags["model"],
        "source_manifest_sha256": tags["manifest_sha256"],
        "raster_sha256": sha(raster_path),
    }
    (predictions / f"{day}.json").write_text(
        json.dumps(output, separators=(",", ":")), encoding="utf-8"
    )
    status_path = destination / "forecast-manifest.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update(
        ready=True,
        synthetic=False,
        missing_sources=[],
        holdout_sealed=False,
        evaluation_released=True,
        model=tags["model"],
        message="Completed real-data pipeline map output",
        available_days=sorted(set(status["available_days"]) | {day}),
    )
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Registered {day}: {len(probabilities)} grid cells; real model {tags['model']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=ROOT / "runs/primary")
    parser.add_argument("--day", required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / "platform/dist/assets")
    args = parser.parse_args()
    try:
        export(args.run.resolve(), args.day, args.destination.resolve())
    except (ValueError, FileNotFoundError, KeyError) as exc:
        parser.exit(2, f"Forecast not registered: {exc}\n")
