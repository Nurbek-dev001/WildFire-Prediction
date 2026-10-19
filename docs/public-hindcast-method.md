# Public Kazakhstan hindcast: documented alternative

This experiment is separate from `configs/real_public.yaml` and the strict primary
study. The user authorised documented public alternatives on 2026-10-17. It uses
real observations and no paid service, credentials or remote compute. It is an
experimental retrospective hindcast, not a validated operational warning system.

## Sources and differences

| Group | Actual public source | Representation and difference |
|---|---|---|
| Weather | [Open-Meteo AWS ERA5](https://github.com/open-meteo/open-data) | Hourly ERA5, 0.25 degrees, nearest native cell. Temperature, dew point, wind components, deaccumulated precipitation and 0–7 cm volumetric soil moisture. ERA5 replaces ERA5-Land. Temperature is already Celsius and rain already mm in these OM files. UTC daily and 7/14-day antecedent summaries are computed locally. |
| Vegetation | [NOAA VIIRS NDVI climate data record](https://www.ncei.noaa.gov/products/climate-data-records/normalized-difference-vegetation-index) | Daily 0.05-degree NDVI, sampled every seven days to bound transfer/storage. Snow, cloud, cirrus, shadow, high aerosol and non-land pixels are excluded using the actual QA bitmask. Missing values stay missing. EVI is omitted, not manufactured. This replaces MOD13A2. |
| Land cover | [NASA ORNL MODIS subsets](https://modis.ornl.gov/data/modis_webservice.html) | MCD12Q1 Collection 6.1 IGBP classes, preceding calendar year only. Native nominal 500 m pixels aggregated to five broad-cover fractions. GDAL area averaging and native pixel-centre country masks approximate partial boundary pixels; this is not the primary exact-overlap implementation. |
| Terrain | [CGIAR SRTM v4.1](https://srtm.csi.cgiar.org/srtmdata/) | Native 90 m elevation. Geodesic pixel spacing is used to derive slope and aspect before area-weighted aggregation to 5 km. Native pixel centres assign contributions to equal-area cells; partial pixel edges are an approximation. Processing strips have gradient halos and non-overlapping cores. Full-tile and cropped processing are checked for numerical agreement. Replaces the primary 30 m source. |
| Human activity | [WorldPop 2010, 1 km](https://data.worldpop.org/GIS/Population/Global_2000_2020_1km/2010/KAZ/) and [Natural Earth 2013 revision](https://github.com/nvkelso/natural-earth-vector/tree/24181daeea339ba2d8224773854b316b3bfba97f/10m_cultural) | Fixed population counts/density and distance to historical major settlements. The population product is retrospective, not an as-issued 2010 release. Major settlements omit many villages. No contemporary roads are substituted for unavailable historical roads. |
| Outcomes | [NASA FIRMS country archives](https://firms.modaps.eosdis.nasa.gov/country/) | Standard-processed Suomi-NPP VIIRS, categorical nominal/high confidence, 2014 prehistory and 2015–2024 outcomes. Low-confidence records do not define events. |

All geometry uses the existing 110,129-cell national 5 km equal-area grid. Fixed
2017 reporting geometry is not a time-varying predictor. Raw downloads and prepared
arrays have SHA-256 sidecars; range-read archives record the provider URL, object
ETag, full object size, native grid and selection. An ETag is not misrepresented
as a checksum of a global file that was never downloaded.

## Temporal limits

The source archives contain later reprocessed releases. Actual retrieval and
provider object dates are recorded separately from observation dates. Historical
as-issued publication dates cannot be reconstructed for all sources. Consequently,
this experiment cannot establish operational, as-issued forecasting performance.
It never pretends the reprocessed files were downloaded in 2015.

For the hindcast feature construction, daily weather is assigned a conservative
five-day release lag after the complete UTC day. Availability must be strictly
before target midnight; this makes the latest weather observation target minus
seven days. Weekly NDVI uses ten days after the observation-day end and the same
strict inequality, with a maximum observation age of 32 days. These are documented
hindcast assumptions, not verified historical publication timestamps. Prior-year
land cover and fixed population are retrospective proxies with the limitations
above. There are no target-day/future weather observations or target-day fire
history features.

## Outcomes, selection and evaluation

Events use the existing 2 km / 48 hour connected-component definition and earliest
detection outcome. Eligibility excludes detections in the preceding 48 hours,
strictly before target midnight. Persistent nonvegetated hot spots are identified
using development data only and frozen. All eligible positives are retained.
Negatives are probability sampled within year × month × broad cover, with explicit
inclusion probabilities and inverse-probability weights.

Development is 2015–2021; rolling validation years are 2019, 2020 and 2021, with
earlier years as training. Logistic regression, random forest, XGBoost and CatBoost
are compared with weather-only logistic and seasonal-cover baselines. Preprocessing
is fitted on each training fold only. Model selection uses development average
precision. The separate 2022 sample is reserved for sigmoid calibration and operating
thresholds. Model files, feature definitions, calibration, thresholds and source
registry must be hash-frozen before access to 2023–2024. Test metrics never select
the winning model. The strict primary nested spatial/time validation, event/grid
sensitivity and ablation protocol remain a separate study; completion of this
practical run does not claim completion of those primary analyses.

Each ensemble has 50 Optuna attempts. A median pruner can stop an unpromising
attempt after a rolling fold; completed/pruned/failed counts and every parameter
set are retained. Industrial masks for rolling validation use only that fold's
earlier training years. The final industrial mask uses development through 2021.
Mandatory weather, cover and terrain gaps are excluded and counted; map gaps remain
missing. NDVI and population gaps can be median-imputed by preprocessing fitted
on training rows only. Test negatives are probability sampled; design-weighted
metrics estimate the eligible population with observed mandatory predictors.

Maps must identify their target date and retrospective status, show continuous
calibrated probabilities and preserve missing cells. No demonstration formula may
be described as output from the trained model. The final run report records actual
sample counts, trials completed, metrics, hashes and limitations.
