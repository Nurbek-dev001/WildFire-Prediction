"""Acquisition of the REAL open-data inputs from public cloud buckets (no credentials).

Every function downloads from a public, anonymous endpoint and writes files in the raw
layout that the pipeline already reads. Nothing is synthesised: if an endpoint is
unreachable the function raises.

* fire labels: NOAA Enterprise Active Fire (EFIRE), Suomi-NPP VIIRS I-band 375 m,
  AWS ``noaa-nesdis-snpp-pds`` -> FIRMS-schema CSV;
* weather: ERA5 hourly, ARCO-ERA5 Zarr, GCS ``gcp-public-data-arco-era5`` -> monthly NetCDF;
* vegetation: NOAA CDR VIIRS daily NDVI 0.05 deg, AWS ``noaa-cdr-ndvi-pds`` -> 16-day
  maximum-value composites (GeoTIFF);
* land cover: ESA WorldCover v200 2021, AWS ``esa-worldcover`` -> class GeoTIFF;
* terrain: Copernicus DEM GLO-90, AWS ``copernicus-dem-90m`` -> 1 deg tiles;
* population: Meta HRSL general population, AWS ``dataforgood-fb-data`` -> counts GeoTIFF;
* settlements: built-up pixels of WorldCover 2021 -> dated point snapshot;
* boundary and regions: Overture Maps divisions, AWS ``overturemaps-us-west-2`` -> GeoJSON.
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import io
import json
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from wildfire_kz.utils.runtime import get_logger

log = get_logger("open_data")

KZ_BBOX = (46.4, 40.5, 87.4, 55.5)  # minlon, minlat, maxlon, maxlat

ARCO = (
    "https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
)
EFIRE = "https://noaa-nesdis-snpp-pds.s3.amazonaws.com"
NDVI_CDR = "https://noaa-cdr-ndvi-pds.s3.amazonaws.com"
WORLDCOVER = "https://esa-worldcover.s3.amazonaws.com/v200/2021/map"
COPDEM = "https://copernicus-dem-90m.s3.amazonaws.com"
HRSL_VRT = (
    "https://dataforgood-fb-data.s3.amazonaws.com/hrsl-cogs/hrsl_general/hrsl_general-latest.vrt"
)


# --------------------------------------------------------------------------- http helpers
def http_get(
    url: str, byte_range: tuple[int, int] | None = None, retries: int = 4, timeout: float = 120.0
) -> bytes:
    req = urllib.request.Request(url)
    if byte_range is not None:
        req.add_header("Range", f"bytes={byte_range[0]}-{byte_range[1]}")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return bytes(r.read())
        except Exception as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"download failed: {url}: {exc}") from exc
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def s3_list(base: str, prefix: str) -> list[tuple[str, int]]:
    """All (key, size) under a prefix of a public S3 bucket (ListObjectsV2, paginated)."""
    out: list[tuple[str, int]] = []
    token = None
    while True:
        url = f"{base}/?list-type=2&prefix={prefix}&max-keys=1000"
        if token:
            url += "&continuation-token=" + urllib.parse.quote(token, safe="")
        xml = http_get(url).decode()
        keys = re.findall(r"<Key>([^<]*)</Key>", xml)
        sizes = [int(s) for s in re.findall(r"<Size>(\d+)</Size>", xml)]
        out += list(zip(keys, sizes, strict=True))
        m = re.search(r"<NextContinuationToken>([^<]*)</NextContinuationToken>", xml)
        if not m:
            return out
        token = m.group(1)


def parallel(fn: Callable[[Any], Any], items: Iterable[Any], workers: int) -> list[Any]:
    with cf.ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, items))


# --------------------------------------------------------------------------- boundary
def fetch_boundary(out_dir: Path, release: str = "2026-09-23.1") -> dict[str, Path]:
    """Kazakhstan land boundary and oblast regions from Overture Maps divisions."""
    import geopandas as gpd
    import pyarrow.compute as pc
    import pyarrow.dataset as ds
    import pyarrow.fs as pafs
    import shapely

    fs = pafs.S3FileSystem(anonymous=True, region="us-west-2")
    d = ds.dataset(
        f"overturemaps-us-west-2/release/{release}/theme=divisions/type=division_area/",
        filesystem=fs,
        format="parquet",
    )
    flt = (
        (pc.field("country") == "KZ")
        & (pc.field("subtype").isin(["country", "region"]))
        & (pc.field("class") == "land")
    )
    tb = d.to_table(columns=["id", "subtype", "names", "geometry"], filter=flt).to_pandas()
    tb["name"] = tb["names"].apply(lambda n: (n or {}).get("primary"))
    g = gpd.GeoDataFrame(
        tb[["id", "subtype", "name"]], geometry=shapely.from_wkb(tb["geometry"]), crs="EPSG:4326"
    )
    g["source"] = f"Overture Maps divisions {release}"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "country": out_dir / "kazakhstan_adm0.geojson",
        "regions": out_dir / "kazakhstan_adm1.geojson",
    }
    g[g.subtype == "country"].to_file(paths["country"], driver="GeoJSON")
    g[g.subtype == "region"].to_file(paths["regions"], driver="GeoJSON")
    return paths


# --------------------------------------------------------------------------- ERA5 (ARCO)
ERA5_VARS = {  # ARCO name -> (our name, hours of day to fetch)
    "2m_temperature": ("t2m", tuple(range(0, 24, 3))),
    "2m_dewpoint_temperature": ("d2m", tuple(range(0, 24, 3))),
    "10m_u_component_of_wind": ("u10", tuple(range(0, 24, 3))),
    "10m_v_component_of_wind": ("v10", tuple(range(0, 24, 3))),
    "total_precipitation": ("tp", tuple(range(24))),
    "volumetric_soil_water_layer_1": ("swvl1", (12,)),
}
_HOURS_EPOCH = dt.datetime(1900, 1, 1)


def _arco_chunk(var: str, hour_index: int) -> np.ndarray:
    import numcodecs

    raw = http_get(f"{ARCO}/{var}/{hour_index}.0.0")
    arr = numcodecs.Blosc().decode(raw)
    return np.frombuffer(arr, dtype="<f4").reshape(721, 1440)


def fetch_era5_month(
    year: int,
    month: int,
    out_dir: Path,
    bbox: tuple[float, float, float, float] = KZ_BBOX,
    workers: int = 32,
) -> Path:
    """One month of ERA5 hourly fields cropped to the bounding box (+1 day for precip)."""
    import xarray as xr

    out = out_dir / f"era5_arco_{year}_{month:02d}.nc"
    if out.exists():
        return out
    w, s, e, n = bbox
    lats = 90 - 0.25 * np.arange(721)
    lons = 0.25 * np.arange(1440)
    r0, r1 = int(np.floor((90 - n) / 0.25)) - 1, int(np.ceil((90 - s) / 0.25)) + 1
    c0, c1 = int(np.floor(w / 0.25)) - 1, int(np.ceil(e / 0.25)) + 1
    start = pd.Timestamp(year, month, 1)
    end = start + pd.offsets.MonthBegin(1)
    hours = pd.date_range(start, end - pd.Timedelta(hours=1), freq="h")
    jobs = []
    for var, (_, hod) in ERA5_VARS.items():
        for t in hours:
            if t.hour in hod:
                jobs.append((var, t))

    def get(job: tuple[str, pd.Timestamp]) -> tuple[str, pd.Timestamp, np.ndarray]:
        var, t = job
        idx = int((t.to_pydatetime() - _HOURS_EPOCH).total_seconds() // 3600)
        return var, t, _arco_chunk(var, idx)[r0:r1, c0:c1].copy()

    res = parallel(get, jobs, workers)
    data = {
        name: np.full((len(hours), r1 - r0, c1 - c0), np.nan, dtype=np.float32)
        for name, _ in ERA5_VARS.values()
    }
    tindex = {t: i for i, t in enumerate(hours)}
    for var, t, a in res:
        data[ERA5_VARS[var][0]][tindex[t]] = a
    ds = xr.Dataset(
        {k: (("valid_time", "latitude", "longitude"), v) for k, v in data.items()},
        coords={"valid_time": hours.values, "latitude": lats[r0:r1], "longitude": lons[c0:c1]},
        attrs={
            "source": "ERA5 hourly (ARCO-ERA5, gs://gcp-public-data-arco-era5)",
            "tp_convention": "hourly accumulation ending at valid_time",
            "sampling": "t2m/d2m/u10/v10 3-hourly, tp hourly, swvl1 12 UTC",
        },
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.nc")
    ds.to_netcdf(tmp, encoding={k: {"zlib": True, "complevel": 4} for k in data})
    tmp.replace(out)
    return out


# --------------------------------------------------------------------------- fires (EFIRE)
_EFIRE_PREFIX = "VIIRS_EFIRE_VIIRSI_EDR"
_POLY = re.compile(rb"POLYGON\(\(([-0-9., ]+)\)\)")


def _granule_bounds(url: str) -> tuple[float, float, float, float] | None:
    head = http_get(url, (0, 40_000))
    m = _POLY.search(head)
    if not m:
        return None
    pts = np.array([[float(v) for v in p.split()] for p in m.group(1).decode().split(",")])
    return (
        float(pts[:, 0].min()),
        float(pts[:, 1].min()),
        float(pts[:, 0].max()),
        float(pts[:, 1].max()),
    )


def _intersects(
    b: tuple[float, float, float, float], box: tuple[float, float, float, float]
) -> bool:
    if b[2] - b[0] > 180:  # granule crossing the antimeridian
        return False
    return not (b[2] < box[0] or b[0] > box[2] or b[3] < box[1] or b[1] > box[3])


def _efire_rows(raw: bytes, box: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    """Parse one EFIRE granule (bytes) -> FIRMS-schema rows inside the box (not thread-safe)."""
    import h5py

    with h5py.File(io.BytesIO(raw), "r") as d:
        if "FP_Latitude" not in d:  # granules without fire pixels omit the FP_* variables
            return []
        lat = np.asarray(d["FP_Latitude"][:], dtype=float)
        if lat.size == 0:
            return []
        lon = np.asarray(d["FP_Longitude"][:], dtype=float)
        keep = (lon >= box[0]) & (lon <= box[2]) & (lat >= box[1]) & (lat <= box[3])
        if not keep.any():
            return []
        mask = np.asarray(d["FP_FireMask"][:])[keep]
        frp = np.asarray(d["FP_FireRadiativePower"][:], dtype=float)[keep]
        day = np.asarray(d["FP_Day"][:])[keep]
        pac = np.asarray(d["FP_PersistentAnomalyCategory"][:])[keep]
        tcs = d.attrs["time_coverage_start"]
        t0 = pd.Timestamp(tcs.decode() if isinstance(tcs, bytes) else str(tcs)).tz_convert(None)
    conf = np.select([mask == 9, mask == 8, mask == 7], ["h", "n", "l"], default="l")
    rows = []
    for la, lo, c, f, dn, pa in zip(lat[keep], lon[keep], conf, frp, day, pac, strict=True):
        rows.append(
            {
                "latitude": round(float(la), 5),
                "longitude": round(float(lo), 5),
                "acq_date": t0.strftime("%Y-%m-%d"),
                "acq_time": int(t0.strftime("%H%M")),
                "satellite": "N",
                "instrument": "VIIRS",
                "confidence": str(c),
                "version": "NOAA-EFIRE-v1r3",
                "frp": round(float(f), 2),
                "daynight": "D" if int(dn) == 1 else "N",
                # persistent (static) anomalies flagged by the algorithm -> FIRMS type 2
                "type": 2 if int(pa) > 0 else 0,
            }
        )
    return rows


def fetch_efire_day(
    day: dt.date, out_dir: Path, box: tuple[float, float, float, float] = KZ_BBOX, workers: int = 24
) -> Path:
    """Fire detections of one UTC day over the box (granules selected by their footprint)."""
    out = out_dir / f"efire_{day:%Y%m%d}.csv"
    if out.exists():
        return out
    keys = sorted(
        k for k, _ in s3_list(EFIRE, f"{_EFIRE_PREFIX}/{day:%Y/%m/%d}/") if k.endswith(".nc")
    )
    urls = [f"{EFIRE}/{k}" for k in keys]
    # Suomi-NPP passes over Kazakhstan only in two UTC windows, in clusters of ~6 consecutive
    # granules. Probe every 2nd granule inside the windows, then expand around every hit, so
    # only ~1/3 of the day's granule headers are read.
    hhmm = [int(re.search(r"_s\d{8}(\d{4})", u).group(1)) for u in urls]  # type: ignore[union-attr]
    in_window = [(h >= 330 and h < 1230) or h >= 1800 or h < 200 for h in hhmm]
    cand = [i for i, ok in enumerate(in_window) if ok]
    bounds: dict[int, tuple[float, float, float, float] | None] = {}

    def probe(idx: list[int]) -> None:
        todo = [i for i in idx if i not in bounds and 0 <= i < len(urls)]
        for i, b in zip(
            todo, parallel(lambda i: _granule_bounds(urls[i]), todo, workers), strict=True
        ):
            bounds[i] = b

    probe(cand[::2])
    while True:
        hits = [i for i, b in bounds.items() if b is not None and _intersects(b, box)]
        nxt = sorted({j for i in hits for j in range(i - 2, i + 3)} - set(bounds))
        nxt = [j for j in nxt if 0 <= j < len(urls)]
        if not nxt:
            break
        probe(nxt)
    hit = [urls[i] for i in sorted(hits)]
    rows: list[dict[str, Any]] = []
    for raw in parallel(http_get, hit, min(workers, 8)):  # download in parallel
        rows += _efire_rows(raw, box)  # parse sequentially (HDF5 is not thread-safe)
    cols = [
        "latitude",
        "longitude",
        "acq_date",
        "acq_time",
        "satellite",
        "instrument",
        "confidence",
        "version",
        "frp",
        "daynight",
        "type",
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=cols).to_csv(out, index=False)
    (out_dir / f"efire_{day:%Y%m%d}.meta.json").write_text(
        json.dumps(
            {
                "granules_listed": len(urls),
                "headers_read": len(bounds),
                "granules_over_box": len(hit),
                "detections": len(rows),
            }
        )
    )
    return out


def _efire_day_worker(args: tuple[str, str]) -> str:
    day, out_dir = args
    try:
        fetch_efire_day(dt.date.fromisoformat(day), Path(out_dir))
        return f"{day} ok"
    except Exception as exc:
        return f"{day} FAILED {exc}"


def fetch_efire_range(start: dt.date, end: dt.date, out_dir: Path, procs: int = 4) -> list[str]:
    """Daily fire files for [start, end] using several processes (HDF5 per process)."""
    import multiprocessing as mp

    days = [
        (str(start + dt.timedelta(days=i)), str(out_dir)) for i in range((end - start).days + 1)
    ]
    days = [d for d in days if not (out_dir / f"efire_{d[0].replace('-', '')}.csv").exists()]
    out = []
    with mp.get_context("spawn").Pool(procs) as pool:
        for msg in pool.imap_unordered(_efire_day_worker, days):
            out.append(msg)
            if "FAILED" in msg or len(out) % 25 == 0:
                log.info("efire progress %d/%d (%s)", len(out), len(days), msg)
    return out


# --------------------------------------------------------------------------- NDVI (CDR)
def _ndvi_day(day: dt.date, box: tuple[float, float, float, float]) -> np.ndarray | None:
    import fsspec
    import h5py

    keys = s3_list(NDVI_CDR, f"data/{day.year}/VIIRS-Land_v001_JP113C1_NOAA-20_{day:%Y%m%d}_")
    if not keys:
        return None
    url = f"{NDVI_CDR}/{keys[-1][0]}"
    w, s, e, n = box
    r0, r1 = int((90 - n) / 0.05), int(np.ceil((90 - s) / 0.05))
    c0, c1 = int((180 + w) / 0.05), int(np.ceil((180 + e) / 0.05))
    with fsspec.open(url, "rb", block_size=4 * 2**20) as f, h5py.File(f, "r") as h:
        a = h["NDVI"][0, r0:r1, c0:c1].astype(np.float32)
    a[a <= -9999] = np.nan
    return a * 1e-4


def fetch_ndvi_composite(
    year: int,
    start_doy: int,
    out_dir: Path,
    box: tuple[float, float, float, float] = KZ_BBOX,
    length: int = 16,
) -> Path | None:
    """16-day maximum-value NDVI composite (MOD13-style interval) from daily CDR NDVI."""
    from rasterio.transform import from_origin

    from wildfire_kz.data.rasterio_utils import write_geotiff

    out = out_dir / f"VIIRS_NDVI_CDR_{year}{start_doy:03d}.tif"
    if out.exists():
        return out
    start = dt.date(year, 1, 1) + dt.timedelta(days=start_doy - 1)
    end = min(start + dt.timedelta(days=length - 1), dt.date(year, 12, 31))
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    arrs = [a for a in parallel(lambda d: _ndvi_day(d, box), days, 8) if a is not None]
    if len(arrs) < max(4, length // 3):
        log.warning(
            "NDVI composite %s/%03d: only %d daily files, skipped", year, start_doy, len(arrs)
        )
        return None
    stack = np.stack(arrs)
    valid = np.isfinite(stack) & (stack > -0.3) & (stack <= 1.0)
    comp = np.where(valid.any(axis=0), np.nanmax(np.where(valid, stack, np.nan), axis=0), np.nan)
    ndvi_i = np.where(np.isfinite(comp), np.round(comp / 1e-4), -3000).astype(np.int16)
    evi_i = np.full_like(ndvi_i, -3000)  # the CDR provides NDVI only
    qa = np.where(np.isfinite(comp), 0, 3).astype(np.int16)
    w, n = box[0], box[3]
    r0, c0 = int((90 - n) / 0.05), int((180 + w) / 0.05)
    tr = from_origin(-180 + c0 * 0.05, 90 - r0 * 0.05, 0.05, 0.05)
    write_geotiff(
        out,
        np.stack([ndvi_i, evi_i, qa]),
        tr,
        "EPSG:4326",
        tags={
            "SOURCE": "NOAA CDR VIIRS NDVI (noaa-cdr-ndvi-pds), daily -> 16-day MVC",
            "composite_start": start.isoformat(),
            "composite_end": end.isoformat(),
            "n_daily_files": str(len(arrs)),
        },
        band_descriptions=["NDVI", "EVI (not available)", "QA (0 valid, 3 missing)"],
    )
    return out


# --------------------------------------------------------------------------- static layers
def _read_window(
    url: str, box: tuple[float, float, float, float], res_deg: float, resampling: str
) -> tuple[np.ndarray, Any]:
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.windows import from_bounds

    with rasterio.open(url) as src:
        win = from_bounds(*box, transform=src.transform).round_offsets().round_lengths()
        h = max(1, round((box[3] - box[1]) / res_deg))
        w = max(1, round((box[2] - box[0]) / res_deg))
        arr = src.read(
            1,
            window=win,
            out_shape=(h, w),
            boundless=True,
            fill_value=src.nodata if src.nodata is not None else 0,
            resampling=getattr(Resampling, resampling),
        )
        tr = from_origin(box[0], box[3], (box[2] - box[0]) / w, (box[3] - box[1]) / h)
        return arr, (tr, src.nodata)


def fetch_worldcover(
    out_dir: Path, box: tuple[float, float, float, float] = KZ_BBOX, res_deg: float = 1 / 240
) -> Path:
    """ESA WorldCover 2021 classes on a ~460 m grid (nearest from the 10 m COG tiles)."""
    from wildfire_kz.data.rasterio_utils import write_geotiff

    out = out_dir / "WorldCover_v200_2021.tif"
    if out.exists():
        return out
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin

    w, s, e, n = box
    W, H = round((e - w) / res_deg), round((n - s) / res_deg)
    mosaic = np.zeros((H, W), dtype=np.uint8)
    tiles = []
    for lat in range(int(np.floor(s / 3) * 3), int(np.ceil(n / 3) * 3), 3):
        for lon in range(int(np.floor(w / 3) * 3), int(np.ceil(e / 3) * 3), 3):
            ns = f"N{lat:02d}" if lat >= 0 else f"S{-lat:02d}"
            ew = f"E{lon:03d}" if lon >= 0 else f"W{-lon:03d}"
            tiles.append((lat, lon, f"{WORLDCOVER}/ESA_WorldCover_10m_2021_v200_{ns}{ew}_Map.tif"))

    def one(t: tuple[int, int, str]) -> tuple[int, int, np.ndarray] | None:
        lat, lon, url = t
        try:
            with rasterio.open(url) as src:
                k = round(3 / res_deg)
                return lat, lon, src.read(1, out_shape=(k, k), resampling=Resampling.mode)
        except Exception:
            return None

    for r in parallel(one, tiles, 8):
        if r is None:
            continue
        lat, lon, a = r
        k = a.shape[0]
        row0 = round((n - (lat + 3)) / res_deg)
        col0 = round((lon - w) / res_deg)
        rr0, cc0 = max(row0, 0), max(col0, 0)
        rr1, cc1 = min(row0 + k, H), min(col0 + k, W)
        if rr1 > rr0 and cc1 > cc0:
            mosaic[rr0:rr1, cc0:cc1] = a[rr0 - row0 : rr1 - row0, cc0 - col0 : cc1 - col0]
    write_geotiff(
        out,
        mosaic,
        from_origin(w, n, res_deg, res_deg),
        "EPSG:4326",
        nodata=0,
        tags={"SOURCE": "ESA WorldCover 10 m 2021 v200 (mode-resampled)"},
        band_descriptions=["WorldCover class"],
    )
    return out


def fetch_copdem(
    out_dir: Path, box: tuple[float, float, float, float] = KZ_BBOX, workers: int = 16
) -> list[Path]:
    """Copernicus DEM GLO-90 1-degree COG tiles covering the box."""
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for lat in range(int(np.floor(box[1])), int(np.ceil(box[3]))):
        for lon in range(int(np.floor(box[0])), int(np.ceil(box[2]))):
            name = f"Copernicus_DSM_COG_30_N{lat:02d}_00_E{lon:03d}_00_DEM"
            jobs.append((f"{COPDEM}/{name}/{name}.tif", out_dir / f"{name}.tif"))

    def one(j: tuple[str, Path]) -> Path | None:
        url, path = j
        if path.exists():
            return path
        try:
            data = http_get(url)
        except RuntimeError:
            return None  # sea tiles are absent
        path.write_bytes(data)
        return path

    return [p for p in parallel(one, jobs, workers) if p is not None]


def fetch_hrsl(
    out_dir: Path, box: tuple[float, float, float, float] = KZ_BBOX, res_deg: float = 1 / 120
) -> Path:
    """Meta HRSL population counts aggregated to ~1 km (sum preserved)."""
    from wildfire_kz.data.rasterio_utils import write_geotiff

    out = out_dir / "hrsl_2020.tif"
    if out.exists():
        return out
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.windows import from_bounds

    w, s, e, n = box
    W, H = round((e - w) / res_deg), round((n - s) / res_deg)
    with rasterio.open(HRSL_VRT) as src:
        win = from_bounds(*box, transform=src.transform)
        native_px = abs(src.transform.a)
        a = (
            src.read(
                1,
                window=win,
                out_shape=(H, W),
                boundless=True,
                fill_value=0,
                resampling=Resampling.average,
                masked=True,
            )
            .filled(0)
            .astype(np.float32)
        )
    a = a * (res_deg / native_px) ** 2  # mean count per native pixel -> count per coarse pixel
    write_geotiff(
        out,
        a,
        from_origin(w, n, res_deg, res_deg),
        "EPSG:4326",
        nodata=-1.0,
        tags={
            "SOURCE": "Meta/CIESIN HRSL general population (dataforgood-fb-data)",
            "UNITS": "persons per pixel",
            "REFERENCE_YEAR": "2020",
        },
    )
    return out


def settlements_from_worldcover(
    worldcover_tif: Path, out_file: Path, min_share: float = 0.25, block: int = 2
) -> Path:
    """Point snapshot of built-up clusters (WorldCover class 50) for settlement proximity."""
    import geopandas as gpd
    import rasterio

    with rasterio.open(worldcover_tif) as src:
        a = src.read(1)
        tr = src.transform
    H, W = (a.shape[0] // block) * block, (a.shape[1] // block) * block
    built = (a[:H, :W] == 50).reshape(H // block, block, W // block, block).mean(axis=(1, 3))
    rr, cc = np.nonzero(built >= min_share)
    xs = tr.c + (cc * block + block / 2) * tr.a
    ys = tr.f + (rr * block + block / 2) * tr.e
    g = gpd.GeoDataFrame(
        {"built_share": built[rr, cc]}, geometry=gpd.points_from_xy(xs, ys), crs="EPSG:4326"
    )
    out_file.parent.mkdir(parents=True, exist_ok=True)
    g.to_file(out_file, driver="GeoJSON")
    return out_file


def efire_to_monthly_csv(day_dir: Path, out_dir: Path) -> list[Path]:
    """Concatenate daily EFIRE CSVs into monthly files in the FIRMS schema."""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: dict[str, list[pd.DataFrame]] = {}
    for f in sorted(day_dir.glob("efire_*.csv")):
        frames.setdefault(f.stem[6:12], []).append(pd.read_csv(f))
    paths = []
    for ym, fs in frames.items():
        p = out_dir / f"noaa_efire_snpp_{ym}.csv"
        pd.concat(fs, ignore_index=True).to_csv(p, index=False)
        paths.append(p)
    return paths


# --------------------------------------------------------------------------- orchestration
def fetch_open(cfg: Any, what: str = "all") -> dict[str, Any]:
    """Download every open source needed by a config (``what``: all|boundary|fires|era5|
    ndvi|static). Idempotent: existing files are kept."""
    raw: Path = cfg.project.raw_dir
    src = cfg.sources
    start = cfg.study.start - dt.timedelta(days=cfg.study.lookback_days)
    end = cfg.study.end + dt.timedelta(days=1)
    done: dict[str, Any] = {}
    if what in ("all", "boundary"):
        done["boundary"] = fetch_boundary(raw / Path(src.boundary.path).parent)
    if what in ("all", "static"):
        dem = fetch_copdem(raw / src.srtm.path)
        wc = fetch_worldcover(raw / src.mcd12q1.path)
        hr = fetch_hrsl(raw / src.worldpop.path)
        snaps = src.settlements.snapshots
        st = settlements_from_worldcover(wc, raw / snaps[0].path) if snaps else None
        done["static"] = {"dem_tiles": len(dem), "worldcover": wc, "hrsl": hr, "settlements": st}
    if what in ("all", "era5"):
        months = pd.date_range(pd.Timestamp(start).replace(day=1), end, freq="MS")
        done["era5"] = [fetch_era5_month(m.year, m.month, raw / src.era5_land.path) for m in months]
    if what in ("all", "ndvi"):
        comps = []
        for year in range(start.year, end.year + 1):
            for doy in range(1, 366, src.mod13a2.composite_length_days):
                s0 = dt.date(year, 1, 1) + dt.timedelta(days=doy - 1)
                if s0.year == year and s0 <= end:
                    comps.append(fetch_ndvi_composite(year, doy, raw / src.mod13a2.path))
        done["ndvi"] = comps
    if what in ("all", "fires"):
        daily = raw / "efire_daily"
        msgs = fetch_efire_range(start, end, daily)
        done["fires"] = {
            "failed": [m for m in msgs if "FAILED" in m],
            "monthly": efire_to_monthly_csv(daily, raw / src.firms.path),
        }
    return done
