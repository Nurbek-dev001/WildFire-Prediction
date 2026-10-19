"""Bounded aligned range cache for anonymous OM objects on S3.

An OM selection can request hundreds of neighbouring tiny compressed chunks.
Coalescing them into shared aligned ranges bounds both HTTP overhead and RAM.
No entire global object is fetched, and cached bytes are never written to disk.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any

import s3fs


class RangeCachedS3(s3fs.S3FileSystem):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.blocks: OrderedDict[tuple[str, int], bytes] = OrderedDict()
        self.pending: dict[tuple[str, int], asyncio.Task] = {}
        self.sizes: dict[str, int] = {}
        self.block_bytes = 262144
        self.maximum_blocks = 512
        self.maximum_cache_bytes = 32 * 1024**2
        self.cached_bytes = 0
        self.range_requests = 0
        self.fetched_bytes = 0

    async def _block(self, path: str, number: int) -> bytes:
        key = path, number
        if key in self.blocks:
            self.blocks.move_to_end(key)
            return self.blocks[key]
        if key not in self.pending:

            async def fetch() -> bytes:
                if path not in self.sizes:
                    self.sizes[path] = int((await self._info(path))["size"])
                block_size = min(self.block_bytes, 65536) if "/chunk_" in path else self.block_bytes
                lo = number * block_size
                hi = min(lo + block_size, self.sizes[path])
                data = await super(RangeCachedS3, self)._cat_file(path, start=lo, end=hi)
                self.range_requests += 1
                self.fetched_bytes += len(data)
                self.blocks[key] = data
                self.cached_bytes += len(data)
                self.blocks.move_to_end(key)
                while (
                    len(self.blocks) > self.maximum_blocks
                    or self.cached_bytes > self.maximum_cache_bytes
                ):
                    _, removed = self.blocks.popitem(last=False)
                    self.cached_bytes -= len(removed)
                return data

            self.pending[key] = asyncio.create_task(fetch())
        task = self.pending[key]
        try:
            return await task
        finally:
            if task.done():
                self.pending.pop(key, None)

    async def _cat_file(
        self, path: str, start: int | None = None, end: int | None = None, **kwargs: Any
    ) -> bytes:
        if path not in self.sizes:
            self.sizes[path] = int((await self._info(path))["size"])
        size = self.sizes[path]
        start = 0 if start is None else (start if start >= 0 else size + start)
        end = size if end is None else min(end, size)
        if end - start > 128 * 1024**2:
            raise MemoryError("Refuse an unbounded OM range; split the spatial selection")
        block_size = min(self.block_bytes, 65536) if "/chunk_" in path else self.block_bytes
        first, last = start // block_size, (end - 1) // block_size
        blocks = await asyncio.gather(*(self._block(path, n) for n in range(first, last + 1)))
        return b"".join(blocks)[start - first * block_size : end - first * block_size]
