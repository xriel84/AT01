# YD P3 Claude Code Prompt
# Paste this entire block into a new Claude Code session on your machine.

---

```
# YD P3 — AUTO CHAPTERS + GPU FRAMEWORK SETUP
# Machine: YD workstation (RTX 4080 16GB, Windows 11)
# Repo: C:\agile-lens\edbot | Branch: AL on AgileLens/edbot
# Date: 2026-02-27
# Prereqs: P1+P2 PASS, AT pushed GPU framework to `at` branch

## HARD RULES
1. py -3.12 | PowerShell only | [yd] commit prefix
2. Human gate on ALL outputs — show me before committing
3. Do NOT try to load large-v3 float16, 70B models, VACE, or ComfyUI SDXL on this 4080
4. This machine = GPU tier 1 (16GB). Skip tier-2 tests.
5. Branch: AL. Remote: origin (AgileLens/edbot).
6. Comms go to comms/from-yd/ — never comms/private/

## PHASE 1 — PULL GPU FRAMEWORK

```powershell
cd C:\agile-lens\edbot
git fetch origin at
git merge origin/at
```

Verify these files now exist:
- configs/gpu_config.py
- configs/gpu_capabilities_stran.json
- configs/task_routing.json
- conftest.py (root)
- tests/test_gpu_config.py

## PHASE 2 — GPU DIAGNOSTIC

Run these and paste ALL output:

```powershell
# GPU
nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version --format=csv,noheader

# Ollama
ollama list

# ML imports
py -3.12 -c "import pyannote.audio; print('pyannote OK')" 2>&1
py -3.12 -c "from ultralytics import YOLO; print('yolo OK')" 2>&1
py -3.12 -c "import mediapipe; print('mediapipe OK')" 2>&1

# GPU tier detection (should say tier 1 after config is filled)
py -3.12 -c "from configs.gpu_config import get_gpu_tier, get_vram_gb; print(f'Tier: {get_gpu_tier()}, VRAM: {get_vram_gb()}GB')" 2>&1
```

## PHASE 3 — FILL GPU CONFIG

Edit `configs/gpu_capabilities_stran.json`:
- Replace `__YD_FILL__largest_model_from_ollama_list__` with your biggest general model from `ollama list`
- Replace `__YD_FILL__best_coder_model__` with your best coder model
- Replace `__YD_FILL__smallest_fast_model__` with your fastest small model
- Replace `__YD_TEST__` values with true/false based on Phase 2 ML import results
- Replace `__YD_CHECK__` with true/false for Resolve
- Replace `__YD_DECIDE__` with 8901 or null

**SHOW ME the filled config before saving.**

## PHASE 4 — RUN TIER-FILTERED TESTS

```powershell
# GPU config tests specifically
py -3.12 -m pytest tests/test_gpu_config.py -v

# Full suite minus tier-2 tests
py -3.12 -m pytest -m "not gpu_tier_2" --tb=short -q
```

Report: total passed, total skipped, any failures.

## PHASE 5 — P3 CHAPTER DETECTION

Start the server:
```powershell
py -3.12 -m uvicorn agents.edbot.server:app --port 8901
```

Then run these in order (in a second terminal):

### P3A: Transcribe (populates session)
```bash
curl -X POST http://127.0.0.1:8901/api/transcribe -H "Content-Type: application/json" -d '{"input_path": "C:/agile-lens/edbot/test_videos/agile_test.MOV", "output_dir": "output"}'
```

### P3B: Silence detection (feeds chapter boundaries)
```bash
curl -X POST http://127.0.0.1:8901/api/silence -H "Content-Type: application/json" -d '{"input_path": "C:/agile-lens/edbot/test_videos/agile_test.MOV", "output_dir": "output"}'
```

### P3C: Chapter detection
```bash
curl http://127.0.0.1:8901/api/chapters
```

Verify:
- At least 1 chapter returned
- Each chapter has: chapter_id, start, end, duration, chunk_ids, title
- Timestamps increase monotonically
- agile_test.MOV is ~39s — expect 1-2 chapters (min duration = 30s default)

### P3F: Unit tests
```powershell
py -3.12 -m pytest tests/test_chapter_detect.py -v
```

Expected: 25 tests, 23+ pass, 2 may skip (real data fixtures).

## PHASE 6 — WRITE RESULTS

Create `comms/from-yd/2026-02-27T-p3-results.md` with:

```markdown
---
from: YD (Claude Code)
to: AT
date: 2026-02-27
re: P3 Chapter Detection + GPU Framework Results
---

# P3 Test Results

**Machine:** [your machine info]
**GPU Config:** Tier [X], [Y]GB VRAM
**Ollama Models:** [list from ollama list]
**ML Imports:** pyannote [OK/FAIL], yolo [OK/FAIL], mediapipe [OK/FAIL]

## GPU Framework Tests
- test_gpu_config.py: [X passed, Y skipped]
- Full suite (not gpu_tier_2): [X passed, Y skipped, Z failed]

## P3 Chapter Tests

| Test | Endpoint | HTTP | Result | Notes |
|------|----------|------|--------|-------|
| P3A | POST /api/transcribe | ??? | PASS/FAIL | ... |
| P3B | POST /api/silence | ??? | PASS/FAIL | ... |
| P3C | GET /api/chapters | ??? | PASS/FAIL | ... |
| P3D | (short video edge) | - | PASS/FAIL | ... |
| P3E | (no gaps edge) | - | PASS/FAIL | ... |
| P3F | pytest unit tests | - | PASS/FAIL | X pass, Y skip |

## Chapter Output (paste full JSON from P3C)
[paste here]

## Issues / Notes
[anything unexpected]
```

## PHASE 7 — COMMIT + PUSH

```powershell
git add configs/gpu_capabilities_stran.json comms/from-yd/2026-02-27T-p3-results.md
git status  # review — no secrets, no private paths
git commit -m "[yd] P3 test results — chapters + GPU framework"
git push origin AL
```

## DO NOT
- Load whisper large-v3 float16 (use medium/int8 on your 4080)
- Try 70B Ollama models (need 42GB+)
- Run ComfyUI SDXL or VACE (need 24GB+)
- Modify AT01 code or push to `at` branch
- Commit secrets or credential files
```

---

# Instructions for YD
Copy everything between the triple-backtick fences above and paste it as your
first message in a fresh Claude Code session. Claude will walk you through each
phase with human gates at every step.
