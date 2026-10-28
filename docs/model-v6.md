# Model v6 — cell-level fire history, tested on 2026

## What changed

Model v6 is the original XGBoost recipe (same tuned parameters) with three groups
of inputs added to the 26 physical features and the six 15/55 km fire-history
features of release v5. All are known on the forecast day:

- fire activity in the same 5 km cell over 30 and 365 days, and days since the
  cell's last fire, ending two days before the target (the lag v5 already uses);
- the share of earlier complete years with fire in the same calendar month, in
  the cell and in its 15 km square;
- Canadian Fire Weather Index codes from the same daily ERA5 data, lagged 7 days
  (`src/wildfire_kz/fire_weather.py`, checked against the Van Wagner reference day).

## How it was chosen

The plan was registered and hashed before any experiment
(`runs/model_v6/protocol.json`). Development used 2015–2022 only. Five
candidates differed only in inputs; each was trained on years before V and tested
on V for V = 2020, 2021, 2022, against the original XGBoost out of fold
(2020, 2021) and release v5 (2022).

| Year | AP: reference → v6 | Daily top 1% capture: reference → v6 |
|---|---|---|
| 2020 | 0.020 → 0.044 | 23.4% → 32.7% |
| 2021 | 0.019 → 0.033 | 22.5% → 30.2% |
| 2022 | 0.016 → 0.032 | 28.5% → 35.4% |

Fire weather codes added almost nothing; the pre-declared rule selected the
cell-history candidate. It was refit on 2015–2021, calibrated on 2022 and its
threshold set on 2022 at precision not below v5's (6.31% at recall 13.6%, versus
v5's 6.10% at 5.59%), then frozen with hashes (`runs/model_v6/release.json`).

## Final test: 1 January – 15 October 2026

Registered before any 2026 label was read (`runs/test_2026/protocol.json`).
Labels: S-NPP VIIRS detections from NASA GIBS vector tiles (FIRMS NRT records),
linked into events exactly as before; on seven 2025 days this source contained
582 of 583 standard-archive fire cell-days plus about 7% extra. Both frozen
models scored the same 1,188,115 sampled cell-days (10,104 positives, all
positives kept, negatives sampled with known weights). Excluded: 29 April –
1 May and 11–17 July, where GIBS has no data. Land cover 2024 (MODIS 2025 is
unpublished).

| 2026 | v5 (current) | v6 |
|---|---:|---:|
| Precision at frozen threshold | 8.04% | 8.71% |
| Recall at frozen threshold | 5.74% | **15.30%** |
| F1 | 0.067 | 0.111 |
| Average precision | 0.0208 | **0.0439** |
| ROC-AUC | 0.934 | 0.950 |
| New fires in each day's top 0.1% of cells | 9.2% | 14.8% |
| New fires in each day's top 1% of cells | 29.7% | 37.8% |

95% paired cluster bootstrap (1000 draws, 100 km × 30 days), v6 minus v5:
recall +8.2 to +10.9 points; precision −1.1 to +1.8 points (no detectable
change). v6 recall alone: 12.7–18.0%.

## Limits

- v6 ranks much better but its probabilities are not calibrated on 2026:
  Brier skill score −0.062 versus v5's +0.009. The error runs both ways
  (`platform/dist/v6/reliability_2026.json`): for values of 0.3–3%, around the
  alert threshold, the observed rate was 4–6 times higher than shown; in the
  0.015% of cell-days above 3% it was about 2.7 times lower. v5 stays within
  1.3 times in the same ranges. Read v6 percentages as a ranking, not as
  chances. Recalibration would need a new held-out period.
- Persistent heat sources inflate both models. 44 cells with at least 20 VIIRS
  detections in every year 2015–2022 (smelters, steel works, gas flares the
  frozen industrial list missed) hold 6% of the 2026 test fires but 33% of v6
  hits and 36% of v5 hits. Without them (post-hoc, `sensitivity_2026.json`):
  v6 precision 7.3%, recall 10.8%, AP 0.032; v5 6.3%, 3.9%, 0.015. v6 keeps
  its lead. The map hides these cells by default. Heat sources that appeared
  after 2022 are not caught by this rule.
- Precision stays low: about 9 of 100 alerts match a new fire in the same cell
  on the same day.
- Weather enters 7 days late, as in every earlier release.
- Labels are NRT, not the standard archive. Both models are compared on the same
  labels, so the comparison is fair; absolute precision is probably slightly
  optimistic.
- Not a prospective as-issued trial and not a spatial holdout.

## On the site

v6 is the map's default model; v5 stays in the switch. `scripts/export_model_v6.py`
writes full-grid daily maps for 2023–2024 and the 2026 test period; every 2026
map is checked cell for cell against the registered test predictions.
`scripts/publish_model_v6.py` copies them to `platform/dist/assets/predictions-v6/`
and writes `forecast-manifest-v6.json`, the hash-bound records in
`platform/dist/v6/` and the observed-events layer `events-v6.bin`.
`platform/scripts/verify-v6-assets.mjs` re-checks all of it.

The 2023–2024 maps are shown for continuity only, since an audit of those years
informed the design of v6. The map, cell card and "Model" report show the
calibration limit next to the numbers.
