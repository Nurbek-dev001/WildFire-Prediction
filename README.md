# wildfire-kz

**An Explainable Multisource ML Framework for Spatiotemporal Wildfire Risk Prediction and
Mapping in Kazakhstan.** This is a reproducible research codebase implementing the study
methodology by S. Zharylkap and N. Bolarbek (Astana IT University).

The framework estimates, for every eligible 5 km equal-area grid cell *i* and UTC day *t*,

    p̂(i,t) = P( y(i,t) = 1 | x(i, ≤ t−1) )

the probability that a **new vegetation-fire event is first detected** by Suomi-NPP VIIRS in
that cell on that day, using only information observed before day *t*.

> **Scope.** Outputs are *occurrence hazard*. They are not damage, exposure, vulnerability or
> risk. Satellite first detection is a proxy for ignition, and absence of a detection is an
> observed negative, not verified absence of fire. SHAP outputs are predictive associations,
> not causal effects.
>
> **No results are claimed here.** This repository contains no performance numbers. Every
> metric is produced by running the pipeline. Runs on the bundled synthetic generator are
> stamped *SYNTHETIC* everywhere and say nothing about Kazakhstan.

## What it does

| # | Stage (`wildfire-kz <stage>`) | Summary |
|---|---|---|
| 1 | `ingest` | Registers raw data and writes a checksummed data manifest (source ids, versions, retrieval dates, SHA-256). Missing sources fail clearly. |
| 2 | `grid` | Builds an equal-area 5 km national grid (1 km regional sensitivity grid) with stable cell ids. |
| 3 | `events` | VIIRS QC (keep n/h, drop l), dedupe, industrial-hotspot mask from development years, 2 km / 48 h space–time linking, earliest detection = positive; 1–5 km × 24–72 h sensitivity. |
| 4 | `risk-set` | Eligible cell-days; cells with any detection in the preceding 48 h excluded (past only). |
| 5 | `sampling` | All positives plus stratified negatives (year × month × land cover, ~10:1, minimum allocation), inverse-inclusion weights; unbalanced evaluation design. |
| 6 | `features` | ERA5-Land prior-day and 7/14-day weather, MOD13A2 NDVI/EVI (lag-aware, ≤32-day gap fill), preceding-year MCD12Q1 fractions, SRTM slope/aspect (native resolution), dated WorldPop, historical settlement/road proximity; every group carries an as-of date; automated leakage check. |
| 7 | `splits` | Rolling-origin development folds; 2022 calibration; 2023–2024 locked; 5-fold spatial-block CV (100 km; 50/150 km), 25 km buffer. |
| 8 | `train` | L2 logistic, Random Forest, XGBoost, CatBoost, plus land-cover × month and weather-only baselines; Optuna (50 trials) on weighted AP; training-only preprocessing; class-weight sensitivity; spatial CV with per-fold tuning. |
| 9 | `calibrate` | Platt scaling on IPW-weighted 2022, τ = argmax weighted F1, map class boundaries — frozen and hashed. |
| 10 | `ablate` | Removes anthropogenic, lagged-weather and vegetation groups separately, plus correlated groups. |
| 11 | `evaluate` | Opens 2023–2024: precision/recall/F1/FPR/FDP/accuracy, step-wise AP vs trapezoid PR-AUC, ROC-AUC, prevalence, Brier/BSS, reliability + ECE, capture 5/10/20 %, strata, paired block bootstrap, resources, generated flags. |
| 12 | `explain` | TreeSHAP on uncalibrated log-odds, grouped and regional comparisons. |
| 13 | `map` | Daily calibrated-probability and class GeoTIFFs (QGIS-ready). |
| 14 | `report` | `REPORT.md`, figures (PNG + PDF), tables (CSV), `reproducibility_record.json`. |

Stages are idempotent and cached by fingerprint (config + upstream + seed), and log to
`<work_dir>/<run_label>/logs/`. See [`docs/architecture.md`](docs/architecture.md).

## Platform

A web platform serves the results operationally: a daily hazard map, cell drill-down with
model drivers, the production-model card and an API (FastAPI + a vendored Leaflet UI).

```bash
pip install -e ".[platform]"
make platform-demo            # synthetic smoke run, then http://localhost:8000
wildfire-kz forecast 2025-07-15 -c configs/default.yaml     # operational next-day map
wildfire-kz serve -c configs/default.yaml                   # or: docker compose up platform
```

The **production model** is chosen automatically. It is the candidate (four classifiers plus a
log-odds-averaging XGBoost+CatBoost ensemble) with the best weighted AP on the
**development** validation folds. Calibration and test years never influence that choice, so
the test metrics shown in the platform remain an honest estimate. See
[`docs/platform.md`](docs/platform.md).

## Installation

Python ≥ 3.11.

```bash
pip install -e ".[dev]"            # core + test/lint/type-check tooling
pip install -e ".[download]"       # optional: FIRMS API + CDS (cdsapi) downloaders
pip install -e ".[gee]"            # optional: Google Earth Engine export helper
```

## Quick start (offline, synthetic data)

```bash
make synthetic-demo
# equivalent to:
wildfire-kz synth -c configs/synthetic.yaml          # writes data/synthetic_raw (SYNTHETIC)
wildfire-kz run   -c configs/synthetic.yaml          # all 14 stages
open data/work/synthetic/primary/report/REPORT.md
```

`make smoke` runs the faster CI configuration (`configs/test_smoke.yaml`).

Runtime guide (measured on a 4-CPU, 16 GB container): the full synthetic demo took about
1 h 40 min, mostly Optuna tuning and the 15-fold spatial-CV experiment; the smoke
configuration takes ~2–3 min. Reduce `models.n_trials_*` or
`splits.spatial_cv.sensitivity_block_sizes_km` for quicker iterations.

## Running on real data

**Without any credentials:** `wildfire-kz fetch-open all -c configs/real_open.yaml` downloads
open substitutes for every source (NOAA VIIRS EFIRE fires, ERA5, NOAA CDR NDVI, ESA
WorldCover, Copernicus DEM, Meta HRSL), and `wildfire-kz run -c configs/real_open.yaml`
trains and evaluates on them. See [`docs/open_data.md`](docs/open_data.md) for the sources and
[`docs/results_open_data.md`](docs/results_open_data.md) for the measured results.

**With the methodology's original sources:**

1. Obtain the sources and place them under `data/raw/` as described in
   [`docs/data_acquisition.md`](docs/data_acquisition.md). FIRMS and ERA5-Land have optional
   downloaders: `wildfire-kz download firms 2014-11-01 2024-12-31` (needs `FIRMS_MAP_KEY`) and
   `wildfire-kz download era5 2019 7` (needs `~/.cdsapirc`). Credentials are never stored in
   the repository.
2. Fill in `retrieved_on` (and versions) for each source in a copy of `configs/default.yaml`.
3. Run stage by stage or all at once:

```bash
wildfire-kz ingest -c configs/default.yaml
wildfire-kz run    -c configs/default.yaml           # or: make all CONFIG=configs/default.yaml
```

Override any parameter without editing files:

```bash
wildfire-kz events -c configs/default.yaml --set events.spatial_link_km=3 --set project.run_label=link3km
wildfire-kz run    -c configs/default.yaml --set grid.active=sensitivity       # 1 km regional grid
wildfire-kz run    -c configs/default.yaml --set sampling.training_weighting=class_weight
```

The 1–5 km × 24–72 h linkage sensitivity table is written by the `events` stage
(`event_linkage_sensitivity.csv`). Spatial-CV block-size sensitivity (50/150 km) runs inside
`train`. The class-weighting sensitivity models are evaluated alongside the primary models.

### Outputs

```
data/work/<run_label>/<grid>/
  report/REPORT.md, figures/*.png|pdf, tables/*.csv, reproducibility_record.json
  evaluate/metrics_overall.csv, metrics_stratified.csv, bootstrap_pairs.csv, result_flags.json
  map/prob_YYYYMMDD.tif, class_YYYYMMDD.tif (+ .qml), map_index.csv
  explain/shap_*.csv|png, dependence/, local/
```

## Guarantees enforced in code

* **No temporal leakage.** Every feature group has an `asof_*` date and `check_no_leakage`
  raises if any as-of date is ≥ the target day. MODIS composites are usable only after their
  interval ends plus a publication lag. ERA5-Land precipitation follows the 00 UTC
  accumulation convention.
* **Test years locked.** `FeatureStore` refuses 2023–2024 until calibration, threshold and map
  class boundaries are frozen; a hash ledger re-locks them if those artifacts change. The
  calibration year can never be used for fitting.
* **Training-only preprocessing.** Screening, imputation, scaling and encoding live in sklearn
  Pipelines fitted on training rows.
* **Representative evaluation.** Validation, calibration and test use unbalanced (or
  probability-sampled, weighted) designs. Resampling exists only in training.
* **No fabricated data.** Missing real sources raise `MissingSourceError`. Present-day roads
  are never substituted for historical snapshots.
* **Determinism.** A global seed with derived per-component seeds, recorded in every stage
  record and in the reproducibility record.

## Development

```bash
make check          # ruff (lint + format check), mypy, pytest
pytest -q           # 91 tests incl. an end-to-end synthetic smoke test (~2–3 min)
```

CI (`.github/workflows/ci.yml`) runs the same checks. Notebooks in `notebooks/` are for
exploration only; all logic lives in `src/wildfire_kz`.

## Documentation

* [`docs/architecture.md`](docs/architecture.md): plan, repository tree, artifact layout,
  config schema, guarantees ↔ tests.
* [`docs/methodology_mapping.md`](docs/methodology_mapping.md): every methodology statement
  (§2.1–2.3, Eqs. 1–4) mapped to modules, config keys and tests.
* [`docs/assumptions.md`](docs/assumptions.md): resolved ambiguities and deviations, with
  justification.
* [`docs/data_acquisition.md`](docs/data_acquisition.md): obtaining and laying out real data.
* [`docs/open_data.md`](docs/open_data.md) and
  [`docs/results_open_data.md`](docs/results_open_data.md): credential-free real-data run.
* [`docs/platform.md`](docs/platform.md): production-model selection, forecasts, API,
  deployment.

## Licence

MIT (see `LICENSE`). Data sources keep their providers' terms.
