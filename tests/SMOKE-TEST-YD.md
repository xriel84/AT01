# YD Smoke Test — EdBot Stages 5/7/8 with RSC Media

**Machine:** YD's workstation, Windows 11, PowerShell, Python 3.12
**Repo:** Clone of xriel84/AT01
**Date:** 2026-02-24

> **DISK SPACE WARNING**
> The RSC Google Drive folder may contain several GB of video.
> Before downloading, check your free space:
> ```powershell
> Get-PSDrive C | Select-Object @{N='FreeGB';E={[math]::Round($_.Free/1GB,1)}}
> ```
> You need at LEAST 20GB free (raw video + processed copies).
> If under 20GB: STOP and tell AT before downloading.

## Rules
- `py -3.12` only — never bare `python`
- PowerShell only — no CMD
- Do NOT touch `C:\NB10\`
- Do NOT commit media files to git
- If anything fails: copy the full error, stop, paste to AT

---

## TEST 0: Preflight — run this FIRST

```powershell
Write-Host "`n=== YD PREFLIGHT ===" -ForegroundColor Cyan

# Disk space
$freeGB = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
Write-Host "Free disk space: ${freeGB} GB" -ForegroundColor $(if($freeGB -gt 20){"Green"}else{"Red"})
if ($freeGB -lt 20) { Write-Host "STOP — tell AT you need more disk space" -ForegroundColor Red; return }

# Repo
cd C:\NB11\AT01
git status
py -3.12 -m pytest -v --tb=short 2>&1 | Select-Object -Last 3

# Deps
py -3.12 -c "import pysubs2, soundfile; print('deps OK')"
auto-editor --version
ffmpeg -version 2>&1 | Select-Object -First 1

Write-Host "=== END PREFLIGHT ===" -ForegroundColor Cyan
```

**GATE:** 209 tests pass, deps OK, 20+ GB free. If not, stop and report to AT.

---

## TEST 1: Download RSC Media

```powershell
py -3.12 -m pip install gdown --break-system-packages

$MEDIA_DIR = "C:\NB11\media\in\rsc"
New-Item -ItemType Directory -Force -Path $MEDIA_DIR

# DRY RUN FIRST — list files without downloading
py -3.12 -m gdown --folder "https://drive.google.com/drive/folders/1BPi-ncgCvg3KCBJqMZmNzgQPW0RfQVpO" --remaining-ok --no-download
```

**CHECKPOINT:** Review the file list. Note total size. If over 15GB, tell AT before continuing.

```powershell
# ACTUAL DOWNLOAD — only after confirming size is OK
py -3.12 -m gdown --folder "https://drive.google.com/drive/folders/1BPi-ncgCvg3KCBJqMZmNzgQPW0RfQVpO" -O $MEDIA_DIR --remaining-ok
```

If gdown fails (auth/quota), try adding `--no-cookies`. If still fails, stop and tell AT.

---

## TEST 2: Inventory — what did we get?

```powershell
Write-Host "`n=== RSC INVENTORY ===" -ForegroundColor Cyan

$videos = Get-ChildItem -Path "C:\NB11\media\in\rsc" -Recurse -Include *.mp4,*.mov,*.mkv,*.webm
$totalMB = [math]::Round(($videos | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host "Video files: $($videos.Count), Total: $totalMB MB`n"

foreach ($v in ($videos | Sort-Object Length)) {
    $mb = [math]::Round($v.Length / 1MB, 1)
    Write-Host "  $($v.Name) — $mb MB"
    ffprobe -v error -select_streams v:0 -show_entries stream=width,height,codec_name,r_frame_rate,duration -of csv=p=0 $v.FullName
}

# Pick smallest clip with speech as test candidate
$TEST_CLIP = ($videos | Sort-Object Length | Select-Object -First 1).FullName
Write-Host "`nSmallest clip (test candidate): $TEST_CLIP" -ForegroundColor Yellow
Write-Host "=== END INVENTORY ===" -ForegroundColor Cyan
```

**CHECKPOINT:** Copy the inventory output. If no .mp4 files found, stop and tell AT.

---

## TEST 3: Stage 5 — Silence Removal (CPU only, safe)

```powershell
$TEST_CLIP = "C:\NB11\media\in\rsc\<REPLACE WITH SMALLEST VIDEO FILENAME>"
$WORK = "C:\NB11\AT01\tests\fixtures\smoke_test"
New-Item -ItemType Directory -Force -Path "$WORK\input", "$WORK\clean"

# Copy single test clip to input dir
Copy-Item $TEST_CLIP "$WORK\input\"

cd C:\NB11\AT01
py -3.12 -c "
from pathlib import Path
from agents.edbot.tools.silence_remove import remove_silence
import json
result = remove_silence(
    input_dir=Path(r'$WORK\input'),
    output_dir=Path(r'$WORK\clean'),
    platform='tiktok'
)
print(json.dumps(result, indent=2))
"
```

**GATE:** Output shows `"processed": 1`. A .mp4 exists in `$WORK\clean\`.
If error: copy full output, stop, send to AT.

```powershell
# Quick check
Get-ChildItem "$WORK\clean\*.mp4" | Select-Object Name, @{N='MB';E={[math]::Round($_.Length/1MB,1)}}
```

---

## TEST 4: Stage 7 — Subtitle Generation (uses GPU for whisper)

```powershell
$CLEAN_CLIP = (Get-ChildItem "$WORK\clean\*.mp4" | Select-Object -First 1).FullName

py -3.12 -c "
from pathlib import Path
from agents.edbot.tools.subtitle_gen import generate_all_platforms
generate_all_platforms(
    clip_path=Path(r'$CLEAN_CLIP'),
    output_dir=Path(r'$WORK\subs'),
    platforms=['tiktok']
)
"
```

**GATE:** `$WORK\subs\*_tiktok.ass` exists.

```powershell
# Inspect the .ass file
$ass = (Get-ChildItem "$WORK\subs\*_tiktok.ass" | Select-Object -First 1).FullName
Write-Host "`n=== ASS HEADER ===" -ForegroundColor Cyan
Get-Content $ass | Select-Object -First 25
Write-Host "`n=== FIRST 5 DIALOGUE LINES ===" -ForegroundColor Cyan
Get-Content $ass | Select-String "Dialogue:" | Select-Object -First 5
```

If error mentions CUDA/GPU: that's OK, whisper may fall back to CPU (slower but works). Copy output either way.

---

## TEST 5: Stage 8 — Subtitle Burn-in (uses GPU for h264_nvenc)

```powershell
$ASS_FILE = (Get-ChildItem "$WORK\subs\*_tiktok.ass" | Select-Object -First 1).FullName
New-Item -ItemType Directory -Force -Path "$WORK\final"

py -3.12 -c "
from pathlib import Path
from agents.edbot.tools.subtitle_burn import burn_subtitle
result = burn_subtitle(
    input_path=Path(r'$CLEAN_CLIP'),
    ass_path=Path(r'$ASS_FILE'),
    output_path=Path(r'$WORK\final\test_tiktok_subbed.mp4')
)
print(result)
"
```

**GATE:** `$WORK\final\test_tiktok_subbed.mp4` exists.

```powershell
# Validate output
Write-Host "`n=== FFPROBE ===" -ForegroundColor Cyan
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,codec_name,r_frame_rate -of csv=p=0 "$WORK\final\test_tiktok_subbed.mp4"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK\final\test_tiktok_subbed.mp4"
```

---

## TEST 6: Summary Report — copy this entire block to AT

```powershell
Write-Host "`n=== YD SMOKE TEST RESULTS ===" -ForegroundColor Cyan

# Disk
Write-Host "Free space remaining: $([math]::Round((Get-PSDrive C).Free/1GB,1)) GB"

# Stage 5
$clean = Get-ChildItem "$WORK\clean\*.mp4" -ErrorAction SilentlyContinue
Write-Host "Stage 5 (silence): $($clean.Count) clips" -ForegroundColor $(if($clean){"Green"}else{"Red"})

# Stage 7
$subs = Get-ChildItem "$WORK\subs\*.ass" -ErrorAction SilentlyContinue
Write-Host "Stage 7 (subs): $($subs.Count) .ass files" -ForegroundColor $(if($subs){"Green"}else{"Red"})

# Stage 8
$final = Get-ChildItem "$WORK\final\*.mp4" -ErrorAction SilentlyContinue
Write-Host "Stage 8 (burn): $($final.Count) final clips" -ForegroundColor $(if($final){"Green"}else{"Red"})

if ($final) {
    Write-Host "`nFinal output specs:"
    ffprobe -v error -select_streams v:0 -show_entries stream=width,height,codec_name,r_frame_rate -of csv=p=0 $final[0].FullName
    ffprobe -v error -show_entries format=duration -of csv=p=0 $final[0].FullName
}

# Tests still green?
Write-Host "`nRegression check:"
py -3.12 -m pytest -v --tb=short 2>&1 | Select-Object -Last 3

Write-Host "=== COPY EVERYTHING ABOVE THIS LINE TO AT ===" -ForegroundColor Yellow
```

---

## Rules for YD

1. Run tests in order (0 through 6). Each test depends on the previous.
2. At every GATE/CHECKPOINT: if it fails, STOP and send output to AT.
3. Do NOT commit media files to git.
4. Do NOT skip the disk space check.
5. The final report (Test 6) is what AT needs — copy all of it.
