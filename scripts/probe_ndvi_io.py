"""Choose a bounded range-read block size by measurement on development data."""

import time

import h5netcdf
import s3fs

fs = s3fs.S3FileSystem(anon=True)
key = fs.glob("noaa-cdr-ndvi-pds/data/2018/VIIRS-Land*_20180707_*.nc")[-1]
for block in [1048576, 65536]:
    start = time.perf_counter()
    with fs.open(key, "rb", block_size=block, cache_type="readahead") as stream:
        with h5netcdf.File(stream, "r") as source:
            print(
                "chunks", source.variables["NDVI"].chunks, source.variables["QA"].chunks, flush=True
            )
            a = source.variables["NDVI"][0, 688:992, 4528:5344]
            qa = source.variables["QA"][0, 688:992, 4528:5344]
            print(
                block,
                a.shape,
                float(a.mean()),
                int(qa.sum()),
                time.perf_counter() - start,
                stream.cache.hit_count,
                stream.cache.miss_count,
                stream.cache.total_requested_bytes,
                flush=True,
            )
