# AT01 — AriBot Context

## Identity
AriBot. GitHub: xriel84. Public repo for EdBot resolve-tools collaboration.

## Remotes
- `origin` = xriel84/AT01 (public)
- `agilelens` = AgileLens/edbot (collaboration — `at` branch)

## Shell
PowerShell only. No CMD. No Unix.
Use `py -3.12` — never bare `python`.

## Scope
- EdBot pipeline: transcription, silence detection, chapters, speakers, portrait crop, TikTok chunks, Resolve bridge, analytics reader, benchmarks
- 27 edbot tools | 7 artbot tools | 50 endpoints | FastAPI :8901 | 988 tests
- Collaboration with YD via AgileLens/edbot (`at` branch pushes, `AL` branch is YD's)
- JP01 coordination via comms/private/ local-only channel

## Rules
- Pull before starting. Always.
- Commits prefixed with `[aribot]`
- Never reference JP01 private details in public commits, PRs, or Slack

## Preflight
Before ANY work, verify correct GitHub account:
```powershell
gh auth switch --user xriel84
gh auth status
```
MUST show: `Logged in to github.com account xriel84`

---

## AT01 ↔ JP01 SECURITY MODEL

### Ownership
AT01 and JP01 are BOTH Ari's accounts. Same owner, different visibility levels.
- AT01 (xriel84) = PUBLIC. Anyone can see it.
- JP01 (NewEccentric) = PRIVATE. Personal creative work, credentials, channel identity.

### Access Rules

| Direction | Access | Rule |
|-----------|--------|------|
| AT → JP01 filesystem | **READ allowed** | AT (Claude Code on /rielt) CAN read C:\JP01 for coordination |
| AT → JP01 content in public output | **BLOCKED** | AT must NEVER leak JP private details into public commits, Slack, PRs |
| JP → AT01 | **FULL ACCESS** | JP can read/write anything on AT01 (it's public, same owner) |
| Sam → AT01 | **Slack only** | Sam interacts via Slack public channels. No repo access. |
| Sam → JP01 | **ZERO. EVER.** | Sam has no awareness of JP01 internals. Non-negotiable. |

### What AT validates before any public output
1. No JP01 file paths (C:\JP01\...) in commits or messages
2. No NewEccentric account references in public materials
3. No YouTube OAuth tokens, credentials, or channel data
4. No jp_ prefixed content or steampunk styling in AT01 code
5. No personal/private creative work from JP01

### AT as security shield
AT01 is the public-facing layer. All shared libraries, agent infrastructure, and collaborative tooling live here. AT acts as a filter — JP01 data can flow INTO AT for coordination purposes, but AT is responsible for ensuring nothing private flows OUT to public surfaces.

---

## Private Comms (AT ↔ JP)

Local-only channel. NEVER committed or pushed to remote.

- Inbox (from JP): `comms/private/jp-to-at/`
- Outbox (to JP): `comms/private/at-to-jp/`
- Check inbox: `Get-ChildItem .\comms\private\jp-to-at\ -Filter *.md | Sort-Object Name`
- Read latest: `Get-ChildItem .\comms\private\jp-to-at\ -Filter *.md | Sort-Object Name | Select-Object -Last 1 | Get-Content`

### Writing a message
Filename: `{YYYY-MM-DD}T{HH-MM}-at-{slug}.md`
Always include YAML frontmatter (from, to, date, re).
Never edit or delete sent messages.

### Reading JP comms from JP01
```powershell
# AT CAN read JP01 comms directly for coordination
Get-ChildItem C:\JP01\comms\at\ -Filter *.md | Sort-Object Name
# Then copy to AT inbox for processing
Copy-Item "C:\JP01\comms\at\{filename}" "C:\AT01\comms\private\jp-to-at\{filename}"
```

---

## Session Start Checklist
1. `gh auth status` — must show xriel84
2. Check JP inbox: `Get-ChildItem C:\JP01\comms\at\ -Filter *.md 2>$null`
3. Check AT inbox: `Get-ChildItem .\comms\private\jp-to-at\ -Filter *.md`
4. If new messages, read before starting work
5. `git pull origin main`

---

## Current State (Post Session 16 — 2026-02-27)

| Item | Value |
|------|-------|
| Branch | main |
| Commit | 878f690 |
| Tests | 988 |
| EdBot tools | 27 |
| ArtBot tools | 7 |
| Endpoints | 50 |
| Server | FastAPI :8901 |
| Resolve | Studio 20.3.1.6 — IPC CONFIRMED, 18/18 live tests PASS |
| ComfyUI | v0.12.3 :8188 — LayerDiffusion + VACE operational |
| Frontend | al_edbot_viewer_v1.html |
| Test videos | IMG_5769.MOV (continuous), test_with_silence.mov (2 gaps) |

### Benchmark Results (S16 live — Resolve running, int8_float16)

| Stage | Short (60s) | Long (7min) | Target |
|-------|-------------|-------------|--------|
| Transcription | 8.3s | 84.1s | <30s |
| Silence detect | 1.5s | 9.8s | <10s |
| Chapter detect | <0.001s | <0.001s | <5s |
| Search | <0.001s | <0.001s | <0.1s |
| Full pipeline | 9.6s | 98.6s | <60s |

Note: Long video transcription exceeds target because Resolve holds GPU, forcing int8 compute. All other stages <10s total.

### Pending
- Scanner credentials (Alex Dropbox, Kevin Drive)
- YD test feedback (not yet received)
- Slack integration (awaiting Sam token)
- JP dispatch results review

---

## Style Firewall
| Prefix | Repo | Style | ComfyUI output |
|--------|------|-------|----------------|
| `at_` | AT01 | Art Deco | output/at/ |
| `jp_` | JP01 | Steampunk | output/jp/ |

No cross-contamination. Ever. Bridge branches are the only exception.
Note: `al_` prefix was renamed to `at_` in S15 for output folders and code references.

---

## Machine Config
- ENKI64 (/rielt): 192.168.1.115 | RTX A6000 48GB | 128GB RAM | Win11
- AT01: C:\AT01 | JP01: C:\JP01
- Ollama: 0.0.0.0:11434 (9 models, A6000)
- Resolve Studio 20.3.1.6 (2-seat license, env vars set user-level)
- Python 3.12.10
