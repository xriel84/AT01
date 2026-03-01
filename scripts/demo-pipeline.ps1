# demo-pipeline.ps1 — One-click demo runner for T1 boss presentation.
# Starts server, runs pipeline on specified input, opens viewers in browser.
#
# Usage:
#   .\scripts\demo-pipeline.ps1                         # uses first file in input\
#   .\scripts\demo-pipeline.ps1 -InputFile "C:\AT01\input\carol.mov"
#   .\scripts\demo-pipeline.ps1 -SkipPipeline           # server + viewers only
#   .\scripts\demo-pipeline.ps1 -LibraryPath "carol-library.json"

param(
    [string]$InputFile = "",
    [string]$LibraryPath = "",
    [switch]$SkipPipeline,
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location C:\AT01

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AT01 EdBot — Demo Pipeline Runner"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# Step 1: Ensure server
# ---------------------------------------------------------------------------
Write-Host "[1/5] Starting server..." -ForegroundColor Yellow
& .\scripts\ensure-server.ps1
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED: Server did not start." -ForegroundColor Red
    exit 1
}
Write-Host ""

# ---------------------------------------------------------------------------
# Step 2: Set library path
# ---------------------------------------------------------------------------
if ($LibraryPath) {
    [System.Environment]::SetEnvironmentVariable('LIBRARY_PATH', $LibraryPath, 'Process')
    Write-Host "[2/5] Library: $LibraryPath" -ForegroundColor Yellow
} else {
    Write-Host "[2/5] Library: default (demo-library.json)" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Step 3: Run pipeline on input file (unless -SkipPipeline)
# ---------------------------------------------------------------------------
if ($SkipPipeline) {
    Write-Host "[3/5] Pipeline: SKIPPED (-SkipPipeline)" -ForegroundColor Yellow
} else {
    # Find input file
    if (-not $InputFile) {
        $candidates = Get-ChildItem C:\AT01\input -Include *.mp4,*.mov,*.mkv,*.avi,*.webm -Recurse -ErrorAction SilentlyContinue |
            Sort-Object Length | Select-Object -First 1
        if ($candidates) {
            $InputFile = $candidates.FullName
        }
    }

    if (-not $InputFile -or -not (Test-Path $InputFile)) {
        Write-Host "[3/5] Pipeline: SKIPPED (no input file found)" -ForegroundColor Yellow
        Write-Host "       Place video files in C:\AT01\input\ or specify -InputFile" -ForegroundColor DarkGray
    } else {
        Write-Host "[3/5] Pipeline: $InputFile" -ForegroundColor Yellow
        $outDir = "C:\AT01\output\demo-run"
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null

        # 3a. Probe
        Write-Host "       Probing..." -NoNewline
        $probeStart = Get-Date
        try {
            $probe = py -3.12 -c "
import json, sys
sys.path.insert(0, 'agents/edbot/tools')
from video_prober import probe_video
r = probe_video('$($InputFile -replace '\\','/')')
print(json.dumps(r))
" 2>$null | ConvertFrom-Json
            $probeDur = ((Get-Date) - $probeStart).TotalSeconds
            Write-Host " OK ($([math]::Round($probeDur,1))s) — $($probe.duration)s, $($probe.resolution)" -ForegroundColor Green
        } catch {
            Write-Host " FAILED" -ForegroundColor Red
            $probe = $null
        }

        # 3b. Transcribe
        Write-Host "       Transcribing..." -NoNewline
        $txStart = Get-Date
        try {
            py -3.12 -c "
import json, sys
sys.path.insert(0, 'agents/edbot/tools')
from transcribe import transcribe_video
r = transcribe_video('$($InputFile -replace '\\','/')')
with open(r'$outDir\transcript.json', 'w', encoding='utf-8') as f:
    json.dump(r, f, indent=2, ensure_ascii=False)
print(len(r.get('chunks', [])))
" 2>$null
            $txDur = ((Get-Date) - $txStart).TotalSeconds
            $txChunks = (Get-Content "$outDir\transcript.json" -Raw | ConvertFrom-Json).chunks.Count
            Write-Host " OK ($([math]::Round($txDur,1))s) — $txChunks chunks" -ForegroundColor Green
        } catch {
            Write-Host " FAILED" -ForegroundColor Red
        }

        # 3c. Chapter detect
        Write-Host "       Detecting chapters..." -NoNewline
        if (Test-Path "$outDir\transcript.json") {
            try {
                py -3.12 -c "
import json, sys
sys.path.insert(0, 'agents/edbot/tools')
from chapter_detect import detect_chapters
with open(r'$outDir\transcript.json', encoding='utf-8') as f:
    tx = json.load(f)
chapters = detect_chapters(tx.get('chunks', []))
with open(r'$outDir\chapters.json', 'w', encoding='utf-8') as f:
    json.dump(chapters, f, indent=2, ensure_ascii=False)
print(len(chapters))
" 2>$null
                $chCount = (Get-Content "$outDir\chapters.json" -Raw | ConvertFrom-Json).Count
                Write-Host " OK — $chCount chapters" -ForegroundColor Green
            } catch {
                Write-Host " FAILED" -ForegroundColor Red
            }
        } else {
            Write-Host " SKIPPED (no transcript)" -ForegroundColor Yellow
        }

        # 3d. Silence detect
        Write-Host "       Detecting silence..." -NoNewline
        try {
            py -3.12 -c "
import json, sys
sys.path.insert(0, 'agents/edbot/tools')
from silence_detect import detect_silence
r = detect_silence('$($InputFile -replace '\\','/')')
with open(r'$outDir\silence.json', 'w', encoding='utf-8') as f:
    json.dump(r, f, indent=2, ensure_ascii=False)
pct = r.get('stats', {}).get('silence_percentage', 0)
print(f'{pct:.1f}')
" 2>$null
            Write-Host " OK" -ForegroundColor Green
        } catch {
            Write-Host " FAILED" -ForegroundColor Red
        }

        Write-Host ""
        Write-Host "       Pipeline outputs: $outDir" -ForegroundColor DarkGray
    }
}
Write-Host ""

# ---------------------------------------------------------------------------
# Step 4: Verify endpoints
# ---------------------------------------------------------------------------
Write-Host "[4/5] Verifying endpoints..." -ForegroundColor Yellow
$endpoints = @(
    @{Name="Health";     Url="http://localhost:8901/api/health"; Method="GET"},
    @{Name="Library";    Url="http://localhost:8901/api/library"; Method="GET"},
    @{Name="Chapters";   Url="http://localhost:8901/api/library/chapters"; Method="GET"},
    @{Name="Resolve";    Url="http://localhost:8901/api/resolve/status"; Method="GET"},
    @{Name="Dashboard";  Url="http://localhost:8901/frontend/index.html"; Method="GET"}
)
foreach ($ep in $endpoints) {
    try {
        $r = Invoke-WebRequest -Uri $ep.Url -Method $ep.Method -UseBasicParsing -ErrorAction Stop -TimeoutSec 5
        Write-Host "       $($ep.Name): $($r.StatusCode)" -ForegroundColor Green
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code) {
            Write-Host "       $($ep.Name): $code" -ForegroundColor Yellow
        } else {
            Write-Host "       $($ep.Name): FAIL" -ForegroundColor Red
        }
    }
}
Write-Host ""

# ---------------------------------------------------------------------------
# Step 5: Open browser
# ---------------------------------------------------------------------------
if (-not $NoBrowser) {
    Write-Host "[5/5] Opening viewers in browser..." -ForegroundColor Yellow
    Start-Process "http://localhost:8901/frontend/index.html"
    Start-Sleep 1
    Start-Process "http://localhost:8901/frontend/chapter-viewer.html"
    Start-Sleep 1
    Start-Process "http://localhost:8901/frontend/command-console.html"
    Write-Host "       Opened: Dashboard, Chapter Viewer, Command Console" -ForegroundColor Green
} else {
    Write-Host "[5/5] Browser: SKIPPED (-NoBrowser)" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Demo Ready"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Dashboard:       http://localhost:8901/frontend/index.html"
Write-Host "  Chapter Viewer:  http://localhost:8901/frontend/chapter-viewer.html"
Write-Host "  Command Console: http://localhost:8901/frontend/command-console.html"
Write-Host "  NLP Search:      http://localhost:8901/frontend/nlp-search.html"
Write-Host "  API Docs:        http://localhost:8901/docs"
Write-Host ""
Write-Host "  Hot-swap to real footage:" -ForegroundColor DarkGray
Write-Host '  $env:LIBRARY_PATH = "carol-library.json"' -ForegroundColor DarkGray
Write-Host "  Then restart server: .\scripts\ensure-server.ps1" -ForegroundColor DarkGray
Write-Host ""
