# COMMS: AT → YD
# Type: HANDOFF
# Date: 2026-02-27
# Re: Transcript → Chapter Pipeline Guide

---

## Transcript → Chapter Pipeline Guide

I've written a guide for you at `docs/YD-TRANSCRIPT-CHAPTER-GUIDE.md`.

It covers:
- All 7 transcript/chapter tools: what they accept, what they output, exact JSON schemas
- Exact curl commands to test each one (copy-paste ready)
- The P3 (chapter_detect) test procedure — your next verification target
- How the tools chain together into a full pipeline (flow diagram)
- Your hardware profile (4080 tier 1) and which tools need GPU vs CPU
- Troubleshooting section for common issues

### What to do:

1. Pull the `at` branch:
   ```powershell
   cd C:\agile-lens\edbot
   git fetch origin at
   git merge origin/at
   ```

2. Read `docs/YD-TRANSCRIPT-CHAPTER-GUIDE.md`

3. Run the P3 test procedure (section "P3 Test Procedure — chapter_detect"):
   - Start server: `py -3.12 -m uvicorn agents.edbot.server:app --port 8901`
   - Steps 1-7 are curl commands + pytest — takes ~5 minutes
   - chapter_detect is CPU-only — no GPU setup needed

4. Report results in `comms/from-yd/` on AL branch using the table format in the guide

### Key point

chapter_detect is **CPU-only** — no GPU dependency, no VRAM requirements. You're fully unblocked on P3 regardless of GPU/Ollama setup status.

### Also in this push

- `docs/YD-TRANSCRIPT-CHAPTER-GUIDE.md` — the full guide
- Previous S21 deliverables (task_routing.json v1.1, gpu_capabilities_stran.json filled, test fixes)
