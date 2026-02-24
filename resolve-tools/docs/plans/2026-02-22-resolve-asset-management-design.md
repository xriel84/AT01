# Resolve Video Asset Management — Design Document

**Date:** 2026-02-22
**Status:** Approved

## Overview

Six Python scripts + one shared module for DaVinci Resolve Studio video asset management. Handles ingest, session scoping, project templates, marker automation, detection testing, render delivery, and MCP server integration.

## Decisions

- **Code sharing:** Single shared module (`resolve_common.py`) with types, ID generation, Resolve connection, and constants. All scripts import from it.
- **Execution context:** Scripts run from `C:\NB11\resolve-tools\`. Resolve module path handled via `sys.path` manipulation in `connect_resolve()`. Not bound to edbot.py's constraint of running from Resolve install dir.
- **Watch mode session naming:** CLI flag `--session NAME` required for watch mode. Auto-increment sequence number on 30s file gap.
- **Organization:** Flat directory, no package structure. Matches edbot.py simplicity.

## File Layout

```
C:\NB11\resolve-tools\
  resolve_common.py        # Shared types, ID system, Resolve connection, constants
  resolve_ingest.py        # P0: Validated ingest pipeline
  resolve_scope.py         # P0: Session-scoped timeline builder
  resolve_template.py      # P1: Project template setup
  resolve_markers.py       # P2: Marker-pair subclip automation
  resolve_detect_test.py   # P2: Detection library test harness
  resolve_deliver.py       # P3: Render dispatch + delivery manifest
  resolve_mcp_server.py    # P4: MCP server wrapping all above
  docs/plans/              # Design docs
```

## Directory Structure

```
C:\NB11\
  resolve-ingest\          # Drop zone for raw files
    vrcam\                 # VR camera feeds
    studcam\               # Studio camera feeds
    mic\                   # Microphone audio
    envaud\                # Environmental audio
    mrrender\              # MR renders
  resolve-staging\         # Validated + organized files
    {SESSION_ID}\          # Per-session directories
      _session.json        # Session manifest
      {feed_id}.json       # Per-feed sidecar
      {filename}           # Validated media file
  resolve-archive\         # Cold backup of originals
    {SESSION_ID}\
  resolve-delivery\        # Rendered outputs
    {SESSION_ID}\
      youtube\
      tiktok\
      instagram\
      archive\
      thumbnails\
      _manifest.json
      _analytics.json
  resolve-tools\           # Scripts live here
```

## Module: resolve_common.py

### Resolve Connection
```python
MODULES_PATH = r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"

def connect_resolve():
    """Connect to running Resolve instance via sys.path manipulation."""
```

### Path Constants
```python
PROJECT_ROOT = Path(r"C:\NB11")
INGEST_DIR   = PROJECT_ROOT / "resolve-ingest"
STAGING_DIR  = PROJECT_ROOT / "resolve-staging"
ARCHIVE_DIR  = PROJECT_ROOT / "resolve-archive"
DELIVERY_DIR = PROJECT_ROOT / "resolve-delivery"
TOOLS_DIR    = PROJECT_ROOT / "resolve-tools"
FEED_SUBDIRS = {"vrcam", "studcam", "mic", "envaud", "mrrender"}
```

### Two-Tier ID System

**SessionID:** `{HUMAN_NAME}_{YYYYMMDD}_{SEQ}`
- human_name: CLI-provided (e.g., KEYNOTE)
- date: From source file creation date (YYYYMMDD)
- seq: Auto-increment per name per day (001, 002...)
- Registry persisted in `STAGING_DIR/_sessions.json`

**FeedID:** `{SESSION_ID}_{FEEDTYPE}-{N}`
- Deterministic: computed from hash(source_path + creation_date + file_size)
- feed_type: VRCAM, STUDCAM, MIC, ENVAUD, MRRENDER
- index: Per feed-type within session

### Sync Hook Stub
```python
class SyncStrategy(ABC):
    @abstractmethod
    def align(self, feeds: list[FeedMetadata]) -> list[SyncOffset]: ...

class TBDSync(SyncStrategy):
    def align(self, feeds):
        return [SyncOffset(f.feed_id, offset=0.0) for f in feeds]
```

### Clip Color Constants
```python
CLIP_COLORS = {
    "unreviewed": "Blue", "select": "Green", "needs_review": "Yellow",
    "reject": "Red", "broll": "Purple", "needs_fix": "Orange"
}
```

### Shared Utilities
- `read_sidecar(path) -> dict` — Load feed sidecar JSON
- `write_sidecar(path, data)` — Write feed sidecar JSON
- `read_session(session_id) -> dict` — Load session manifest
- `write_session(session_id, data)` — Write session manifest
- `list_all_sessions() -> list[dict]` — Scan staging dir for all sessions
- `get_session_clips(media_pool, session_id) -> list` — Scoped clip lookup from session bin only
- `validate_video(path) -> dict` — ffprobe metadata extraction + VFR check
- `ensure_dirs()` — Create all required directories if missing

## Script: resolve_ingest.py (~200 lines)

### Flow
1. Scan INGEST_DIR subdirectories, map subdir name to feed type
2. Validate each file:
   - ffprobe to detect VFR (compare r_frame_rate vs avg_frame_rate) — reject if VFR
   - MKV remux to MP4 (stream-copy first, re-encode fallback)
   - Reject unsupported formats
3. Generate deterministic Feed ID via resolve_common
4. Copy (never move) to STAGING_DIR/{session_id}/
5. Write per-feed sidecar JSON + session manifest JSON
6. Import to Resolve: bin RAW FOOTAGE/{session_id}, set Blue clip color, stamp metadata
7. Copy to ARCHIVE_DIR/{session_id}/

### CLI
- `--watch --session NAME` — Continuous poll, 30s batch window, auto-increment seq
- `--once --session NAME` — Process current files and exit
- `--file PATH --session NAME` — Single file ingest
- `--list` — Show all sessions and feed counts

### Error Handling
Never crash on bad files. Log, skip, continue. Summary at end.

## Script: resolve_scope.py (~150 lines)

### Core Constraint
Every function requires explicit session or feed scope. No unscoped media pool operations.

### Functions
- `list_sessions()` — Read staging dir, print table of sessions with feed counts/types
- `build_timeline(session_id)` — All feeds from one session into one timeline. Apply TBDSync offsets.
- `build_feed_timeline(feed_id)` — Single feed timeline
- `build_multi_timeline(session_ids, name)` — Cross-session combine with Orange boundary markers and text notes at session transitions. Requires human-provided name.

### CLI
- `--list` — List sessions
- `--build {SESSION_ID}` — Build from one session
- `--build-feed {FEED_ID}` — Build from one feed
- `--combine {S1} {S2} --name "X"` — Cross-session

## Script: resolve_template.py

### Bin Structure
RAW FOOTAGE, SELECTS, SUBCLIPS, B-ROLL, GRAPHICS, MUSIC & SFX, TIMELINES, EXPORTS

### Smart Bins
Auto-filter by clip color (Blue=Unreviewed, Green=Selects, etc.) + per feed type (VR Cameras, Studio Cameras, Audio, MR Renders). If API doesn't support Smart Bin creation, print manual setup instructions.

### Render Presets
YouTube 16:9 (H.264, 1920x1080, 24Mbps), TikTok 9:16 (1080x1920, 15Mbps), IG Square 1:1 (1080x1080, 15Mbps), Archive (ProRes 422 HQ, source res), Thumbnail (PNG sequence, single frame). If preset saving not exposed via API, generate .setting files to TOOLS_DIR.

### CLI
- `--setup` — Create template (idempotent)
- `--check` — Report drift
- `--fix` — Add missing, don't delete extras

## Script: resolve_markers.py

### Marker Pair Workflow
1. Read Green/Red marker pairs from active timeline
2. Create subclip per pair
3. Inherit all parent metadata (Session ID, Feed ID, Feed Type)
4. Green subclips auto-move to SELECTS bin

### Edge Cases
- Unpaired markers: log warning, skip
- Overlapping pairs: use outermost boundaries
- Always scoped to current timeline's session

### CLI
- `--process` — Read markers, create subclips
- `--preview` — Dry run
- `--session {ID}` — Process specific session's timeline

## Script: resolve_detect_test.py

### Detector Interface
```python
class Detector(ABC):
    name: str
    @abstractmethod
    def detect(self, media_path: str) -> list[DetectionResult]: ...
```

### Detectors
1. SilenceDetector — ffmpeg silencedetect (threshold_dB, min_duration)
2. SceneChangeDetector — ffmpeg scene filter (threshold 0.0-1.0)
3. SpeakerChangeDetector — placeholder stub
4. BreathDetector — placeholder stub
5. AudioPeakDetector — ffmpeg astats
6. BlackFrameDetector — ffmpeg blackdetect

### Output
JSON results file + console summary ranked by detection count, avg confidence, processing time.

### CLI
- `--test {FILE}` — Run all detectors
- `--test {FILE} --only silence,scene` — Run specific detectors
- `--results` — Past test run summaries
- `--inject {JSON}` — Place detections as Yellow markers in Resolve

## Script: resolve_deliver.py

### Flow
1. Read timeline metadata (Session ID, duration, resolution)
2. Render to platform outputs using template presets
3. Organize to DELIVERY_DIR/{session_id}/{platform}/
4. Generate _manifest.json (deliverables + social_metadata placeholders + analytics_hooks + feedback_loop)
5. Create empty _analytics.json for future population

### CLI
- `--render {SESSION_ID}` — Render all platforms
- `--render {SESSION_ID} --platform youtube tiktok` — Specific platforms
- `--manifest-only {SESSION_ID}` — Manifest without rendering
- `--status` — Pending/completed deliveries
- `--list` — All delivery sessions

## Script: resolve_mcp_server.py

### Transport
stdio via `mcp` Python SDK

### Read Tools (8)
resolve_list_sessions, resolve_list_feeds, resolve_get_metadata, resolve_list_timelines, resolve_query_markers, resolve_render_status, resolve_delivery_status, resolve_search_clips

### Write Tools (8)
resolve_ingest, resolve_build_timeline, resolve_build_feed_timeline, resolve_add_marker, resolve_process_markers, resolve_render, resolve_set_clip_color, resolve_promote_to_selects

### Resources (4)
resolve://sessions, resolve://session/{id}, resolve://delivery/{id}, resolve://analytics/{id}

### Safety
- All writes require session scope
- No delete operations exposed
- Renders additive only (no overwrite)
- Audit log: TOOLS_DIR/mcp_audit.log (timestamp, tool, params, result)
- Unimplemented tools return `{"error": "not_implemented"}` instead of crashing

## Execution Order

1. **P0:** resolve_common.py + resolve_ingest.py + resolve_scope.py (foundation)
2. **P1:** resolve_template.py (project setup)
3. **P2:** resolve_markers.py + resolve_detect_test.py (marker automation)
4. **P3:** resolve_deliver.py (render pipeline)
5. **P4:** resolve_mcp_server.py (integration layer)

## Testing Strategy

Each script gets manual test scenarios verifiable against running Resolve:
- Ingest: deterministic ID (run twice = same ID), MKV remux, VFR rejection
- Scope: empty session refusal, single-session scoping, no cross-contamination
- Template: idempotent setup, drift detection
- Markers: pair extraction, unpaired handling, metadata inheritance
- Detection: FFmpeg detectors produce valid JSON, console summary accuracy
- Delivery: manifest schema validation, output directory structure
- MCP: tool invocation + audit log verification
