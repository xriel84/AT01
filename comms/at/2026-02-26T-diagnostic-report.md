# JP01 Diagnostic Report
# Date: 2026-02-26
# Type: DIAGNOSTIC

## 1.1 JP01 Repo Status
- Branch: jp/contrib-viewer-v8 (active)
- Remotes: 2 (origin=NewEccentric/JP01.git, upstream=xriel84/AT01.git)
- Branches: 2 local (main, jp/contrib-viewer-v8), 4 remote
- Dirty files: 2 untracked (raptor-library.html, scripts/jp_transcribe_all.py)
- Identity: NewEccentric / xriel84@protonmail.com
- NOTE: Email is AT01's address — should be JP-specific email
- Status: OK (minor: email mismatch)

## 1.2 AT01 Repo Status
- Branch: main (up to date with origin)
- Remotes: 2 (origin=xriel84/AT01.git, agilelens=AgileLens/edbot.git)
- Branches: 3 local (main, edbot-shorts, jp01-bridge), 5 remote
- Dirty files: 4 untracked (agents/edbot/frontend/, comms/at/handoff, comms/from-at/, comms/jp/, tests/test_round7_integration.py)
- Latest: [aribot] round 6 — transcript intelligence layer
- Status: OK (untracked files present, AT terminal should commit)

## 1.3 Comms Infrastructure
- C:\JP01\comms\at\ — EXISTS (4 .md files)
- C:\JP01\comms\jp\ — EXISTS (0 .md files)
- C:\AT01\comms\at\ — EXISTS (3 .md files — missing partB-ready)
- C:\AT01\comms\jp\ — EXISTS (0 .md files)
- JP→AT: 4 messages sent, 3 delivered to AT01 (1 pending: partB-ready)
- AT→JP: 0 messages
- Unread: none (AT hasn't sent any messages to JP)

## 1.4 File Inventory
- phone-space-viewer.html — OK (150,586 bytes, ~3870 lines)
- jp01-dev-server.py — OK (12,717 bytes, 354 lines)
- raptor-library.json — OK (16,312 bytes, 4 entries)
- assembly_manifest.json — OK (1,387 bytes, 3 test entries)
- shortform-aggregator.html — MISSING
- edbot-adapter-phone-viewer.js — MISSING
- AT01 backend/output/assembly_manifest.json — MISSING
- C:\NB11\raptor-history — EXISTS (91 video files)

## 1.5 Environment
- python: 3.11.0 (bare `python` command)
- py -3.12: 3.12.10 — OK
- node: v22.19.0 — OK
- git: 2.53.0 — OK
- ffmpeg: 2023-10-29 full build — OK
- ffprobe: 2023-10-29 — OK
- auto-editor: 29.3.1 — OK
- faster-whisper: 1.2.1 — OK
- pysubs2: 1.8.0 — OK

## 1.6 Resolve API
- PASS — DaVinci Resolve 20.3.1.6 running, API accessible

## 1.7 Disk Space
- C: drive — 37 GB free of 465 GB (93% used)
- NOTE: up from 19GB last known — batch ops have more room now

## 1.8 Network / Ollama
- Ollama: NOT REACHABLE (localhost:11434 not responding)

## 1.9 Scripts Inventory
- C:\JP01\scripts\jp_transcribe_all.py — batch transcription script
- C:\AT01\scripts\ — empty (.gitkeep only)
- C:\AT01\agents\edbot\tools\ — 6+ tools (auto_chapter, batch_transcribe, chapter_detect, etc.)
- C:\NB11\JasperBot\ — 3 .py (resolve_timeline_dump, server) + 3 .ps1 (discover, preflight, scaffold)
- No duplicates across repos (different scopes)
