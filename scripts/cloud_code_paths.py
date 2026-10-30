"""Cloud only: give the frozen code checks the files they recorded on Windows.

Releases and registries under runs/ pin code files by SHA-256 as they were on Windows: paths
with backslashes and, for some files, CRLF line ends. Their checks are frozen code and cannot
change, so on Linux each pinned file is provided at the recorded path, in the recorded bytes,
and only when those bytes hash to the recorded value. Nothing is relaxed: a file whose content
differs from its release still fails the release check.
Usage: cloud_code_paths.py   (forecast.yml runs it before the forecast)
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIGEST = re.compile(r"^[0-9a-f]{64}$")


def pins(value: object) -> list[tuple[str, str]]:
    """Every {"some/code.py": "<sha256>"} pair anywhere in a JSON document."""
    out = []
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, str) and DIGEST.match(v) and k.endswith(".py"):
                out.append((k, v))
            else:
                out += pins(v)
    elif isinstance(value, list):
        for v in value:
            out += pins(v)
    return out


def main() -> None:
    placed, failed = 0, []
    for record in sorted((ROOT / "runs").rglob("*.json")):
        try:
            found = pins(json.loads(record.read_text(encoding="utf-8")))
        except (ValueError, UnicodeDecodeError):
            continue
        for name, digest in found:
            source = ROOT / name.replace("\\", "/")
            if not source.is_file():
                continue
            raw = source.read_bytes()
            windows = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            data = next(
                (b for b in (raw, windows) if hashlib.sha256(b).hexdigest() == digest), None
            )
            target = ROOT / name  # a literal backslash name on Linux, the same file on Windows
            if data is None:
                failed.append(f"{record.relative_to(ROOT)}: {name}")
            elif not target.is_file() or target.read_bytes() != data:
                target.write_bytes(data)
                placed += 1
    print(f"code pins: {placed} files placed in their recorded form")
    for f in failed:
        print(f"  differs from its record (left as is): {f}")


if __name__ == "__main__":
    main()
