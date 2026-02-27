# COMMS: AT → YD
# Type: HANDOFF
# Date: 2026-02-27
# Re: S18 GPU-aware orchestration + Claude→Ollama delegation

---

## Summary

Built a GPU capability config system so code auto-adapts to each machine's hardware.

- **Your 4080 (16GB) = tier 1.** My A6000 (48GB) = tier 2.
- Tests tagged `gpu_tier_2` auto-skip on your machine — no OOM, no failures.
- Task routing picks the right whisper model, Ollama model, and ML method per tier.
- Claude→Ollama delegation helper: Claude plans, Ollama executes free on local GPU, Claude evaluates.

### What Was Built

| File | Purpose |
|------|---------|
| `configs/gpu_capabilities.json` | AT/rielt machine declaration (tier 2) |
| `configs/gpu_capabilities_stran.json` | **YOUR config template — needs filling** |
| `configs/gpu_config.py` | Runtime config loader, tier/VRAM helpers |
| `configs/task_routing.json` | All tasks mapped to tier 0/1/2 configs |
| `configs/task_router.py` | Resolves task config for current machine |
| `agents/shared/ollama_delegate.py` | Claude→Ollama delegation with logging |
| `agents/shared/claude_ollama_pattern.md` | Docs on when to use Ollama vs Claude |
| `conftest.py` | pytest markers: gpu_tier_1, gpu_tier_2, vram_min |
| `tests/test_gpu_config.py` | 28 new tests (total now 1016) |

---

## Your Setup Steps

### 1. Check Ollama

```powershell
ollama list
```

Note which models you have installed.

### 2. Fill your config

Edit `configs/gpu_capabilities_stran.json`:

- Replace all `__YD_FILL__` with your actual Ollama model names from step 1
  - `max_model_for_planning` → your largest general model
  - `max_model_for_coding` → your best coder model
  - `default_worker_model` → your smallest/fastest model
- Replace `__YD_TEST__` after running the import tests in step 3
- Replace `__YD_CHECK__` / `__YD_DECIDE__` based on your local setup

### 3. Test ML imports

```powershell
py -3.12 -c "import pyannote.audio; print('pyannote OK')"
py -3.12 -c "from ultralytics import YOLO; print('yolo OK')"
py -3.12 -c "import mediapipe; print('mediapipe OK')"
```

Set `true` or `false` in your config for each result.

### 4. Run tests

```powershell
py -3.12 -m pytest tests/test_gpu_config.py -v
py -3.12 -m pytest -q
```

Expect: gpu_tier_2 marked tests skip cleanly on your machine.

### 5. Report back

Tell me: Ollama models available, ML import results, test count, any issues.

---

## What NOT To Try On Your 4080 (16GB)

| Task | Why Not |
|------|---------|
| whisper large-v3 float16 | Needs 10GB+ with overhead — use `medium` / `int8` instead |
| VACE animation | Needs 20GB+ VRAM |
| 70B Ollama models (llama3.3:70b) | Needs 42GB+ |
| ComfyUI SDXL generation | Tight/impossible on 16GB |

The config system handles all of this automatically — tasks route to your tier's best option.

---

## Claude→Ollama Pattern

Full docs: `agents/shared/claude_ollama_pattern.md`

Quick version:
- **Claude Code** = planner + orchestrator (cloud, uses tokens)
- **Ollama** = local worker (free, runs on your GPU for repetitive tasks)
- Claude calls Ollama via `agents/shared/ollama_delegate.py`, evaluates results, logs pass/fail

Use Ollama for: tag generation, small code review, report writing, repetitive formatting.
Use Claude for: architecture, multi-file refactoring, complex debugging, prompt engineering.
