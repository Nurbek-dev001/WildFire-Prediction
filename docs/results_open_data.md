# Results of the open-data run (`configs/real_open.yaml`)

Every number below was produced by running `wildfire-kz run -c configs/real_open.yaml` on
data downloaded with `wildfire-kz fetch-open` (run date 2026-10-16, seed 20240917, 4 CPUs).
They describe this run only: about 2.6 years of labels, one test season, EFIRE rather than
FIRMS labels. See [open_data.md](open_data.md) for sources, processing and limitations.
Probabilities are the occurrence hazard of a **new** vegetation-fire detection in a 5 km cell
on the next UTC day. They are not damage, exposure or risk, and SHAP values describe
associations learned by the model, not causes.

## Data volume

| item | value |
|---|---|
| grid | 109,068 cells of 5 km (Lambert azimuthal equal-area) |
| VIIRS detections in the bounding box | 397,406 |
| new-fire events after QC, industrial mask and 48 h linking | 27,994 |
| eligible cell-days (risk set) | 89.4 M |
| eligible positive cell-days | 22,579 |
| days with unknown labels (archive gaps + 2 following days) | 158, removed |
| test-period evaluation rows (5 % probability sample of negatives, weights 1/q) | 1,216,819 rows, 7,710 positives |
| test-period prevalence (weighted) | 0.000319 |

## Model selection (development period only)

Rolling-origin validation: train 2024-03..07 → validate 2024-08..12, and train 2024-03..12 →
validate 2025-01..06. Mean weighted average precision (AP), 15 Optuna trials per ensemble
member (10 for logistic regression):

| candidate | dev-CV weighted AP |
|---|---|
| **ensemble_trees** (log-odds mean of RF, XGBoost, CatBoost) | **0.0119** |
| xgboost | 0.0111 |
| catboost | 0.0103 |
| random_forest | 0.0043 |
| logistic | 0.0020 |
| seasonal_landcover baseline | 0.0011 |
| weather_logistic baseline | 0.0008 |

The production model is **ensemble_trees**. It was chosen before the calibration or test data
were read and is not re-chosen afterwards.

## Final evaluation on the test period (2026-01-01 – 2026-09-30)

Platt calibration, the decision threshold τ (weighted F1) and the map class boundaries were
fitted on the calibration period (2025-07-01 – 2025-12-31) and frozen. 95 % intervals come
from a paired space–time block bootstrap (100 km × 7 days, 1,000 resamples).

| model | AP [95 % CI] | AP / prevalence | ROC-AUC [95 % CI] | Brier skill vs seasonal reference |
|---|---|---|---|---|
| **ensemble_trees** | **0.0209** [0.0148, 0.0298] | 66× | **0.920** [0.912, 0.927] | 0.0100 [0.0067, 0.0141] |
| xgboost | 0.0222 [0.0158, 0.0315] | 70× | 0.925 [0.918, 0.932] | 0.0102 |
| catboost | 0.0174 [0.0120, 0.0258] | 55× | 0.908 [0.899, 0.915] | 0.0083 |
| random_forest | 0.0122 [0.0087, 0.0171] | 38× | 0.888 [0.878, 0.898] | 0.0030 |
| logistic | 0.0037 [0.0030, 0.0046] | 12× | 0.862 [0.850, 0.871] | 0.0004 |
| seasonal_landcover | 0.0020 [0.0017, 0.0024] | 6× | 0.802 | 0.0001 |
| weather_logistic | 0.0010 [0.0008, 0.0011] | 3× | 0.773 | −0.0006 |

On the test period XGBoost scores slightly higher than the ensemble, but the paired AP
difference has a 95 % CI of [−0.0039, 0.0008], which includes zero. At its threshold τ = 0.0151,
the ensemble has precision 0.043 and recall 0.141.

**Practical capture (ensemble_trees, test period).** Flagging the 5 % of cells with the
highest hazard each day captures 46 % of new fires. The top 10 % captures 64 % and the top 20 %
captures 81 %.

**Map classes** (boundaries frozen on the calibration period):

| class | share of cell-days | observed new-fire frequency | mean calibrated p | share of events |
|---|---|---|---|---|
| very low | 44.0 % | 0.000018 | 0.000024 | 2.5 % |
| low | 31.7 % | 0.000068 | 0.000072 | 6.8 % |
| moderate | 16.5 % | 0.000335 | 0.000282 | 17.3 % |
| high | 6.0 % | 0.00154 | 0.00115 | 29.2 % |
| very high | 1.8 % | 0.00802 | 0.00631 | 44.2 % |

The classes are ordered as intended. In the two highest classes, observed frequencies in 2026
are about 25–35 % above the calibrated probabilities. That is under-forecasting in the test
season.

## Spatial generalisation (development period, 100 km blocks, 25 km buffer)

Mean AP over 5 held-out regions: ensemble_trees 0.0099 (range 0.0005–0.0182), catboost 0.0079,
random_forest 0.0063, xgboost 0.0036, logistic 0.0021. Skill varies strongly between regions
(flagged: coefficient of variation 0.8–1.1 for the tree models). Transfer to regions without
training fires is therefore uncertain.

## Feature associations (TreeSHAP, development period, mean |SHAP| on log-odds)

Cropland fraction (0.60), distance to settlements (0.39), season (day-of-year sine, 0.38),
population density (0.32), grassland fraction (0.24), 7-day mean maximum temperature (0.19),
minimum relative humidity (0.12) and same-day precipitation (0.10) contribute most. This is
consistent with fire starts in Kazakhstan being concentrated in human-used agricultural
landscapes and modulated by weather. These are associations, not causal effects.

## Flags raised by the pipeline

* Road distance omitted (no historical snapshot available credential-free).
* Land cover (2021) and population (~2020) are single static maps applied to 2024–2026.
* Several ablations (dropping correlated feature groups) have bootstrap CIs that include
  zero, so they do not show a clear effect.
* Two strata have fewer than 5 positives, so their metrics are unstable.
* Spatial-CV skill varies strongly across regions (see above).

## Operational forecast

`wildfire-kz export-site --day 2026-10-09` produced a calibrated map for 2026-10-09 from
predictors observed up to 2026-10-08. That is the last day with complete ERA5T weather
at run time. The forecast falls in the operational partition and was never used for fitting,
tuning, calibration or evaluation.
