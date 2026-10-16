# Real-data run on open, credential-free sources

`configs/real_open.yaml` trains the framework on real observations that anyone can download
without accounts or API keys. Acquire everything with:

```bash
wildfire-kz fetch-open all -c configs/real_open.yaml      # idempotent; resumes
wildfire-kz run -c configs/real_open.yaml
```

## Sources

| Feature group | Source | Access | Coverage used | Replaces (methodology) |
|---|---|---|---|---|
| Fire labels | **NOAA Enterprise Active Fire (EFIRE)**, Suomi-NPP VIIRS I-band 375 m | `s3://noaa-nesdis-snpp-pds/VIIRS_EFIRE_VIIRSI_EDR` | 2024-02 → present | FIRMS VIIRS_SNPP_SP (same sensor and resolution; different processing chain) |
| Weather | **ERA5 hourly**, 0.25° (ARCO-ERA5): T2m, Td2m, u10, v10, precipitation, soil water layer 1 | `gs://gcp-public-data-arco-era5` | 2024-01 → 2026-10 | ERA5-Land 0.1° |
| Vegetation | **NOAA CDR VIIRS NDVI** v001, daily 0.05°, turned into 16-day maximum-value composites on the MOD13 calendar | `s3://noaa-cdr-ndvi-pds` | 2024-01 → 2026-09 | MOD13A2 v061 (NDVI and EVI) |
| Land cover | **ESA WorldCover v200 2021**, 10 m, mode-resampled to ~460 m | `s3://esa-worldcover` | 2021 map | MCD12Q1 preceding-year maps |
| Terrain | **Copernicus DEM GLO-90** | `s3://copernicus-dem-90m` | static | SRTM |
| Population | **Meta HRSL** general population, summed exactly to 30″ (KZ total 18.76 M) | `s3://dataforgood-fb-data/hrsl-cogs` | ~2020 | WorldPop |
| Settlements | built-up pixels (class 50) of WorldCover 2021, 2×2-pixel clusters | derived | 2021 snapshot | gazetteer snapshots |
| Roads | **not used**: no historical road snapshot is available credential-free; present-day roads are never substituted (methodology rule) and the variable is flagged | – | – | historical OSM |
| Boundary, regions | **Overture Maps** divisions (KZ land boundary + oblasts) | `s3://overturemaps-us-west-2` | 2026-09 release | geoBoundaries |

## How each source is processed

* **Fires.** Each day lists about 1,000 global granules. Only granules whose footprint
  (`geospatial_bounds`, read from the first 40 kB of the file) intersects Kazakhstan are
  downloaded. Overpasses only occur in two UTC windows, so headers are probed every second
  granule and the search expands around hits. Fire-mask classes 7/8/9 map to the categorical
  confidence l/n/h (low is dropped, as in the methodology). Pixels flagged as persistent
  anomalies (gas flares, industry) become `type = 2` and are removed together with the
  development-period industrial mask.
* **Archive outages.** The NOAA bucket has days with no granules (e.g. 2024-07-11..17,
  2026-07-11..19) and partial days next to them. A day holding fewer than 95 % of the usual
  ~1,012 granules is listed in `firms_coverage/efire_gaps.csv` (88 days inside the study
  period). Labels on those days are unknown rather than zero, so they leave the risk set
  together with the two following days (a fire that started during the outage would look
  new, and recent-detection eligibility cannot be established).
* **ERA5.** Each hourly global chunk is fetched and cropped to 40.5–55.5°N, 46.4–87.4°E.
  Temperature, dewpoint and wind are 3-hourly (8 steps per day); precipitation is hourly and
  summed per UTC day with the ERA5 *hourly* accumulation convention
  (`precip_convention: hourly`); soil water uses the 12 UTC value. The current month is only
  partly published (ERA5T lags ~1 week): it is written as `era5_arco_YYYY_MM_partial.nc` with
  unpublished hours left missing, and replaced once the month is complete.
* **Population.** HRSL is missing (NaN) where no buildings were detected, so averaging
  overviews would inflate sparse areas. The ten 10° tiles over Kazakhstan are downloaded whole
  and summed at full resolution onto the 30″ grid.
* **NDVI.** Only the two HDF5 chunks that cover Kazakhstan are read per daily file (HTTP
  range requests). Daily NDVI in [−0.3, 1] is maximum-composited over each 16-day MOD13
  interval. The CDR is published about three weeks after acquisition, so the composite
  availability lag is set to 25 days. EVI is not provided and drops out automatically
  (training-only screening of empty features).

## Study design forced by data availability

Fire labels exist only from February 2024, so the year-based protocol (2015–2021 / 2022 /
2023–2024) cannot be used. The same chronological logic is applied with date periods:

| partition | period | use |
|---|---|---|
| development | 2024-03-01 – 2025-06-30 | training, Optuna tuning, model selection, spatial CV |
| rolling-origin fold 1 | train 2024-03 – 2024-07 → validate 2024-08 – 2024-12 | tuning |
| rolling-origin fold 2 | train 2024-03 – 2024-12 → validate 2025-01 – 2025-06 | tuning |
| calibration | 2025-07-01 – 2025-12-31 | Platt calibration, threshold, map classes only |
| test | 2026-01-01 – 2026-09-30 | untouched until final evaluation (code-enforced) |
| operational | 2026-10-01 – 2026-10-09 (last published ERA5T day) and later | forecasts only; never used for fitting, tuning, calibration or evaluation |

Compute-driven reductions on a 4-CPU machine (all configurable): 15 Optuna trials per
ensemble (methodology: 50), 3 trials per spatial fold, no 50/150 km block sensitivity,
ablations for logistic regression and XGBoost only, evaluation negatives sampled at 5 % with
inverse-inclusion weights.

## What the results can and cannot say

* About 2.6 years of labels is short. Inter-annual variability is barely sampled, and the
  test period is a single fire season.
* EFIRE is not FIRMS. Detection rates and confidence classes may differ, so models trained
  here should not be compared number-for-number with FIRMS-based studies.
* ERA5 at 0.25° is coarser than ERA5-Land, and 3-hourly sampling slightly underestimates
  daily temperature extremes.
* Land cover and population are single static maps (2021 and ~2020), so they cannot capture
  change between 2024 and 2026.
