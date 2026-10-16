# Acquiring the real data

The pipeline never downloads data implicitly and never fabricates data. Place the files below
under `project.raw_dir` (default `data/raw/`), then run `wildfire-kz ingest`. Ingest checksums
every file and fails with a list of anything missing. Record retrieval dates in
`sources.<name>.retrieved_on` so they appear in the manifest. Public access does not imply
unrestricted redistribution: keep each provider's terms.

| Source | Expected location / naming | How to obtain |
|---|---|---|
| Kazakhstan boundary | `boundary/kazakhstan_adm0.geojson` (any OGR format via config) | geoBoundaries (gbOpen KAZ ADM0) or another authoritative boundary; set `sources.boundary.source_id/version`. |
| FIRMS VIIRS S-NPP 375 m, standard processing (archive) | `firms/*.csv` with columns `latitude, longitude, acq_date, acq_time, confidence (l/n/h), satellite, instrument, frp, type, …` | FIRMS archive download (country = Kazakhstan, source *VIIRS S-NPP*, *standard processed*), or `wildfire-kz download firms 2014-11-01 2024-12-31` with `FIRMS_MAP_KEY` exported. Use S-NPP only, not NOAA-20/21 or MODIS files. |
| ERA5-Land hourly | `era5_land/*.nc`, one file per month containing whole UTC days, variables `t2m, d2m, u10, v10, tp, swvl1`, dims `valid_time` (or `time`), `latitude`, `longitude` | `wildfire-kz download era5 <year> <month>` (needs `pip install 'wildfire-kz[download]'` and `~/.cdsapirc`). Include the 60 lookback days before 2015-01-01 and **the first day of 2025** (its 00 UTC step holds the precipitation total of 2024-12-31). |
| MOD13A2 v061 | `mod13a2/MOD13A2_061_<YYYY><DOY>.tif`, 3 bands: NDVI, EVI (scaled ×10⁴, fill −3000), SummaryQA | GEE collection `MODIS/061/MOD13A2` (bands `NDVI, EVI, SummaryQA`), or LP DAAC HDF converted with GDAL. File name date = composite start day-of-year. Cover from ~2014-10 for the lookback. |
| MCD12Q1 v061 | `mcd12q1/MCD12Q1_061_<YYYY>.tif`, band 1 = `LC_Type1` (IGBP) | GEE `MODIS/061/MCD12Q1` or LP DAAC. Years 2014–2023 are needed (preceding-year rule; 2014 is used for 2015). |
| SRTM | `srtm/*.tif` tiles (any names), elevation in metres, nodata −32768 | SRTMGL1 v003 (NASA/USGS EarthExplorer or GEE `USGS/SRTMGL1_003`). Tiles are mosaicked on the fly per processing window. |
| WorldPop | `worldpop/kaz_ppp_<YYYY>.tif` (persons per pixel) | WorldPop Hub, Kazakhstan, unconstrained population counts. Years after the last product year fall back to the latest earlier year, and this is flagged. |
| Settlements (optional) | any vector file; list it as a dated snapshot in `sources.settlements.snapshots` | A dated gazetteer extract (e.g. OSM `place=*` nodes from a historical full-history extract). |
| Roads (optional) | dated vector files listed in `sources.roads.snapshots` | **Historical** OSM snapshots (e.g. extracted with `osmium time-filter` from an OSM full-history file at dates before each study year). If no snapshot predates 2015-01-01, the road variable is omitted from the primary experiment and flagged. |
| Admin regions (optional) | `sources.regions.snapshots[-1].path` | Used only to stratify evaluation by region. |
| Burned area / incident records (optional) | `sources.burned_area` | Corroboration only; never used to define labels. |

## Memory notes for the national 5 km run (~109 k cells)

* ERA5-Land is processed one monthly file at a time; the per-year weather cube is cached as
  NetCDF (`features/layers/weather/`).
* SRTM 30 m is warped in 50 km windows with a 2-pixel halo (slope without seams). WorldPop
  100 m in 200 km windows.
* With `sampling.eval_negative_fraction: 0.1`, evaluation tables stay a few GB per year.
  Complete evaluation (`1.0`) is supported but needs more memory.
