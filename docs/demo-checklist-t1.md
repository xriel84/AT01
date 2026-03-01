# T1 Demo Checklist — Boss Presentation 2026-03-17

## Pre-Demo Setup (30 min before)

- [ ] ENKI64 powered on, logged in as /rielt
- [ ] Resolve Studio open with Carol project loaded
- [ ] No other GPU-heavy processes (ComfyUI, Ollama large models)
- [ ] Browser open, bookmarks ready

## Server

- [ ] Run `.\scripts\ensure-server.ps1` — verify "Server ready on :8901"
- [ ] Verify: `http://localhost:8901/docs` loads Swagger UI
- [ ] Verify: `http://localhost:8901/api/resolve/status` shows `available: true`

## Data

- [ ] Carol footage in `C:\AT01\input\`
- [ ] Library JSON generated: `agents/edbot/static/carol-library.json`
- [ ] `LIBRARY_PATH` env var set to `carol-library.json` (or library placed as default)
- [ ] DEMO MODE banner NOT showing (confirms real data loaded)

## Demo Flow

### Screen 1: Dashboard (2 min)
- [ ] Open `http://localhost:8901/frontend/index.html`
- [ ] All 3 status dots green (Server, Resolve, Library)
- [ ] Walk through: "This is the AI pipeline dashboard"

### Screen 2: NLP Search (3 min)
- [ ] Open NLP Search from dashboard
- [ ] Search for a topic from Carol footage (e.g., "ghost", "Christmas morning")
- [ ] Show highlighted matches with timecodes
- [ ] Click a result — navigates to Chapter Viewer

### Screen 3: Chapter Viewer (3 min)
- [ ] Show file tabs — Carol footage entries
- [ ] Show timeline bar with chapter boundaries
- [ ] Click a chapter — show details (title, timecodes, segment count)
- [ ] Use filter to narrow chapters
- [ ] "These chapters were detected automatically from the transcript"

### Screen 4: Command Console (3 min)
- [ ] Open Command Console from dashboard
- [ ] Click preset: "Add chapter markers to timeline"
- [ ] Show dry-run result — edit decisions JSON
- [ ] "These are the exact markers that would be placed in Resolve"
- [ ] If Resolve is live: execute one marker placement, show in Resolve UI

### Screen 5: Resolve (2 min, if live)
- [ ] Show timeline with AI-placed chapter markers
- [ ] Show clip colors (if speaker color-coding was run)
- [ ] "From raw footage to structured timeline with zero manual work"

## Fallback Plans

- [ ] If Resolve won't connect: demo in DRY-RUN mode, show JSON output
- [ ] If Carol footage not ready: use demo data (DEMO MODE banner visible)
- [ ] If server crashes: `.\scripts\ensure-server.ps1` restarts in <10s
- [ ] If search returns no results: use known-good demo queries from presets

## One-Click Demo Runner

```powershell
.\scripts\demo-pipeline.ps1 -LibraryPath "carol-library.json"
```

Or with demo data:
```powershell
.\scripts\demo-pipeline.ps1
```

## Post-Demo

- [ ] Note feedback from boss
- [ ] Record which demos landed best
- [ ] Record any feature requests
- [ ] PLACEHOLDER: [Ari's notes from meeting]

## Technical Notes

- Server: FastAPI on :8901, started via ensure-server.ps1
- Library hot-swap: set `LIBRARY_PATH` env var, restart server
- All viewers are self-contained HTML — no build step, no npm
- Resolve IPC is serialized (not thread-safe) — one command at a time
- Pipeline outputs go to `C:\AT01\output\demo-run\`
