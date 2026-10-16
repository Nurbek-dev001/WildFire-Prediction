# Executed validation

This file describes verification scope. Machine-readable run records and pytest output are the authority for executed results; generated performance values are not copied into source documentation.

Unit checks cover connected event boundaries/transitivity, earliest labels, past-only exclusion, UTC timestamp units, strict availability, MODIS lag/expiry, sealed test access, inverse-probability totals, spatial buffers, hand-computed metrics, calibration guards and training-only imputation. The end-to-end smoke test executes all stages with generated artificial observations, validates outputs and checks cached reruns.

The synthetic demonstration deliberately uses separated artificial patches to exercise spatial buffering. It does not validate Kazakhstan's national source extraction or train a usable national forecast. Run the primary configuration on verified observations and inspect fold geography, coverage, missingness, calibration, class frequencies and negative/unstable results before drawing scientific conclusions.

Local verification on 16 October 2026 completed 17 focused tests plus the independent end-to-end smoke test (18 passing tests in total). Ruff lint/format checks and mypy passed. The smoke test used actual scikit-learn, XGBoost, CatBoost, TreeSHAP and rasterio code, executed all stages, checked all daily test rasters, and confirmed report cache stability. Its deliberately corrupted-source check raised the expected checksum error and passed; that logged exception is not an unresolved pipeline failure.

The demonstration was also run separately with primary and sensitivity spatial block designs. Its artifacts retain timings and peak process RSS in each stage manifest. The dashboard was visually inspected in the browser, and the daily control was observed changing the target date. `requirements-tested-windows-py312.txt` records observed dependency versions for this Windows/Python environment; CI has been configured but has not been executed on a remote runner.
