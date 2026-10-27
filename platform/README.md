# Steppe map platform

## Current trained model revision

The current map uses XGBoost plus a trained chronological logistic stack, with
32 inputs including six lagged fire-history features. Training ends in 2021;
selection/calibration end in 2022. On the previously reported 2023–2024 benchmark,
recall is 7.3421%, precision 7.3608%, AP 0.02392 and ROC-AUC 0.94211. Precision
is lower than the original model; it was not fully preserved. See
[`docs/model-upgrade-v3.md`](../docs/model-upgrade-v3.md) and `/upgrade/`.

The float16 transport was declared before final evaluation. All metrics use
the exact same rounded probabilities as the map. Browser code verifies the
model release, evaluation, frozen threshold and all probability-file hashes.
Checks: `node scripts/verify-model-assets.mjs` and
`node scripts/test-upgraded-model.mjs`.

## Previous alert-policy revision v2

The preceding publication defaulted to the maximum-F2 threshold selected only on 2022. Its selector
also offers the original F1 threshold and a lower-precision coverage profile
(selected with recall at least 30% on 2022). See
[`docs/operating-policy-v2.md`](../docs/operating-policy-v2.md).
The `/alerts/` report discloses the precision/recall tradeoff and reuse of an
already reported final benchmark. The model and probability maps are unchanged.
CSV exports include the active alert, threshold, profile and policy SHA-256.

Validate with `node scripts/test-operating-policy.mjs` and
`node scripts/verify-model-assets.mjs` before Site packaging.

A Russian-language map application built around the actual Kazakhstan 5 km
equal-area grid. Buildless HTML, CSS, and JavaScript; no API key, tile service,
server-side dependency, paid service, or heavyweight frontend build required.

From the research repository root:

```powershell
.venv\Scripts\python.exe -m http.server 8770 --bind 127.0.0.1 --directory platform\dist
```

Open http://127.0.0.1:8770/. Serve over HTTP; opening index.html as a local file
does not support fetching the map assets.

## What works

- Pan and zoom the actual national map; select cells by click or keyboard.
- Change dates, inspect cell details, search/select historical reporting
  regions, and export the displayed probabilities to CSV.
- View actual nominal/high-confidence S-NPP VIIRS detections for 2015–2022.
  These are observations before event linking and industrial-source filtering.
- Inspect source readiness and the temporal study protocol.
- Load the real model layer when `assets/forecast-manifest.json` records a
  completed frozen evaluation. Otherwise the layer reports that it is unavailable.
  Its alert threshold comes from 2022 calibration; missing cells remain missing.
- Inspect actual model comparisons and follow links to the evaluated report,
  calibration figures, paired bootstrap intervals, and source inventory.
- Switch any layer to 3D. `relief3d.js` draws SRTM elevation for every cell
  (`assets/elevation.i16`, checked against `elevation.json`) as a WebGL2 block
  model; cells at or above the alert threshold rise as pillars. It is loaded
  only when 3D is first opened. Rebuild the elevation file with
  `.venv\Scripts\python.exe scripts\build_relief_asset.py`.
- Forecast colours use seven log-spaced classes (0.01, 0.03, 0.1, 0.3, 1% and
  the alert threshold): across all 731 maps 99% of cell-days are below 0.33%,
  so linear bins would colour almost the whole country the same. The demo
  formula uses its own edges ending at its 5% filter.
- Without the daily payloads (a fresh Git checkout), the map opens the demo
  with an explicit note instead of an error.
- The default basemap is a true-colour satellite image: NASA Blue Marble Next
  Generation (cloud-free composite, public domain) from NASA GIBS, resampled to
  the 1 km equal-area grid in `assets/satellite.jpg` and checked against
  `satellite.json`. It also textures the 3D relief. Rebuild with
  `.venv\Scripts\python.exe scripts\build_satellite_asset.py`; raw tiles and
  their SHA-256 records stay in `data/real/public_predictors/satellite/raw/`.
  Over the image, cells below 0.03% are transparent.
- For a model date the map marks possible ignition points: cells at or above
  the alert threshold (rings, and a list sorted by probability) and the
  observed new-fire events of that day (diamonds; yellow when the same cell
  had an alert). `assets/events-2023-2024.bin` holds the 17,139 events of the
  release's event audit; these labels were opened only after the model was
  frozen and evaluated, so the comparison is retrospective. Rebuild with
  `.venv\Scripts\python.exe scripts\build_events_asset.py`.
- "Посмотреть место на снимке" (cell card, or any point in the list) opens a
  zoomable satellite view of that place: Esri World Imagery by default
  (about 0.5–1 m; attribution Esri, Maxar, Earthstar Geographics; commercial
  use needs an ArcGIS account under Esri's terms) or Sentinel-2 cloudless 2016
  by EOX (10 m, CC BY 4.0). It overlays the 5 km cells coloured by the
  forecast, the day's alert cells and events, and every observed 2023–2024
  event nearby; cells open a popup with the date's probability, VIIRS counts
  for 2015–2022 and the cell's 2023–2024 events. This is the only part of the
  site that needs a network connection. `detail.js` loads Leaflet and proj4
  from `vendor/` (versions, licences and SHA-256 in `vendor/README.md`) on
  first use. Cell squares use the grid CRS, LAEA lat_0 48, lon_0 67, WGS 84.
- `reports/` holds the readable report pages (model, previous model, alert
  thresholds, data quality) in the shared design. Each page reads only release
  files and checks every one against its `complete.json` (or
  `assets/model-evaluation.json`) SHA-256 before showing a number. The pages
  under `upgrade/`, `results/`, `alerts/` and `quality/` stay byte-for-byte as
  published: they are hash-locked release records, linked as archives.

The DEMO layer is a deterministic spatial/seasonal formula for demonstrating
the product. Its probabilities, 5% filter, and factor indices are illustrative.
They are not calibrated ML results, measured weather, SHAP, or operational
forecasts. Statistics and CSV exports preserve this distinction. The current
default is the evaluated XGBoost map for 2024-07-15. Its retrospective status is
shown throughout the interface.

The actual release passed all 731 daily raster/browser checks. Three dates
(2023-09-18, 2023-09-19 and 2023-12-14) have no eligible cells because mandatory
soil-moisture observations are missing. They show an explicit unavailable-data
message and no numeric maximum; CSV is disabled for those dates. The remaining
728 dates contain actual calibrated probabilities. Model selection and 2022
calibration were frozen before final evaluation; no refit used 2023–2024.

Daily probability payloads are generated build artifacts. They remain on disk
and in the deployment archive, but are excluded from source Git because of its
receive-size limit. The tracked forecast manifest binds every byte by SHA-256.
Before packaging, `node scripts/verify-model-assets.mjs` verifies all 731 files,
coverage, evaluation/report hashes and exact full-grid alert-burden metadata.
A fresh source checkout needs the payloads from the verified research export
above before this check and local packaging can succeed. The Site archive
contains these checked artifacts; raw datasets and model weights stay local.

## Rebuild the public display assets

After the public data registration has completed:

```powershell
.venv\Scripts\python.exe scripts\build_platform_assets.py
```

The exporter reads the actual grid, boundary, regions, and **only** normalized
2015–2022 detections. It does not open the 2023–2024 sealed archives. It emits
a 3.75 MB compact cell dataset plus simplified display outlines. Original
research geometries are preserved. Regions follow the source's **2017**
administrative geography, not modern administrative boundaries. Display assets
include public source attribution; no raw detection files are deployed.

`cells.bin` is little endian, 34 bytes per cell: signed int16 row, signed int16
column, float32 clipped area (km²), float32 longitude/latitude of a point inside
the cell, uint16 region index, eight uint16 annual observation counts (2015–22).
Order matches the registered grid. Native lattice centers are reconstructed from
row/column; clipped cell area is retained.

## Connect the public-data model

The public-data runner chooses models using rolling 2019–2021 validation,
trains on 2015–2021, calibrates on 2022, and freezes all models and thresholds
before evaluating 2023–2024. After those stages complete:

```powershell
.venv\Scripts\python.exe scripts\run_public_hindcast.py export
```

This exports 731 daily maps and verifies all browser payloads against their
two-band GeoTIFFs. The public model uses ERA5, NOAA VIIRS NDVI, MODIS land cover,
SRTM terrain, WorldPop, and dated settlements. Source substitutions and archive
limitations are documented in `docs/public-hindcast-method.md`. These outputs
are retrospective estimates, with no claim of operational validation.

`assets/predictions/YYYY-MM-DD.f32.gz` contains little-endian float32
probabilities in `cells.bin` order. The current lossless transport byte-shuffles
the four byte positions into four contiguous planes before gzip; the browser
restores the exact original float32 bits. The manifest format identifies this
encoding. NaN means missing. The manifest contains
the selected model, frozen release hash, actual test metrics, thresholds,
daily coverage and payload SHA-256. The browser verifies provenance, checksum,
coverage, and probability range before drawing a date. It discards stale
requests and reports failures without substituting demonstration values.
The default evaluated date is 2024-07-15, predefined before final evaluation.

The exported report is under `dist/results/`; CSV metrics are under
`dist/evaluate/`. `assets/export-verification.json` records the full calendar
check, and `assets/full_grid_top_capture.csv` records exact alert burden on
the full eligible grid. Publish only after that verification completes.

## Connect the strict primary pipeline

After a real, completed final evaluation and map stage, register a daily raster:

```powershell
.venv\Scripts\python.exe scripts\export_platform_forecast.py --run runs\primary --day 2023-07-15
```

This separate adapter requires completed non-synthetic stage manifests, matching final-release hashes,
real raster provenance, the full actual national grid, and valid probabilities.
It samples the existing 5 km raster directly without interpolation. Missing
cells remain null; no labels or sealed raw archives are opened by this command.

For this primary adapter, `assets/forecast-manifest.json` lists available dates and the real model status;
`assets/predictions/YYYY-MM-DD.json` contains probabilities in the same order as
`cells.bin`, `target_day`, and `synthetic:false`. Browser date changes reload
that date's output and stale requests are discarded. Feature explanations are
not invented when absent. Re-publish the Site after adding verified outputs.

Running the geography asset builder resets the real-forecast manifest; export
the verified rasters again after rebuilding geography. Keep the test years
sealed until the pipeline's explicit final evaluation gate is reached.

## Sources and licenses

- [geoBoundaries](https://www.geoboundaries.org/), OSM/Wambacher 2017, ODbL.
  Simplified outlines and cell geometry are derived from this public boundary.
- [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/), S-NPP VIIRS country files,
  nominal and high confidence; 2015–2022 aggregates only.

The exact acquisition URLs, revisions, hashes, and access checks remain in
`runs/primary/acquisition/` locally. Sealed files and ML runtime artifacts are
excluded from the Site source and deployment package.
