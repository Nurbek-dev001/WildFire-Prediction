# Render every slide of a .pptx to PNG with PowerPoint (for visual checks).
# Usage: render.ps1 <deck.pptx> <outdir> [widthPx]
param([string]$Deck, [string]$OutDir, [int]$Width = 1600)
$Deck = (Resolve-Path $Deck).Path
if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path
$ppt = New-Object -ComObject PowerPoint.Application
try {
    $pres = $ppt.Presentations.Open($Deck, $true, $false, $false)
    $h = [int]($Width * $pres.PageSetup.SlideHeight / $pres.PageSetup.SlideWidth)
    $i = 1
    foreach ($s in $pres.Slides) {
        $s.Export((Join-Path $OutDir ("slide-{0:D2}.png" -f $i)), "PNG", $Width, $h)
        $i++
    }
    $pres.Close()
} finally {
    $ppt.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null
}
Get-ChildItem $OutDir | ForEach-Object { $_.FullName }
