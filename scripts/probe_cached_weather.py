"""Benchmark cached source byte ranges on an unsealed development year."""

import asyncio
import sys
import time

from omfiles import OmFileReaderAsync

from wildfire_kz.data.range_cache import RangeCachedS3


async def main():
    fs = RangeCachedS3(
        anon=True,
        asynchronous=True,
        skip_instance_cache=True,
        config_kwargs={"max_pool_connections": 6},
    )
    fs.block_bytes = 262144
    t = time.perf_counter()
    r = await OmFileReaderAsync.from_fsspec(
        fs, "openmeteo/data/copernicus_era5/temperature_2m/year_2015.om"
    )
    a = await r.read_array((558, slice(906, 1072), slice(None)))
    print(
        a.shape,
        a[86, :3],
        "seconds",
        time.perf_counter() - t,
        "requests",
        fs.range_requests,
        "MiB",
        fs.fetched_bytes / 2**20,
        flush=True,
    )
    b = await r.read_array((559, slice(906, 1072), slice(None)))
    print(
        "second latitude",
        b.shape,
        "total seconds",
        time.perf_counter() - t,
        "requests",
        fs.range_requests,
        "MiB",
        fs.fetched_bytes / 2**20,
        flush=True,
    )
    r.close()
    await fs._s3creator.__aexit__(None, None, None)


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
asyncio.run(main())
