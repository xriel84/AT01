# YD Claude Code Session: Machine Setup + RSC Test Media

**Date:** 2026-02-24
**Machine:** YD's workstation, Windows 11, fresh install

## Your Role
You are helping onboard YD to the EdBot pipeline on a fresh Windows machine.
AT is not available. Run YD through setup step by step.

## Hard Rules (never deviate)
- `py -3.12` only — never bare `python` or `python3`
- PowerShell only — no CMD, no Unix syntax
- `cd` to Resolve install dir before any Resolve script
- Sequential GPU only — no parallel GPU stages
- Use `polars` not `pandas` — pandas is not installed
- No Goose, no Ollama — Claude Code only
- If anything requires AT input, flag it clearly and WAIT — do not guess

## Reference Stack (AT's machine ENKI64 — match these)
| Package | Version |
|---------|---------|
| Python | 3.12.10 |
| faster-whisper | 1.2.1 |
| ultralytics | 8.4.14 |
| auto-editor | 29.3.1 |
| pysubs2 | 1.8.0 |
| soundfile | 0.13.1 |
| torch | 2.6.0+cu124 |
| FFmpeg | gyan.dev full build (libass + h264_nvenc) |
| Resolve Studio | 20.3.1.6 |

---

# PART A: MACHINE SETUP (do first)

## A0: Meeting Gates — confirm these BEFORE touching the machine
Ask YD to confirm:
1. **GPU spec** — what NVIDIA card? (determines CUDA packages)
2. **Resolve Studio license key** — does YD have it from AT or Kevin?
3. **GitHub access** — can YD clone xriel84/AT01?

If GPU is unknown or not NVIDIA: install CPU-only packages, skip CUDA deps, flag for AT.

## A1: Python 3.12
```powershell
py -3.12 --version
```
If missing: install from python.org Windows installer. Check "Add to PATH".

GATE: prints `Python 3.12.x`

## A2: FFmpeg
```powershell
ffmpeg -version
```
If missing:
1. Download gyan.dev FULL build (not essentials) from https://www.gyan.dev/ffmpeg/builds/
2. Extract to `C:\ffmpeg\`
3. Add `C:\ffmpeg\bin` to system PATH
4. Restart PowerShell

GATE:
```powershell
ffmpeg -version 2>&1 | Select-String "libass"
ffmpeg -encoders 2>&1 | Select-String "h264_nvenc"
```
`--enable-libass` MUST show. `h264_nvenc` only if NVIDIA GPU confirmed.

## A3: DaVinci Resolve Studio
1. Download Studio version from blackmagicdesign.com (NOT the free version)
2. Install with defaults
3. Activate with shared license key (from AT or Kevin — do not commit it anywhere)
4. Launch — title bar must say "DaVinci Resolve Studio"

## A4: Resolve Python API test
Resolve MUST be running for this test.
```powershell
cd "C:\Program Files\Blackmagic Design\DaVinci Resolve"
py -3.12 -c "
import sys
sys.path.append(r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr
r = dvr.scriptapp('Resolve')
print('Resolve API:', r.GetVersionString() if r else 'FAILED - check env vars')
"
```
GATE: prints `Resolve API: 20.x.x.x`

## A5: Python packages

**Install regardless of GPU:**
```powershell
py -3.12 -m pip install pysubs2 soundfile requests PyYAML polars gdown --break-system-packages
```

**Install only if NVIDIA GPU with CUDA confirmed:**
```powershell
py -3.12 -m pip install faster-whisper ultralytics auto-editor "auto-subs[transcribe]" --break-system-packages
```

**No GPU or GPU unknown — install CPU-safe subset only:**
```powershell
py -3.12 -m pip install auto-editor "auto-subs[transcribe]" --break-system-packages
# faster-whisper and ultralytics need CUDA — skip until GPU confirmed
```

## A6: Clone repo
```powershell
New-Item -ItemType Directory -Force C:\NB11
cd C:\NB11
git clone https://github.com/xriel84/AT01.git
cd AT01
py -3.12 -m pytest -v --tb=short 2>&1 | Select-Object -Last 5
```
GATE: 209 tests pass

## A7: Preflight validation — RUN THIS, PASTE FULL OUTPUT
```powershell
Write-Host "`n=== YD PREFLIGHT ===" -ForegroundColor Cyan

py -3.12 --version
ffmpeg -version 2>&1 | Select-Object -First 1
ffmpeg -version 2>&1 | Select-String "libass|nvenc"

py -3.12 -c "import pysubs2; print('pysubs2', pysubs2.VERSION)"
py -3.12 -c "import soundfile; print('soundfile', soundfile.__version__)"
py -3.12 -c "import polars; print('polars OK')"
py -3.12 -c "import gdown; print('gdown', gdown.__version__)"

# GPU packages (skip errors if no CUDA)
py -3.12 -c "from faster_whisper import WhisperModel; print('faster-whisper OK')" 2>&1
py -3.12 -c "from ultralytics import YOLO; print('YOLOv8 OK')" 2>&1
py -3.12 -c "import auto_editor; print('auto-editor OK')" 2>&1
py -3.12 -c "import autosubs; print('auto-subs OK')" 2>&1

# Resolve (must be running)
cd "C:\Program Files\Blackmagic Design\DaVinci Resolve"
py -3.12 -c "
import sys
sys.path.append(r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr
r = dvr.scriptapp('Resolve')
print('Resolve:', r.GetVersionString() if r else 'FAILED')
"

# Disk space
$freeGB = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
Write-Host "`nFree disk: ${freeGB} GB" -ForegroundColor $(if($freeGB -gt 20){"Green"}else{"Red"})

# Tests
cd C:\NB11\AT01
py -3.12 -m pytest -v --tb=short 2>&1 | Select-Object -Last 3

Write-Host "=== END PREFLIGHT ===" -ForegroundColor Cyan
```

**STOP HERE.** Evaluate preflight output before proceeding to Part B.
If any critical item fails, troubleshoot it. Do NOT proceed with media download on a broken environment.

---

# PART B: RSC TEST MEDIA (after Part A is green)

## Disk Space Check
```powershell
$freeGB = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
Write-Host "Free space: ${freeGB} GB" -ForegroundColor $(if($freeGB -gt 20){"Green"}else{"Red"})
if ($freeGB -lt 20) { Write-Host "STOP - not enough space. Tell AT." -ForegroundColor Red; return }
```

## B1: Dry run — list files WITHOUT downloading
```powershell
$MEDIA_DIR = "C:\NB11\media\in\rsc"
New-Item -ItemType Directory -Force -Path $MEDIA_DIR

py -3.12 -m gdown --folder "https://drive.google.com/drive/folders/1BPi-ncgCvg3KCBJqMZmNzgQPW0RfQVpO" --remaining-ok --no-download
```
**CHECKPOINT:** Review file list and total size. If over 15GB total, tell AT before continuing.

## B2: Download
```powershell
py -3.12 -m gdown --folder "https://drive.google.com/drive/folders/1BPi-ncgCvg3KCBJqMZmNzgQPW0RfQVpO" -O $MEDIA_DIR --remaining-ok
```
If auth/quota error: try `--no-cookies`. If still fails, stop and flag for AT.

## B3: Inventory
```powershell
Write-Host "`n=== RSC INVENTORY ===" -ForegroundColor Cyan

$videos = Get-ChildItem -Path "C:\NB11\media\in\rsc" -Recurse -Include *.mp4,*.mov,*.mkv,*.webm
$totalMB = [math]::Round(($videos | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host "Video files: $($videos.Count), Total: $totalMB MB`n"

foreach ($v in ($videos | Sort-Object Length)) {
    $mb = [math]::Round($v.Length / 1MB, 1)
    Write-Host "  $($v.Name) - $mb MB"
    ffprobe -v error -select_streams v:0 -show_entries stream=width,height,codec_name,r_frame_rate,duration -of csv=p=0 $v.FullName
}

$TEST_CLIP = ($videos | Sort-Object Length | Select-Object -First 1).FullName
Write-Host "`nTest candidate (smallest): $TEST_CLIP" -ForegroundColor Yellow
Write-Host "=== END ===" -ForegroundColor Cyan
```

---

# PART C: SMOKE TESTS (after Parts A+B green)

Use the smallest video from the RSC download as test clip.

## C0: Setup work dirs
```powershell
$TEST_CLIP = "C:\NB11\media\in\rsc\<REPLACE WITH SMALLEST VIDEO FILENAME FROM B3>"
$WORK = "C:\NB11\AT01\tests\fixtures\smoke_test"
New-Item -ItemType Directory -Force -Path "$WORK\input","$WORK\clean","$WORK\subs","$WORK\final"
Copy-Item $TEST_CLIP "$WORK\input\"
cd C:\NB11\AT01
```

## C1: Stage 5 — Silence removal (CPU only)
```powershell
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
GATE: `"processed": 1`, .mp4 exists in `$WORK\clean\`

```powershell
Get-ChildItem "$WORK\clean\*.mp4" | Select-Object Name, @{N='MB';E={[math]::Round($_.Length/1MB,1)}}
```

## C2: Stage 7 — Subtitle generation (GPU if available)
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
GATE: `*_tiktok.ass` exists with `PlayResX: 1080`, `PlayResY: 1920`, `Dialogue:` lines

```powershell
$ass = (Get-ChildItem "$WORK\subs\*_tiktok.ass" | Select-Object -First 1).FullName
Get-Content $ass | Select-Object -First 25
Get-Content $ass | Select-String "Dialogue:" | Select-Object -First 5
```

If error mentions CUDA/GPU: whisper may fall back to CPU (slower but works). Copy output either way.

## C3: Stage 8 — Subtitle burn-in (GPU for nvenc, CPU fallback OK)
```powershell
$ASS_FILE = (Get-ChildItem "$WORK\subs\*_tiktok.ass" | Select-Object -First 1).FullName

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
GATE:
```powershell
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,codec_name,r_frame_rate -of csv=p=0 "$WORK\final\test_tiktok_subbed.mp4"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK\final\test_tiktok_subbed.mp4"
```

## C4: Full report — YD copies this entire output to AT
```powershell
Write-Host "`n=== YD SMOKE TEST RESULTS ===" -ForegroundColor Cyan
Write-Host "Free space: $([math]::Round((Get-PSDrive C).Free/1GB,1)) GB"

$clean = Get-ChildItem "$WORK\clean\*.mp4" -EA SilentlyContinue
$subs = Get-ChildItem "$WORK\subs\*.ass" -EA SilentlyContinue
$final = Get-ChildItem "$WORK\final\*.mp4" -EA SilentlyContinue

Write-Host "Stage 5 (silence): $($clean.Count) clips" -ForegroundColor $(if($clean){"Green"}else{"Red"})
Write-Host "Stage 7 (subs): $($subs.Count) .ass files" -ForegroundColor $(if($subs){"Green"}else{"Red"})
Write-Host "Stage 8 (burn): $($final.Count) final clips" -ForegroundColor $(if($final){"Green"}else{"Red"})

if ($final) {
    Write-Host "`nFinal specs:"
    ffprobe -v error -select_streams v:0 -show_entries stream=width,height,codec_name,r_frame_rate -of csv=p=0 $final[0].FullName
    ffprobe -v error -show_entries format=duration -of csv=p=0 $final[0].FullName
}

Write-Host "`nTests:"
cd C:\NB11\AT01
py -3.12 -m pytest -v --tb=short 2>&1 | Select-Object -Last 3

Write-Host "=== COPY EVERYTHING ABOVE TO AT ===" -ForegroundColor Yellow
```

---

## Rules for YD
1. Parts A, B, C in order. Each depends on the previous.
2. At every GATE/CHECKPOINT: if it fails, STOP and send output to AT.
3. Do NOT commit media files to git.
4. Do NOT skip the disk space check.
5. The final report (C4) is what AT needs — copy ALL of it.
