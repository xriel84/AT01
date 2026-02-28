---
from: AT01 (AriBot)
to: YD
date: 2026-02-27
re: P3 library generator + encoding fix + test procedure
---

# P3 Ready — Library Generator + Encoding Fix

## Pull First

```powershell
git pull origin main
```

## Question A: Install requirements.txt?

**YES.** Run:

```powershell
py -3.12 -m pip install -r requirements.txt
```

This gets you fastapi, pysubs2, and other deps. torch/torchaudio must be
installed separately if you want GPU transcription:

```powershell
py -3.12 -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

## Question B: Encoding fixed?

**YES.** All `open()` text calls across the codebase now include
`encoding='utf-8'`. The 3 `UnicodeDecodeError` failures on Chinese-locale
Windows should be resolved. Verify:

```powershell
py -3.12 -m pytest tests/test_gpu_config.py -v
```

All 28 tests should pass (previously 3 failed with gbk errors).

## GPU Config Renamed

`configs/gpu_capabilities_stran.json` is now `configs/gpu_capabilities_yd.json`.
Same contents, just a clearer name. Auto-detection still works — non-ENKI
machines load this file automatically.

## Generate Your Video Library

The chapter nav viewer needs a library JSON file. Generate one from your
test videos:

```powershell
py -3.12 -m agents.edbot.tools.library_generator `
    --input "D:\Videos\UnrealInterviewMix" `
    --output "agents\edbot\static\yd-library.json"
```

Replace the path with wherever your test videos live. It will:
1. Scan recursively for .mp4/.mov/.avi/.mkv/.webm files
2. Run ffprobe on each for duration/resolution/codec
3. Load any existing `*_chunks.json` transcript files alongside videos
4. Output a JSON file the viewer can read

If you want transcripts in the library (needed for chapter detection),
first run the transcription pipeline on your videos, then re-run the
generator so it picks up the chunks files.

## Serve and Test the Viewer

```powershell
cd agents\edbot\static
py -3.12 -m http.server 8080
```

Then open: `http://localhost:8080/yd-chapter-nav.html`

The viewer auto-loads `yd-library.json` from the same directory. You can
also use a URL param: `?library=my-other-file.json` or drag-and-drop any
library JSON onto the drop zone.

## P3 Test Checklist

Run through these in order:

1. [ ] Pull latest: `git pull origin main`
2. [ ] Install deps: `py -3.12 -m pip install -r requirements.txt`
3. [ ] Run GPU config tests: `py -3.12 -m pytest tests/test_gpu_config.py -v` (28 pass, 0 fail)
4. [ ] Run chapter tests: `py -3.12 -m pytest tests/test_chapter_detect.py -v` (31 pass)
5. [ ] Run library gen tests: `py -3.12 -m pytest tests/test_library_generator.py -v` (15 pass)
6. [ ] Generate library from your test videos (command above)
7. [ ] Serve static dir at :8080
8. [ ] Open viewer in Chrome
9. [ ] Select a clip from dropdown — chapters should auto-detect
10. [ ] Try search — type a keyword, cards filter, amber highlights
11. [ ] Expand a chapter card — verify snippet text
12. [ ] Export single chapter EDL — download should trigger
13. [ ] Export single chapter markers — JSON download
14. [ ] Export all chapters EDL (top bar button)
15. [ ] Adjust min gap slider — chapter count should change

## Reporting Results

Write your results to `comms/from-yd/2026-02-27T-p3-results.md` on the
`at` branch, then push.

Include: pass/fail per step, any errors, screenshots if relevant.

```powershell
git add comms/from-yd/
git commit -m "[yd] P3 test results"
git push origin at
```
