# Registers the nightly forecast in Windows Task Scheduler for the current user.
# Runs at 04:40, 06:40 and 08:40 Kazakhstan time (23:40, 01:40, 03:40 UTC); wakes the PC from
# sleep and catches up after a start-up. -Push also publishes the log branch after each run.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install_forecast_schedule.ps1 [-Push]
param([switch]$Push)
$root = Split-Path -Parent $PSScriptRoot
$cmd = Join-Path $root "scripts\forecast_daily.cmd"
$arg = if ($Push) { "/c set FORECAST_PUSH=1&& `"$cmd`"" } else { "/c `"$cmd`"" }
# Trigger times are local: convert the UTC schedule so it holds in any time zone.
$times = @(23, 1, 3) | ForEach-Object { [DateTime]::UtcNow.Date.AddHours($_).AddMinutes(40).ToLocalTime() }
Register-ScheduledTask -Force -TaskName "WildfireKZ daily forecast" `
    -Description "v6 and v7 forecast for the next UTC day; log in runs\forecast_live\log.jsonl" `
    -Action (New-ScheduledTaskAction -Execute "cmd.exe" -Argument $arg -WorkingDirectory $root) `
    -Trigger ($times | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }) `
    -Settings (New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)) | Out-Null
Get-ScheduledTask -TaskName "WildfireKZ daily forecast" | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime
