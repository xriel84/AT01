# demo_subtitle_styles.ps1 — Generate sample .ass files for all 5 platforms
# Double-click or run in PowerShell
# No GPU or media required — uses mock transcript

Write-Host "Generating demo subtitle files for all platforms..." -ForegroundColor Cyan
Write-Host ""

py -3.12 agents/edbot/tools/subtitle_gen.py --demo

Write-Host ""
Write-Host "Output files are in: tests\demos\subtitle_samples\" -ForegroundColor Green
Write-Host "Open any .ass file in Notepad to inspect the ASS format." -ForegroundColor Gray
Write-Host "Or use Aegisub (free) to preview subtitle rendering." -ForegroundColor Gray

if (Test-Path "tests\demos\subtitle_samples") {
    Write-Host ""
    Write-Host "Generated files:" -ForegroundColor Cyan
    Get-ChildItem "tests\demos\subtitle_samples\*.ass" | ForEach-Object {
        Write-Host "  $($_.Name)" -ForegroundColor White
    }
}
