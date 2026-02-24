# Creates fake filenames and shows how footage_match.py groups them
Write-Host "=== Demo: Footage Matching ===" -ForegroundColor Cyan

$demoDir = "$env:TEMP\edbot_demo_footage"
New-Item -ItemType Directory -Force -Path $demoDir | Out-Null

# Create empty files with realistic names
@(
    "2023-12-08 18-45-03.mp4",
    "2023-12-08 18-45-03_CAM2.mp4",
    "2023-12-08 19-30-00.mp4",
    "workshop_take01.mp4",
    "workshop_take02.mp4",
    "siggraph_talk_full.mp4"
) | ForEach-Object { New-Item -Path "$demoDir\$_" -ItemType File -Force | Out-Null }

Write-Host "Created demo files in: $demoDir" -ForegroundColor Yellow
Write-Host ""

Set-Location $PSScriptRoot\..\..
py -3.12 resolve-tools/footage_match.py --scan-dir $demoDir

# Clean up
Remove-Item -Recurse -Force $demoDir

Write-Host ""
Write-Host "Press any key to close..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
