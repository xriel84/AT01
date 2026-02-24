# Shows the target specs for each platform EdBot renders to
Write-Host "=== Demo: Platform Render Specs ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "EdBot renders to 5 platforms automatically:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  TikTok           1080x1920  9:16  30fps  max 60s" -ForegroundColor White
Write-Host "  Instagram Reels  1080x1920  9:16  30fps  max 90s" -ForegroundColor White
Write-Host "  YouTube Shorts   1080x1920  9:16  30fps  max 60s" -ForegroundColor White
Write-Host "  YouTube          1920x1080  16:9  30fps  max 10min" -ForegroundColor White
Write-Host "  LinkedIn         1920x1080  16:9  30fps  max 120s" -ForegroundColor White
Write-Host ""
Write-Host "All: H.264 codec, AAC audio 48kHz, 15-20 Mbps" -ForegroundColor Gray
Write-Host ""
Write-Host "SmartReframe (Resolve AI) handles the landscape-to-portrait" -ForegroundColor Yellow
Write-Host "conversion by tracking the speaker. This is why we need" -ForegroundColor Yellow
Write-Host "Resolve Studio — the free version doesn't have this." -ForegroundColor Yellow
Write-Host ""
Write-Host "Press any key to close..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
