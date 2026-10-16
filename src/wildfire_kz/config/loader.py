"""YAML loading, layered overrides and stable hashing of configuration sections."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from wildfire_kz.config.schema import Config


def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _set_dotted(tree: dict[str, Any], dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    node = tree
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value


def parse_overrides(overrides: list[str] | None) -> dict[str, Any]:
    """Parse ``key.sub=value`` strings; values are parsed as YAML scalars/lists."""
    tree: dict[str, Any] = {}
    for item in overrides or []:
        if "=" not in item:
            raise ValueError(f"override must look like key.sub=value, got {item!r}")
        key, raw = item.split("=", 1)
        _set_dotted(tree, key.strip(), yaml.safe_load(raw))
    return tree


def load_config(
    paths: list[Path] | Path | None = None, overrides: list[str] | None = None
) -> Config:
    """Load one or more YAML files (later files override earlier) plus dotted overrides.

    A file may declare ``extends: other.yaml`` (relative to itself) to inherit.
    """
    if paths is None:
        paths = []
    if isinstance(paths, Path):
        paths = [paths]
    merged: dict[str, Any] = {}
    for p in paths:
        merged = _deep_merge(merged, _read_with_extends(Path(p)))
    merged = _deep_merge(merged, parse_overrides(overrides))
    return Config.model_validate(merged)


def _read_with_extends(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    parent = data.pop("extends", None)
    if parent:
        base = _read_with_extends((path.parent / parent).resolve())
        data = _deep_merge(base, data)
    return data


def config_section_hash(cfg: Config, *sections: str) -> str:
    """Stable SHA-256 of selected top-level config sections (used for stage caching)."""
    dumped = cfg.model_dump(mode="json")
    payload = {s: dumped[s] for s in sections} if sections else dumped
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def dump_config(cfg: Config, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        yaml.safe_dump(cfg.model_dump(mode="json"), fh, sort_keys=False)
