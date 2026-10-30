@echo off
rem Daily v6 and v7 forecast for the next UTC day; Task Scheduler runs it three times a night,
rem a run after a successful issue stops at once. Output goes to runs\forecast_live\runs.log.
rem FORECAST_PUSH=1 (set by install_forecast_schedule.ps1 -Push) also pushes the log branch.
cd /d "%~dp0.."
set OPENBLAS_NUM_THREADS=1
set PYTHONUTF8=1
if not exist runs\forecast_live mkdir runs\forecast_live
".venv\Scripts\python.exe" scripts\forecast_daily.py >> runs\forecast_live\runs.log 2>&1
if "%FORECAST_PUSH%"=="1" ".venv\Scripts\python.exe" scripts\push_forecast_log.py >> runs\forecast_live\runs.log 2>&1
