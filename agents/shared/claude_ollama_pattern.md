# Claude<->Ollama Delegation Pattern

## Architecture

```
YOU (human) -> Claude Code CLI (plans + evaluates) -> Ollama (local GPU, executes free)
```

Claude Code is the brain. Ollama is the hands.

## When Ollama (free) vs Claude (tokens)

| Task | Use Ollama | Use Claude |
|------|-----------|------------|
| Tag generation from transcript | Yes | |
| Code review (small file) | Yes | |
| Report narrative writing | Yes | |
| Repetitive format tasks | Yes | |
| Architecture decisions | | Yes |
| Multi-file refactoring | | Yes |
| Complex debugging | | Yes |
| Prompt engineering | | Yes |

## GPU Tier Reference

| Tier | Machine | VRAM | Ollama | Whisper | Special |
|------|---------|------|--------|---------|---------|
| 2 | AT/rielt | 48GB | 70B, 32B, 12B | large-v3 fp16 | VACE, ComfyUI, Resolve |
| 1 | YD/stran | 16GB | 14B, 12B | medium int8 | YOLO, pyannote |
| 0 | CPU only | 0 | None | small CPU | Nothing |

## Running Tests

```powershell
# Full suite — tier-2 tests auto-skip on tier-1 machines
py -3.12 -m pytest -q

# See what skips on your machine
py -3.12 -m pytest -q -m "gpu_tier_2" --co

# Only tests your GPU can handle
py -3.12 -m pytest -q -m "not gpu_tier_2"
```

## YD Setup

1. `ollama list` — note models
2. Edit `configs/gpu_capabilities_stran.json` — fill `__YD_*__` fields
3. `py -3.12 -m pytest tests/test_gpu_config.py -v` — verify
4. `py -3.12 -m pytest -q` — full suite, check tier-2 skips
