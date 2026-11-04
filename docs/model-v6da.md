# v6da: the day-ahead forecast

The project's aim is a forecast for day D that is ready before D begins. The frozen v6 and v7
cannot be issued that early: both read ERA5 for D-7, and the archive publishes that day only
around the night before D (at 19:20 UTC of 2026-11-04 it ended on 2026-10-28). They stay as
registered for the 2027 prospective test and are issued in the morning of D.

v6da is v6 with one change: its ten ERA5 predictors (daily values and the 7- and 14-day
windows) end on D-8, the latest day published from 12:00 UTC of D-1. Features, rows,
hyperparameters, training years (2015-2021), sigmoid calibration on 2022 and the threshold
rule (v6's precision floor) are v6's. v6's fire history already ends on D-2, so it needs no
change. Code: `scripts/develop_model_v6da.py` (`check` rebuilds v6's lag-7 weather byte for
byte before anything else); release: `runs/model_v6da`.

## Validation (v6's rolling protocol, no test-year label read)

Fit on the years before, scored on 2020, 2021 and 2022 (`runs/model_v6da/lag_comparison.csv`):

| Year | AP, lag 7 | AP, lag 8 | Top-1% capture, lag 7 | Top-1% capture, lag 8 | ROC-AUC 7 / 8 |
|---|---|---|---|---|---|
| 2020 | 0.0442 | 0.0402 | 32.7% | 32.8% | 0.938 / 0.937 |
| 2021 | 0.0330 | 0.0232 | 30.2% | 29.5% | 0.938 / 0.935 |
| 2022 | 0.0323 | 0.0352 | 35.4% | 34.9% | 0.949 / 0.949 |

Ranking keeps its skill (top-1% capture -1%, ROC-AUC unchanged); average precision is about
10% lower on average and varies by year, as the paper's ablation found for week-old weather.
On 2022 the frozen operating point gives precision 6.1% and recall 13.7% (v6: 6.3%, 13.6%).

## Serving

`scripts/forecast_dayahead.py`, scheduled by `.github/workflows/dayahead.yml`: from 12:05 UTC
of D-1 every 30 minutes to 18:35, then hourly to 23:05. Detections of D-1 count to 12:00 UTC
(its day pass) in every attempt and replay. An issue before 19:00 UTC of D-1 (midnight in
Kazakhstan) is on time; later ones are logged as late, and a failure from 23:30 UTC is logged
as missed. Entries go to `dayahead.jsonl` on the forecast-log branch, a hash chain of its own,
so the registered log of v6 and v7 is unchanged.

The site opens on "Tomorrow" (v6da) while a day-ahead forecast is newer than the latest morning
issue; the bot sends it in the evening with the note that it is refined in the morning. The
morning issue of v6 and v7 for the same day then replaces it on the site and in /today without
a second message.
