# Executed validation

This file describes verification scope. Machine-readable run records and pytest output are the authority for executed results; generated performance values are not copied into source documentation.

Unit checks cover connected event boundaries/transitivity, earliest labels, past-only exclusion, UTC timestamp units, strict availability, MODIS lag/expiry, sealed test access, inverse-probability totals, spatial buffers, hand-computed metrics, calibration guards and training-only imputation. The end-to-end smoke test executes all stages with generated artificial observations, validates outputs and checks cached reruns.

The synthetic demonstration deliberately uses separated artificial patches to exercise spatial buffering. It does not validate Kazakhstan's national source extraction or train a usable national forecast. Run the primary configuration on verified observations and inspect fold geography, coverage, missingness, calibration, class frequencies and negative/unstable results before drawing scientific conclusions.

Local verification on 16 October 2026 completed 17 focused tests plus the independent end-to-end smoke test (18 passing tests in total). Ruff lint/format checks and mypy passed. The smoke test used actual scikit-learn, XGBoost, CatBoost, TreeSHAP and rasterio code, executed all stages, checked all daily test rasters, and confirmed report cache stability. Its deliberately corrupted-source check raised the expected checksum error and passed; that logged exception is not an unresolved pipeline failure.

The demonstration was also run separately with primary and sensitivity spatial block designs. Its artifacts retain timings and peak process RSS in each stage manifest. The dashboard was visually inspected in the browser, and the daily control was observed changing the target date. `requirements-tested-windows-py312.txt` records observed dependency versions for this Windows/Python environment; CI has been configured but has not been executed on a remote runner.

The subsequent real-data acquisition changes passed 21 focused tests plus the complete offline smoke test (22 tests total), along with Ruff and mypy. Added checks reject NRT archives, preserve observed version fields, enforce the holdout check before CSV opening, reject incomplete real registrations, and verify that ingestion hashes opaque held-out bytes without parsing them. The actual national grid was also checked for valid geometry, unique IDs, complete/unique fixed-region assignment, and area agreement with the projected boundary. The real pipeline attempt stopped at missing-source validation before training; this is recorded separately from the successful synthetic smoke test.

On 19–20 October the expanded suite completed **33 tests** in 811.68 seconds
while real-data training competed for CPU time. After additional boundary/seal
guards and the CatBoost explanation fix, the public-data and explanation subset
completed **14 tests** in 23.90 seconds. These are two separately executed checks,
not a claim that a later full suite was run. Ruff lint/format checks and mypy
passed for the modified explanation/report code. The remaining warning is the
dependency WebOb's deprecation of Python's `cgi` module.

A separate small synthetic compatibility fixture exercised actual installed
scikit-learn, XGBoost 3.4.1, CatBoost 1.2.10 and SHAP 0.54.1 across all six
families. All corrected explanation outputs passed raw-output reconstruction.
The [CatBoost decision](explanation-compatibility.md) was made before access to
2023–2024; the explanation implementation is included in the release seal.
This software check used no real trained study model or held-out observation.

The national development audit independently checked all 11 actual permitted
feature tables, source/value ranges, temporal availability, unique keys,
inclusion probabilities, design weights, optional missingness and mandatory
source exclusions. Its actual results and hashes are retained in
`runs/public_hindcast/development_quality.json`. Model fitting was still in
progress when these verification notes were updated; no final-test metric or
completed map verification is claimed here.

On 22 October the user removed the 50-attempt search requirement. The unchanged
comparison worker was resumed with a five-attempt budget after checking identical
scientific source/table/model-code hashes and archiving the original SQLite
history and protocol. The budget change and public holdout guards passed **19
tests** in 44.17 seconds; Ruff checks/format and mypy passed for the changed
scripts/report module. These checks are not final-test performance measurements.

The subsequent pre-test constant-quantile repair passed the public-data subset:
**15 tests** in 38.02 seconds, plus Ruff checks/format and mypy. The added fixture
checks actual weighted frequencies and conserved mass when calibration quantiles
coincide, as well as the ordinary four-class case. Model fitting and holdout
access rules were not changed.

The original-provider recovery transport passed **4 offline checks** in 3.80
seconds: UTC rainfall intervals and native units; coordinate/time/unit rejection
and preserved nodata; quota waiting; and refusal of source recovery after final
label access. Actual API daily features also matched the existing archive exactly
at 200 native points on each of two development days. This is source validation,
not final model performance. Another public copy failed a development comparison
and was not used.

After the recovery transport was integrated, the complete offline suite passed
**48 tests** in 246.58 seconds. Ruff checks/format and mypy passed (34 source
modules including the new transport scripts). The integration fixture used
generated observations and actual estimators/raster writers; it remains a
software regression check, not evidence of real-data predictive performance.

One subsequent sparse-time transport fixture checked native chunk offsets and
preserved missing hours. The focused transport subset then passed **5 tests** in
2.91 seconds; the complete suite was not rerun after this test-only addition.

The real public-data final evaluation completed on 22 October at 15:21 UTC.
The six model families, calibrators, thresholds, feature rules and metric code
had been sealed at 13:28 UTC. It used 345,954 actual final rows, including
15,704 positives, and 1,000 paired 100 km × 30 day bootstrap resamples per model.
The model SHA-256 remained
`31728c7fccf7d2af3098691373e38350972f975ac9b9d780c2c9398333c6aea7`.
Actual performance is recorded in `runs/public_hindcast/evaluate/complete.json`;
these real results are separate from the offline regression checks above.

Browser QA on the predefined 2024-07-15 map showed XGBoost probabilities,
110,071 finite cells and seven cells above the frozen threshold. An independent
single-cell re-inference matched the served float32 value exactly, including its
displayed rounded percentage. The actual browser CSV contained all seven
threshold cells with `synthetic=false`, matching every float32 probability.
The metric dialog showed the actual six-model results; no console warning/error
was observed. Search and region selection worked. The calibration figure's
overlapping decimal tick labels were repaired with percentage formatting and
visually rechecked; this changed presentation only. Ruff and mypy passed for that
report-only change. Full-calendar verification and published-host checks are
recorded separately when complete.
