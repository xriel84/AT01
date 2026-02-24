# YD double-clicks this ONLY when Resolve is open
# Tests that the Resolve API connection works

Write-Host "=== EdBot Resolve Tests ===" -ForegroundColor Cyan
Write-Host "These tests require DaVinci Resolve to be running." -ForegroundColor Yellow
Write-Host ""

# Check Resolve is running
$resolve = Get-Process -Name "Resolve" -ErrorAction SilentlyContinue
if (-not $resolve) {
    Write-Host "ERROR: DaVinci Resolve is not running." -ForegroundColor Red
    Write-Host "Open Resolve first, then run this again." -ForegroundColor Yellow
    Write-Host "Press any key to close..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

Set-Location "C:\Program Files\Blackmagic Design\DaVinci Resolve"
py -3.12 -m pytest "$PSScriptRoot\..\tests" "$PSScriptRoot\..\resolve-tools\tests" -v --tb=short -k "requires_resolve" 2>&1 | Tee-Object -Variable results

Write-Host ""
if ($LASTEXITCODE -eq 0) {
    Write-Host "ALL RESOLVE TESTS PASSED" -ForegroundColor Green
} else {
    Write-Host "SOME TESTS FAILED — paste output above to Claude" -ForegroundColor Red
}

Write-Host ""
Write-Host "Press any key to close..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
