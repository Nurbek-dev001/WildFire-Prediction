"""Measure bounded asynchronous public OM reads, without held-out years."""

import asyncio
import time

import s3fs
from omfiles import OmFileReaderAsync


async def main():
    fs = s3fs.S3FileSystem(anon=True, asynchronous=True, config_kwargs={"max_pool_connections": 8})
    key = "openmeteo/data/copernicus_era5/temperature_2m/year_2015.om"
    t = time.perf_counter()
    reader = await OmFileReaderAsync.from_fsspec(fs, key)
    print("opened", time.perf_counter() - t, flush=True)
    a = await reader.read_array((slice(558, 559), slice(906, 1072), slice(None)))
    print("one row", a.shape, time.perf_counter() - t, "C", a[0, 86, :3], flush=True)
    reader.close()
    await fs._s3creator.__aexit__(None, None, None)


asyncio.run(main())
