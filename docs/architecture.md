# Architecture

## Goal

Estimate, for every eligible equal-area grid cell *i* and UTC day *t*,

    p̂(i,t) = P( y(i,t) = 1 | x(i, ≤ t−1) )

where *y(i,t)* = 1 when the **earliest detection of a new vegetation-fire event** (Suomi-NPP
VIIRS 375 m) falls in cell *i* on day *t*. Only information observed before day *t* enters the
predictors. The output is **occurrence hazard**, not damage, exposure, vulnerability or risk.

## Pipeline

```
 raw data (real, or `wildfire-kz synth`)
   │
 1 ingest ─────► data_manifest.json (source ids, versions, retrieval dates, SHA-256)
 2 grid ───────► grid.parquet + grid_meta.json (equal-area cells, stable ids)
 3 events ─────► detections_qc / events / positives (+ industrial mask, linkage sensitivity)
 4 risk_set ───► eligible cell-days per year (48 h past-only exclusion)
 5 sampling ───► training design (~10:1, IPW) + evaluation design (unbalanced), strata table
 6 features ───► as-of feature tables per year + leakage report  (cached source layers)
 7 splits ─────► rolling-origin manifest, spatial folds (100/50/150 km), regions
 8 train ──────► Optuna-tuned models, baselines, class-weight variants, spatial CV
 9 calibrate ──► Platt params, τ, map class boundaries  ── frozen + hashed ──┐
10 ablate ─────► grouped ablation models (dev validation + calibrated)       │
11 evaluate ◄── opens 2023–2024 only if calibration hash matches ───────────┘
12 explain ────► TreeSHAP (log-odds), grouped/regional comparisons
13 map ────────► daily prob_/class_ GeoTIFFs (+ .qml), map_index.csv
14 report ─────► REPORT.md, figures (PNG+PDF), tables (CSV), reproducibility_record.json
```

Each stage is a Typer sub-command (`wildfire-kz <stage>`), declared in
`src/wildfire_kz/cli/pipeline.py` with: the config sections that affect it, its upstream
stages and its expected outputs. The stage fingerprint is a SHA-256 of
`{stage, seed, package version, relevant config sections, upstream fingerprints}` (plus the
raw-file listing for `ingest`). A stage whose fingerprint and outputs are unchanged is skipped;
`--force` re-runs it. Every stage directory contains `_stage.json` (fingerprint, seed, inputs,
outputs, timings, summary) and `config_resolved.yaml`, and all runs log to
`<run>/logs/pipeline.log`.

## Repository layout

```
src/wildfire_kz/
  config/       schema.py (pydantic, every parameter + defaults), loader.py (YAML, extends, --set)
  data/         synthetic.py (offline generator), manifest.py (ingest), download.py (optional
                FIRMS/CDS/GEE), rasters.py (catalogs + windowed raster→grid aggregation)
  grid/         grid.py (equal-area grid, stable cell ids, lookups)
  events/       firms.py (read + QC), linking.py (space–time linkage, earliest detection),
                build.py (industrial mask, labels, sensitivity table)
  sampling/     risk_set.py (48 h exclusion), design.py (stratified designs + weights)
  features/     era5.py, modis.py, landcover.py, terrain.py, human.py, fire_history.py,
                registry.py (names/groups/as-of rules), leakage.py, build.py (assembly)
  splits/       build.py (manifests), spatial.py (block folds + buffer), guard.py (FeatureStore)
  models/       pipelines.py (preprocessing, estimators, baselines), tuning.py (Optuna),
                train.py (temporal + spatial experiments), ablation.py
  calibration/  calibrate.py (Platt, τ, class boundaries)
  evaluation/   metrics.py, bootstrap.py, evaluate.py
  explain/      shap_analysis.py
  mapping/      export.py (GeoTIFF + QGIS style)
  report/       build.py, figures.py, style.py
  cli/          main.py (Typer), pipeline.py (stage registry/runner)
  utils/        runtime.py (logging, seeds, hashing, cache), io.py (Parquet), resources.py
  paths.py      artifact layout
configs/        default.yaml (real data), synthetic.yaml (demo), test_smoke.yaml (CI)
tests/          unit tests per guarantee + end-to-end synthetic smoke test
docs/           this file, methodology_mapping.md, assumptions.md, data_acquisition.md
notebooks/      exploration only (reads artifacts; no pipeline logic)
```

## Artifact layout

```
<work_dir>/<run_label>/
  ingest/                       data_manifest.json, checksum_cache.json
  <grid_variant>/               primary | sensitivity (1 km runs never overwrite 5 km runs)
    grid/  events/  risk_set/risk_set/year=YYYY/  sampling/sample/year=YYYY/
    features/features/year=YYYY/  features/layers/{terrain,landcover,population,
             modis_composites}.parquet, distances_*.npy, weather/weather_YYYY.nc
    splits/  train/<model>/model.joblib  calibrate/  ablate/  evaluate/  explain/  map/  report/
  logs/pipeline.log
```

## Configuration schema (summary)

All parameters live in `configs/*.yaml` and are validated by `config/schema.py`
(unknown keys are rejected). Top-level sections:

| Section | Key parameters (defaults) |
|---|---|
| `project` | seed, raw_dir, work_dir, run_label |
| `crs` | equal-area proj string (Albers, lat₀ 48, lon₀ 67, φ₁ 43, φ₂ 53) |
| `study` | start 2015-01-01, end 2024-12-31, lookback_days 60 |
| `grid` | primary 5 km; sensitivity 1 km + region bbox; min_inside_fraction 0.5 |
| `sources.*` | per source: source_id, version, provider, url, path/glob/regex, retrieved_on; FIRMS keep n/h, drop l; MODIS lag 10 d, gap fill 32 d, valid QA; MCD12Q1 class groups, year_offset −1; SRTM working res; WorldPop year_offset −1; dated vector snapshots |
| `events` | spatial 2 km, temporal 48 h, sensitivity 1–5 km × 24–72 h, industrial mask thresholds, tie-break order |
| `risk_set` | exclusion_hours 48 |
| `sampling` | negatives_per_positive 10, min_negatives_per_stratum, strata (year, month, lc_group), eval_negative_fraction, training_weighting |
| `features` | antecedent windows [7, 14], rain threshold, optional FWI, human-factor switches, optional fire history, ablation & correlated groups |
| `splits` | dev 2015–2021, rolling-origin folds, calibration 2022, test 2023–2024, spatial CV (5 folds, 100 km, 50/150 km sensitivity, 25 km buffer) |
| `models` | classifiers, baselines, 50 Optuna trials per ensemble, early stopping, search spaces |
| `calibration` | sigmoid, weighted-F1 threshold |
| `ablation` | models, retune flag, correlated-group ablations |
| `evaluation` | 10 bins, capture 5/10/20 %, bootstrap 1000 × (100 km × 7 d blocks), strata |
| `explain` | partitions, row budget, plots |
| `mapping` | years, class quantiles/labels, nodata |
| `synthetic` | generator domain and resolutions |

## Hard guarantees and where they are enforced

| Guarantee | Enforcement | Test |
|---|---|---|
| predictors use only data before *t* | `features/leakage.py` raises on `asof ≥ t`; per-group as-of columns | `test_leakage.py`, `test_end_to_end.py` |
| MODIS usable only after interval end + lag | `features/modis.py` | `test_leakage.py` |
| later detections never in predictors | `fire_history.py` window `[t−W, t)`; labels separate | `test_leakage.py`, `test_end_to_end.py` |
| test years untouched until final evaluation | `splits/guard.py` (`FeatureStore`, hash ledger) | `test_splits.py`, `test_end_to_end.py` |
| preprocessing fitted on training only | sklearn `Pipeline` in `models/pipelines.py` | `test_preprocessing.py` |
| no balanced evaluation sets | evaluation design + weights in `sampling/design.py` | `test_risk_set_sampling.py`, `test_end_to_end.py` |
| spatial buffer ≥ 25 km, no block overlap | `splits/spatial.py` | `test_splits.py` |
| no fabricated real data | `data/manifest.py` raises `MissingSourceError` | manual (see README) |
