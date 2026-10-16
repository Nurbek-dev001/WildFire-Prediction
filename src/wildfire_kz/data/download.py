"""Optional real-data downloaders (network + credentials required).

These are deliberately separate from the pipeline: the pipeline only *registers* local files.
Credentials are read from the environment / provider config files, never from this repository.
Every function fails with an explicit message if the dependency, credential or network is
unavailable. They are not exercised by the offline test-suite.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

from wildfire_kz.config.schema import Config
from wildfire_kz.utils.runtime import get_logger

log = get_logger("download")

FIRMS_AREA_API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{product}/{bbox}/{days}/{date}"


class DownloadError(RuntimeError):
    """Raised when a remote source cannot be reached or credentials are missing."""


def _require(module: str, extra: str) -> object:
    try:
        return __import__(module)
    except ImportError as exc:  # pragma: no cover - depends on optional extras
        raise DownloadError(f"'{module}' is not installed; install with pip install "
                            f"'wildfire-kz[{extra}]'") from exc


def download_firms(cfg: Config, bbox: tuple[float, float, float, float],
                   start: dt.date, end: dt.date, out_dir: Path | None = None) -> list[Path]:
    """Download archived standard-processed Suomi-NPP VIIRS detections via the FIRMS area API.

    Requires a MAP_KEY in the environment variable configured at ``sources.firms.api_key_env``.
    """
    requests = _require("requests", "download")
    src = cfg.sources.firms
    key = os.environ.get(src.api_key_env)
    if not key:
        raise DownloadError(f"FIRMS MAP_KEY not set: export {src.api_key_env}=<your key> "
                            "(https://firms.modaps.eosdis.nasa.gov/api/map_key/)")
    out = out_dir or cfg.raw(src.path)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    day = start
    step = dt.timedelta(days=src.api_max_days_per_request)
    bbox_s = ",".join(f"{v:.4f}" for v in bbox)
    while day <= end:
        n = min(src.api_max_days_per_request, (end - day).days + 1)
        url = FIRMS_AREA_API.format(key=key, product=src.api_product, bbox=bbox_s, days=n,
                                    date=day.isoformat())
        try:
            resp = requests.get(url, timeout=120)  # type: ignore[attr-defined]
        except Exception as exc:
            raise DownloadError(
                f"FIRMS unreachable ({exc}); no data were written for {day}") from exc
        if resp.status_code != 200 or resp.text.lower().startswith("invalid"):
            raise DownloadError(f"FIRMS request failed ({resp.status_code}): {resp.text[:200]}")
        path = out / f"firms_{src.api_product}_{day:%Y%m%d}_{n}d.csv"
        path.write_text(resp.text)
        written.append(path)
        day += step
        time.sleep(1.0)  # be polite to the API transaction limit
    log.info("downloaded %d FIRMS chunks", len(written))
    return written


def download_era5_land(cfg: Config, bbox: tuple[float, float, float, float], year: int,
                       month: int, out_dir: Path | None = None) -> Path:
    """Download one month of hourly ERA5-Land fields with ``cdsapi`` (needs ~/.cdsapirc)."""
    cdsapi = _require("cdsapi", "download")
    src = cfg.sources.era5_land
    out = (out_dir or cfg.raw(src.path)) / f"era5_land_{year}_{month:02d}.nc"
    out.parent.mkdir(parents=True, exist_ok=True)
    w, s, e, n = bbox
    request = {
        "variable": list(src.variables.values()),
        "year": str(year), "month": f"{month:02d}",
        "day": [f"{d:02d}" for d in range(1, 32)],
        "time": [f"{h:02d}:00" for h in range(24)],
        "area": [n, w, s, e], "data_format": "netcdf", "download_format": "unarchived",
    }
    try:
        client = cdsapi.Client()  # type: ignore[attr-defined]
        client.retrieve(src.cds_dataset, request, str(out))
    except Exception as exc:  # pragma: no cover - network
        raise DownloadError(f"CDS retrieval failed for {year}-{month:02d}: {exc}") from exc
    return out


def export_gee_collection(collection: str, bands: list[str], bbox: tuple[float, float, float,
                          float], start: dt.date, end: dt.date, scale_m: float,
                          out_dir: Path, filename_fmt: str) -> list[Path]:  # pragma: no cover
    """Export images of an Earth Engine collection to local GeoTIFFs (optional backend).

    Uses ``ee.data.computePixels`` tile-by-tile is outside scope; this helper uses
    ``getDownloadURL`` per image, which is suitable for regional extents. For national
    extents export to Drive/Cloud Storage and register the files locally instead.
    The resulting files are consumed by exactly the same local readers, so GEE remains
    swappable with local rasters.
    """
    ee = _require("ee", "gee")
    requests = _require("requests", "download")
    try:
        ee.Initialize()  # type: ignore[attr-defined]
    except Exception as exc:
        raise DownloadError(f"Earth Engine not authenticated: {exc}. Run `earthengine "
                            "authenticate` first.") from exc
    region = ee.Geometry.Rectangle(list(bbox))  # type: ignore[attr-defined]
    col = (ee.ImageCollection(collection)  # type: ignore[attr-defined]
           .filterDate(start.isoformat(), end.isoformat()).select(bands))
    images = col.toList(col.size()).getInfo()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for info in images:
        img = ee.Image(info["id"])  # type: ignore[attr-defined]
        date = dt.datetime.fromtimestamp(info["properties"]["system:time_start"] / 1000, dt.UTC)
        url = img.getDownloadURL({"region": region, "scale": scale_m, "format": "GEO_TIFF",
                                  "crs": "EPSG:4326"})
        resp = requests.get(url, timeout=600)  # type: ignore[attr-defined]
        if resp.status_code != 200:
            raise DownloadError(f"GEE download failed for {info['id']}: {resp.status_code}")
        path = out_dir / filename_fmt.format(year=date.year, doy=date.timetuple().tm_yday)
        path.write_bytes(resp.content)
        written.append(path)
    return written
