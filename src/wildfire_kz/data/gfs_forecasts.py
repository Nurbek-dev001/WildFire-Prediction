"""As-issued GFS 1° forecasts for a UTC day, from the public NOAA archive on AWS (no key).

A forecast for day D issued before 00 UTC of D can only use runs that are out by then. The
18 UTC run of D-1 is published about 3.5 hours after its start, so it is the latest run
available; its lead times 6-30 hours cover D from 00 to 24 UTC. Daily values follow the
local ERA5 definitions as closely as GFS output allows:

  tmax, tmin  maximum / minimum of the four 6-hour TMAX / TMIN windows (00-24 UTC)
  rh          mean of 2 m RH at 00, 06, 12 and 18 UTC (ERA5: mean of 24 hourly values)
  wind        mean 10 m speed at the same four times (ERA5: hourly mean)
  precip      APCP 0-30 h minus APCP 0-6 h of the run (ERA5: sum of hourly precipitation)

Only the needed GRIB messages are read, by HTTP byte range from each file's .idx. The 1° files
are used because the link to the archive delivered 0.05-0.5 MB/s and their messages are about
a twelfth of the 0.25° size; values are interpolated bilinearly to the 0.25° ERA5 cells of the
Kazakhstan window. Daily weather fields over the steppe are smooth at this scale, and a daily
operational pipeline needs the same small download.
"""

from __future__ import annotations

import http.client
import time
import urllib.request
from datetime import date, timedelta

import numpy as np

BUCKET = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
RUN_HOUR = 18
# ERA5 window of the local weather files: Open-Meteo grid, latitude from -90°, longitude
# from -180°, 0.25°; GFS rows run from 90° and columns from 0°.
ERA5_Y0, ERA5_X0, ROWS, COLS = 522, 906, 61, 164
RESOLUTION, NI, NJ = 1.0, 360, 181
INSTANT = [6, 12, 18, 24]
WINDOWS = [12, 18, 24, 30]


def _get(url: str, headers: dict[str, str] | None = None, attempts: int = 5) -> bytes:
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(request, timeout=120) as response:
                return bytes(response.read())
        except (OSError, http.client.HTTPException):
            if attempt == attempts - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def _url(run_day: date, lead: int) -> str:
    stamp = run_day.strftime("%Y%m%d")
    return f"{BUCKET}/gfs.{stamp}/{RUN_HOUR:02}/atmos/gfs.t{RUN_HOUR:02}z.pgrb2.1p00.f{lead:03}"


def _ranges(run_day: date, lead: int, wanted: list[str]) -> dict[str, tuple[int, int]]:
    """Byte ranges of the wanted messages; keys are 'VAR:level:step' as in the .idx."""
    lines = _get(_url(run_day, lead) + ".idx").decode().strip().splitlines()
    starts = [int(line.split(":")[1]) for line in lines]
    out = {}
    for i, line in enumerate(lines):
        key = ":".join(line.split(":")[3:6])
        if key in wanted and key not in out:
            end = starts[i + 1] - 1 if i + 1 < len(lines) else -1
            out[key] = (starts[i], end)
    missing = set(wanted) - set(out)
    if missing:
        raise ValueError(f"GFS {run_day} f{lead:03} lacks {sorted(missing)}")
    return out


def _field(run_day: date, lead: int, start: int, end: int) -> np.ndarray:
    import eccodes
    from scipy.ndimage import map_coordinates

    data = _get(_url(run_day, lead), {"Range": f"bytes={start}-{end if end >= 0 else ''}"})
    handle = eccodes.codes_new_from_message(data)
    try:
        if (eccodes.codes_get(handle, "Ni"), eccodes.codes_get(handle, "Nj")) != (NI, NJ):
            raise ValueError("Unexpected GFS grid")
        if eccodes.codes_get(handle, "latitudeOfFirstGridPointInDegrees") != 90:
            raise ValueError("Unexpected GFS grid origin")
        values = eccodes.codes_get_values(handle).reshape(NJ, NI)
    finally:
        eccodes.codes_release(handle)
    lat = -90 + 0.25 * (ERA5_Y0 + np.arange(ROWS))
    lon = -180 + 0.25 * (ERA5_X0 + np.arange(COLS))
    j, i = np.meshgrid((90 - lat) / RESOLUTION, lon / RESOLUTION, indexing="ij")
    return map_coordinates(values, [j, i], order=1).astype("float32")


def daily(day: date) -> dict[str, np.ndarray]:
    """Daily weather for UTC day `day` from the 18 UTC run of the previous day."""
    run = day - timedelta(days=1)
    temps_max, temps_min, rh, wind = [], [], [], []
    for lead in INSTANT:
        keys = {
            "rh": f"RH:2 m above ground:{lead} hour fcst",
            "u": f"UGRD:10 m above ground:{lead} hour fcst",
            "v": f"VGRD:10 m above ground:{lead} hour fcst",
        }
        r = _ranges(run, lead, list(keys.values()))
        rh.append(_field(run, lead, *r[keys["rh"]]))
        wind.append(np.hypot(_field(run, lead, *r[keys["u"]]), _field(run, lead, *r[keys["v"]])))
    for lead in WINDOWS:
        span = f"{lead - 6}-{lead} hour"
        keys = {
            "max": f"TMAX:2 m above ground:{span} max fcst",
            "min": f"TMIN:2 m above ground:{span} min fcst",
        }
        r = _ranges(run, lead, list(keys.values()))
        temps_max.append(_field(run, lead, *r[keys["max"]]))
        temps_min.append(_field(run, lead, *r[keys["min"]]))
    early = _ranges(run, 6, ["APCP:surface:0-6 hour acc fcst"])
    late = _ranges(run, 30, ["APCP:surface:0-30 hour acc fcst"])
    precip = _field(run, 30, *late["APCP:surface:0-30 hour acc fcst"]) - _field(
        run, 6, *early["APCP:surface:0-6 hour acc fcst"]
    )
    return {
        "tmax": np.max(temps_max, axis=0) - 273.15,
        "tmin": np.min(temps_min, axis=0) - 273.15,
        "rh": np.clip(np.mean(rh, axis=0), 0, 100),
        "wind": np.mean(wind, axis=0),
        "precip": np.maximum(precip, 0),
    }


def build(first: date, last: date, folder: str, workers: int = 12) -> None:
    """Write one compressed file per day; days already written are skipped (resumable)."""
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]

    def one(day: date) -> str:
        path = out / f"{day}.npz"
        if path.exists():
            return "cached"
        values = daily(day)
        temporary = path.with_suffix(".working.npz")
        np.savez_compressed(temporary, **{k: np.asarray(v) for k, v in values.items()})  # type: ignore[arg-type]
        temporary.replace(path)
        return "written"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, _ in enumerate(pool.map(one, days), 1):
            if done % 30 == 0:
                print(f"gfs {done}/{len(days)}", flush=True)
