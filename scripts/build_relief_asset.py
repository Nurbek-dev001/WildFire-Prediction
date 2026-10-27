"""Export per-cell SRTM elevation for the 3D relief view of the map UI.

Reads the registered national terrain predictor, whose order matches cells.bin.
Writes little-endian int16 metres, one value per cell; -32768 marks missing.
This is a display export, not model input.
"""

import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/real/public_predictors/terrain/national.npz"
DEST = ROOT / "platform/dist/assets"
MISSING = -32768


def main():
    elevation = np.load(SOURCE)["elevation"]
    cells = (DEST / "cells.bin").stat().st_size // 34
    assert elevation.shape == (cells,)
    metres = np.where(np.isfinite(elevation), np.rint(elevation), MISSING)
    assert metres.min() >= MISSING and metres.max() <= 32767
    payload = metres.astype("<i2").tobytes()
    (DEST / "elevation.i16").write_bytes(payload)
    meta = {
        "source": "SRTM 90 m via data/real/public_predictors/terrain/national.npz",
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "cells": cells,
        "format": "little_endian_int16_metres",
        "missing": MISSING,
        "missing_cells": int((metres == MISSING).sum()),
        "min_m": int(metres[metres != MISSING].min()),
        "max_m": int(metres.max()),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    (DEST / "elevation.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
