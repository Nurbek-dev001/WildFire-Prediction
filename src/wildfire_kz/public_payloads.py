"""Lossless float32 byte shuffle for compact browser map transport."""

import gzip

import numpy as np

FORMAT = "little_endian_float32_byte_shuffle_gzip"
LEGACY_FORMAT = "little_endian_float32_gzip"


def encode(values: np.ndarray) -> bytes:
    raw = np.asarray(values, dtype="<f4").view("uint8").reshape(-1, 4)
    return gzip.compress(raw.T.tobytes(), mtime=0)


def decode(payload: bytes, encoding: str) -> np.ndarray:
    raw = gzip.decompress(payload)
    if len(raw) % 4:
        raise ValueError("Float32 payload length must be a multiple of four")
    if encoding == FORMAT:
        raw = np.frombuffer(raw, dtype="uint8").reshape(4, -1).T.tobytes()
    elif encoding != LEGACY_FORMAT:
        raise ValueError(f"Unknown probability payload encoding: {encoding}")
    return np.frombuffer(raw, dtype="<f4")
