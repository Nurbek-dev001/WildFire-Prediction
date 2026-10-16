# Source contracts and availability

Real archives are not bundled. Register local normalized Parquet tables; every non-boundary table has `cell_id` and an integer `year` for predicate pushdown. UTC timestamps must be timezone-aware. Coordinates use the configured projected equal-area CRS. `cell_id` must match the grid; it can be assigned to raw VIIRS points by the events stage when missing.

Each YAML source entry has `path`, `source_id`, `version`, `downloaded_at`, optional `sha256`, and optional `url`. The run manifest hashes every registered source. Keep immutable original assets and their own acquisition/checksum manifests alongside the normalized tables. A normalized file's checksum alone does not certify its provenance; supply the actual product IDs and archive version.

```yaml
data:
  sources:
    weather:
      path: ../data/real/era5_land_hourly.parquet
      source_id: ECMWF/ERA5-Land/hourly
      version: recorded extraction revision
      downloaded_at: '2026-10-16T00:00:00Z'
      sha256: replace_with_actual_digest
```

| Source key | Required fields beyond cell_id/year | Contract |
| --- | --- | --- |
| boundary | geometry, CRS | GeoParquet or vector file; authoritative Kazakhstan boundary. For a regional run, supply the region boundary. |
| detections | timestamp, x, y_coord, confidence, satellite | NASA FIRMS archived **standard-processed Suomi-NPP VIIRS 375 m**; confidence n/h/l; satellite N or Suomi-NPP. Never NRT or MODIS confidence percentages. year is UTC acquisition year. |
| weather, hourly mode | timestamp, available_at, t2m, d2m, u10, v10, tp, swvl1 | Temperatures kelvin, wind m/s, precipitation metres, surface moisture m³/m³. One row/cell/hour; no duplicate hours. Record actual archive availability. |
| weather, daily mode | day, available_at, tmax, tmin, wind, rh, precip, soil_moisture | Explicit normalized daily alternative, °C, m/s, RH percent, precipitation mm. No synthetic substitution. |
| vegetation | interval_start, interval_end, available_at, qa, ndvi, evi | MOD13A2 v061; full end-exclusive 16-day interval; **detailed** uint16 QA; physical NDVI/EVI after scale 0.0001, nodata removed. Strict good-quality policy masks bad VI, aerosol usefulness, cloud, snow and shadow bits. |
| landcover | map_year, available_at, forest, grassland, shrubland, cropland, other | MCD12Q1 v061 IGBP fractions, each [0,1], sum 1 across valid land. Forest=IGBP 1–5; shrubland=6–7; grassland=8–10 (including savannas); cropland=12,14; other=11,13,15–17. Only preceding map year and already published observations can enter. |
| static | available_at, elevation, slope, aspect_sin, aspect_cos, nonvegetated | SRTM elevation m, slope degrees, aspect circular encoding. Derive terrain at native resolution **before** aggregation, with a halo and metric/geodesic pixel spacing. nonvegetated must be frozen from development-dated evidence. Exactly one row/cell. |
| human | available_at, population, settlement_distance, optionally road_distance | Dated WorldPop and settlement evidence; distance m. Optional roads require actual historical OSM snapshot IDs/checksums and `historical_roads: true`. No present-day replacement. |
| regions | geometry, region, CRS | Dated administrative region polygons for real-data regional stratification; record boundary version explicitly. |

For detections, `cell_id` can be omitted when x/y coordinates are supplied. For boundary/regions, `cell_id` and `year` do not apply. Tables may be physically partitioned upstream, but each registered source path currently denotes a single Parquet file; Arrow filters limit materialized observations. National feature outputs are directory datasets.

Local extraction helpers in `data/rasters.py` open NetCDF with Dask and read raster windows. Source-specific acquisition, QA decoding to the above contract, exact area fractions and zonal extraction must be prepared explicitly; these are not inferred from arbitrary raw filenames. A GEE exporter can produce the same contracts without changing the modeling stages. Keep underlying source resolution in metadata: a 5 km cell does not create 5 km information from coarse ERA5-Land.

`zonal_raster()` implements exact equal-area pixel-overlap means or categorical fractions, and native-resolution terrain with metric or per-latitude geodesic spacing. `firms_csv()` converts a declared standard-processed FIRMS CSV and clips detections to cells. `historical_proximity()` requires an explicitly dated local snapshot. Use these Python adapters to prepare the normalized tables; preserve their source metadata rather than inferring publication dates from filenames.

## ERA5-Land rainfall and publication

`era5_land_cumulative` uses the value at 00 UTC as the preceding day's total, converted from metres to mm. It never sums cumulative hourly values. `hourly_increment` sums end-labelled hourly increments after deaccumulation upstream; do not choose it for cumulative data. Incomplete daily meteorology remains missing. Rolling summaries require complete 7/14-day windows.

The official [ERA5-Land documentation](https://confluence.ecmwf.int/pages/viewpage.action?pageId=453673214) and [daily statistics documentation](https://confluence.ecmwf.int/pages/viewpage.action?navigatingVersions=true&pageId=462529317) describe these conventions. [MODIS VI documentation](https://lpdaac.usgs.gov/documents/103/MOD13_User_Guide_V6.pdf) defines the detailed QA fields; record the v061 product revision used.

`available_at` is the actual availability to the intended forecast system, not just the observation time. The configured weather lag adds a minimum latency; it does not overwrite a later actual publication date. A summary ending exactly at target midnight fails the strict `< target` rule and first enters a subsequent target day. Historical ERA5-Land reanalysis is not a live next-day weather feed: using its later final revisions with invented prior-day availability would invalidate an operational claim. The code supports an availability-respecting retrospective experiment; an operational system needs an appropriately archived operational input feed.

MODIS age is measured from the composite interval end, not the publication date. No value older than 32 days is carried forward by default. Annual land-cover availability may leave early-year gaps when the preceding-year product has not yet been published; retain these gaps for training-only imputation.
