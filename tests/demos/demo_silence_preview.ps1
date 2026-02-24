# demo_silence_preview.ps1 — Preview what auto-editor would cut
# Double-click or run in PowerShell
# Requires: a test clip at tests\fixtures\test_clip.mp4

$clip = "tests\fixtures\test_clip.mp4"
if (Test-Path $clip) {
    Write-Host "Running auto-editor preview on: $clip" -ForegroundColor Cyan
    auto-editor $clip --preview
} else {
    Write-Host "No test clip found." -ForegroundColor Yellow
    Write-Host "Place a short .mp4 at: $clip" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "To create a test clip, record a short screen capture or download a sample." -ForegroundColor Gray
}
