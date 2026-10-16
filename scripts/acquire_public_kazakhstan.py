"""Acquire verified public geometry/VIIRS assets within a strict disk budget.

Only opaque bytes of held-out files are handled. Normalization of those files is
deliberately absent here; it belongs behind the final-evaluation gate.
"""

from __future__ import annotations

import csv
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from wildfire_kz.data import checksum, dump_json

ROOT = Path("data/real").resolve()
STATE = Path("runs/primary/acquisition").resolve()
RESERVE_BYTES = 5 * 1024**3


def fetch(url: str, destination: Path, expected_bytes: int | None = None) -> dict[str, object]:
    """Stream one public asset atomically; retain partial files only on failure."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and (
        expected_bytes is None or destination.stat().st_size == expected_bytes
    ):
        return {
            "path": str(destination),
            "url": url,
            "sha256": checksum(destination),
            "bytes": destination.stat().st_size,
            "downloaded_at": datetime.fromtimestamp(destination.stat().st_mtime, UTC).isoformat(),
            "status": "downloaded",
        }
    free = shutil.disk_usage(ROOT).free
    if free - (expected_bytes or 0) < RESERVE_BYTES:
        raise OSError("Insufficient free disk space after reserving 5 GiB")
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = Request(url, headers={"User-Agent": "wildfire-kz/0.1 research public acquisition"})
    written = 0
    with urlopen(request, timeout=45) as response, temporary.open("wb") as stream:
        if "html" in response.headers.get("Content-Type", "").lower():
            raise ValueError("Expected data, received an HTML/login page")
        while block := response.read(1024 * 1024):
            written += len(block)
            if written > (expected_bytes if expected_bytes is not None else 50 * 1024 * 1024):
                raise ValueError("Asset exceeds its declared public-download budget")
            if shutil.disk_usage(ROOT).free < RESERVE_BYTES:
                raise OSError("Disk reserve reached; download halted")
            stream.write(block)
        final_url = response.url
    if expected_bytes is not None and written != expected_bytes:
        raise ValueError(f"Size mismatch: expected {expected_bytes}, received {written}")
    temporary.replace(destination)
    return {
        "path": str(destination),
        "url": url,
        "resolved_url": final_url,
        "sha256": checksum(destination),
        "bytes": written,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "status": "downloaded",
    }


def main() -> None:
    """Download only inventory-listed Kazakhstan Suomi-NPP files, not global archives."""
    sys.stdout.reconfigure(encoding="utf-8")
    STATE.mkdir(parents=True, exist_ok=True)
    records = []
    base = "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/KAZ"
    for level in ["ADM0", "ADM1"]:
        path = ROOT / "raw" / f"kaz_{level.lower()}.geojson"
        item = fetch(f"{base}/{level}/geoBoundaries-KAZ-{level}.geojson", path)
        item.update(
            kind="boundary" if level == "ADM0" else "regions",
            source_id=f"geoBoundaries/gbOpen/KAZ/{level}",
            version="9469f09592ced973a3448cf66b6100b741b64c0d",
            license="ODbL-1.0 (source layer)",
            represented_year=2017,
            role="fixed study/reporting geometry; never a temporal predictor",
        )
        records.append(item)
    inventory_url = "https://firms.modaps.eosdis.nasa.gov/data/country/yearly_summary_files.txt"
    index = fetch(inventory_url, ROOT / "raw" / "firms_yearly_summary_files.txt")
    records.append(
        {**index, "kind": "provider_inventory", "source_id": "NASA/FIRMS/annual-country-index"}
    )
    with Path(str(index["path"])).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    chosen = []
    for row in rows:
        if (
            len(row) == 3
            and row[0].startswith("viirs-snpp_")
            and row[0].endswith("_Kazakhstan.csv")
        ):
            year = int(row[0].split("_")[1])
            if 2014 <= year <= 2024:
                chosen.append((year, row[0], int(row[1]), row[2]))
    if {y for y, _, _, _ in chosen} != set(range(2014, 2025)):
        raise ValueError("Provider index does not contain every required acquisition year")
    total = sum(size for _, _, size, _ in chosen)
    if total > 512 * 1024**2:
        raise OSError("Country archives exceed this acquisition's 512 MiB budget")
    print(f"Inventory-verified bytes for 2014 prehistory + 2015-2024: {total}", flush=True)
    manifest = {
        "status": "partial_acquisition",
        "synthetic": False,
        "test_state": "sealed",
        "test_observations_opened": False,
        "reserve_bytes": RESERVE_BYTES,
        "sources": records,
    }
    for year, name, size, modified in sorted(chosen):
        sealed = year >= 2023
        destination = (
            ROOT / "raw" / ("sealed_2023_2024" if sealed else "development_calibration") / name
        )
        record = fetch(
            f"https://firms.modaps.eosdis.nasa.gov/data/country/{name}", destination, size
        )
        record.update(
            kind="detections_archive",
            source_id="NASA/FIRMS/VIIRS_SNPP_SP/annual-country",
            year=year,
            provider_modified_at=modified,
            processing="standard-processed annual country archive; verify version during permitted normalization",
            access_state="sealed_opaque" if sealed else "development_or_calibration",
            observations_parsed=False,
        )
        records.append(record)
        dump_json(STATE / "manifest.json", manifest)
        print(
            f"Downloaded {year}: {size} bytes; {'SEALED, not parsed' if sealed else 'ready for permitted validation'}",
            flush=True,
        )
    dump_json(STATE / "manifest.json", manifest)


if __name__ == "__main__":
    main()
