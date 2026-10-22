# Real Kazakhstan acquisition status — 22 October 2026

## Current public-data experiment

The user authorised documented free alternatives after the initial access audit.
Development/calibration acquisition and feature preparation are now complete.
The separate practical model comparison is running; no winner has been frozen
and no 2023–2024 observation has been materialised for modelling or evaluation.
There are no final real-data performance metrics yet.

| Group | Actual prepared inputs |
| --- | --- |
| Weather | Anonymous Open-Meteo AWS ERA5, 0.25°, hourly temperature, dewpoint, wind components, precipitation and surface soil moisture; 2014 prehistory and 2015–2022 annual arrays. |
| Vegetation | 425 verified weekly NOAA VIIRS NDVI snapshots across the permitted interval, native quality flags and missing-data handling. Two unavailable provider dates in July/August 2022 are recorded as gaps. |
| Land cover | ORNL anonymous MCD12Q1 v061 subset responses, 2014–2021 annual cover, used only for the following year's targets. |
| Terrain | 29 CGIAR SRTM v4.1 tiles; native-centre aggregation, slope before averaging, 99.9737% national finite coverage. |
| Human factors | WorldPop 2010 population and Natural Earth settlements pinned to a 2013 revision. No present-day road layer or EVI was fabricated. |

The development audit records **11** feature tables, **1,250,992** training
rows and **113,442** positive rows before the final development industrial
filter. Required-source, calendar, key, inclusion-probability, weight and range
checks passed. NDVI is missing in 32.1–49.0% of sampled rows, and population
in 0.7–2.0%; preprocessing learns optional-feature medians on training rows only.
Missing mandatory weather, cover or terrain excludes a row. See the actual
`runs/public_hindcast/development_quality.json` and immutable source/table hashes
in `training_sources.json`.

The user waived the original 50-attempt requirement on 22 October, before test
access. Existing random-forest results are retained (14 complete, eight pruned,
one interrupted); XGBoost and CatBoost each target five attempts. The archived
original protocol and `budget_amendment.json` record the change. Scientific inputs
and model-fitting code are unchanged. The comparison retains rolling 2019–2021
validation, training through 2021, and separate 2022 calibration. Six model
families are compared. After release, the coordinator may acquire 2023–2024
predictors and open the opaque detection archives for the single final
evaluation. Model selection, parameters, preprocessing, calibration and thresholds
must be fixed first. All 731 map dates will be independently verified against
their GeoTIFFs before publication.

The [public method](public-hindcast-method.md),
[source checks](source-quality-verification.md), and
[pre-test explanation compatibility decision](explanation-compatibility.md)
document this retrospective experiment. It does not fulfil the strict primary
study's original ERA5-Land/MOD13A2 source contracts or claim its full nested
spatial/sensitivity/ablation analyses. No synthetic software-check result is
being presented as measured model performance.

## Historical initial access audit — 16 October 2026

The remainder records the original access attempt before the user authorised
the public alternative. Its missing-input statements refer to that initial
strict-source attempt, not the prepared public-data experiment above.

**The full real-data study has not run.** Under the user's public-access-only constraint, acquisition and registration are partial. The attempted pipeline stopped before ingestion completed because required predictor tables were missing. No real-data performance results, selected model, calibration, threshold or test evaluation exist.

## Downloaded and registered

* NASA FIRMS annual Kazakhstan **Suomi-NPP VIIRS** archives for 2015–2024, plus 2014 for prehistory: 11 files, 108,368,985 bytes. Every file was discovered in NASA's country inventory, checked against its declared byte size and assigned a SHA-256 digest. No account or API key was used.
* The 2014–2022 archives were validated and clipped to the study grid. The normalized result contains 1,280,158 detections before confidence filtering and industrial screening; 1,129,546 are from the requested 2015–2022 period. Observed product-version fields are `2`, with no NRT version accepted. These are source-record counts, **not events or model results**.
* The 2023 and 2024 archives were downloaded as opaque files. Only byte counts and checksums were handled; their CSVs were not parsed and their detection counts were not inspected. They are separately registered under `data.sealed_detection_archives` and can be normalized by the pipeline only through final evaluation.
* Kazakhstan ADM0 and ADM1 geometry from geoBoundaries at revision `9469f09592ced973a3448cf66b6100b741b64c0d`, with source-layer ODbL attribution. These are OSM-derived boundaries representing 2017, **not a claimed government boundary**. The ADM1 layer is a fixed historical reporting geography, not a contemporary region predictor.
* The full unsimplified national boundary produced **110,129** clipped 5 km cells in the documented equal-area CRS. Interior-cell construction was accelerated with prepared geometric predicates; boundary intersections and stable IDs retain their original definitions.

Actual assets are under `data/real/`. The partial configuration is `configs/real_public.yaml`. Acquisition evidence lives in `runs/primary/acquisition/`:

| File | Meaning |
| --- | --- |
| manifest.json | Original URLs, resolved URLs, source versions, download times, byte counts and hashes; opaque holdout state |
| registration.json | Normalization audit by permitted year, grid geometry count, arithmetic storage estimate and missing source list |
| public_access_probes.json | Actual anonymous-access outcomes for required product URLs |
| preflight.json | Current registered-file hashes, missing sources and holdout release state |
| run_state.json | Recorded stop before ingestion, with no training or final evaluation started |
| run_attempt.log | Actual attempted full-pipeline failure and its missing-input message |

## Required inputs still missing

| Input | Observed status |
| --- | --- |
| MOD13A2 v061 vegetation | Public CMR metadata available; the actual LP DAAC granule endpoint returned **HTTP 401** anonymously. |
| MCD12Q1 v061 land cover | Public CMR metadata available; the actual LP DAAC granule endpoint returned **HTTP 401** anonymously. |
| ERA5-Land weather | The checked Earth Data Hub Zarr metadata endpoint returned **HTTP 401**. CDS requires an account/API setup and manual licence acceptance. Open-Meteo documents a public ERA5/ERA5-Land distribution, but a complete compatible source containing every required field, native conventions and publication metadata has not been acquired or verified. |
| SRTM terrain | Not acquired or normalized. No alternative DEM was silently substituted. |
| Dated human factors | Not acquired or normalized. Contemporary roads were omitted. WorldPop Global2 was released after the study period and cannot be silently treated as historical information available in 2015–2024. |

The anonymous Planetary Computer collection catalog was also checked and contained no exact MOD13A2/MCD12Q1 candidates. These probes establish the access blockers encountered here; they are not a claim that every possible public mirror was exhaustively searched.

The national lattice implies 402,301,237 target cell-days before risk-set exclusions. A dense representation of 25 float64 predictors plus 25 int64 availability timestamps alone occupies about 149.9 GiB **uncompressed**, before IDs, staging and raster inputs. This is an arithmetic footprint, not an estimate of compressed Parquet size. About 16 GiB remained free after preparation. Downloads preserve a 5 GiB reserve; no cleanup of unrelated user files was performed.

Publication time must be distinguished from observation year. Current reprocessed MODIS granules and retrospective population products cannot be assigned invented earlier availability. Missing historical availability/provenance must be resolved before the primary experiment is eligible to train.

## Reproduce the permitted preparation

```sh
python scripts/acquire_public_kazakhstan.py
python -m wildfire_kz register-public
python -m wildfire_kz real-preflight -c configs/real_public.yaml
```

The preflight intentionally exits with status 2 while any required source is missing. `run-all -c configs/real_public.yaml` stops at ingestion under that condition. **Do not replace missing tables with synthetic data, NRT fires, alternate MODIS collections or present-day human factors.** Once compatible required data are available, retain the full tuning/bootstrap budgets and the sealed holdout registry when proceeding.

## Source references

NASA documents the [annual-country archive route and standard-processing replacement](https://firms.modaps.eosdis.nasa.gov/download/). The [geoBoundaries API](https://www.geoboundaries.org/api.html) documents source-specific provenance/licences. [CDS setup](https://cds.climate.copernicus.eu/en/how-to-api) documents account and licence prerequisites; [NASA LAADS download pages](https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/61/MOD13A2/2025/177/) describe Earthdata-token downloads. [Open-Meteo's own distribution tutorial](https://github.com/open-meteo/open-data/blob/main/tutorial_download_era5/README.md) explains its native/mixed-grid products. [WorldPop's Global2 release description](https://www.worldpop.org/blog/worldpop-global2-global-high-resolution-population-estimates-for-2015-2030/) explains its retrospective construction and later release.
