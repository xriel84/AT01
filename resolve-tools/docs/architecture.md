# Architecture — resolve-tools

## Module Dependency Graph

```
resolve_common.py ← foundation, imported by everything
  ↑
  ├── resolve_ingest.py       (heavy imports: SessionID, FeedID, all paths, validators, helpers)
  ├── resolve_scope.py        (paths, Resolve helpers, sidecar I/O, sync_strategy)
  ├── resolve_template.py     (connect_resolve, find_or_create_bin, TOOLS_DIR)
  ├── resolve_markers.py      (connect_resolve, find_or_create_bin, CLIP_COLORS)
  ├── resolve_detect_test.py  (TOOLS_DIR, connect_resolve)
  ├── resolve_deliver.py      (paths, Resolve helpers, JSON I/O) + resolve_template.RENDER_PRESETS
  └── resolve_mcp_server.py   (paths, JSON I/O, CLIP_COLORS) + lazy imports all others
```

No circular dependencies. Only two cross-module links outside resolve_common:
1. `resolve_deliver` → `resolve_template.RENDER_PRESETS`
2. `resolve_mcp_server` → lazy imports from all 6 domain modules (try/except)

## What Each Module Does

### resolve_common.py (~515 lines) — Foundation

Everything shared. Other modules import from here exclusively (except the two links above).

**Exports:**
- Path constants: PROJECT_ROOT, INGEST_DIR, STAGING_DIR, ARCHIVE_DIR, DELIVERY_DIR, TOOLS_DIR
- ID dataclasses: SessionID (frozen), FeedID (frozen), FeedMetadata, SyncOffset
- Taxonomy: FEED_SUBDIRS, FEED_TYPE_MAP, SUPPORTED_VIDEO_EXTS, SUPPORTED_AUDIO_EXTS, CLIP_COLORS
- Sync: SyncStrategy ABC, TBDSync placeholder, module-level `sync_strategy` singleton
- Directory management: ensure_dirs()
- Session registry: load/save/next_session_seq/register_session (JSON-backed counter)
- Hashing: deterministic_feed_hash() — SHA-256 of path|date|size, first 16 hex chars
- File helpers: get_file_creation_date() — st_ctime as YYYYMMDD
- Validation: validate_video() — ffprobe-based, detects VFR (>5% diff = rejected), flags MKV for remux
- Remux: remux_mkv_to_mp4() — stream copy fallback to re-encode
- JSON I/O: write_sidecar, read_sidecar, write_session_manifest, read_session_manifest, list_all_sessions
- Resolve: connect_resolve(), find_or_create_bin(), get_session_clips()

### resolve_ingest.py (~504 lines) — Validated Ingest Pipeline

Scans INGEST_DIR subdirs, validates media, generates IDs, stages with sidecars, archives originals, imports to Resolve.

**Pipeline:** scan → validate → (remux MKV) → stage + sidecar → archive → import to Resolve
**Watch mode:** Polls every 1s, batches after 30s of no new files, Ctrl+C flushes
**Key functions:** scan_ingest_dir, process_file, ingest_batch, watch_mode, cmd_list
**Side effects:** Creates dirs in STAGING_DIR and ARCHIVE_DIR, writes _session.json, updates _sessions.json registry

### resolve_scope.py (~400 lines) — Session-Scoped Timeline Builder

Builds timelines from ingested sessions. Every function requires explicit session_id or feed_id — no "all clips" mode.

**Key functions:**
- build_timeline(session_id) — all feeds from one session
- build_feed_timeline(feed_id) — single feed file
- build_multi_timeline(session_ids, name) — combines sessions, adds Orange "SESSION BOUNDARY" markers
- All support dry-run when resolve=None

### resolve_template.py (~260 lines) — Project Template

Creates/audits/fixes standard Resolve project structure: 8 bins, smart bin definitions (print-only), 5 render presets.

**Bins:** RAW FOOTAGE, SELECTS, SUBCLIPS, B-ROLL, GRAPHICS, MUSIC & SFX, TIMELINES, EXPORTS
**Presets:** YouTube 16:9, TikTok 9:16, IG Square 1:1, Archive (ProRes), Thumbnail (PNG)

### resolve_markers.py (~240 lines) — Marker-Pair Subclip Automation

Reads Green/Red marker pairs from timeline, creates subclips, moves them to SELECTS bin with Green color.

**Algorithm:** Fast path (clean interleaving) or depth-based pairing (overlapping markers → outermost boundaries).
**Subclip naming:** `{session_id}_{timeline_name}_sel{i:03d}` or `{timeline_name}_sel{i:03d}`

### resolve_detect_test.py (~450 lines) — Detection Test Harness

6 detectors (4 real FFmpeg-based, 2 stubs):
- **Real:** SilenceDetector, SceneChangeDetector, AudioPeakDetector, BlackFrameDetector
- **Stubs:** SpeakerChangeDetector, BreathDetector (return empty lists)

Results saved as JSON in TOOLS_DIR/detect_results/. Can inject detections as Yellow markers into Resolve.

### resolve_deliver.py (~400 lines) — Render Dispatch & Delivery

Renders per-platform using RENDER_PRESETS, generates delivery manifests with social_metadata (PLACEHOLDER), analytics_hooks, and feedback_loop stubs.

**Output per session:** DELIVERY_DIR/{session_id}/delivery_manifest.json + analytics.json
**Platforms:** youtube, tiktok, instagram, archive, thumbnails

### resolve_mcp_server.py (~940 lines) — MCP Server

16 tools (8 read + 8 write), 4 resources, audit logging. Uses `mcp` Python package with stdio transport.

**Read tools:** list_sessions, list_feeds, get_metadata, list_timelines, query_markers, render_status, delivery_status, search_clips
**Write tools:** ingest, build_timeline, build_feed_timeline, add_marker, process_markers, render, set_clip_color, promote_to_selects
**Resources:** resolve://sessions, resolve://session/{id}, resolve://delivery/{id}, resolve://analytics/{id}
**Audit:** Append-only JSON lines in TOOLS_DIR/mcp_audit.log

## Data Flow

```
Files dropped in resolve-ingest/{feedtype}/
  ↓ resolve_ingest --once --session NAME
  ↓ validate → stage → sidecar → archive
resolve-staging/{SESSION_ID}/
  ├── {FEED_ID}.mp4          (staged media)
  ├── {FEED_ID}.json         (sidecar metadata)
  └── _session.json           (session manifest)
  ↓ resolve_scope --build SESSION_ID
DaVinci Resolve timeline created
  ↓ resolve_markers --process
Subclips created in SELECTS bin
  ↓ resolve_deliver --render SESSION_ID
resolve-delivery/{SESSION_ID}/
  ├── delivery_manifest.json
  └── analytics.json
```

## Filesystem Conventions

- Session manifests: `_session.json` (underscore prefix = metadata, not media)
- Session registry: `_sessions.json` in STAGING_DIR root
- Sidecars: same stem as media file, `.json` extension
- Detection results: `TOOLS_DIR/detect_results/{stem}_{timestamp}.json`
- MCP audit log: `TOOLS_DIR/mcp_audit.log` (append-only JSON lines)
