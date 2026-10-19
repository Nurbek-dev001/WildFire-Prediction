"""Inspect a public NOAA daily NDVI record through anonymous range requests."""

import json
from pathlib import Path

import fsspec
import h5netcdf

url = "https://noaa-cdr-ndvi-pds.s3.amazonaws.com/data/2015/VIIRS-Land_v001_NPP13C1_S-NPP_20150101_c20240124140047.nc"
with fsspec.open(url, "rb", block_size=65536).open() as stream:
    with h5netcdf.File(stream, "r") as src:
        result = {
            "url": url,
            "variables": {
                name: {"shape": var.shape, "attrs": {k: str(v) for k, v in var.attrs.items()}}
                for name, var in src.variables.items()
            },
        }
        for name in ["NDVI", "QA"]:
            data = src.variables[name][0, 800:810, 4900:4910]
            result[name + "_sample"] = data.tolist()
        print(json.dumps(result), flush=True)
        Path("data/real/public_discovery/noaa_ndvi_sample.json").write_text(
            json.dumps(result, indent=2)
        )
