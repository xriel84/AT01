---
paths:
  - "agents/edbot/tools/transcribe*.py"
  - "agents/edbot/tools/speaker*.py"
  - "agents/edbot/tools/portrait*.py"
  - "agents/edbot/tools/*_scanner.py"
  - "agents/edbot/tools/frame_scanner.py"
  - "agents/edbot/tools/video_cataloger.py"
  - "agents/artbot/tools/*.py"
  - "gpu_check.py"
---
# ML Pipeline Rules
- Check GPU availability before ANY model loading
- Implement fallback chain: GPU float16 → int8 → medium/int8 → small/cpu
- Cache model instances — don't reload per-call
- Sequential model loading — don't hold multiple large models in VRAM simultaneously
- Release models explicitly when done: `del model` + `torch.cuda.empty_cache()`
- Log VRAM before/after model load in debug mode
