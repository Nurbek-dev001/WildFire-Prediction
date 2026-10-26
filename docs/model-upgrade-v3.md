# Trained model revision — 23 October 2026

The new model changes probability estimates and ranking. It is a learned stack
of the original XGBoost and a logistic second level using six causal history
features plus the XGBoost logit. The final score mixes the two estimates 50/50
before sigmoid calibration. The physical inputs remain the original 26
features; six fire-history features bring the deployed input set to 32.

History uses unique observed active cell-days in square 15/55 km neighbourhoods
and 7/30/90/365-day windows ending at target day minus two days. No current-day
labels, future observations, or future-connected event identifiers are inputs.
The source is the reprocessed FIRMS archive, so a two-day feature lag does not
establish historical as-issued operational availability.

Five richer XGBoost candidates and two baseline-parameter/history candidates
were tested and rejected. Four second-level models were then compared. OOF
first-stage scores for 2019, 2020 and 2021 came from models trained on earlier
years. Second-level regularization was selected by training on 2019–2020 and
checking 2021. The second level was refitted on 2019–2021. Blend weight was
selected using the minimum relative recall gain across 2021 and 2022, requiring
AP to improve in both years. Training and selection use no year after 2022.

The original choice at precision ≥10% on 2021 alone failed the 2022 check. The
joint check selected weight 0.5 instead of 0.75. At that weight, 2021 recall at
precision ≥10% is 3.2011% versus 1.6469%, and AP is 0.02414 versus 0.01922.
On 2022, the published-value calibration operating point has precision 6.1049%
and recall 5.5858%, versus the original 5.9486% and 4.7355%.

The model, preprocessing, blend, calibration and threshold were hash-frozen at
**2026-10-23 10:37:04 UTC**, before reassessing 2023–2024. The frozen threshold
is **0.03564453125**. Selection metadata's `selected` metric fields retain the
initial regularization-selection point; `joint_criterion`, `joint_comparison.csv`
and `frozen.json` describe the actual final blend and operating point. The
original records remain immutable.

Final reassessment (345,954 sampled rows, 15,704 positive cell-days, design
weights representing 80,081,865 eligible cell-days):

| Metric | Original model | New learned stack |
| --- | ---: | ---: |
| Precision | 9.7609% | 7.3608% |
| Recall | 5.1643% | 7.3421% |
| F1 | 0.06755 | 0.07351 |
| AP | 0.02045 | 0.02392 |
| ROC-AUC | 0.92368 | 0.94211 |
| Brier | 0.000196064 | 0.000193848 |

This is a real ranking improvement, with a remaining precision/recall tradeoff.
Precision was **not fully preserved**: it falls about 24.6%, compared with about
49.4% for the previous threshold-only change. Recall rises about 42.2%. The
paired 100 km × 30 day bootstrap (1,000 draws) gives recall improvement interval
0.98–3.62 percentage points and precision difference interval −5.57 to −0.018
points. Do not claim both precision and recall improved.

The benchmark had been reported previously. This is a disclosed reassessment,
not a new independent holdout. No model or threshold changes were made after
this reassessment. Current operational forecast suitability remains unvalidated.

For storage, float16 rounding was declared before final evaluation. Threshold
selection, final metrics, browser arrays and GeoTIFFs use exactly those rounded
values. Every map is checked against all applicable saved benchmark predictions.
The browser's half decoder was verified against all 65,536 IEEE half bit patterns.

Local run: `runs/model_stack_v5`. Candidate histories: `runs/model_upgrade_v3`
and `runs/model_upgrade_v4`. Entry points:

```powershell
.venv\Scripts\python.exe -X utf8 scripts\train_stacked_upgrade.py train
.venv\Scripts\python.exe -X utf8 scripts\train_stacked_upgrade.py evaluate
.venv\Scripts\python.exe -X utf8 scripts\export_model_upgrade.py
.venv\Scripts\python.exe -X utf8 scripts\publish_upgraded_model.py
```

Training and evaluation refuse overwriting a frozen/completed experiment.
Export can resume verified date files and compute disjoint year ranges. Its
legacy release checks are cached only within each day; full checks occur again
at the end. This export optimization changes no feature equation or model score.
Two already uploaded temporary Site archives were reclaimed to preserve storage.
