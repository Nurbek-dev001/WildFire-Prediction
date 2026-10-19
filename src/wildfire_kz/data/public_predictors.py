"""Anonymous, resumable public predictors for the documented practical hindcast.

This module does not read fire labels. Held-out predictor years require an
explicit frozen-model release file. The strict primary study is unchanged.
"""

from __future__ import annotations

import asyncio
import calendar
import json
import os
import shutil
import subprocess
import zipfile
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlencode

import geopandas as gpd
import h5netcdf
import numpy as np
import pandas as pd
import pyproj
import rasterio
import s3fs
from omfiles import OmFileReaderAsync
from pydap.client import open_dods_file
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from rasterio.windows import Window
from scipy.spatial import cKDTree
from shapely.geometry import box

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.range_cache import RangeCachedS3

# Prevent an unrelated PostgreSQL PROJ installation from shadowing this runtime.
os.environ["PROJ_DATA"] = pyproj.datadir.get_data_dir()

ROOT = Path(__file__).resolve().parents[3]
PUBLIC = ROOT / "data/real/public_predictors"
CRS_MODIS = "+proj=sinu +R=6371007.181 +nadgrids=@null +wktext"
SOURCES = {
    "weather": "https://github.com/open-meteo/open-data",
    "vegetation": "https://www.ncei.noaa.gov/products/climate-data-records/normalized-difference-vegetation-index",
    "landcover": "https://modis.ornl.gov/data/modis_webservice.html",
    "terrain": "https://srtm.csi.cgiar.org/srtmdata/",
    "population": "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km/2010/KAZ/",
    "settlements": "https://github.com/nvkelso/natural-earth-vector/tree/24181daeea339ba2d8224773854b316b3bfba97f/10m_cultural",
}
T = TypeVar("T")


def reserve() -> None:
    if shutil.disk_usage(ROOT).free < 5 * 1024**3:
        raise OSError("Acquisition stopped: preserve 5 GiB of free storage")


def permitted(years: list[int], release: Path | None = None) -> None:
    if any(y >= 2023 for y in years):
        if release is None or not release.is_file():
            raise PermissionError("2023–2024 predictors are sealed until model freeze")
        record = json.loads(release.read_text())
        if (
            record.get("status") != "frozen_before_final_evaluation"
            or record.get("synthetic") is not False
        ):
            raise PermissionError("A genuine frozen-model release is required")
        model = release.parent / record["model_file"]
        if checksum(model) != record["model_sha256"]:
            raise PermissionError("Frozen model hash mismatch")
        artifacts = record.get("artifact_hashes", {})
        if not {"models.joblib", "calibrators.joblib", "frozen.json"} <= artifacts.keys():
            raise PermissionError("Model, calibration, thresholds and features must all be frozen")
        for filename, digest in artifacts.items():
            if checksum(release.parent / filename) != digest:
                raise PermissionError(f"Frozen artifact changed: {filename}")
        if "source_registry.json" in artifacts:
            registry = json.loads((release.parent / "source_registry.json").read_text())
            for filename, digest in registry.get("code_sha256", {}).items():
                if checksum(ROOT / filename) != digest:
                    raise PermissionError(f"Frozen processing code changed: {filename}")


def save_npz(path: Path, **arrays: Any) -> None:
    reserve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".working")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    temporary.replace(path)
    dump_json(
        path.with_suffix(".sha256.json"), {"sha256": checksum(path), "bytes": path.stat().st_size}
    )


def complete(path: Path) -> bool:
    digest = path.with_suffix(".sha256.json")
    return (
        path.is_file()
        and digest.is_file()
        and json.loads(digest.read_text())["sha256"] == checksum(path)
    )


def download(url: str, path: Path, *, timeout: int = 300, resumable_zip: bool = False) -> Path:
    """System curl validates TLS with the Windows trust store; no TLS bypass."""
    reserve()
    if complete(path):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".working")
    command = [
        "curl.exe",
        "--fail",
        "--location",
        "--globoff",
        "--compressed",
        "--silent",
        "--show-error",
        "--retry",
        "2",
        "--retry-all-errors",
        "--retry-delay",
        "2",
        "--max-time",
        str(timeout),
        url,
        "--output",
        str(temporary),
    ]
    if resumable_zip:
        command.remove("--compressed")
        command[command.index("--retry") + 1] = "0"
        for attempt in range(6):
            try:
                subprocess.run(command + ["--continue-at", "-"], check=True)
                with zipfile.ZipFile(temporary) as archive:
                    if archive.testzip() is not None:
                        raise ValueError("SRTM ZIP CRC mismatch")
                break
            except subprocess.CalledProcessError:
                if attempt == 5:
                    raise
                reserve()
    else:
        subprocess.run(command, check=True)
    if temporary.stat().st_size == 0:
        raise ValueError(f"Empty provider response: {url}")
    temporary.replace(path)
    dump_json(
        path.with_suffix(".sha256.json"),
        {
            "url": url,
            "sha256": checksum(path),
            "bytes": path.stat().st_size,
            "downloaded_utc": datetime.now(UTC).isoformat(),
        },
    )
    return path


@lru_cache(maxsize=1)
def geography() -> tuple[gpd.GeoDataFrame, np.ndarray, np.ndarray]:
    grid = gpd.read_parquet(ROOT / "data/real/normalized/grid_5km.parquet")
    points = grid.to_crs(4326).representative_point()
    return grid, points.x.to_numpy(), points.y.to_numpy()


@lru_cache(maxsize=1)
def modis_geography() -> tuple[pd.Series, pd.Series]:
    grid, _, _ = geography()
    projected = grid.to_crs(CRS_MODIS)
    centers = projected.representative_point()
    return np.floor(centers.x / 180000).astype(int), np.floor(centers.y / 180000).astype(int)


def log(message: str) -> None:
    print(f"{datetime.now(UTC).isoformat()} {message}", flush=True)


class WeatherSeries:
    """One UTC year backed by a yearly object or epoch-indexed 21-day objects."""

    def __init__(self, records: list[tuple[int, Any]], hours: int) -> None:
        self.records = records
        self.hours = hours

    async def read_array(self, selection: tuple[Any, Any, slice]) -> np.ndarray:
        row, columns, times = selection
        start = times.start or 0
        stop = self.hours if times.stop is None else times.stop
        semaphore = asyncio.Semaphore(4)

        async def read(offset: int, reader: Any) -> np.ndarray | None:
            lo, hi = max(start, offset), min(stop, offset + reader.shape[-1])
            if hi <= lo:
                return None
            async with semaphore:
                return await reader.read_array((row, columns, slice(lo - offset, hi - offset)))

        chunks = await asyncio.gather(*(read(offset, r) for offset, r in self.records))
        arrays = [a for a in chunks if a is not None]
        result = np.concatenate(arrays, axis=-1)
        if result.shape[-1] != stop - start:
            raise ValueError("ERA5 UTC hour coverage is incomplete")
        return result

    def close(self) -> None:
        for _, reader in self.records:
            reader.close()


async def open_weather_series(
    fs: Any,
    variable: str,
    year: int,
    provenance: list[dict[str, Any]],
    *,
    first_hour: int = 0,
    stop_hour: int | None = None,
) -> WeatherSeries:
    hours = (366 if calendar.isleap(year) else 365) * 24
    stop_hour = hours if stop_hour is None else stop_hour
    prefix = f"openmeteo/data/copernicus_era5/{variable}"
    if year <= 2021:
        objects = [(0, f"{prefix}/year_{year}.om")]
    else:
        # Confirmed by the provider's Era5Domain.swift omFileLength and a point
        # comparison against the public UTC API. Epoch is 1970-01-01 00:00 UTC.
        epoch_hour = int(pd.Timestamp(f"{year}-01-01").timestamp() // 3600)
        objects = [
            (chunk * 504 - epoch_hour, f"{prefix}/chunk_{chunk}.om")
            for chunk in range(
                (epoch_hour + first_hour) // 504, (epoch_hour + stop_hour - 1) // 504 + 1
            )
        ]
    semaphore = asyncio.Semaphore(6)

    async def open_one(offset: int, key: str) -> tuple[int, Any]:
        async with semaphore:
            reader = await OmFileReaderAsync.from_fsspec(fs, key)
            info = await fs._info(key)
            provenance.append(
                {
                    "source": "s3://" + key,
                    "etag": info.get("ETag"),
                    "provider_last_modified": str(info.get("LastModified")),
                    "source_bytes": info["size"],
                    "shape": reader.shape,
                    "chunks": reader.chunks,
                    "year_hour_offset": offset,
                }
            )
            return offset, reader

    return WeatherSeries(await asyncio.gather(*(open_one(o, k) for o, k in objects)), hours)


def weather_year(year: int, *, release: Path | None = None) -> None:
    """Decode one native latitude at a time, with hashed restart checkpoints."""
    permitted([year], release)
    path = PUBLIC / f"weather/{year}.npz"
    if complete(path):
        log(f"weather {year}: verified cache")
        return
    _, lon, lat = geography()
    iy = np.rint((lat + 90) / 0.25).astype(int)
    ix = np.rint((lon + 180) / 0.25).astype(int)
    y0, y1, x0, x1 = int(iy.min()), int(iy.max()) + 1, int(ix.min()), int(ix.max()) + 1
    start = pd.Timestamp(f"{year}-11-01" if year == 2014 else f"{year}-01-01")
    first_hour = int((start - pd.Timestamp(f"{year}-01-01")).total_seconds() / 3600)
    nday = (366 if calendar.isleap(year) else 365) - first_hour // 24
    names = ["tmax", "tmin", "temperature", "rh", "wind", "precip", "soil_moisture"]
    provenance: list[dict[str, Any]] = []

    async def acquire() -> None:
        fs = RangeCachedS3(
            anon=True,
            asynchronous=True,
            skip_instance_cache=True,
            config_kwargs={"max_pool_connections": 8},
        )
        variables = [
            "temperature_2m",
            "dew_point_2m",
            "wind_u_component_10m",
            "wind_v_component_10m",
            "precipitation",
            "soil_moisture_0_to_7cm",
        ]
        readers = {}
        try:
            for variable in variables:
                readers[variable] = await open_weather_series(
                    fs, variable, year, provenance, first_hour=first_hour
                )
            next_rain = None
            # Last pre-freeze day is missing rather than reading 2023 to complete it.
            if year < 2022 or (release is not None and year < 2024):
                next_rain = await open_weather_series(
                    fs, "precipitation", year + 1, provenance, stop_hour=1
                )
                readers["next_rain"] = next_rain
            for row in range(y0, y1):
                checkpoint = PUBLIC / f"weather/rows_{year}/{row}.npz"
                if complete(checkpoint):
                    continue
                reserve()
                # Empty cells outside the country's native row are never downloaded.
                used = ix[iy == row]
                if len(used) == 0:
                    save_npz(
                        checkpoint,
                        **{n: np.full((x1 - x0, nday), np.nan, dtype="float32") for n in names},
                    )
                    continue
                left, right = int(used.min()), int(used.max()) + 1
                selection = (row, slice(left, right), slice(first_hour, None))

                async def read(variable: str, selected: Any = selection) -> np.ndarray:
                    return (await readers[variable].read_array(selected)).astype(
                        "float32", copy=False
                    )

                def daily(
                    a: np.ndarray, operation: str = "mean", width: int = right - left
                ) -> np.ndarray:
                    return getattr(np, operation)(a.reshape(width, nday, 24), axis=-1).astype(
                        "float32"
                    )

                temperature, dewpoint, u, v, rain, soil = await asyncio.gather(
                    *(read(variable) for variable in variables)
                )
                values = {
                    "tmax": daily(temperature, "max"),
                    "tmin": daily(temperature, "min"),
                    "temperature": daily(temperature),
                }
                rh = 100 * np.exp(
                    17.625 * dewpoint / (243.04 + dewpoint)
                    - 17.625 * temperature / (243.04 + temperature)
                )
                values["rh"] = daily(np.clip(rh, 0, 100))
                del temperature, dewpoint, rh
                values["wind"] = daily(np.hypot(u, v))
                del u, v
                midnight = (
                    (await next_rain.read_array((row, slice(left, right), slice(0, 1))))
                    if next_rain
                    else np.full((right - left, 1), np.nan, dtype="float32")
                )
                values["precip"] = daily(np.concatenate([rain[:, 1:], midnight], axis=-1), "sum")
                values["soil_moisture"] = daily(soil)
                padded = {}
                for name, a in values.items():
                    padded[name] = np.full((x1 - x0, nday), np.nan, dtype="float32")
                    padded[name][left - x0 : right - x0] = a
                save_npz(checkpoint, **padded)
                log(f"weather {year}: latitude {row - y0 + 1}/{y1 - y0} complete")
        finally:
            for reader in readers.values():
                reader.close()
            if fs._s3creator is not None:
                await fs._s3creator.__aexit__(None, None, None)

    asyncio.run(acquire())
    output = {name: np.full((y1 - y0, x1 - x0, nday), np.nan, dtype="float32") for name in names}
    for row in range(y0, y1):
        with np.load(PUBLIC / f"weather/rows_{year}/{row}.npz") as chunk:
            for name in names:
                output[name][row - y0] = chunk[name]
    for name, array in output.items():
        if name == "precip" and np.nanmin(array) < -1e-5:
            raise ValueError("Negative deaccumulated precipitation")
    save_npz(
        path,
        **output,
        first_day=np.array(start.strftime("%Y-%m-%d")),
        native_cell_y=(iy - y0).astype("uint16"),
        native_cell_x=(ix - x0).astype("uint16"),
        y0=y0,
        x0=x0,
    )
    dump_json(
        path.with_suffix(".provenance.json"),
        {
            "sources": provenance,
            "provider": SOURCES["weather"],
            "resolution_deg": 0.25,
            "weather_release_lag_days": 5,
            "reprocessed_hindcast": True,
            "units": {
                "tmax": "C",
                "tmin": "C",
                "wind": "m/s",
                "rh": "%",
                "precip": "mm/calendar UTC day",
                "soil_moisture": "m3/m3",
            },
        },
    )
    log(f"weather {year}: complete; {path.stat().st_size:,} bytes")


def vegetation_day(day: str, fs: Any = None) -> None:
    date = pd.Timestamp(day)
    path = PUBLIC / f"vegetation/{day}.npz"
    if complete(path):
        return
    fs = fs or s3fs.S3FileSystem(anon=True, config_kwargs={"max_pool_connections": 4})
    keys = fs.glob(f"noaa-cdr-ndvi-pds/data/{date.year}/VIIRS-Land*_{date:%Y%m%d}_*.nc")
    if not keys:
        dump_json(
            path.with_suffix(".unavailable.json"),
            {"day": day, "reason": "No provider VIIRS record for the scheduled weekly snapshot"},
        )
        log(f"vegetation {day}: source gap, retained missing")
        return
    key = sorted(keys)[-1]
    _, lon, lat = geography()
    iy = np.floor((90 - lat) / 0.05).astype(int)
    ix = np.floor((lon + 180) / 0.05).astype(int)
    y0, y1, x0, x1 = int(iy.min()), int(iy.max()) + 1, int(ix.min()), int(ix.max()) + 1
    transport, subset_hash = "NCEI OPeNDAP", None
    suffix = key.split("/data/", 1)[1]
    selector = f"[0:1:0][{y0}:1:{y1 - 1}][{x0}:1:{x1 - 1}]"
    subset_url = f"https://www.ncei.noaa.gov/thredds/dodsC/cdr/ndvi/{suffix}.dods?NDVI{selector},QA{selector}"
    raw_path = PUBLIC / f"vegetation/subsets/{day}.dods"
    try:
        download(subset_url, raw_path, timeout=90)
        subset = open_dods_file(raw_path)
        raw = np.asarray(subset["NDVI"].array.data)[0]
        qa = np.asarray(subset["QA"].array.data)[0].astype("uint16")
        if raw.shape != (y1 - y0, x1 - x0) or qa.shape != raw.shape:
            raise ValueError("NOAA DAP subset dimensions differ from the native selection")
        subset_hash = checksum(raw_path)
    except (subprocess.CalledProcessError, ValueError, KeyError):
        transport = "AWS source range-read fallback"
        with fs.open(key, "rb", block_size=1048576, cache_type="readahead") as stream:
            with h5netcdf.File(stream, "r") as src:
                raw = src.variables["NDVI"][0, y0:y1, x0:x1]
                qa = src.variables["QA"][0, y0:y1, :][:, x0:x1].astype("uint16")
    valid = (raw >= -1000) & (raw <= 10000)
    valid &= (qa & (32768 | 1024 | 512 | 256 | 4)) == 0
    valid &= (qa & 3) <= 1
    valid &= (qa & 192) != 192
    valid &= np.isin(qa & 56, [0, 8])
    ndvi = np.where(valid, raw * 0.0001, np.nan).astype("float32")
    selected = ndvi[iy - y0, ix - x0]
    save_npz(path, ndvi=selected, observation_day=np.array(day))
    dump_json(
        path.with_suffix(".provenance.json"),
        {
            "source": "s3://" + key,
            "source_etag": fs.info(key).get("ETag"),
            "transport": transport,
            "subset_url": subset_url if subset_hash else None,
            "subset_sha256": subset_hash,
            "scale": 0.0001,
            "snapshot_interval_days": 7,
            "native_resolution_deg": 0.05,
            "quality": "clear/probably-clear land, no snow/cloud/cirrus/shadow/high aerosol",
            "EVI": "not available; explicitly omitted from public variant",
            "available_after_days": 10,
            "reprocessed_hindcast": True,
        },
    )
    log(f"vegetation {day}: {np.isfinite(selected).mean():.1%} valid national cells")


def vegetation(years: list[int], workers: int, release: Path | None = None) -> None:
    permitted(years, release)
    days = [
        d.strftime("%Y-%m-%d")
        for d in pd.date_range("2014-11-01", "2024-12-31", freq="7D")
        if d.year in years
    ]
    parallel(vegetation_day, days, workers)


def landcover_tile(key: tuple[int, int], years: list[int]) -> None:
    tx, ty = key
    tile_path = PUBLIC / f"landcover/tile_{tx}_{ty}_{min(years)}_{max(years)}.npz"
    if complete(tile_path):
        return
    grid, _, _ = geography()
    tile_x, tile_y = modis_geography()
    assigned = (tile_x == tx) & (tile_y == ty)
    local = grid[assigned]
    indices = np.flatnonzero(assigned)
    x, y = (tx + 0.5) * 180000, (ty + 0.5) * 180000
    lng, lat = pyproj.Transformer.from_crs(CRS_MODIS, 4326, always_xy=True).transform(x, y)
    query = {
        "latitude": round(lat, 7),
        "longitude": round(lng, 7),
        "startDate": f"A{min(years)}001",
        "endDate": f"A{max(years)}001",
        "band": "LC_Type1",
        "kmAboveBelow": 100,
        "kmLeftRight": 100,
    }
    url = "https://modis.ornl.gov/rst/api/v1/MCD12Q1/subset?" + urlencode(query)
    raw_path = PUBLIC / f"landcover/raw_{tx}_{ty}_{min(years)}_{max(years)}.json"
    download(url, raw_path, timeout=300)
    data = json.loads(raw_path.read_text())
    nrows, ncols = int(data["nrows"]), int(data["ncols"])
    cellsize = float(data["cellsize"])
    transform = from_origin(
        float(data["xllcorner"]), float(data["yllcorner"]) + nrows * cellsize, cellsize, cellsize
    )
    xmin, ymin, xmax, ymax = local.total_bounds
    left, bottom = np.floor(np.array([xmin, ymin]) / 5000) * 5000
    right, top = np.ceil(np.array([xmax, ymax]) / 5000) * 5000
    dst_transform = from_origin(left, top, 5000, 5000)
    shape = (int(round((top - bottom) / 5000)), int(round((right - left) / 5000)))
    rows = ((top - local.y_coord.to_numpy()) / 5000).astype(int)
    cols = ((local.x.to_numpy() - left) / 5000).astype(int)
    channels = {
        "forest": [1, 2, 3, 4, 5],
        "grassland": [8, 9, 10],
        "shrubland": [6, 7],
        "cropland": [12, 14],
        "other": [0, 11, 13, 15, 16, 17],
        "nonvegetated": [0, 13, 15, 16, 17],
    }
    result = {"indices": indices.astype("int32")}
    border = (
        gpd.read_parquet(ROOT / "data/real/normalized/boundary.parquet")
        .to_crs(CRS_MODIS)
        .geometry.union_all()
    )
    country_mask = geometry_mask(
        [border.__geo_interface__], out_shape=(nrows, ncols), transform=transform, invert=True
    )
    seen = set()
    for item in data["subset"]:
        year = int(item["modis_date"][1:5])
        if year not in years:
            continue
        seen.add(year)
        array = np.asarray(item["data"], dtype="uint8").reshape(nrows, ncols)
        valid = (array <= 17) & country_mask
        for name, codes in channels.items():
            source = np.where(valid, np.isin(array, codes).astype("float32"), -9999)
            dest = np.full(shape, np.nan, dtype="float32")
            reproject(
                source,
                dest,
                src_transform=transform,
                src_crs=CRS_MODIS,
                src_nodata=-9999,
                dst_transform=dst_transform,
                dst_crs=grid.crs,
                dst_nodata=np.nan,
                resampling=Resampling.average,
                num_threads=1,
            )
            result[f"{name}_{year}"] = dest[rows, cols]
    if seen != set(years):
        raise ValueError(f"Missing annual MODIS maps: {set(years) - seen}")
    save_npz(tile_path, **result)
    log(f"landcover tile {tx},{ty}: {len(indices)} cells x {len(years)} years")


def landcover(years: list[int], workers: int, release: Path | None = None) -> None:
    permitted([y + 1 for y in years], release)
    grid, _, _ = geography()
    centers = grid.to_crs(CRS_MODIS).representative_point()
    keys = sorted(
        set(
            zip(
                np.floor(centers.x / 180000).astype(int),
                np.floor(centers.y / 180000).astype(int),
                strict=True,
            )
        )
    )
    log(f"landcover: {len(keys)} disjoint tile assignments; source subsets overlap at edges")
    parallel(lambda key: landcover_tile(key, years), keys, workers)
    result = {
        f"{name}_{year}": np.full(len(grid), np.nan, dtype="float32")
        for year in years
        for name in ["forest", "grassland", "shrubland", "cropland", "other", "nonvegetated"]
    }
    for tx, ty in keys:
        with np.load(PUBLIC / f"landcover/tile_{tx}_{ty}_{min(years)}_{max(years)}.npz") as d:
            for name in result:
                result[name][d["indices"]] = d[name]
    for year in years:
        fractions = np.stack(
            [
                result[f"{name}_{year}"]
                for name in ["forest", "grassland", "shrubland", "cropland", "other"]
            ]
        )
        valid = np.isfinite(fractions).all(axis=0)
        if valid.mean() < 0.98:
            raise ValueError(f"Insufficient land-cover coverage for {year}: {valid.mean()}")
        if not np.allclose(fractions[:, valid].sum(axis=0), 1, atol=0.005):
            raise ValueError("Land-cover fractions do not sum to one")
    save_npz(PUBLIC / f"landcover/annual_{min(years)}_{max(years)}.npz", **result)


def target_lattice(grid: gpd.GeoDataFrame) -> tuple[Any, Any, np.ndarray, np.ndarray]:
    c0, c1 = int(grid.col.min()), int(grid.col.max())
    r0, r1 = int(grid.row.min()), int(grid.row.max())
    return (
        (r1 - r0 + 1, c1 - c0 + 1),
        from_origin(c0 * 5000, (r1 + 1) * 5000, 5000, 5000),
        (r1 - grid.row.to_numpy()),
        (grid.col.to_numpy() - c0),
    )


def terrain_tile(tile: tuple[int, int], *, crop: bool = True) -> None:
    x, y = tile
    path = PUBLIC / f"terrain/srtm_{x:02}_{y:02}.npz"
    if complete(path):
        with np.load(path) as cached:
            if "method_version" in cached and str(cached["method_version"]) == "native_centres_v2":
                return
    zip_path = PUBLIC / f"terrain/raw/srtm_{x:02}_{y:02}.zip"
    url = (
        f"https://srtm.csi.cgiar.org/wp-content/uploads/files/srtm_5x5/TIFF/srtm_{x:02}_{y:02}.zip"
    )
    download(url, zip_path, timeout=300, resumable_zip=True)
    grid, _, _ = geography()
    shape, transform, _, _ = target_lattice(grid)
    border = (
        gpd.read_parquet(ROOT / "data/real/normalized/boundary.parquet")
        .to_crs(4326)
        .geometry.union_all()
    )
    with zipfile.ZipFile(zip_path) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".tif"))
    with rasterio.open(f"zip://{zip_path.as_posix()}!{name}") as src:
        clipped = border.intersection(box(*src.bounds))
        output = {
            n: np.zeros(shape, dtype="float64")
            for n in ["weight", "elevation", "slope", "aspect_sin", "aspect_cos"]
        }
        geod = pyproj.Geod(ellps="WGS84")
        projection = pyproj.Transformer.from_crs(src.crs, grid.crs, always_xy=True)
        row_max, col_min = int(grid.row.max()), int(grid.col.min())
        # Native gradients include a one-row halo. Only the core is aggregated,
        # so strip boundaries neither duplicate pixels nor introduce false slopes.
        roi = src.window(*clipped.bounds)
        row_first, row_last = (
            max(0, int(np.floor(roi.row_off))),
            min(src.height, int(np.ceil(roi.row_off + roi.height))),
        )
        col_first, col_last = (
            max(0, int(np.floor(roi.col_off))),
            min(src.width, int(np.ceil(roi.col_off + roi.width))),
        )
        halo_left, halo_right = max(0, col_first - 1), min(src.width, col_last + 1)
        if not crop:
            row_first, row_last, col_first, col_last = 0, src.height, 0, src.width
            halo_left, halo_right = 0, src.width
        for first in range(row_first, row_last, 256):
            stop = min(first + 256, row_last)
            lo, hi = max(0, first - 1), min(src.height, stop + 1)
            window = Window(halo_left, lo, halo_right - halo_left, hi - lo)
            z = src.read(1, window=window, masked=True).astype("float32").filled(np.nan)
            affine = src.window_transform(window)
            lats = affine.f + (np.arange(z.shape[0]) + 0.5) * affine.e
            lngs = np.full_like(lats, affine.c)
            _, _, dx = geod.inv(lngs, lats, lngs + affine.a, lats)
            _, _, dy = geod.inv(lngs, lats, lngs, lats + affine.e)
            down, east = np.gradient(z)
            down /= np.abs(dy[:, None])
            east /= np.abs(dx[:, None])
            angle = np.arctan2(-east, down)
            row_core = slice(first - lo, stop - lo)
            core = (row_core, slice(col_first - halo_left, col_last - halo_left))
            channels = {
                "elevation": z[core],
                "slope": np.degrees(np.arctan(np.hypot(down[core], east[core]))),
                "aspect_sin": np.sin(angle[core]),
                "aspect_cos": np.cos(angle[core]),
            }
            affine = src.window_transform(
                Window(col_first, first, col_last - col_first, stop - first)
            )
            inside = geometry_mask(
                [clipped.__geo_interface__],
                out_shape=(stop - first, col_last - col_first),
                transform=affine,
                invert=True,
            )
            valid = np.isfinite(channels["elevation"]) & inside
            weights = np.where(valid, np.abs(dx[row_core] * dy[row_core])[:, None], 0).astype(
                "float32"
            )
            channels["weight"] = np.ones_like(weights)
            rr, cc = np.nonzero(valid)
            longitude = affine.c + (cc + 0.5) * affine.a
            latitude = affine.f + (rr + 0.5) * affine.e
            px, py = projection.transform(longitude, latitude)
            out_rows = row_max - np.floor(py / 5000).astype(int)
            out_cols = np.floor(px / 5000).astype(int) - col_min
            keep = (out_rows >= 0) & (out_rows < shape[0]) & (out_cols >= 0) & (out_cols < shape[1])
            locations = out_rows[keep] * shape[1] + out_cols[keep]
            for channel_name, channel in channels.items():
                values = (channel[rr, cc] * weights[rr, cc])[keep]
                output[channel_name] += np.bincount(
                    locations, weights=values, minlength=shape[0] * shape[1]
                ).reshape(shape)
        output["method_version"] = np.array("native_centres_v2")
        save_npz(path, **output)
    log(f"terrain {x},{y}: native gradients and area-weighted cell sums complete")


def terrain(workers: int) -> None:
    grid, _, _ = geography()
    border = (
        gpd.read_parquet(ROOT / "data/real/normalized/boundary.parquet")
        .to_crs(4326)
        .geometry.union_all()
    )
    tiles = []
    for x in range(46, 55):
        for y in range(1, 5):
            west = -180 + (x - 1) * 5
            north = 60 - (y - 1) * 5
            if border.intersection(box(west, north - 5, west + 5, north)).area > 0:
                tiles.append((x, y))
    parallel(terrain_tile, tiles, workers)
    shape, _, rows, cols = target_lattice(grid)
    totals = {
        name: np.zeros(shape, dtype="float64")
        for name in ["weight", "elevation", "slope", "aspect_sin", "aspect_cos"]
    }
    for x, y in tiles:
        with np.load(PUBLIC / f"terrain/srtm_{x:02}_{y:02}.npz") as data:
            for name in totals:
                totals[name] += data[name]
    weight = totals.pop("weight")
    result = {
        name: np.divide(array, weight, out=np.full(shape, np.nan), where=weight > 0)[
            rows, cols
        ].astype("float32")
        for name, array in totals.items()
    }
    result["observed_area_km2"] = (weight[rows, cols] / 1e6).astype("float32")
    if np.isfinite(result["elevation"]).mean() < 0.98:
        raise ValueError("SRTM coverage below 98%")
    save_npz(PUBLIC / "terrain/national.npz", **result)


def human() -> None:
    grid, _, _ = geography()
    population = download(
        "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km/2010/KAZ/kaz_ppp_2010_1km_Aggregated.tif",
        PUBLIC / "human/worldpop_2010_1km.tif",
    )
    shape, transform, rows, cols = target_lattice(grid)
    with rasterio.open(population) as src:
        destination = np.full(shape, np.nan, dtype="float32")
        reproject(
            rasterio.band(src, 1),
            destination,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=transform,
            dst_crs=grid.crs,
            dst_nodata=np.nan,
            resampling=Resampling.sum,
            num_threads=2,
        )
    # Historical Natural Earth revision dated 2013-06-02, not modern OSM roads.
    directory = PUBLIC / "human/settlements_2013"
    for extension in ["shp", "shx", "dbf", "prj"]:
        download(
            f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/24181daeea339ba2d8224773854b316b3bfba97f/10m_cultural/ne_10m_populated_places.{extension}",
            directory / f"places.{extension}",
        )
    places = gpd.read_file(directory / "places.shp").to_crs(grid.crs)
    tree = cKDTree(np.c_[places.geometry.x, places.geometry.y])
    distances, _ = tree.query(np.c_[grid.x, grid.y_coord])
    values = destination[rows, cols]
    save_npz(
        PUBLIC / "human/national.npz",
        population=values,
        population_density=values / grid.area_km2.to_numpy(),
        settlement_distance=distances.astype("float32"),
    )
    log("human: population 2010 and historical settlements 2013 complete; roads omitted")


def parallel(function: Callable[[T], None], items: Iterable[T], workers: int) -> None:
    errors = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(function, item): item for item in items}
        for future in as_completed(jobs):
            try:
                future.result()
            except Exception as exc:
                log(f"FAILED {jobs[future]}: {type(exc).__name__}: {exc}")
                errors.append(str(jobs[future]))
    if errors:
        raise RuntimeError(f"Acquisition incomplete; resumable failed jobs: {errors}")
