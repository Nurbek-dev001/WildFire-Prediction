"""As-of joins with auditable availability for every predictor."""

from __future__ import annotations

import numpy as np
import pandas as pd

WEATHER = ["tmax", "tmin", "wind", "rh", "precip", "soil_moisture"]
LAGGED = [f"{name}_{days}d" for name in ["precip", "temperature"] for days in [7, 14]]
VEGETATION = ["ndvi", "evi"]
ANTHROPOGENIC = ["population", "settlement_distance", "road_distance"]
TERRAIN = ["elevation", "slope", "aspect_sin", "aspect_cos"]
COVER = ["forest", "grassland", "shrubland", "cropland", "other"]
GROUPS = {
    "weather": WEATHER,
    "lagged_weather": LAGGED,
    "vegetation": VEGETATION,
    "anthropogenic": ANTHROPOGENIC,
    "terrain": TERRAIN,
    "landcover": COVER,
    "calendar": ["month_sin", "month_cos"],
}


def weather_daily(hourly: pd.DataFrame, mode: str, publication_lag_days: int) -> pd.DataFrame:
    """Aggregate hourly ERA5-Land at UTC; cumulative midnight tp belongs to yesterday.

    Input temperatures are kelvin, precipitation metres, wind m/s, surface moisture m3/m3.
    Hourly increments are end-labelled and assigned to the interval ending at valid_time.
    Cumulative tp is never summed. A complete day is required for all hourly variables.
    """
    if mode == "daily":
        daily = hourly.copy()
        daily["day"] = pd.to_datetime(daily.day, utc=True)
        daily["available_at"] = pd.to_datetime(daily.available_at, utc=True)
    else:
        h = hourly.copy()
        h["timestamp"] = pd.to_datetime(h.timestamp, utc=True)
        h["available_at"] = pd.to_datetime(h.available_at, utc=True)
        if h.duplicated(["cell_id", "timestamp"]).any():
            raise ValueError("Duplicate hourly cell observations")
        h["day"] = h.timestamp.dt.floor("D")
        t = h.t2m - 273.15
        d = h.d2m - 273.15
        h["rh"] = np.clip(
            100 * np.exp(17.625 * d / (243.04 + d) - 17.625 * t / (243.04 + t)), 0, 100
        )
        h["wind"] = np.hypot(h.u10, h.v10)
        h["t_c"] = t
        daily = (
            h.groupby(["cell_id", "day"])
            .agg(
                tmax=("t_c", "max"),
                tmin=("t_c", "min"),
                rh=("rh", "mean"),
                wind=("wind", "mean"),
                soil_moisture=("swvl1", "mean"),
                available_at=("available_at", "max"),
                hours=("timestamp", "nunique"),
            )
            .reset_index()
        )
        daily.loc[daily.hours != 24, ["tmax", "tmin", "rh", "wind", "soil_moisture"]] = np.nan
        if mode == "era5_land_cumulative":
            rain = h[h.timestamp.dt.hour == 0].copy()
            rain["day"] = rain.timestamp.dt.floor("D") - pd.Timedelta(days=1)
            rain["precip"] = rain.tp * 1000
            rain = rain.rename(columns={"available_at": "rain_available"})
        elif mode == "hourly_increment":
            h["rain_day"] = (h.timestamp - pd.Timedelta(nanoseconds=1)).dt.floor("D")
            rain = (
                h.groupby(["cell_id", "rain_day"])
                .agg(
                    precip=("tp", lambda x: x.sum(min_count=24) * 1000),
                    rain_available=("available_at", "max"),
                )
                .reset_index()
                .rename(columns={"rain_day": "day"})
            )
        else:
            raise ValueError(f"Unknown precipitation convention {mode}")
        daily = daily.merge(
            rain[["cell_id", "day", "precip", "rain_available"]], on=["cell_id", "day"], how="left"
        )
        daily["available_at"] = daily[["available_at", "rain_available"]].max(axis=1)
    minimum = daily.day + pd.Timedelta(days=1 + publication_lag_days)
    daily["available_at"] = pd.concat([daily.available_at, minimum], axis=1).max(axis=1)
    pieces = []
    for _, group in daily.groupby("cell_id", sort=False):
        g = group.sort_values("day").set_index("day").asfreq("D")
        for window in [7, 14]:
            g[f"precip_{window}d"] = g.precip.rolling(window, min_periods=window).sum()
            g[f"temperature_{window}d"] = (
                ((g.tmax + g.tmin) / 2).rolling(window, min_periods=window).mean()
            )
        # Late arrivals in any antecedent day also govern a rolling aggregate's availability.
        timestamps = g.available_at.dt.as_unit("ns").astype("int64").astype(float)
        g["available_at"] = pd.to_datetime(timestamps.rolling(14, min_periods=1).max(), utc=True)
        pieces.append(g.reset_index())
    return pd.concat(pieces, ignore_index=True)


def asof_join(
    target: pd.DataFrame,
    observations: pd.DataFrame,
    columns: list[str],
    *,
    maximum_age_days: int | None = None,
) -> pd.DataFrame:
    """Join by source publication, strictly before target midnight, within each cell."""
    target = target.copy()
    target["day"] = pd.to_datetime(target.day, utc=True).dt.as_unit("ns")
    available = observations.copy()
    available["available_at"] = pd.to_datetime(available.available_at, utc=True).dt.as_unit("ns")
    available = available.dropna(subset=["available_at"]).sort_values("available_at")
    result = pd.merge_asof(
        target.sort_values("day"),
        available,
        by="cell_id",
        left_on="day",
        right_on="available_at",
        allow_exact_matches=False,
        direction="backward",
        suffixes=("", "_source"),
    )
    if maximum_age_days is not None:
        origin = result["interval_end"] if "interval_end" in result else result.available_at
        stale = result.day - pd.to_datetime(origin, utc=True) > pd.Timedelta(days=maximum_age_days)
        result.loc[stale, columns] = np.nan
    for col in columns:
        result[f"{col}__asof"] = result.available_at.where(result[col].notna())
    keep = list(target.columns) + columns + [f"{c}__asof" for c in columns]
    return result[keep]


def vegetation_available(composites: pd.DataFrame, publication_lag_days: int) -> pd.DataFrame:
    """Mask MOD13A2 detailed QA and enforce end-exclusive interval availability."""
    data = composites.copy()
    data["interval_end"] = pd.to_datetime(data.interval_end, utc=True)
    qa = data.qa.to_numpy(dtype="uint16")
    good = ((qa & 3) == 0) & (((qa >> 2) & 15) <= 2) & (((qa >> 8) & 1) == 0)
    good &= (((qa >> 10) & 1) == 0) & (((qa >> 14) & 1) == 0) & (((qa >> 15) & 1) == 0)
    data = data.loc[good].copy()
    earliest = data.interval_end + pd.Timedelta(days=publication_lag_days)
    published = pd.to_datetime(data.available_at, utc=True)
    data["available_at"] = pd.concat([earliest, published], axis=1).max(axis=1)
    return data


def assert_no_leakage(frame: pd.DataFrame, features: list[str]) -> None:
    """Fail closed for untracked values, nonpast availability, or label-derived features."""
    for col in features:
        if any(term in col.lower() for term in ["detect", "event", "label", "frp", "confidence"]):
            raise ValueError(f"Label-derived predictor forbidden: {col}")
        stamp = f"{col}__asof"
        if stamp not in frame:
            raise ValueError(f"Untracked availability: {col}")
        times = pd.to_datetime(frame[stamp], utc=True)
        invalid = frame[col].notna() & (times.isna() | (times >= frame.day))
        if invalid.any():
            raise ValueError(f"Feature availability leakage: {col}")


def build_features(
    target: pd.DataFrame,
    weather: pd.DataFrame,
    vegetation: pd.DataFrame,
    cover: pd.DataFrame,
    static: pd.DataFrame,
    human: pd.DataFrame,
    publication_lag_days: int,
    fill_days: int,
    historical_roads: bool,
) -> tuple[pd.DataFrame, list[str]]:
    """Create approved predictors with no route from detections to predictor values."""
    data = target.copy()
    data = asof_join(data, weather, WEATHER + LAGGED)
    data = asof_join(
        data,
        vegetation_available(vegetation, publication_lag_days),
        VEGETATION,
        maximum_age_days=fill_days,
    )
    pieces = []
    for year, rows in data.groupby(data.day.dt.year):
        preceding = cover[cover.map_year == year - 1].copy()
        if preceding.cell_id.duplicated().any():
            raise ValueError("Duplicate annual land-cover cells")
        pieces.append(asof_join(rows, preceding, COVER))
    data = pd.concat(pieces, ignore_index=True)
    data = asof_join(data, static, TERRAIN)
    human_cols = ["population", "settlement_distance"] + (
        ["road_distance"] if historical_roads else []
    )
    data = asof_join(data, human, human_cols)
    for col, values in {
        "month_sin": np.sin(2 * np.pi * data.day.dt.month / 12),
        "month_cos": np.cos(2 * np.pi * data.day.dt.month / 12),
    }.items():
        data[col] = values
        data[f"{col}__asof"] = data.day - pd.Timedelta(nanoseconds=1)
    data["landcover"] = data[COVER].idxmax(axis=1).fillna("unknown")
    features = (
        WEATHER + LAGGED + VEGETATION + COVER + TERRAIN + human_cols + ["month_sin", "month_cos"]
    )
    assert_no_leakage(data, features)
    return data, features
