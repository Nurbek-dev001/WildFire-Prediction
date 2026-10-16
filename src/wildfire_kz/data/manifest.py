"""Stage 1 — ingest: register raw data and write the data manifest.

The manifest records, for every source, its identifier, version, provider, retrieval date and
a SHA-256 checksum for every file. A missing *required* source fails with a clear message;
nothing is ever fabricated in place of missing real data.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wildfire_kz.config.schema import (
    Config,
    RasterCatalogSource,
    SourceMeta,
    VectorSource,
)
from wildfire_kz.data.synthetic import SYNTHETIC_MARKER
from wildfire_kz.utils.runtime import get_logger, read_json, sha256_file, utc_now, write_json

log = get_logger("ingest")


class MissingSourceError(RuntimeError):
    """A required data source is absent or unreadable."""


@dataclass
class SourceFiles:
    name: str
    meta: SourceMeta
    files: list[Path]


def _files_for(cfg: Config, name: str, src: SourceMeta) -> list[Path]:
    if isinstance(src, VectorSource):
        return [cfg.raw(s.path) for s in src.snapshots]
    path = cfg.raw(getattr(src, "path"))  # noqa: B009 - every non-vector source has a path
    if path.is_file():
        return [path]
    if path.is_dir():
        pattern = getattr(src, "glob", "*")
        return sorted(p for p in path.glob(pattern) if p.is_file())
    return []


def enumerate_sources(cfg: Config) -> list[SourceFiles]:
    out: list[SourceFiles] = []
    for name in type(cfg.sources).model_fields:
        src = getattr(cfg.sources, name)
        if src is None:
            continue
        out.append(SourceFiles(name=name, meta=src, files=_files_for(cfg, name, src)))
    return out


def is_synthetic(cfg: Config) -> bool:
    return (cfg.project.raw_dir / SYNTHETIC_MARKER).exists()


def _checksum_cached(path: Path, cache: dict[str, Any]) -> str:
    st = path.stat()
    key = str(path.resolve())
    hit = cache.get(key)
    if hit and hit["size"] == st.st_size and hit["mtime"] == st.st_mtime:
        return str(hit["sha256"])
    digest = sha256_file(path)
    cache[key] = {"size": st.st_size, "mtime": st.st_mtime, "sha256": digest}
    return digest


def build_manifest(cfg: Config, cache_path: Path | None = None) -> dict[str, Any]:
    """Validate presence of every source and checksum all files."""
    cache: dict[str, Any] = read_json(cache_path) if cache_path and cache_path.exists() else {}
    synthetic = is_synthetic(cfg)
    entries: dict[str, Any] = {}
    problems: list[str] = []
    for sf in enumerate_sources(cfg):
        meta = sf.meta.model_dump(mode="json")
        if not sf.files:
            msg = f"source '{sf.name}' ({sf.meta.source_id}) has no files at " \
                  f"{_describe_location(cfg, sf)}"
            if sf.meta.required:
                problems.append(msg)
            else:
                log.warning("%s — optional, continuing (it will be omitted and flagged)", msg)
        missing = [p for p in sf.files if not p.exists()]
        if missing:
            problems.append(f"source '{sf.name}': listed files do not exist: {missing[:3]}")
        files = []
        for p in sf.files:
            if not p.exists():
                continue
            st = p.stat()
            files.append({
                "path": str(p), "bytes": st.st_size, "sha256": _checksum_cached(p, cache),
                "modified_utc": dt.datetime.fromtimestamp(st.st_mtime, dt.UTC).isoformat(),
            })
        if isinstance(sf.meta, RasterCatalogSource):
            meta["backend"] = sf.meta.backend
        entries[sf.name] = {"meta": meta, "n_files": len(files), "files": files,
                            "retrieved_on": str(sf.meta.retrieved_on or "unrecorded")}
    if problems:
        raise MissingSourceError(
            "Required data sources are missing — the pipeline will not fabricate data.\n  - "
            + "\n  - ".join(problems)
            + "\nObtain the data (see docs/data_acquisition.md or `wildfire-kz download ...`), "
            "or generate a SYNTHETIC dataset with `wildfire-kz synth` for offline testing."
        )
    if cache_path:
        write_json(cache_path, cache)
    return {
        "created_utc": utc_now(), "project": cfg.project.name, "run_label": cfg.project.run_label,
        "seed": cfg.project.seed, "synthetic": synthetic,
        "synthetic_notice": ("ALL INPUT DATA ARE SYNTHETIC — results are not findings about "
                             "Kazakhstan") if synthetic else "",
        "crs": cfg.crs.model_dump(), "study": cfg.study.model_dump(mode="json"),
        "sources": entries,
    }


def _describe_location(cfg: Config, sf: SourceFiles) -> str:
    if isinstance(sf.meta, VectorSource):
        return "configured snapshots (none listed)" if not sf.meta.snapshots else "snapshots"
    return str(cfg.raw(getattr(sf.meta, "path")))  # noqa: B009


def run_ingest(cfg: Config, out_dir: Path) -> Path:
    manifest = build_manifest(cfg, cache_path=out_dir / "checksum_cache.json")
    path = out_dir / "data_manifest.json"
    write_json(path, manifest)
    n = sum(e["n_files"] for e in manifest["sources"].values())
    log.info("manifest written: %d files across %d sources (synthetic=%s)", n,
             len(manifest["sources"]), manifest["synthetic"])
    return path
