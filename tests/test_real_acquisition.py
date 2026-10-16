"""Real-data source guards tested with tiny artificial CSV fixtures only."""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from wildfire_kz.config import Config, Source
from wildfire_kz.data import checksum, ingest
from wildfire_kz.data.adapters import firms_csv
from wildfire_kz.data.real import normalize_detection_archive, real_preflight
from wildfire_kz.grid import build_grid


def grid_fixture():
    cfg = Config()
    boundary = gpd.GeoDataFrame(geometry=[box(-5000, -5000, 5000, 5000)], crs=cfg.grid.crs)
    return build_grid(boundary, cfg.grid.crs, 5000)


def write_csv(path: Path, version: str = "2"):
    pd.DataFrame(
        {
            "latitude": [48.001],
            "longitude": [67.001],
            "acq_date": ["2015-01-01"],
            "acq_time": ["135"],
            "confidence": ["n"],
            "satellite": ["N"],
            "instrument": ["VIIRS"],
            "version": [version],
        }
    ).to_csv(path, index=False)


def test_holdout_guard_runs_before_csv_open(tmp_path: Path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A sealed archive was opened")

    monkeypatch.setattr(pd, "read_csv", forbidden)
    with pytest.raises(PermissionError):
        normalize_detection_archive(tmp_path / "2023.csv", grid_fixture(), 2023, Config())


def test_real_csv_adapter_rejects_nrt_and_preserves_version(tmp_path: Path):
    path = tmp_path / "development.csv"
    write_csv(path, "2.0NRT")
    with pytest.raises(ValueError, match="NRT"):
        firms_csv(path, grid_fixture(), standard_processed=True)
    write_csv(path)
    frame = normalize_detection_archive(path, grid_fixture(), 2015, Config())
    assert frame.product_version.tolist() == ["2"]
    assert frame.timestamp.iloc[0] == pd.Timestamp("2015-01-01T01:35:00Z")
    with pytest.raises(ValueError, match="year mismatch"):
        normalize_detection_archive(path, grid_fixture(), 2016, Config())


def test_preflight_does_not_call_partial_acquisition_ready(tmp_path: Path):
    cfg = Config(output_dir=tmp_path / "run")
    result = real_preflight(cfg)
    assert result["ready"] is False
    assert set(result["missing_sources"]) >= {
        "weather",
        "vegetation",
        "landcover",
        "human",
        "static",
    }


def test_ingest_checksums_heldout_bytes_without_parsing(tmp_path: Path):
    opaque = tmp_path / "opaque.bin"
    opaque.write_bytes(b"not a CSV; must never be parsed during ingest")
    source = Source(
        path=opaque,
        source_id="fixture",
        version="test-only",
        downloaded_at="test fixture",
        sha256=checksum(opaque),
    )
    cfg = Config(output_dir=tmp_path / "run")
    cfg.data.sources = {
        k: source
        for k in [
            "boundary",
            "regions",
            "detections",
            "weather",
            "vegetation",
            "landcover",
            "static",
            "human",
        ]
    }
    cfg.data.sealed_detection_archives = {2023: source}
    ingest(cfg, tmp_path / "ingest")
    assert (tmp_path / "ingest" / "manifest.json").is_file()
