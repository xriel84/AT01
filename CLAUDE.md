# AT01 — AriBot Context

## WHAT
- AriBot. GitHub: xriel84. Public repo.
- Remotes: `origin` = xriel84/AT01 | `agilelens` = AgileLens/edbot (`at` branch)
- Python 3.12.10, FastAPI :8901, Pydantic v2, uvicorn
- 27 EdBot tools | 7 ArtBot tools | 50 endpoints | 988 tests
- ML: faster-whisper, pyannote-audio, ultralytics YOLO11, mediapipe
- FFmpeg (via ffmpeg-python wrapper) | ComfyUI :8188 | Resolve Studio 20.3.1.6 (pybmd)
- Node.js: al_asset_bridge.js, al_review_server.js :3456, al_gen.js
- ENKI64: RTX A6000 48GB | 128GB RAM | Win11 | C:\AT01 | C:\JP01

## WHY
- faster-whisper over openai-whisper: CTranslate2 backend, 4x faster
- ffmpeg-python over subprocess: structured filter chains, error handling
- GPU fallback chain: float16 → int8 → medium/int8 → small/cpu (no crashes)
- JSON message bus (agents/shared/*.json) over direct IPC: independent agent dev
- FastMCP over raw MCP SDK: simpler registration, stdio transport

## HOW

### Shell
PowerShell only. No CMD. No Unix. `py -3.12` — never bare `python`.

### Commands
- Tests: `py -3.12 -m pytest [path] -q`
- Server: `py -3.12 -m uvicorn agents.edbot.server:app --port 8901`
- Preflight: `gh auth switch --user xriel84 && gh auth status`
- Pull: `git pull origin main` before ANY work

### Verification (after ANY change)
- Tool change → `py -3.12 -m pytest agents/edbot/tests/ -q`
- ArtBot change → `py -3.12 -m pytest agents/artbot/tests/ -q`
- Server/endpoint change → `py -3.12 -m pytest tests/ -q`
- Test count must NOT decrease. Current: 988.

### Commits
- Prefix: `[aribot]`
- Pull before work. Push comms before code push.

### Comms (AT ↔ JP — local only, NEVER committed)
- Inbox: `comms/private/jp-to-at/` | Outbox: `comms/private/at-to-jp/`
- Check JP: `Get-ChildItem C:\JP01\comms\at\ -Filter *.md 2>$null`
- Check AT: `Get-ChildItem .\comms\private\jp-to-at\ -Filter *.md`
- Filename: `{YYYY-MM-DD}T{HH-MM}-at-{slug}.md` with YAML frontmatter

### Session Start
1. `gh auth status` → must show xriel84
2. Check JP inbox + AT inbox
3. Read new messages before starting
4. `git pull origin main`

---

## SECURITY (non-negotiable)

| Direction | Rule |
|-----------|------|
| AT → JP01 filesystem | READ allowed for coordination |
| AT → public output | BLOCKED — no JP01 paths, no NewEccentric refs, no credentials, no jp_ content |
| Sam → AT01 | Slack only. No repo access. |
| Sam → JP01 | **ZERO. EVER.** |

### Style Firewall
| Prefix | Repo | Style | ComfyUI output |
|--------|------|-------|----------------|
| `at_` | AT01 | Art Deco | output/at/ |
| `jp_` | JP01 | Steampunk | output/jp/ |

No cross-contamination. Bridge branches only exception.

---

## PITFALLS (things Claude Code gets wrong)

- `pyannote-audio`: requires HF_TOKEN env var set BEFORE import
- `faster-whisper`: model loading ~10s — cache instance, don't reload per-call
- `mediapipe`: CPU-ONLY on desktop Python (15-25 FPS) — no GPU acceleration
- `pybmd`/Resolve: must be running + env vars set at USER level (not system)
- FFmpeg: ALWAYS use `ffmpeg-python` wrapper, never raw `subprocess`
- VACE I2V: 512x512 ONLY — 1024 causes OOM on 48GB A6000
- Resolve API: NOT thread-safe — serialize all IPC calls through queue
- Resolve API: CANNOT trim/split/retime clips, no color control, no playback, no effects
- `[PLACEHOLDER: ADD PITFALLS AS YOU DISCOVER THEM]`

---

## REFERENCES
- Endpoint inventory: @docs/API.md
- `[PLACEHOLDER: @agents/edbot/README.md — create if useful]`
- `[PLACEHOLDER: @agents/artbot/README.md — create if useful]`
- `[PLACEHOLDER: @docs/message-bus-spec.md — document IPC schema if needed]`
