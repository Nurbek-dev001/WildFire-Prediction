"""Losslessly archive verified source subsets and discard duplicate weather row caches."""

import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "data/real/public_predictors"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verified(path: Path) -> bool:
    if not path.is_file():
        return False
    expected = digest(path)
    return any(
        sidecar.is_file() and json.loads(sidecar.read_text())["sha256"] == expected
        for sidecar in [
            path.with_name(path.name + ".sha256.json"),
            path.with_suffix(".sha256.json"),
        ]
    )


def contained(path: Path) -> None:
    if not path.resolve().is_relative_to(PUBLIC.resolve()) or path.resolve() == PUBLIC.resolve():
        raise ValueError(f"Refuse cache mutation outside the public dataset directory: {path}")


def archive(path: Path) -> int:
    contained(path)
    if not verified(path):
        raise ValueError(f"Unverified source cannot be archived: {path}")
    original_hash, original_bytes = digest(path), path.stat().st_size
    target = path.with_name(path.name + ".gz")
    contained(target)
    if not target.is_file():
        temporary = target.with_suffix(target.suffix + ".working")
        with path.open("rb") as source, temporary.open("wb") as stream:
            with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as compressed:
                shutil.copyfileobj(source, compressed, length=1024 * 1024)
        temporary.replace(target)
    with gzip.open(target, "rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != original_hash:
            raise ValueError("Lossless source archive verification failed")
    if target.stat().st_size >= original_bytes:
        target.unlink()
        return 0
    sidecar = target.with_name(target.name + ".sha256.json")
    sidecar.write_text(
        json.dumps(
            {
                "sha256": digest(target),
                "uncompressed_sha256": original_hash,
                "bytes": target.stat().st_size,
                "uncompressed_bytes": original_bytes,
                "original_filename": path.name,
                "archived_utc": datetime.now(UTC).isoformat(),
                "restore": "gzip decompression restores the exact original provider subset bytes",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    saved = original_bytes - target.stat().st_size
    path.unlink()
    return saved


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--include-final", action="store_true")
args = parser.parse_args()
maximum = 2022
if args.include_final:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; from wildfire_kz.data.public_predictors import permitted; "
            "permitted([2023,2024],Path('runs/public_hindcast/release.json'))",
        ],
        cwd=ROOT,
        check=True,
    )
    maximum = 2024
saved, archives, checkpoints = 0, 0, 0
for path in sorted((PUBLIC / "vegetation/subsets").glob("????-??-??.dods")):
    if int(path.name[:4]) <= maximum and verified(PUBLIC / f"vegetation/{path.stem}.npz"):
        saved += archive(path)
        archives += 1
for path in sorted((PUBLIC / "landcover").glob("raw_*.json")):
    match = re.fullmatch(r"raw_(-?\d+)_(-?\d+)_(\d{4})_(\d{4})\.json", path.name)
    if (
        match
        and int(match[4]) < maximum
        and verified(path.with_name(path.name.replace("raw_", "tile_", 1)).with_suffix(".npz"))
    ):
        if verified(PUBLIC / f"landcover/annual_{match[3]}_{match[4]}.npz"):
            saved += archive(path)
            archives += 1
for directory in sorted((PUBLIC / "weather").glob("rows_*")):
    match = re.fullmatch(r"rows_(\d{4})", directory.name)
    if not match or int(match[1]) > maximum or not verified(PUBLIC / f"weather/{match[1]}.npz"):
        continue
    contained(directory)
    # These are shallow, duplicate prepared caches, not unique source archives.
    for path in directory.iterdir():
        if path.is_file() and (path.suffix == ".npz" or path.name.endswith(".sha256.json")):
            contained(path)
            saved += path.stat().st_size
            path.unlink()
            checkpoints += 1
    if not any(directory.iterdir()):
        directory.rmdir()
record = {
    "saved_bytes": saved,
    "source_subsets_archived": archives,
    "redundant_checkpoint_files_removed": checkpoints,
    "maximum_observation_year": maximum,
    "completed_utc": datetime.now(UTC).isoformat(),
}
(ROOT / f"runs/public_hindcast/storage_{maximum}.json").write_text(
    json.dumps(record, indent=2), encoding="utf-8"
)
print(record)
