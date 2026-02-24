# YD double-clicks this to run all offline tests
# No Resolve needed. No GPU needed. No video files needed.

Write-Host "=== EdBot Test Suite ===" -ForegroundColor Cyan
Write-Host "Running offline tests (no Resolve required)..." -ForegroundColor Yellow
Write-Host ""

Set-Location $PSScriptRoot\..
py -3.12 -m pytest tests/ resolve-tools/tests/ -v --tb=short -k "not requires_resolve" 2>&1 | Tee-Object -Variable results

Write-Host ""
Write-Host "=== Test Results ===" -ForegroundColor Cyan
if ($LASTEXITCODE -eq 0) {
    Write-Host "ALL TESTS PASSED" -ForegroundColor Green
} else {
    Write-Host "SOME TESTS FAILED — paste output above to Claude" -ForegroundColor Red
}

Write-Host ""
Write-Host "Press any key to close..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
