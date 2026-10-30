# Backs up what cannot be rebuilt byte for byte: frozen models, releases, protocols, test
# records, the forecast log (runs\) and the hash-pinned public data (data\real\).
# The archive carries a SHA-256 manifest of every file and is tested after writing.
# -Encrypt asks for a password (AES-256, file names hidden too); you type it, nothing stores it.
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\backup_evidence.ps1                       # C:\WildFireBackup
#   powershell -ExecutionPolicy Bypass -File scripts\backup_evidence.ps1 -Destination E:\ -Encrypt   # USB disk
#   powershell -ExecutionPolicy Bypass -File scripts\backup_evidence.ps1 -Destination "$env:OneDrive\WildFireBackup" -Encrypt
param([string]$Destination = "C:\WildFireBackup", [switch]$Encrypt, [int]$Keep = 3)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$sevenZip = "C:\Program Files\7-Zip\7z.exe"
if (-not (Test-Path $sevenZip)) { throw "7-Zip not found at $sevenZip" }
New-Item -ItemType Directory -Force $Destination | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$archive = Join-Path $Destination "wildfire-evidence-$stamp.7z"
$manifest = Join-Path $root "runs\backup-manifest.csv"

Push-Location $root
try {
    # Worktrees of the data and log branches are copies of what is already here.
    $skip = @("runs\forecast_inputs_tree", "runs\forecast_live\git")
    $files = Get-ChildItem runs, data\real -Recurse -File |
        Where-Object { $f = $_.FullName.Substring($root.Length + 1); -not ($skip | Where-Object { $f.StartsWith($_) }) }
    $files = $files | Where-Object { $_.FullName -ne $manifest -and $_.Extension -ne ".log" }
    # Logs are still being written by running jobs; everything else is hashed.
    $files | ForEach-Object {
        [pscustomobject]@{ path = $_.FullName.Substring($root.Length + 1); bytes = $_.Length; sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower() }
    } | Export-Csv $manifest -NoTypeInformation -Encoding UTF8
    $zip = @("a", "-t7z", "-mx=1", "-bso0", "-bsp0", "-ssw", $archive, "runs", "data\real", "-xr!forecast_inputs_tree", "-xr!git")
    if ($Encrypt) { $zip += @("-p", "-mhe=on") }
    & $sevenZip @zip
    if ($LASTEXITCODE -ne 0) { throw "7-Zip failed ($LASTEXITCODE)" }
    $test = @("t", "-bso0", $archive)
    if ($Encrypt) { $test += "-p" }
    & $sevenZip @test
    if ($LASTEXITCODE -ne 0) { throw "Archive test failed ($LASTEXITCODE)" }
    $size = [math]::Round((Get-Item $archive).Length / 1GB, 2)
    Write-Output "Backup: $archive ($size GB, $($files.Count) files, tested)"
    Get-ChildItem $Destination -Filter "wildfire-evidence-*.7z" | Sort-Object Name -Descending |
        Select-Object -Skip $Keep | ForEach-Object { Remove-Item $_.FullName; Write-Output "Removed old backup $($_.Name)" }
}
finally { Pop-Location }
