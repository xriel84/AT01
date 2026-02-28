# COMMS: AT01 → YD
# Type: STATUS
# Date: 2026-02-28
# Session: S23

---

## S23: Frontend↔Backend Wiring Complete

### What Changed

**Phase 1 — URL Rewrites (at-command-console.html)**
- `/task` → `/api/resolve/command` (POST, 2 call sites)
- `/resolve/state` → `/api/resolve/status` (GET)
- `/docs` hardcoded absolute → relative `/docs`
- Removed `DEV_SERVER` dead variable, `BRIDGE_PORT` from fetch URLs
- Fixed decision payloads: now send `{decisions, mode}` instead of `{command, agent, decisions}` — prevents server taking NLP path for pre-built decisions

**Phase 2 — SSE → WebSocket (at-command-console.html)**
- Removed EventSource (`/stream/{id}`) — server has no SSE endpoint
- Command results now rendered directly from POST response (plan, results, details)
- Added global WebSocket connection to `/ws/progress` for pipeline progress events
- WS auto-connects when bridge is live, disconnects when not
- Graceful fallback: if WS fails, console still works (no live progress only)

**Phase 3 — Static File Serving (server.py + 2 viewers)**
- Added `/static/` mount → `agents/edbot/static/` (serves JSON, assets)
- Added `/frontend/` mount → same dir with `html=True` (serves HTML tools via browser)
- Updated `at-dialogue-matcher.html` + `yd-chapter-nav.html` default library URL → `/static/yd-library.json`
- `?library=` param override still works in both viewers
- Note: `yd-library.json` returns 404 until library generator runs — viewers handle this gracefully

### Commits
- `be619ac` — S23P1: rewire console fetch URLs to server routes
- `000d360` — S23P2: replace SSE with WebSocket + direct response rendering
- `9f80cfc` — S23P3: add static file mounts + update library defaults

### Test Results
- 1134 total tests, 0 regressions
- 1 pre-existing live Resolve test failure (infra-dependent, not related)

### Frontend Access (new)
All 3 HTML tools now accessible via browser at `:8901`:
- `http://localhost:8901/frontend/at-command-console.html`
- `http://localhost:8901/frontend/at-dialogue-matcher.html`
- `http://localhost:8901/frontend/yd-chapter-nav.html`

### Known Gap
- `yd-library.json` lives in `output/` when generated, but `/static/` mount points to `agents/edbot/static/`. Library generator output path or a symlink needed to bridge this.
