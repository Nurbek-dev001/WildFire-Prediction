# Steppe map platform

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
- Change the illustrative scenario date, filter probabilities at 5%, inspect
  cell details, search/select historical reporting regions, and export CSV.
- View actual nominal/high-confidence S-NPP VIIRS detections for 2015–2022.
  These are observations before event linking and industrial-source filtering.
- Inspect source readiness and the temporal study protocol.
- Switch to the real model layer. It is currently unavailable because the real
  training pipeline has not completed. No synthetic smoke model is reused as
  a real geographic model.

The DEMO layer is a deterministic spatial/seasonal formula for demonstrating
the product. Its probabilities, 5% filter, and factor indices are illustrative.
They are not calibrated ML results, measured weather, SHAP, or operational
forecasts. Statistics and CSV exports preserve this distinction. The default
date is a historical demonstration date, not today's operational forecast.

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

## Connect a completed real pipeline

After a real, completed final evaluation and map stage, register a daily raster:

```powershell
.venv\Scripts\python.exe scripts\export_platform_forecast.py --run runs\primary --day 2023-07-15
```

This command currently fails closed because the real model does not exist. It
requires completed non-synthetic stage manifests, matching final-release hashes,
real raster provenance, the full actual national grid, and valid probabilities.
It samples the existing 5 km raster directly without interpolation. Missing
cells remain null; no labels or sealed raw archives are opened by this command.

`assets/forecast-manifest.json` lists available dates and the real model status;
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
