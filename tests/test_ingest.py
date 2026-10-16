"""Ingest never fabricates data: missing required sources fail with a clear message."""

from __future__ import annotations

from pathlib import Path

import pytest

from wildfire_kz.config.schema import Config
from wildfire_kz.data.manifest import MissingSourceError, build_manifest


def test_missing_required_sources_fail_clearly(tmp_path: Path) -> None:
    cfg = Config.model_validate({"project": {"raw_dir": str(tmp_path)}})
    with pytest.raises(MissingSourceError) as err:
        build_manifest(cfg)
    msg = str(err.value)
    assert "will not fabricate data" in msg
    for source in ("firms", "era5_land", "mod13a2", "mcd12q1", "srtm", "worldpop"):
        assert f"'{source}'" in msg


def test_optional_sources_may_be_absent(tmp_path: Path) -> None:
    cfg = Config.model_validate({"project": {"raw_dir": str(tmp_path)}})
    with pytest.raises(MissingSourceError) as err:
        build_manifest(cfg)
    assert "'roads'" not in str(err.value) and "'settlements'" not in str(err.value)
