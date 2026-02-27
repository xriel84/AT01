---
paths:
  - "agents/edbot/tools/*video*.py"
  - "agents/edbot/tools/*audio*.py"
  - "agents/edbot/tools/*silence*.py"
  - "agents/edbot/tools/*format*.py"
  - "agents/edbot/tools/*tiktok*.py"
---
# FFmpeg Rules
- Use `ffmpeg-python` wrapper, NEVER raw subprocess
- Always `ffmpeg.probe()` before processing (validate input exists and is readable)
- Use `.overwrite_output()` explicitly — never implicit overwrite
- Hardware acceleration: `.global_args('-hwaccel', 'cuda')` when available
- Verify output file exists and `size > 0` after processing
