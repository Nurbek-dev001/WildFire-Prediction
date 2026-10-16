# Assumptions, ambiguities and deviations

None of these choices required a blocking decision. Each is configurable unless stated
otherwise, and each is recorded here so it can be challenged or changed.

## A. Interpretations of the methodology (ambiguities resolved)

| # | Topic | Decision | Where / config |
|---|---|---|---|
| A1 | Equal-area CRS | Custom Albers Equal-Area Conic for Kazakhstan: lat₀ 48°, lon₀ 67°, standard parallels 43° and 53°, WGS84. ESRI:102025 (Asia North Albers) is centred at 95°E, far from Kazakhstan. | `crs.proj4` |
| A2 | "Information timestamped before *t*" | Each feature group stores an **observation/availability date** (`asof_*`) and the check is `asof < t` at day resolution. ERA5-Land daily precipitation for day D is *stored* at 00 UTC of D+1 but *describes* day D, so its as-of date is D. | `features/leakage.py` |
| A3 | MODIS availability | A composite covering [start, end] becomes available on `end + 1 day + publication_lag_days`. It is usable for target *t* only if that date is ≤ *t−1*. The methodology gives no lag value; the default 10 days is a conservative assumption. | `sources.mod13a2.publication_lag_days` |
| A4 | 32-day gap rule | When the newest usable composite is invalid for a cell, the last valid value is reused while its composite end is ≤ 32 days older than the newest usable composite's end. Beyond that the value is NaN. | `sources.mod13a2.max_gap_fill_days` |
| A5 | Earliest-detection ties | One positive per event. Ties at the earliest timestamp go to high before nominal confidence, then larger FRP, then lower cell id. Several events starting in one cell on one day give one positive cell-day (`n_events` stored). | `events.tie_break` |
| A6 | Events starting outside the country | Detections within a 10 km border buffer are kept so cross-border events link correctly. An event whose earliest detection lies outside the grid yields no positive (counted in `qc_counts.json`). | `sources.boundary.border_buffer_km` |
| A7 | Industrial-hotspot mask | 1 km screening pixels with detections on ≥ 20 distinct days in ≥ 3 development years. A pixel is masked if its mean non-vegetated MCD12Q1 share over development-year maps is ≥ 0.5, or if ≥ 50 % of its detections carry FIRMS `type = 2` (static land source). It is built from development years only and applied to all years. | `events.industrial_mask` |
| A8 | Detections used for the 48 h exclusion | Retained (QC'd, vegetation-type, unmasked) detections. Masked industrial detections do not remove cells from the risk set. | `sampling/risk_set.py` |
| A9 | Sampling strata | Strata are (calendar year × month × dominant land-cover group). Nesting strata in years keeps the development, calibration and test samples independent. Allocation is n_h = min(N_h, max(round(10·P_h), m)), drawn by simple random sampling without replacement. | `sampling.*` |
| A10 | Evaluation design | Default real-data config uses a stratified 10 % negative sample with inverse-inclusion weights. The methodology allows probability-sampled evaluation when the complete risk set (~40 M cell-days per year at 5 km) is infeasible. Set `sampling.eval_negative_fraction: 1.0` for complete evaluation. | `sampling.eval_negative_fraction` |
| A11 | "Lagged weather" ablation | Removes the 7- and 14-day antecedent summaries. Prior-day (t−1) weather stays in, since without it there is no weather model. | `features.groups.ablation_groups` |
| A12 | Training weights | Primary: inverse-inclusion weights normalised to mean 1 (normalisation does not change the optimum, but improves numerical conditioning). Sensitivity: balanced class weights with the same hyper-parameters. | `sampling.training_weighting` |
| A13 | Tuning objective | Mean weighted AP over the rolling-origin validation years, scored on the unbalanced evaluation design with evaluation weights. Boosted trees are refitted with the mean early-stopping iteration across folds. Logistic regression tunes C with 20 trials. | `models.*` |
| A14 | Spatial-CV inner tuning | Within each fold's training region, tune on development years except the last and validate on the last development year. Then refit on all development years of the training region and score the held-out region. | `models/train.py::spatial_cv` |
| A15 | Geographically separated folds | 100 km blocks are clustered with seeded k-means on block centroids into 5 compact regions. Training cells within 25 km (edge to edge) of the held-out region are buffered out. | `splits.spatial_cv` |
| A16 | "Region" stratum | Administrative regions when `sources.regions` is configured. Otherwise the 5 spatial-CV fold regions. | `splits/build.py::regions_for_cells` |
| A17 | Seasonal reference for BSS | The smoothed land-cover × calendar-month frequency baseline, fitted on development years with IPW weights and not recalibrated. BSS against constant development-period climatology is reported too. | `evaluation/evaluate.py` |
| A18 | Reliability bins | 10 equal-width bins define the ECE. Weighted-quantile bins are also shown, because rare-event probabilities crowd the first equal-width bin. Uncertainty uses Wilson intervals with the Kish effective sample size. | `evaluation.reliability_bins` |
| A19 | Capture rate | Reported both pooled (top x % of all eligible cell-days) and daily (top x % of each day's eligible cells). Area = flagged weighted cell-days × cell area. | `evaluation.capture_modes` |
| A20 | Bootstrap blocks | 100 km spatial × 7-day temporal blocks; 1,000 resamples; percentile 95 % intervals; every model scored on the same resampled units. | `evaluation.bootstrap` |
| A21 | Map classes | Boundaries are weighted quantiles (50/80/95/99 %) of calibration-year calibrated probabilities of the map model (best classifier by development AP). Observed event frequency per class is reported for both calibration and test years. | `mapping.class_quantiles` |
| A22 | SHAP scale | XGBoost/CatBoost SHAP is on the raw log-odds margin. scikit-learn Random Forest exposes no log-odds, so if RF is the selected tree model its SHAP values are on the probability scale. This is written to `explain_meta.json`. | `explain/shap_analysis.py` |
| A23 | Calendar features | `doy_sin` and `doy_cos` of the target day are deterministic (known in advance, no observation), so they are whitelisted in the leakage check. Disable with `features.include_calendar: false`. | `features.include_calendar` |
| A24 | Population year | Uses the preceding year's WorldPop map. If unavailable (e.g. product series ends earlier), it falls back to the latest *earlier* map and records a flag; later maps are never used. Density = summed persons / in-boundary cell area. | `sources.worldpop` |
| A25 | Optional fire-weather index | Fosberg FFWI from t−1 Tmax, RHmin and mean wind. It needs only prior-day data, unlike the full Canadian FWI system (which needs noon values and code state). Off by default. | `features.weather.include_fire_weather_index` |
| A26 | Optional fire-history predictor | Distinct detection days in the cell over [t−365 d, t). Not in the methodology's predictor list, so off by default. It exists to exercise the "later detections never enter predictors" guarantee. | `features.fire_history` |

## B. Deviations from the specification (with justification)

| # | Deviation | Justification |
|---|---|---|
| B1 | **Synthetic demo uses 10 km cells; the CI smoke test uses a shortened period (2015–2019: dev 2015–2017, calibration 2018, test 2019), 3 spatial folds of 50 km and very few Optuna trials.** | Lets the full pipeline run offline in minutes. The real-data defaults (`configs/default.yaml`) keep every methodological value: 5 km, 2015–2024, 2022/2023–2024, 5 folds × 100 km, 50 trials, 1,000 bootstrap resamples. |
| B2 | **MOD13A2 / MCD12Q1 are read as GeoTIFFs, not native HDF4 sinusoidal tiles.** | GDAL HDF4 support is often missing from wheels. Files exported from GEE or converted with `gdal_translate`/`gdalwarp` are read by the same reader. Expected file names and band order are in `docs/data_acquisition.md`. |
| B3 | **Downloaders exist for FIRMS (API), ERA5-Land (CDS) and a GEE export helper only.** SRTM, WorldPop, settlements and historical OSM snapshots are registered from local files. | These providers need interactive licence acceptance or bespoke extraction (OSM full-history). The downloaders are not exercised by the offline tests (no network or credentials in CI). |
| B4 | **Chunked processing uses explicit windows/files rather than a dask task graph.** ERA5-Land is aggregated file by file (one month in memory); rasters are warped in windows (`window_size_km`) with halos. | On the smoke data a dask graph over hourly ERA5 took 161 s per year versus 7 s file by file (scheduler overhead dominated). Peak memory stays bounded by one monthly file or one raster window. dask remains a dependency for users who prefer lazy loading. |
| B5 | **Ablations reuse the full model's selected hyper-parameters** (`ablation.retune: false`). | Re-tuning 50 trials × every group × every model is a large cost. Holding hyper-parameters fixed isolates the information content of the removed group. Set `ablation.retune: true` to re-tune. |
| B6 | **The test-year guard protects model-facing reads**, i.e. `FeatureStore` used by train/calibrate/ablate. The features stage still *computes* feature rows for 2023–2024. | Feature construction uses no labels or fitted quantities, and building all years at once keeps caches consistent. Nothing fitted (models, calibration, threshold, class boundaries) can read test rows before the ledger is opened, and the ledger refuses to open until calibration artifacts are frozen. |
| B7 | **Settlement proximity is computed from point snapshots** (one dated snapshot per configured file) rather than a gridded settlement-extent product. | The methodology names no specific settlement product; point gazetteers are the most widely available dated source. |

## C. What is deliberately *not* in this repository

* No performance numbers, published-style scores or claims of novelty. The only numbers in
  any report are produced by running the pipeline, and synthetic runs are bannered as such.
* No random train/test splits, no balanced validation/test sets, no deep-learning models.
* No present-day road network silently standing in for historical roads.
