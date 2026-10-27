"""Export observed new-fire events of 2023–2024 for the map's comparison layer.

Reads the exhaustive event audit of the current release (first SNPP VIIRS
nominal/high detection of each connected event) and writes one fixed-size
record per event. These labels were opened only after the model was frozen and
evaluated; showing them is a retrospective comparison, not a new test.

Record, little endian, 16 bytes: uint16 day index into the forecast manifest's
available_days, uint8 flags (1 covered by an eligible forecast, 2 alert in the
same cell that day, 4 alert in the same cell the previous day), uint8 padding,
int32 cell index in cells.bin order (-1 if outside the grid), float32 x and
y of the detection in map km (x east, y south).
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runs/model_stack_v5/audit/events.parquet"
DEST = ROOT / "platform/dist/assets"


def main():
    manifest = json.loads((DEST / "forecast-manifest.json").read_text(encoding="utf-8"))
    days = {d: i for i, d in enumerate(manifest["available_days"])}
    raw = np.fromfile(DEST / "cells.bin", dtype=np.uint8).reshape(-1, 34)
    rows = raw[:, 0:2].copy().view("<i2").ravel()
    cols = raw[:, 2:4].copy().view("<i2").ravel()
    index = {f"g5000_{r}_{c}": i for i, (r, c) in enumerate(zip(rows, cols, strict=True))}

    events = pd.read_parquet(SOURCE).sort_values(["day", "timestamp"])
    day = events["day"].dt.strftime("%Y-%m-%d")
    assert day.isin(days.keys()).all()
    record = np.zeros(
        len(events),
        dtype=[
            ("day", "<u2"),
            ("flags", "u1"),
            ("pad", "u1"),
            ("cell", "<i4"),
            ("x", "<f4"),
            ("y", "<f4"),
        ],
    )
    record["day"] = day.map(days).to_numpy()
    record["flags"] = (
        events["covered"].to_numpy() * 1
        + events["hit_same_day"].to_numpy() * 2
        + events["hit_previous_day"].to_numpy() * 4
    )
    record["cell"] = events["cell_id"].map(index).fillna(-1).astype(int).to_numpy()
    record["x"] = events["x"].to_numpy() / 1000
    record["y"] = -events["y_coord"].to_numpy() / 1000
    payload = record.tobytes()
    (DEST / "events-2023-2024.bin").write_bytes(payload)
    meta = {
        "source": "runs/model_stack_v5/audit/events.parquet",
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "definition": "First SNPP VIIRS nominal/high detection of each event connected within 2 km and 48 hours",
        "labels_opened_after_release": True,
        "release_sha256": manifest["release_sha256"],
        "events": len(events),
        "covered": int(events["covered"].sum()),
        "hit_same_day": int(events["hit_same_day"].sum()),
        "record_bytes": 16,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    (DEST / "events-2023-2024.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
