# COMMS: AT -> YD
# Type: HANDOFF
# Date: 2026-02-27
# Re: P3 — Auto Chapters + GPU Framework Setup

---

## Part A: GPU Framework Setup (one-time)

S18 shipped a GPU config system. Your 4080 = tier 1, my A6000 = tier 2.
Tests tagged `gpu_tier_2` auto-skip on your machine.

### A1. Pull the `at` branch

```powershell
cd C:\agile-lens\edbot
git fetch origin at
git merge origin/at
```

### A2. GPU config — PRE-FILLED (S19)

Your `configs/gpu_capabilities_stran.json` is now **fully filled** with your confirmed specs:
- GPU: NVIDIA RTX 4080 16GB, CUDA 13.1, driver 591.74
- Ollama models: llama3.1:8b, mistral-nemo, nomic-embed-text, qwen2.5-coder:14b
- Planning model: mistral-nemo | Coding model: qwen2.5-coder:14b | Worker: llama3.1:8b
- ML: whisper medium/int8, pyannote true, yolo true, mediapipe true
- Services: ollama 11434, edbot_api 8901, resolve true

**No placeholders remain.** After pulling, just verify the config loads:

```powershell
py -3.12 -c "from configs.gpu_config import get_gpu_tier, get_vram_gb; print(f'Tier: {get_gpu_tier()}, VRAM: {get_vram_gb()}GB')"
```

Expected output: `Tier: 1, VRAM: 16GB`

If pyannote or yolo don't actually work on your setup, update the `ml_capabilities` section to `false` for those.

### A3. Test ML imports

```powershell
py -3.12 -c "import pyannote.audio; print('pyannote OK')"
py -3.12 -c "from ultralytics import YOLO; print('yolo OK')"
py -3.12 -c "import mediapipe; print('mediapipe OK')"
```

### A4. Run tier-filtered tests

```powershell
py -3.12 -m pytest tests/test_gpu_config.py -v
py -3.12 -m pytest -m "not gpu_tier_2" --tb=short -q
```

The `-m "not gpu_tier_2"` flag skips AT-only tests. Everything else should pass.

---

## Part A2: Ollama Cross-Machine Setup

### For YD to reach AT's Ollama (AT already configured):

```powershell
curl http://192.168.1.115:11434/api/tags
```

Should return 9 models. If fails: AT's VPN may need reconnect with LAN enabled.

### For AT to reach YD's Ollama (YD needs to configure):

Currently AT cannot reach your Ollama (tested 2026-02-27, connection timed out).
Your Ollama is likely bound to 127.0.0.1 instead of 0.0.0.0.

**Fix — run these on your machine (DESKTOP-BD76CV3):**

```powershell
# Set machine-level env var to bind Ollama to all interfaces:
[System.Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0", "Machine")

# Restart Ollama (close tray icon, relaunch — or reboot)

# Verify it's binding correctly:
netstat -an | findstr "11434"
# Must show 0.0.0.0:11434, NOT 127.0.0.1:11434
```

**Windows Firewall (if netstat shows 0.0.0.0 but AT still can't connect):**

```powershell
# Run as Administrator:
New-NetFirewallRule -DisplayName "Ollama LAN" -Direction Inbound -Protocol TCP -LocalPort 11434 -Action Allow
```

**Test from your machine that AT can see you:**

```powershell
curl http://192.168.1.151:11434/api/tags
```

Once both directions work, we can route Ollama tasks cross-machine via task_router.

---

## Part B: P3 Chapter Detection Tests

**Prerequisite:** Server must be running.

```powershell
py -3.12 -m uvicorn agents.edbot.server:app --port 8901
```

### P3A. Transcribe a test video (prerequisite for chapters)

You already did this in P1. Run it again to populate the session:

```bash
curl -X POST http://127.0.0.1:8901/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"input_path": "C:/agile-lens/edbot/test_videos/agile_test.MOV", "output_dir": "output"}'
```

Expected: 200 OK, chunks in response.

### P3B. Run silence detection (feeds chapter boundaries)

```bash
curl -X POST http://127.0.0.1:8901/api/silence \
  -H "Content-Type: application/json" \
  -d '{"input_path": "C:/agile-lens/edbot/test_videos/agile_test.MOV", "output_dir": "output"}'
```

Expected: 200 OK, silence_map with gaps array.

### P3C. Run chapter detection

```bash
curl http://127.0.0.1:8901/api/chapters
```

Expected: 200 OK, JSON with `chapters` array. Each chapter has:
- `chapter_id` (int, sequential from 0)
- `start` / `end` (float, seconds)
- `duration` (float, seconds)
- `chunk_ids` (list of int)
- `title` (string, first ~8 words of speech)

Verify:
- [ ] At least 1 chapter returned
- [ ] Timestamps are monotonically increasing
- [ ] All chunk IDs from transcription appear in exactly one chapter
- [ ] Titles contain recognizable words from the video
- [ ] `duration` = `end - start` for each chapter

### P3D. Edge case: short video (<2 min)

Your agile_test.MOV is ~39 seconds. This IS the short video test.
Expected: 1-2 chapters max (the min_chapter_duration default is 30s).

### P3E. Edge case: no silence gaps

If P3B returned zero gaps, P3C should still return at least 1 chapter
(falls back to chunk silence_ratio boundaries).

### P3F. Run chapter_detect unit tests

```powershell
py -3.12 -m pytest tests/test_chapter_detect.py -v
```

Expected: 25 tests pass (23 synthetic + 2 real-data that skip if no test files).

---

## Part C: Feedback Format

Write your results to: `comms/from-yd/2026-02-27T-p3-results.md` on the AL branch.

Include for each test:
```
| Test | Endpoint | HTTP | Result | Notes |
|------|----------|------|--------|-------|
| P3A  | POST /api/transcribe | ??? | PASS/FAIL | ... |
| P3B  | POST /api/silence | ??? | PASS/FAIL | ... |
| P3C  | GET /api/chapters | ??? | PASS/FAIL | ... |
| P3D  | (edge: short video) | - | PASS/FAIL | ... |
| P3E  | (edge: no gaps) | - | PASS/FAIL | ... |
| P3F  | pytest unit tests | - | PASS/FAIL | X passed, Y skipped |
```

Also include:
- GPU config values you filled in (your Ollama models, ML import results)
- Full test count from `py -3.12 -m pytest -m "not gpu_tier_2" -q`
- Any tier-skip surprises (tests that skipped but you expected to run)
- YD P1 feedback items status (index build gap, search text enhancement)

Commit with: `[yd] P3 test results — chapters + GPU framework`
Push to: `AL` branch on AgileLens/edbot
