"""VIIRS active-fire points from NASA GIBS vector tiles, which need no API key.

GIBS serves the FIRMS thermal-anomaly layers as Mapbox Vector Tiles on its EPSG:4326
500m tile set (512 px tiles; level 0 tiles span 288 degrees). This module decodes the
tiles with a small protobuf reader, so no extra dependency is needed, and returns one
row per detection with the attributes the tile carries.
"""

from __future__ import annotations

import gzip
import http.client
import time
import urllib.request
from collections.abc import Iterator
from typing import Any

import pandas as pd

WMTS = "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/wmts.cgi"
TILE_DEGREES_LEVEL0 = 288.0


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if b < 0x80:
            return result, i
        shift += 7


def _fields(buf: bytes) -> Iterator[tuple[int, int, Any]]:
    """Yield (field number, wire type, value) for one protobuf message."""
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        field, wire = key >> 3, key & 7
        value: Any
        if wire == 0:
            value, i = _varint(buf, i)
        elif wire == 1:
            value, i = buf[i : i + 8], i + 8
        elif wire == 2:
            length, i = _varint(buf, i)
            value, i = buf[i : i + length], i + length
        elif wire == 5:
            value, i = buf[i : i + 4], i + 4
        else:
            raise ValueError(f"Unsupported protobuf wire type {wire}")
        yield field, wire, value


def _packed(buf: bytes) -> list[int]:
    out, i = [], 0
    while i < len(buf):
        v, i = _varint(buf, i)
        out.append(v)
    return out


def _value(buf: bytes) -> Any:
    import struct

    for field, _, v in _fields(buf):
        if field == 1:
            return v.decode("utf-8")
        if field == 2:
            return struct.unpack("<f", v)[0]
        if field == 3:
            return struct.unpack("<d", v)[0]
        if field in (4, 5):
            return v
        if field == 6:
            return (v >> 1) ^ -(v & 1)
        if field == 7:
            return bool(v)
    return None


def decode_points(tile: bytes, level: int, row: int, col: int) -> list[dict]:
    """Points of every layer in one tile, with longitude/latitude and attributes."""
    span = TILE_DEGREES_LEVEL0 / 2**level
    west, north = -180 + col * span, 90 - row * span
    points = []
    for field, _, layer in _fields(tile):
        if field != 3:
            continue
        keys, values, features, extent = [], [], [], 4096
        for f, _, v in _fields(layer):
            if f == 3:
                keys.append(v.decode("utf-8"))
            elif f == 4:
                values.append(_value(v))
            elif f == 2:
                features.append(v)
            elif f == 5:
                extent = v
        for feature in features:
            tags, geometry, kind = [], [], 0
            for f, _, v in _fields(feature):
                if f == 2:
                    tags = _packed(v)
                elif f == 3:
                    kind = v
                elif f == 4:
                    geometry = _packed(v)
            if kind != 1:
                continue
            attrs = {keys[tags[k]]: values[tags[k + 1]] for k in range(0, len(tags), 2)}
            x = y = 0
            j = 0
            while j < len(geometry):
                command, count = geometry[j] & 7, geometry[j] >> 3
                j += 1
                for _ in range(count):
                    if command in (1, 2):
                        dx, dy = geometry[j], geometry[j + 1]
                        j += 2
                        x += (dx >> 1) ^ -(dx & 1)
                        y += (dy >> 1) ^ -(dy & 1)
                        if command == 1:
                            points.append(
                                {
                                    **attrs,
                                    "longitude": west + x / extent * span,
                                    "latitude": north - y / extent * span,
                                }
                            )
    return points


def _get(url: str, attempts: int = 6) -> bytes:
    """GIBS occasionally drops connections; retry with growing pauses before giving up."""
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                return response.read()
        except (OSError, http.client.HTTPException):
            if attempt == attempts - 1:
                raise
            time.sleep(5 * 2**attempt)
    raise RuntimeError("unreachable")


def fetch_day(
    day: str,
    bbox: tuple[float, float, float, float],
    level: int = 5,
    layer: str = "VIIRS_SNPP_Thermal_Anomalies_375m_All",
) -> pd.DataFrame:
    """All points inside bbox (west, south, east, north) for one UTC day."""
    span = TILE_DEGREES_LEVEL0 / 2**level
    west, south, east, north = bbox
    rows = range(int((90 - north) // span), int((90 - south) // span) + 1)
    cols = range(int((west + 180) // span), int((east + 180) // span) + 1)
    points = []
    for r in rows:
        for c in cols:
            url = (
                f"{WMTS}?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER={layer}&STYLE=default"
                f"&TILEMATRIXSET=500m&TILEMATRIX={level}&TILEROW={r}&TILECOL={c}"
                f"&FORMAT=application%2Fvnd.mapbox-vector-tile&TIME={day}"
            )
            body = _get(url)
            if body[:2] == bytes((0x1F, 0x8B)):
                body = gzip.decompress(body)
            if body:
                points.extend(decode_points(body, level, r, c))
    frame = pd.DataFrame(points)
    if frame.empty:
        return frame
    inside = frame.longitude.between(west, east) & frame.latitude.between(south, north)
    return frame[inside].reset_index(drop=True)
