# Alert-policy revision v2 — 23 October 2026

The user requested more recall after the first final evaluation. This revision
changes alert thresholds, not the trained XGBoost, preprocessing, calibration,
probabilities, map classes or ranking. The original release and original final
evaluation remain immutable. It is a reassessment on an already reported test,
not a new independent holdout.

Selection reads only the actual `2022_evaluation.parquet`, excludes the frozen
development industrial mask, and uses negative-example inclusion weights.
There are 197,096 eligible calibration rows and 10,115 positives. The source
table, model, calibrator, selection code and runner are checksum bound.

The three profiles were frozen at **2026-10-23 06:05:15 UTC**, before the new
evaluation command opened the cached 2023–2024 predictions:

| Profile | Selection on 2022 | Probability threshold |
| --- | --- | --- |
| Original | Original weighted-F1 optimum | 0.04728369414806366 |
| Balanced (default) | Maximum weighted F2 | 0.022486481815576553 |
| Coverage | Maximum weighted F2 subject to recall ≥0.30 | 0.004977398086339235 |

F2 = 5PR/(4P+R). Exact objective ties select the higher threshold. Comparisons
include equality (`probability >= threshold`). No test-derived threshold,
parameter, model or calibration choice was made after the policy freeze.

On the previously reported 2023–2024 benchmark:

| Profile | Precision | Recall | F1 | F2 | Weighted alert fraction |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original | 9.7609% | 5.1643% | 0.06755 | 0.05701 | 0.01038% |
| Balanced | 4.9383% | 10.9845% | 0.06813 | 0.08824 | 0.04362% |
| Coverage | 0.8113% | 35.9017% | 0.01587 | 0.03720 | 0.86773% |

Greater recall means more false alerts. Balanced recall has a paired cluster
bootstrap 95% interval of 8.7188–13.6113%. The paired improvement in F2 over the
original profile has interval 0.02318–0.03948 (1,000 resamples, 100 km × 30 days,
seed 42). This does not remove the limitation of reusing a reported benchmark.

All 731 map payload hashes were checked unchanged. Float32 map decisions match
evaluation decisions. Exact national alert cell-days are 9,940 / 38,648 / 703,482
for original / balanced / coverage; these differ from inverse-weighted sampled
burden estimates. All-nodata dates stay all-nodata. NDVI, weather availability
and operational-validation limitations of the original experiment still apply.

Run with UTF-8 console output on Windows:

```powershell
.venv\Scripts\python.exe -X utf8 scripts\improve_operating_point.py select
.venv\Scripts\python.exe -X utf8 scripts\improve_operating_point.py evaluate
.venv\Scripts\python.exe -X utf8 scripts\publish_operating_policy.py
```

The first two commands refuse to overwrite existing frozen outputs. The initial
selection completed and saved its policy; its console print required UTF-8
because the system CP1251 console cannot encode ≥. The saved policy was not
regenerated. Its SHA-256 is
`77328706da088f98aec98a38710a4396c7bb3a7ed5bd2aff94097f5098a395eb`.

The website verifies the policy and evaluation hashes before loading the real
mode. The selector changes the filter, alert count, cell decision and CSV alert
columns together. The continuous probabilities and original six-model report
remain available. The updated comparison report is published at `/alerts/`.
