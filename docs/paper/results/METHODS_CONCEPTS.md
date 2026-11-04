# Methodology concepts, as used in this study

Short definitions of every concept in Section 3, with the value actually used.

## Target and data

- **Occurrence forecasting** – probability that a new fire starts in a place on a future day.
  Not detection (fire already burning), not spread (where it moves), not susceptibility
  (static predisposition), not risk (no exposure or damage).
- **Grid cell, cell-day** – 5 x 5 km equal-area cell (110,129 cells); one cell on one UTC day
  is one prediction unit.
- **Target y(i,t)** – 1 if the first satellite detection of a new connected event falls in
  cell i on day t. A proxy for ignition, not the ignition itself.
- **Event linkage** – detections within 2 km and 48 h are joined into one event; only its
  earliest detection is a positive (sensitivity values 1-5 km, 24-72 h configured).
- **Risk set / eligibility** – cells with any detection in the previous 48 h are excluded
  that day (they are already burning), and the frozen list of industrial cells is removed.
- **Information cut-off x(i, <= t-1)** – predictors use only data timestamped before the
  target day. In practice weather enters as day D-7 (ERA5 is published ~5 days late), NDVI
  12+ days old, fire history to D-2.
- **Prevalence** – share of positive cell-days in the risk set (0.000196 in 2023-2024); the
  precision of a random forecast and the no-skill level of AP.
- **Negative sampling with inverse-inclusion weights** – all positives kept, ~10 negatives
  per positive sampled within month x land-cover strata with probability q; each negative
  gets weight 1/q so weighted sums equal the full risk set.

## Models and references

- **Logistic regression (L2)** – linear, interpretable baseline.
- **Random Forest, XGBoost, CatBoost** – tree ensembles capturing non-linear interactions.
- **Seasonal frequency reference** – smoothed fire rate by land cover x calendar month from
  the development years (no weather, no place-specific data).
- **Weather-only logistic** – logistic regression on weather and antecedent weather only.
- **Ablation** – refit the model with one predictor group removed; the drop in skill is the
  group's added value (T16).

## Validation design

- **Development / calibration / test split** – 2015-2021 development, 2022 calibration and
  threshold, 2023-2024 untouched test.
- **Rolling-origin validation** – train through Y-1, validate on Y, for Y = 2019, 2020,
  2021; mimics forecasting the next year; used for model and hyperparameter selection.
- **Optuna** – hyperparameter search (5 trials per ensemble in the final run).
- **Spatial-block cross-validation** – 100 km blocks grouped into 5 folds; a held-out fold's
  blocks plus a 25 km buffer are excluded from training; tests transfer to unseen regions.
- **Leakage control** – imputation, scaling and tuning fitted on training data only; no
  test-year information in any choice.

## Metrics

- **Precision, recall, F1** – at a fixed threshold (chosen on 2022 by weighted F1).
- **FPR** = FP / (FP + TN): share of non-fire cell-days wrongly alerted.
- **False-discovery proportion** = FP / (TP + FP): share of alerts that are false.
- **Accuracy** – reported only for comparability; near 1 at this prevalence regardless of skill.
- **Average precision (AP)** – area under the precision-recall step curve; the primary
  threshold-free metric for rare events. Compare it to prevalence: AP / prevalence = lift.
- **ROC-AUC** – probability that a random positive ranks above a random negative; looks high
  for rare events and is secondary here.
- **Brier score** – weighted mean squared error of probabilities.
- **Brier skill score (BSS)** = 1 - BS / BS(seasonal reference); > 0 means better
  probabilities than the reference.
- **Calibration / reliability diagram** – mean predicted probability against observed
  frequency in bins; on the diagonal = calibrated.
- **ECE (expected calibration error)** – weighted mean |predicted - observed| over 10 bins;
  small here mainly because nearly all probabilities are near zero.
- **Sigmoid (Platt) calibration** – a logistic curve fitted on 2022 that maps raw model scores
  to probabilities.
- **Top-k capture** – share of new starts inside the highest-scoring 5/10/20% of eligible
  cell-days: how much of the fire activity a limited patrol budget would cover.
- **Map classes** – four probability classes with bounds fixed on 2022 for daily maps.
- **Space-time block bootstrap** – resample 100 km x 30 day blocks 1000 times, recompute
  metrics for every model on the same resample; 95% percentile intervals of differences
  respect spatial and temporal dependence.

## Explanation

- **TreeSHAP** – exact Shapley contributions of each input to one prediction of a tree model,
  in uncalibrated log-odds. Global importance = mean |SHAP|; grouped importance sums a
  predictor group; dependence plots show contribution against the input value.
- **Association, not cause** – SHAP shows what the model uses, not what causes ignition.

## Research questions and where they are answered

1. Combined predictors vs seasonal and weather-only references: T2, T4, T5, T16, F1, F2, F14.
2. Future years and separate regions: T3, T4, T6, F4, F12.
3. Calibration and explanations by region and land cover: T2, T7, T8, T11-T13, F3, F5-F10.
