# Model v7 — progress (rolling-origin development)

Brief: [steppe-prediction-accuracy-prompt-v4-2026-10-29.md](steppe-prediction-accuracy-prompt-v4-2026-10-29.md).
Code: `scripts/develop_model_v7.py`. Records (local, `runs/` is not in Git): `runs/model_v7/`.

No v7 has been released. Everything below is development evidence, not a test.

## Protocol

Registered before any experiment: `runs/model_v7/protocol.json`, SHA-256
`3bf2e3e59ca9d3421abd0155393fbcf42a44ef4f73ba5c7a9309459e66a9b73e`. It pins the brief by hash.

- Rolling origins 2020–2025. At origin Y: fit on years < Y−1, calibrate on Y−1, evaluate on Y.
- Primary risk set: the old one minus persistent heat sources — cells with ≥ 30 nominal/high
  active days in [D−366, D−2], or ≥ 30 in any of the three previous calendar years. Causal; N
  chosen from the 2015–2022 distribution (99th percentile 10 days per cell-year, 99.9th 172).
- Reference: the v6 recipe refit at each origin. Release needs higher AP at every origin, no
  lower recall at the reference's precision, BSS > 0 and reliability within ×1.5.
- Final test: prospective, 1 March – 31 October 2027, labels opened only after it ends.

Amendment 2026-10-29-01: v6's calibrator is a sigmoid, not isotonic as the brief says; no
effect on the plan.

## Data

One table per year, 2015–2025, plus the 2026 reassessment rows (`runs/model_v7/samples`).
Checks: rebuilt v6 features equal v6's development table for 2015; recomputed v5
probabilities equal the registered 2025 test exactly (max difference 0); recomputed v6
probabilities equal the registered 2026 test exactly on all 1,188,115 rows.

## Results on the primary risk set

AP / recall at the v6 recipe's precision / Brier skill score.

| Origin | v6 recipe | H1: fit without heat sources | H3: + yesterday's fires | v6 frozen |
|---|---|---|---|---|
| 2020 | 0.0198 / 0.14% / −0.056 | 0.0188 / 0.17% / −0.140 | **0.0243** / 0.25% / −0.026 | — |
| 2021 | 0.0146 / 5.03% / −0.031 | 0.0129 / 1.01% / −0.049 | **0.0158** / 7.43% / −0.051 | — |
| 2022 | 0.0152 / 5.56% / −0.066 | 0.0141 / 4.64% / −0.110 | **0.0160** / 7.54% / −0.081 | 0.0192 / 6.00% / +0.004 |
| 2023 | 0.0236 / 5.39% / −0.013 | 0.0154 / 2.66% / −0.097 | 0.0179 / 7.22% / −0.194 | 0.0236 / 5.39% / +0.007 |
| 2024 | 0.0270 / 5.32% / +0.002 | 0.0184 / 3.33% / −0.141 | 0.0192 / 6.95% / −0.102 | 0.0236 / 4.00% / +0.007 |
| 2025 | 0.0167 / 1.46% / −0.021 | 0.0158 / 1.13% / −0.067 | **0.0189** / 0.61% / −0.046 | 0.0176 / 2.03% / −0.004 |

Paired block bootstrap (95%), H3 minus v6 recipe, AP: 2020 +0.0017..+0.0099;
2021 −0.0016..+0.0079; 2022 −0.0061..+0.0038; 2023 −0.0149..+0.0056; 2024 −0.0157..+0.0088;
2025 −0.0001..+0.0044.

## What this says

- **Honest skill is lower than reported before.** Without persistent heat sources AP is
  0.015–0.027, against 0.044 for v6 on the full 2026 set. Those cells carried a large share
  of every earlier score.
- **H1 refuted (0 of 6 origins).** Dropping heat-source rows from training lowers AP at every
  origin and does not remove values near 1. The heat-source rule stays as the evaluation
  risk set, as the protocol fixes.
- **H3 accepted by the hypothesis rule (AP higher at 4 of 6 origins)**, but it does not pass
  the release rule: AP falls at 2023 and 2024, and recall at the reference precision falls at
  2025. It raises recall at the working precision at five origins.
- **Calibration is the open problem.** The sigmoid fitted on the previous year gives negative
  Brier skill at almost every origin, for every candidate. No candidate meets the release
  criterion yet. Frozen v6, calibrated on 2022 with heat sources included, is slightly
  positive on 2022–2024.

## Next, in protocol order

H2 (weather for the target day; as-issued 1-day-lead forecasts exist only from 2024),
H4 (snow-off, dryness, NDVI anomaly), H5, then H6 (calibration on two years, isotonic and
beta against sigmoid, tuned boosting), which is where the release criteria are decided.
