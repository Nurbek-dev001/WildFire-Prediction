"""GFS daily weather for UTC day D from an earlier run, for forecasts issued the day before.

gfs_forecasts.daily(D) uses the 18 UTC run of D-1 (lead 6-30 h), which is out only after
about 21:30 UTC of D-1. A forecast that must be ready during D-1 uses the 06 UTC run of D-1
instead (published about 09:30-10:30 UTC): the same daily definitions with leads 18-42 h.

  tmax, tmin  maximum / minimum of the four 6-hour TMAX / TMIN windows ending 06..24 UTC of D
  rh, wind    mean of the instants 00, 06, 12, 18 UTC of D
  precip      APCP 0-42 h minus APCP 0-18 h of the run

gfs_forecasts.py is pinned by the v7 release and stays unchanged; its download and
interpolation helpers are reused here with an explicit run hour.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from wildfire_kz.data import gfs_forecasts as g

RUN_HOUR = 6


def _url(run_day: date, run_hour: int, lead: int) -> str:
    stamp = run_day.strftime("%Y%m%d")
    return f"{g.BUCKET}/gfs.{stamp}/{run_hour:02}/atmos/gfs.t{run_hour:02}z.pgrb2.1p00.f{lead:03}"


def _ranges(url: str, wanted: list[str]) -> dict[str, tuple[int, int]]:
    lines = g._get(url + ".idx").decode().strip().splitlines()
    starts = [int(line.split(":")[1]) for line in lines]
    out = {}
    for i, line in enumerate(lines):
        key = ":".join(line.split(":")[3:6])
        if key in wanted and key not in out:
            out[key] = (starts[i], starts[i + 1] - 1 if i + 1 < len(lines) else -1)
    missing = set(wanted) - set(out)
    if missing:
        raise ValueError(f"{url} lacks {sorted(missing)}")
    return out


def _field(url: str, start: int, end: int) -> np.ndarray:
    import eccodes
    from scipy.ndimage import map_coordinates

    data = g._get(url, {"Range": f"bytes={start}-{end if end >= 0 else ''}"})
    handle = eccodes.codes_new_from_message(data)
    try:
        if (eccodes.codes_get(handle, "Ni"), eccodes.codes_get(handle, "Nj")) != (g.NI, g.NJ):
            raise ValueError("Unexpected GFS grid")
        if eccodes.codes_get(handle, "latitudeOfFirstGridPointInDegrees") != 90:
            raise ValueError("Unexpected GFS grid origin")
        values = eccodes.codes_get_values(handle).reshape(g.NJ, g.NI)
    finally:
        eccodes.codes_release(handle)
    lat = -90 + 0.25 * (g.ERA5_Y0 + np.arange(g.ROWS))
    lon = -180 + 0.25 * (g.ERA5_X0 + np.arange(g.COLS))
    j, i = np.meshgrid((90 - lat) / g.RESOLUTION, lon / g.RESOLUTION, indexing="ij")
    return map_coordinates(values, [j, i], order=1).astype("float32")


def daily(day: date, run_hour: int = RUN_HOUR) -> dict[str, np.ndarray]:
    """Daily weather for UTC day `day` from the `run_hour` UTC run of the previous day."""
    run = day - timedelta(days=1)
    first = 24 - run_hour  # lead of 00 UTC of `day`
    temps_max, temps_min, rh, wind = [], [], [], []
    for lead in [first, first + 6, first + 12, first + 18]:
        url = _url(run, run_hour, lead)
        keys = {
            "rh": f"RH:2 m above ground:{lead} hour fcst",
            "u": f"UGRD:10 m above ground:{lead} hour fcst",
            "v": f"VGRD:10 m above ground:{lead} hour fcst",
        }
        r = _ranges(url, list(keys.values()))
        rh.append(_field(url, *r[keys["rh"]]))
        wind.append(np.hypot(_field(url, *r[keys["u"]]), _field(url, *r[keys["v"]])))
    for lead in [first + 6, first + 12, first + 18, first + 24]:
        url = _url(run, run_hour, lead)
        span = f"{lead - 6}-{lead} hour"
        keys = {
            "max": f"TMAX:2 m above ground:{span} max fcst",
            "min": f"TMIN:2 m above ground:{span} min fcst",
        }
        r = _ranges(url, list(keys.values()))
        temps_max.append(_field(url, *r[keys["max"]]))
        temps_min.append(_field(url, *r[keys["min"]]))
    early_url, late_url = _url(run, run_hour, first), _url(run, run_hour, first + 24)
    early_key, late_key = (
        f"APCP:surface:0-{first} hour acc fcst",
        f"APCP:surface:0-{first + 24} hour acc fcst",
    )
    precip = _field(late_url, *_ranges(late_url, [late_key])[late_key]) - _field(
        early_url, *_ranges(early_url, [early_key])[early_key]
    )
    return {
        "tmax": np.max(temps_max, axis=0) - 273.15,
        "tmin": np.min(temps_min, axis=0) - 273.15,
        "rh": np.clip(np.mean(rh, axis=0), 0, 100),
        "wind": np.mean(wind, axis=0),
        "precip": np.maximum(precip, 0),
    }
