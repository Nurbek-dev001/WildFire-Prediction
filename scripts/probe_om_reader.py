"""Validate anonymous, bounded-range weather decoding against a public API sample."""

import json
from pathlib import Path

import fsspec
import numpy as np
from omfiles import OmFileReader

url = "s3://openmeteo/data/copernicus_era5/temperature_2m/year_2015.om"
backend = fsspec.open(url, mode="rb", anon=True, default_block_size=65536)
with OmFileReader(backend) as reader:
    print("shape", reader.shape, "chunks", reader.chunks, flush=True)
    print("attributes", [s for s in dir(reader) if not s.startswith("_")], flush=True)
    if len(reader.shape) == 3:
        values = reader[558:559, 992:993, 4344:4416]
    else:
        location = 558 * 1440 + 992
        values = reader[location : location + 1, 4344:4416]
    print("decoded", values.shape, values.flatten()[:24], flush=True)
    daily = values.reshape(-1, 24)
    report = {
        "url": url,
        "shape": reader.shape,
        "sample_min": np.min(daily, axis=1).tolist(),
        "sample_max": np.max(daily, axis=1).tolist(),
        "note": "Single native grid point, 3 development days; no global file download",
    }
    Path("data/real/public_discovery/om_range_sample.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
