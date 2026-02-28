# ensure-server.ps1 — Kill stale server, clean corrupt media, start fresh, verify routes.
# Idempotent: safe to run multiple times. Always produces a clean :8901 server.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# 1. Kill any process holding port 8901
$staleIds = Get-NetTCPConnection -LocalPort 8901 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($id in $staleIds) {
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($p) {
        Write-Host "Killing stale PID $id ($($p.ProcessName)) on :8901"
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
}
if ($staleIds) { Start-Sleep 1 }

# 2. Clean corrupt mp4 files in output/ (no moov atom = incomplete render)
Get-ChildItem C:\AT01\output\*.mp4 -ErrorAction SilentlyContinue | ForEach-Object {
    $r = Start-Process ffprobe -ArgumentList "-v error `"$($_.FullName)`"" -Wait -PassThru -NoNewWindow
    if ($r.ExitCode -ne 0) {
        Remove-Item $_.FullName
        Write-Host "Cleaned corrupt: $($_.Name)"
    }
}

# 3. Start server
Set-Location C:\AT01
$proc = Start-Process -NoNewWindow -FilePath "py" -ArgumentList "-3.12 -m uvicorn agents.edbot.server:app --port 8901" -PassThru
Write-Host "Started server PID $($proc.Id)"

# 4. Wait up to 10s for health
$ok = $false
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep 1
    try {
        $r = Invoke-WebRequest http://localhost:8901/health -UseBasicParsing -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {}
}
if (-not $ok) {
    Write-Error "Server failed to start within 10s"
    exit 1
}
Write-Host "Health check passed"

# 5. Verify /api/resolve/command is registered (not 404)
try {
    $null = Invoke-WebRequest -Method POST http://localhost:8901/api/resolve/command `
        -ContentType "application/json" -Body '{"command":"ping"}' `
        -UseBasicParsing -ErrorAction Stop
} catch {
    $status = $_.Exception.Response.StatusCode.value__
    if ($status -eq 404) {
        Write-Error "STALE SERVER: /api/resolve/command not found. Code not loaded correctly."
        exit 1
    }
    # Non-404 errors (400, 422 validation etc) mean the route EXISTS
}

Write-Host "Server ready on :8901 -- all routes verified"
exit 0
