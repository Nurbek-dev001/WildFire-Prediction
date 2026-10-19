import asyncio

import s3fs
from omfiles import OmFileReaderAsync


async def main():
    fs = s3fs.S3FileSystem(anon=True, asynchronous=True)
    key = "openmeteo/data/copernicus_era5/temperature_2m/chunk_904.om"
    r = await OmFileReaderAsync.from_fsspec(fs, key)
    print(r.shape, r.chunks, flush=True)
    print(await r.read_array((558, 992, slice(9 * 24, 10 * 24))), flush=True)
    r.close()
    await fs._s3creator.__aexit__(None, None, None)


asyncio.run(main())
