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

## H2 upper bound: reanalysis of the target day

Not operational (the weather of day D is not known at 00 UTC of D) and never used for
selection; it shows how much forecast weather can be worth. Point estimates; the 1000-draw
bootstrap is still to run.

| Origin | AP: v6 recipe / + H3 / + weather of D | Recall at v6 recipe precision: v6 recipe / + weather of D |
|---|---|---|
| 2020 | 0.0198 / 0.0243 / **0.0292** | 0.14% / **6.39%** |
| 2021 | 0.0146 / 0.0158 / **0.0171** | 5.03% / **10.01%** |
| 2022 | 0.0152 / 0.0160 / **0.0169** | 5.56% / **8.80%** |
| 2023 | 0.0236 / 0.0179 / **0.0281** | 5.39% / **9.69%** |
| 2024 | 0.0270 / 0.0192 / 0.0238 | 5.32% / **17.17%** |
| 2025 | 0.0167 / 0.0189 / **0.0237** | 1.46% / **6.82%** |

Weather of the target day roughly doubles to triples recall at the working precision at
every origin, and raises AP at five of six. The operational test (trained on reanalysis,
served with the GFS 18 UTC run of D-1, `src/wildfire_kz/data/gfs_forecasts.py`, 1°
interpolated to the ERA5 cells) needs GFS for 2024-2025; the download is resumable and
limited by the connection (0.05-0.5 MB/s).

## H6, calibration part

Base models v6 recipe and v6 + H3, each calibrated by four methods on one prior year (fit
< Y-1) or two prior years (fit < Y-2, the two years weighted equally). Metrics at all six
origins on the primary risk set. Brier skill is against the evaluation year's own base rate,
which no forecast knows in advance, so even small positive values are meaningful.

| Scheme, model, method | BSS > 0 at | Mean BSS | Worst reliability gap | Mean AP |
|---|---|---|---|---|
| one year, v6 recipe, sigmoid (as v6) | 1 of 6 | −0.031 | ×5.93 | 0.0195 |
| two years, v6 + H3, sigmoid | 1 of 6 | −0.062 | ×3.75 | 0.0206 |
| two years, v6 + H3, beta | 1 of 6 | −0.016 | ×2.51 | 0.0204 |
| **two years, v6 + H3, isotonic** | **6 of 6** | **+0.008** | **×1.66** | 0.0180 |
| two years, v6 + H3, isotonic joined by lines | 5 of 6 | +0.004 | ×1.66 | 0.0195 |

- **Two-year isotonic calibration is the first to give positive Brier skill at every origin**
  (+0.004 to +0.014), and shown and observed rates agree within ×1.66 in every bin with at
  least 100 fires (v6: ×4-6). The two bins over ×1.5 are the lowest bin in 2022 (0.002% shown,
  0.001% observed) and the top bin in 2024 (6.7% shown, 4.5% observed; 2024 had a third fewer
  fires than 2023).
- Its cost is ranking: AP 0.0180 against 0.0206 with sigmoid, because cells inside an
  isotonic step tie. Joining the step centres by lines recovers most of it (0.0195) at the
  price of one origin with negative skill.
- No variant meets the release criteria in full yet (×1.5). Calibration is the release
  decision; it is rechecked once H2 (served) and H4 are in the model.

## H2 served with as-issued forecasts (origin 2025)

Fitted on reanalysis, calibrated on 2024 and evaluated on 2025 with the GFS 18 UTC run of the
previous day: AP 0.0215 (v6 recipe 0.0167, + H3 0.0189, reanalysis upper bound 0.0237);
recall at the v6 recipe precision 4.36% (v6 recipe 1.46%). About 70% of the upper bound's
gain survives real forecasts. H2 accepted.

## v7 candidate and freeze

v6 inputs + H3 + H2, fit < Y-2 on reanalysis, isotonic on Y-2..Y-1 with the inputs of those
years (GFS from 2024), against the v6 recipe.

| Origin | AP v6 recipe → v7 | Recall at v6 recipe precision | BSS v7 (v6 recipe) | Reliability gap v7 (v6 recipe) |
|---|---|---|---|---|
| 2020 | 0.0198 → **0.0282** | 0.14% → **7.37%** | **+0.017** (−0.056) | ×1.26 (×5.93) |
| 2021 | 0.0146 → **0.0176** | 5.03% → **9.51%** | **+0.009** (−0.031) | ×1.35 (×2.40) |
| 2022 | 0.0152 → **0.0214** | 5.56% → **13.03%** | **+0.013** (−0.066) | ×1.53 (×2.68) |
| 2023 | 0.0236 → 0.0182 | 5.39% → 0.19% | +0.002 (−0.013) | ×1.29 (×1.96) |
| 2024, GFS | 0.0270 → 0.0210 | 5.32% → **13.50%** | −0.015 (+0.002) | ×1.43 (×2.25) |
| 2025, GFS | 0.0167 → **0.0212** | 1.46% → **5.63%** | **+0.001** (−0.021) | ×1.63 (×1.71) |

Paired block bootstrap (1000 draws, 100 km x 30 days), v7 minus v6 recipe, AP (95%):
2020 +0.0047..+0.0124; 2021 -0.0003..+0.0055; 2022 -0.0024..+0.0110; 2023 -0.0152..-0.0017;
2024 -0.0143..+0.0128; 2025 +0.0024..+0.0068. v7 is better beyond noise at 2020 and at 2025, the
year served exactly as in operation; worse beyond noise at 2023; the other three are open.
`scripts/bootstrap_v7.py`, `runs/model_v7/experiments/v7_candidate/bootstrap.json`.

The candidate does not meet the selection rule (2023 and 2024). Amendment
2026-10-29-02, written after these results: no release under the rule, v6 stays the map
default, and the candidate is frozen as a challenger for the prospective 2027 test, which
scores both models on the same days. Frozen 2026-10-29: fit 2015–2023, isotonic on 2024–2025
with GFS inputs, alert threshold 4.50% (2024–2025 precision 6.63%, recall 8.76%).
`runs/model_v7/release.json`.

## Next, in protocol order

H2 (weather for the target day; as-issued 1-day-lead forecasts exist only from 2024),
H4 (snow-off, dryness, NDVI anomaly), H5, then H6 (calibration on two years, isotonic and
beta against sigmoid, tuned boosting), which is where the release criteria are decided.

## Daily forecasts for the prospective test

`scripts/forecast_daily.py` issues frozen v6 and frozen v7 for the next UTC day on the full
grid, with the inputs that exist at issue time: S-NPP detections from NASA GIBS (D-1 to 21 UTC),
ERA5 through D-7, NDVI through D-12, GFS 18 UTC runs for D-2..D. Payloads and a hash-chained,
append-only log are in `runs/forecast_live/` (`log.jsonl`; each entry carries the previous
entry's hash, the payload hashes and the input record). One entry per day, the first issue
stands. An entry counts for the 2027 test only if issued before 06:00 UTC of D (`on_time`).
Windows Task Scheduler runs `scripts/forecast_daily.cmd` at 23:40, 01:40 and 03:40 UTC.

Checks: a replay of 2026-10-15 reproduces the registered v6 map byte for byte, and the H3 and
H2 inputs equal v7's development features exactly (4,334 rows of 2026-10-15; two 2025 days).
The log proves order, not time, to anyone outside this machine: pushing it daily (or any
external timestamp) is what makes the 2027 comparison verifiable.

### Operation (from 2026-10-30)

- First entry: 2026-10-30, issued 05:36 UTC, on time; alerts v6 51, v7 34 of 109,838 cells.
- Detections: GIBS first; the public FIRMS seven-day file when GIBS fails or is empty
  (`firms_days` in each entry). A day that cannot be issued by the last attempt (03:40 UTC) is
  logged as `missed` with the reason, so gaps are visible, not silent.
- Each entry also records the H1 heat-source cells known before D, the 2027 primary risk set.
- `scripts/publish_forecasts.py` puts every issued day on the map (v6 timeline and v7 as a third
  model, `platform/dist/assets/forecast-live.json`) and writes the alert bulletin
  (`assets/bulletin-latest.csv`, region, coordinates, both probabilities).
- `scripts/push_forecast_log.py` commits the log to the `forecast-log` branch from its own
  worktree and pushes it: the GitHub time of each push is the external timestamp.
- Install once: `powershell -ExecutionPolicy Bypass -File scripts\install_forecast_schedule.ps1 -Push`.
- `forecast_daily.py --status` summarises on-time, late and missed test days.

## Baselines (2026-10-30)

Climatology, persistence, FWI of D-1 and a simple logistic model on them, on the same rows:
mean AP 0.0107, 0.0088, 0.0003, 0.0184; v6 recipe 0.0195, v7 0.0213. v7 beats the best of them
at 5 of 6 origins, the v6 recipe at 4 of 6. On cropland v7 0.0311 against 0.0273; elsewhere
v7 0.0198 against 0.0175. Details and the table by land type: docs/operations.md.

## Amendment 2026-11-04-03: day-ahead issue

Management asked that the forecast for day D be ready during D-1 rather than in the morning
of D. From 2026-11-05 both models are issued between 12:00 and 19:00 UTC of D-1 (17:00 to
midnight in Kazakhstan); on time means before 19:00 UTC of D-1. Neither frozen model is
retrained; their inputs change as follows, identically for both, so the 2027 comparison stays
paired on the same days and inputs:

| Input | Before (issue 23:00-06:00 UTC) | Day-ahead (issue 12:00-19:00 UTC of D-1) |
|---|---|---|
| D-1 detections | to 21:00 UTC (v7 H3 as trained) | to 12:00 UTC (day pass only) |
| 48 h exclusion | detections in the 48 h before D | the same, through 12:00 UTC of D-1 |
| GFS for D | 18 UTC run of D-1, lead 6-30 h | 06 UTC run of D-1, lead 18-42 h |
| GFS for D-1, D-2 | 18 UTC runs | unchanged |
| ERA5, NDVI | D-7, D-12 | unchanged |

On 2026-11-03 the 06 UTC run reproduced the 18 UTC daily fields closely (correlation 0.999
tmax, 0.998 tmin, 0.994 RH, 0.991 wind, 0.987 precipitation over the window). v7's H3 inputs
now see only the day pass of D-1, which v7 was not trained on: its 2027 scores measure the
model as served day-ahead. Entries record `issue: day_ahead` and the detection cut-off.

## Amendment 2026-11-04-03 withdrawn (2026-11-04, 19:40 UTC)

The day-ahead issue never produced a forecast and is withdrawn before its first issue. v6 needs
ERA5 for D-7, and the archive publishes that day only around the night before D: at 19:20 UTC
of 2026-11-04 it ended on 2026-10-28, so no attempt between 12:00 and 19:00 UTC of D-1 could
issue D. The scheduled attempts of 2026-11-04 also fell into two GitHub Actions incidents
(16:05-17:01 and 17:40-18:16 UTC) and left no record. Both models are again issued between
23:00 UTC of D-1 and 06:00 UTC of D with the inputs of the table's left column, as they were
through 2026-11-04; no log entry was ever written under the amendment. A day-ahead forecast
would need v6 to take older weather (D-8), which is a new model version, not an amendment.

## Amendment 2026-11-05-01: NOAA-20 fills an S-NPP outage

NASA's S-NPP VIIRS fire feed (GIBS and FIRMS) stopped at 10:21 UTC on 2026-11-02, while
NOAA-20, NOAA-21 and MODIS stayed current. Every model reads its fire history from S-NPP only,
so the history froze: the last known fires repeated in each forecast (v7 alerts of 4 and 5
November overlapped 70%, against about 30% normally) and v7's "fires yesterday" inputs were
empty. NOAA-20 carries the same VIIRS instrument and active-fire algorithm in the same orbit,
about 50 minutes ahead of S-NPP.

Rule (`scripts/forecast_daily.py`, `noaa20_fill`): when the last S-NPP point is more than 24 h
older than the end of D-1 (or the issue time, if earlier), NOAA-20 points from the GIBS layer
`VIIRS_NOAA20_Thermal_Anomalies_375m_All` after that last S-NPP point are added. With S-NPP
current nothing changes. Entries record `inputs.detections.noaa20_fill` and a warning; the
models, thresholds and every other input are unchanged.

Check on days both satellites exist (16 days, 20 October – 4 November): NOAA-20 found
0.9–1.6 times as many nominal/high fire cells per day as S-NPP; 57–74% of S-NPP's fire cells
were also NOAA-20 fire cells the same day. Replays of 31 October and 1 November with the last
three days of S-NPP replaced (`scripts/check_noaa20_fill.py`), compared with S-NPP as issued:

| Day, model | NOAA-20 fill: alerts / same alerts / same top 1% | Outage (no data): alerts / same / top 1% | S-NPP alerts |
|---|---|---|---|
| 31 Oct, v6 | 53 / 75% / 92% | 75 / 62% / 86% | 50 |
| 31 Oct, v7 | 57 / 60% / 83% | 50 / 31% / 77% | 74 |
| 1 Nov, v6 | 59 / 74% / 93% | 78 / 57% / 85% | 54 |
| 1 Nov, v7 | 193 / 62% / 86% | 52 / 14% / 72% | 210 |

("Same alerts": shared alert cells over all alert cells of either run.) The fill is much
closer to S-NPP than the outage is, above all for v7. It is a fallback for outages only: the
2027 prospective scores are computed on S-NPP labels, and days issued with the fill are
flagged in the log.
