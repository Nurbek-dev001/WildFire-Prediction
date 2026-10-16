# Methodology → code mapping

Section numbers refer to *Zharylkap & Bolarbek, "An Explainable Multisource Machine Learning
Framework for Spatiotemporal Wildfire Risk Prediction and Mapping in Kazakhstan"* (research
methodology). "Config" names the YAML keys holding the parameters; "Tests" names the tests
that check the behaviour.

## §2.1 Research design

| Methodology statement | Code | Config | Tests |
|---|---|---|---|
| Eq. (1) p̂(i,t) = P(y(i,t)=1 \| x(i,≤t−1)); predictors timestamped before *t* | `features/registry.py` (as-of rule per group), `features/build.py` (`asof_*` columns), `features/leakage.py` (`check_no_leakage`) | `features.*` | `test_leakage.py`, `test_end_to_end.py::test_every_feature_row_is_leakage_free` |
| 2015–2024, national equal-area 5 km grid; 1 km regional sensitivity | `grid/grid.py` (`build_grid`, stable `make_cell_id`) | `study`, `crs`, `grid.primary`, `grid.sensitivity`, `grid.active` | `test_config_grid.py` |
| UTC daily intervals; all months retained | `events/firms.py` (`parse_acq_datetime`, UTC), `sampling/risk_set.py` (every day of every year) | `study.timezone` | `test_events.py`, `test_risk_set_sampling.py` |
| Interpolated ERA5 not treated as extra detail | `features/era5.py` (daily fields on native grid, then interpolation to centroids) | `sources.era5_land.interpolation` | — |
| Cropland reported separately; output is hazard, not damage/risk | `evaluation/evaluate.py` (`stratified_metrics`, cropland vs non-cropland), `mapping/export.py` (disclaimer tags), `report/build.py` | `evaluation.strata` | `test_end_to_end.py::test_maps_are_qgis_ready` |
| **Event construction:** dedupe, link at 2 km / 48 h; sensitivity 1–5 km × 24–72 h | `events/firms.py` (`deduplicate`), `events/linking.py` (`link_detections`), `events/build.py` (`run_event_sensitivity`) | `events.spatial_link_km`, `events.temporal_link_h`, `events.sensitivity` | `test_events.py` |
| Only the earliest detection of each event is the positive cell-day | `events/linking.py` (`earliest_detection`), `events/build.py` (`positives_from_events`) | `events.tie_break` | `test_events.py`, `test_end_to_end.py::test_positives_are_earliest_detections` |
| Cells with a detection in the preceding 48 h excluded (past observations only) | `sampling/risk_set.py` (`excluded_cell_days`) | `risk_set.exclusion_hours` | `test_risk_set_sampling.py` |
| Later detections may group/label events but never enter predictors | labels in `events/`; predictors in `features/` only use data before *t* (`fire_history.py`) | `features.fire_history` | `test_leakage.py::test_later_detections_never_enter_predictors`, `test_end_to_end.py` |
| **Sampling:** keep all positives; negatives stratified by month × land cover with documented q_h, ~10 per positive, minimum allocation; weights 1/q_h | `sampling/design.py` (`allocate_training`, `stratified_sample`), `strata_inclusion_probabilities.csv` | `sampling.*` | `test_risk_set_sampling.py` |
| Training-only class weighting as sensitivity | `models/tuning.py` (`training_weights`), `models/train.py` (`train_class_weight_variants`) | `sampling.training_weighting`, `models.run_class_weight_sensitivity` | — |
| Validation/test unbalanced (or probability-sampled with weights) | `sampling/design.py` (evaluation design), weights used in every metric | `sampling.eval_negative_fraction` | `test_end_to_end.py::test_evaluation_is_unbalanced_and_metrics_present` |
| Absence of detection = observed negative, not verified absence | wording in `report/build.py`, `mapping/export.py` | — | — |
| **Models:** L2 logistic, RF, XGBoost, CatBoost; baselines: smoothed land-cover × month frequency, weather-only logistic; identical splits/features | `models/pipelines.py` (`make_estimator`, `SeasonalLandcoverBaseline`), `models/train.py` (`model_specs`) | `models.classifiers`, `models.baselines`, `models.seasonal_smoothing_alpha` | `test_preprocessing.py::test_seasonal_baseline_smoothing` |
| Remove anthropogenic, lagged-weather, vegetation features separately | `models/ablation.py` | `features.groups.ablation_groups`, `ablation.*` | `test_end_to_end.py` |
| Resampling only inside training folds; no synthetic samples in evaluation | sampling designs are drawn per year; models train only on `in_train` rows; no oversampling of evaluation rows anywhere | — | `test_end_to_end.py` |
| **Validation:** dev 2015–2021, rolling origin (≤2018→2019, …, →2021) | `splits/build.py` (`temporal_manifest`), `models/train.py` (`rolling_folds`) | `splits.development_years`, `splits.rolling_origin` | `test_config_grid.py` |
| 50 Optuna trials per ensemble; depth, min leaf, learning rate, regularisation, estimators; weighted AP | `models/tuning.py` (`tune`, `search_space`) | `models.n_trials_*`, `models.search_spaces` | — |
| Early stopping on development-fold validation only; refit on all development years | `models/pipelines.py` (`fit_model` eval set), `models/tuning.py` (mean best iteration), `models/train.py` (`train_temporal`) | `models.early_stopping_rounds` | — |
| 2022 for sigmoid calibration and threshold only; 2023–2024 untouched until final evaluation | `calibration/calibrate.py`, `splits/guard.py` (`FeatureStore`, `unlock_final_evaluation`) | `splits.calibration_years`, `splits.test_years` | `test_splits.py`, `test_end_to_end.py::test_test_years_opened_only_after_calibration` |
| Five-fold spatial-block CV, 100 km blocks, 25 km buffer; 50/150 km sensitivity; preprocessing and tuning repeated per fold | `splits/spatial.py` (`assign_folds`, `fold_roles`), `models/train.py` (`spatial_cv`) | `splits.spatial_cv.*`, `models.n_trials_spatial_cv` | `test_splits.py` |
| Calibration on representative / IPW-weighted 2022 data | `calibration/calibrate.py` (`fit_platt` with evaluation weights) | `calibration.method` | — |
| **Explanation:** TreeSHAP global mean \|SHAP\|, dependence plots, local examples (high-scoring and misclassified), on uncalibrated log-odds; correlated groups together; compare land-cover groups and held-out regions; associations, not causes | `explain/shap_analysis.py` | `explain.*`, `features.groups.correlated_groups` | — |
| **Mapping:** daily calibrated probabilities as GeoTIFF, no point interpolation; class boundaries set on calibration data and fixed before testing; continuous probabilities and observed class frequencies kept | `mapping/export.py`, `calibration/calibrate.py` (`weighted_quantiles`, `class_frequencies`), `evaluation/evaluate.py` (test class frequencies) | `mapping.*` | `test_end_to_end.py::test_maps_are_qgis_ready` |

## §2.2 Data sources

| Methodology statement | Code | Config |
|---|---|---|
| FIRMS archived standard-processed Suomi-NPP VIIRS 375 m; keep nominal + high, drop low; categories not treated as MODIS percentages | `events/firms.py` (`read_firms` rejects numeric confidence), `config/schema.py` (`FirmsSource` validator) | `sources.firms.keep_confidence`, `drop_confidence` |
| Check coordinates, dates, confidence, source-type fields | `events/firms.py` (schema/time validation, satellite/instrument), `events/build.py` (`type` filter) | `sources.firms.vegetation_type_values` |
| Screen persistent industrial hotspots with a mask from development-period evidence only | `events/build.py` (`build_industrial_mask` uses development years only) | `events.industrial_mask.*` |
| MODIS burned area / incident records only for corroboration | optional `sources.burned_area` registered in the manifest, never used as a label | `sources.burned_area` |
| ERA5-Land hourly T, Td, u/v, precipitation, soil moisture; Tmax/Tmin, mean wind, RH from T and Td, daily precipitation per accumulation convention; 7/14-day summaries; optional FWI from earlier observations only | `features/era5.py` (`daily_fields_from_files`, `daily_precip_from_accumulated`, `relative_humidity`, `weather_feature_cube`, `fosberg_ffwi`) | `sources.era5_land`, `features.weather` |
| MOD13A2 v061 1 km 16-day NDVI/EVI with QA masks; usable only after the interval ends plus a recorded publication lag | `features/modis.py` (`composite_dates`, `aggregate_composites`, `vegetation_regimes`) | `sources.mod13a2.*` |
| Annual MCD12Q1 as fractions of forest, grassland, shrubland, cropland, other; preceding year's map | `features/landcover.py` | `sources.mcd12q1.classes`, `year_offset` |
| SRTM elevation, slope, aspect | `features/terrain.py` | `sources.srtm` |
| WorldPop (dated), settlements, roads from historical OSM snapshots; never substitute present-day roads; omit and flag if unavailable | `features/human.py` (`check_snapshot_coverage`, `snapshot_for`), flags in `feature_registry.json` and the report | `sources.worldpop`, `sources.settlements`, `sources.roads`, `features.human` |
| Clip to the Kazakhstan boundary; documented equal-area projection | `grid/grid.py` (`load_boundary`, `build_grid`), `events/build.py` (`project_and_clip`) | `sources.boundary`, `crs` |
| Continuous layers area-averaged/interpolated; categorical as area fractions; slope at native resolution before aggregation | `data/rasters.py` (`GridAggregator`), `features/terrain.py` | `sources.*.working_resolution_m` |
| Vegetation gaps: latest valid value for ≤ 32 days, then missing | `features/modis.py` (`vegetation_regimes`) | `sources.mod13a2.max_gap_fill_days` |
| Imputation, scaling, encoding, screening fitted on training partitions only | `models/pipelines.py` (`make_preprocessor`, `FeatureScreen`) | `models.feature_screening_max_missing` |
| Correlated features: grouped ablations, not automatic removal | `models/ablation.py` (`correlation_clusters`, `ablation_groups`) | `features.groups.correlated_groups`, `correlation_threshold` |
| GEE optional; ~32 GB workstation; partitioned Parquet; chunked rasters | `data/download.py` (`export_gee_collection`), `data/rasters.py` (windowed processing), `features/era5.py` (file-by-file), `utils/io.py` | `sources.*.window_size_km`, `backend` |
| Record hardware, package versions, seeds, source ids, exclusions, split manifests | `data/manifest.py`, `report/build.py` (`reproducibility_record`) | — |

## §2.3 Evaluation metrics

| Methodology statement | Code | Tests |
|---|---|---|
| Eq. (2) precision, recall, F1 from weighted or complete confusion counts; accuracy reported, not used for selection; FPR and FDP | `evaluation/metrics.py` (`confusion`, `Confusion.as_metrics`) | `test_metrics.py::test_confusion_and_rates` |
| Threshold maximising weighted calibration-year F1; never optimised on test | `evaluation/metrics.py` (`best_f1_threshold`), `calibration/calibrate.py` | `test_metrics.py::test_best_f1_threshold` |
| Eq. (3) AP = Σ (R_k − R_{k−1}) P_k, distinct from trapezoidal PR-AUC | `evaluation/metrics.py` (`average_precision`, `pr_auc_trapezoid`) | `test_metrics.py` |
| Prevalence as the no-skill reference; ROC-AUC supplementary | `evaluation/metrics.py` (`prevalence`, `roc_auc`, `summary_metrics`) | — |
| Eq. (4) weighted Brier score and BSS vs the seasonal reference | `evaluation/metrics.py` (`brier`, `brier_skill`), `evaluation/evaluate.py` (seasonal land-cover × month reference fitted on development years) | `test_metrics.py::test_brier_and_bss_hand_example` |
| Reliability diagrams and 10-bin ECE with bin counts and uncertainty | `evaluation/metrics.py` (`reliability_table`, Wilson interval on Kish n_eff; `expected_calibration_error`), `report/figures.py` | `test_metrics.py::test_ece_hand_example` |
| Capture of event starts in the top 5/10/20 % with area and false-alert burden | `evaluation/metrics.py` (`capture_rate`, pooled and daily) | `test_metrics.py::test_capture_rate_pooled_and_daily` |
| Stratified by year, month, region, land-cover group | `evaluation/evaluate.py` (`stratified_metrics`) | — |
| Paired 95 % CIs via 1,000 space–time block bootstrap resamples on identical units | `evaluation/bootstrap.py` (`paired_block_bootstrap`) | `test_bootstrap.py` |
| Training time, inference time, peak memory | `utils/resources.py`, `models/pipelines.py`, `evaluation/evaluate.py` (`resources.csv`) | — |
| Report negative or unstable improvements explicitly | `evaluation/evaluate.py` (`result_flags`), `report/build.py` section "Negative, null or unstable results" | — |
