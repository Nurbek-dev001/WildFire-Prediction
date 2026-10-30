# Operations: the nightly forecast

What the platform does every night, how to keep it running and how to read its output.

## What it predicts

For each 5 km cell of Kazakhstan, the chance that a **new** satellite fire detection
(S-NPP VIIRS, nominal or any confidence) appears there tomorrow (UTC day), in cells with no
detection in the previous 48 hours. This includes stubble and pasture burning, not only wild
vegetation fires. The bulletin marks the land type of each alert: on `пашня` (cropland) an alert
is most likely a planned burn; on `степь`, `лес` and `кустарник` it is a possible wildfire.

Honest accuracy (2020–2025 development, primary risk set): of 100 cells on alert about 6–7 burn;
about 9–11% of new fires fall inside the alert area. The forecast ranks where risk is highest;
it does not name the cell that will burn.

## Night schedule

The forecast runs in the cloud (GitHub Actions, `.github/workflows/forecast.yml`); the site is
on Cloudflare Pages and the Telegram bot on Cloudflare Workers: see
[cloud-setup.md](cloud-setup.md). The local schedule below is only a fallback for a machine
without the cloud; never run both, or two issuers race for the same log.


`scripts/forecast_daily.cmd`, registered once with

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_forecast_schedule.ps1
```

runs at 04:40, 06:40 and 08:40 Kazakhstan time (23:40, 01:40, 03:40 UTC), wakes the PC and
catches up after a start-up. Each run:

1. checks that the library versions equal `requirements-forecast.txt` (the models are pickles
   of these versions) and that every frozen model and code file matches its release hash;
2. downloads only public data: NASA GIBS detections (FIRMS seven-day file as fallback), ERA5,
   NOAA NDVI, NOAA GFS. Nothing is uploaded;
3. issues v6 and v7, appends the hash-chained log entry, puts the day on the map and writes
   `platform/dist/assets/bulletin-latest.csv`;
4. checks the inputs and outputs (`health` and `warnings` in the entry): detections present in
   season, NDVI age and coverage, GFS ranges, eligible cells and mean probability against the
   last 30 days.

A warning, or a day that cannot be issued by the last attempt, shows a Windows notification and
a line in `runs/forecast_live/ALERTS.txt`; a missed day is also logged as `missed`.
`python scripts/forecast_daily.py --status` summarises on-time, late and missed test days.

## Backup

`runs/` (frozen models, releases, protocols, test records, the log) and `data/real/` (hash-pinned
public inputs) cannot be rebuilt byte for byte. Back them up after every model change and
monthly:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup_evidence.ps1 -Destination E:\ -Encrypt
```

The archive (7-Zip, AES-256 with your password, file names hidden) carries a SHA-256 manifest
of every file and is tested after writing; the last three are kept. A copy on the same disk
(`C:\WildFireBackup`, the default) protects against deletion, not against disk failure: keep one
on a USB disk or, encrypted, in OneDrive.

## Is the model better than simple rules?

`scripts/baselines_v7.py`, same test rows and years as the v7 development
(`runs/model_v7/experiments/baselines/`). Mean AP over 2020–2025:

| Method | All cells | Cropland | Steppe, forest, shrub |
|---|---|---|---|
| FWI of D-1 (weather only) | 0.0003 | 0.0018 | 0.0002 |
| Persistence (fires yesterday nearby) | 0.0088 | 0.0167 | 0.0087 |
| Climatology (cell, month) | 0.0107 | 0.0137 | 0.0106 |
| Simple logistic model on the above | 0.0184 | 0.0273 | 0.0175 |
| v6 recipe | 0.0195 | 0.0225 | 0.0203 |
| **v7** | **0.0213** | **0.0311** | 0.0198 |

- Weather alone (FWI) is close to chance: in Kazakhstan the place of a new fire depends on
  people (burning calendar, settlements, fields), not on dryness alone.
- Climatology and yesterday's fires carry most of the signal; a simple logistic model on them
  comes close to the v6 recipe.
- v7 beats the best simple method at 5 of 6 years (v6 recipe at 4 of 6), most clearly on
  cropland. The added value of ML is real but moderate; this is what the 2027 test measures.

## Not automated

- The old ChatGPT hosting (`platform/.openai/hosting.json`) is updated by hand only; Cloudflare
  Pages is updated every night.
