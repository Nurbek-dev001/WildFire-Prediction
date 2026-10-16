"""Feature registry: names, groups and the as-of rule of every predictor.

Each feature group stores an ``asof_<group>`` column holding the *observation date* of the
most recent information used (the UTC day the information describes, or the date it became
available, whichever is later). The leakage check requires ``asof < target date`` for every
row and every non-deterministic group.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from wildfire_kz.config.schema import Config


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: str
    description: str
    asof_rule: str
    categorical: bool = False
    deterministic: bool = False  # calendar features are known in advance (no observation)


GROUP_ASOF_RULE = {
    "weather_prior_day": "UTC day t-1 (hourly fields 00-23 UTC of t-1; precipitation total of "
                         "t-1 read from the 00 UTC step of t per ERA5-Land accumulation)",
    "weather_antecedent": "window [t-W, t-1] (W = 7, 14 days); as-of = t-1",
    "fire_weather": "computed only from t-1 daily weather; as-of = t-1",
    "vegetation": "latest MOD13A2 composite whose interval ended and publication lag elapsed "
                  "by t-1; as-of = availability date",
    "landcover": "MCD12Q1 map of the preceding year; as-of = 31 Dec of the product year",
    "terrain": "SRTM (static, acquired Feb 2000); as-of = acquisition date",
    "anthropogenic": "WorldPop of the preceding year; settlement/road snapshots dated before t; "
                     "as-of = latest of these dates",
    "fire_history": "detections strictly before t (window [t-W, t-1]); as-of = t-1",
    "calendar": "deterministic function of the target date (no observation; exempt)",
}


def feature_specs(cfg: Config) -> list[FeatureSpec]:
    """All candidate features given the configuration (before availability screening)."""
    f = cfg.features
    specs: list[FeatureSpec] = []

    def add(name: str, group: str, desc: str, **kw: bool) -> None:
        specs.append(FeatureSpec(name, group, desc, GROUP_ASOF_RULE[group], **kw))

    for n, d in [
        ("t2m_max_c", "daily max 2 m temperature (°C)"),
        ("t2m_min_c", "daily min 2 m temperature (°C)"),
        ("t2m_mean_c", "daily mean 2 m temperature (°C)"),
        ("d2m_mean_c", "daily mean 2 m dewpoint (°C)"),
        ("rh_mean_pct", "daily mean relative humidity from T and Td (%)"),
        ("rh_min_pct", "daily min relative humidity (%)"),
        ("wind_mean_ms", "daily mean 10 m wind speed (m/s)"),
        ("wind_max_ms", "daily max hourly 10 m wind speed (m/s)"),
        ("precip_mm", "daily total precipitation (mm)"),
        ("swvl1", "daily mean volumetric soil water layer 1 (m3/m3)"),
    ]:
        add(n, "weather_prior_day", d)
    for w in f.weather.antecedent_windows_days:
        add(f"precip_sum_{w}d_mm", "weather_antecedent", f"{w}-day precipitation total (mm)")
        add(f"t2m_max_mean_{w}d_c", "weather_antecedent", f"{w}-day mean of daily Tmax (°C)")
        add(f"rh_mean_{w}d_pct", "weather_antecedent", f"{w}-day mean relative humidity (%)")
    wmax = max(f.weather.antecedent_windows_days)
    add(f"dry_days_{wmax}d", "weather_antecedent",
        f"days with precip < {f.weather.rain_day_threshold_mm} mm in the last {wmax} days")
    if f.weather.include_fire_weather_index:
        add("ffwi_fosberg", "fire_weather", "Fosberg fire-weather index from t-1 Tmax, RHmin, "
            "mean wind")
    for n, d in [("ndvi", "NDVI (QA-masked, gap-filled <= max_gap_fill_days)"),
                 ("evi", "EVI (QA-masked, gap-filled)"),
                 ("ndvi_delta", "NDVI change between the two latest valid composites"),
                 ("veg_age_days", "days between composite end and t-1")]:
        add(n, "vegetation", d)
    for g in ("forest", "shrubland", "grassland", "cropland", "other"):
        add(f"lc_frac_{g}", "landcover", f"area fraction of {g}")
    add("lc_group", "landcover", "dominant broad land-cover group", categorical=True)
    for n, d in [("elevation_m", "mean elevation (m)"),
                 ("slope_deg", "mean slope from native-resolution DEM (°)"),
                 ("aspect_sin", "mean sine of aspect"), ("aspect_cos", "mean cosine of aspect")]:
        add(n, "terrain", d)
    if f.human.use_population:
        add("pop_density", "anthropogenic", "population density (persons/km²)")
    if f.human.use_settlements:
        add("dist_settlement_km", "anthropogenic", "distance to nearest settlement (km)")
    if f.human.use_roads:
        add("dist_road_km", "anthropogenic", "distance to nearest road, historical snapshot (km)")
    if f.fire_history.enabled:
        add("hist_det_days", "fire_history",
            f"distinct detection days in the cell in the previous {f.fire_history.window_days} d")
    if f.include_calendar:
        add("doy_sin", "calendar", "sin(2π doy/365.25) of the target day", deterministic=True)
        add("doy_cos", "calendar", "cos(2π doy/365.25) of the target day", deterministic=True)
    return specs


def resolve_group_refs(names: list[str], specs: list[FeatureSpec]) -> list[str]:
    """Expand ``@group`` references into feature names (keeps only known features)."""
    known = {s.name for s in specs}
    out: list[str] = []
    for n in names:
        if n.startswith("@"):
            out += [s.name for s in specs if s.group == n[1:]]
        elif n in known:
            out.append(n)
    return list(dict.fromkeys(out))


def registry_records(specs: list[FeatureSpec]) -> list[dict[str, object]]:
    return [asdict(s) for s in specs]
