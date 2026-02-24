# resolve-tools — DaVinci Resolve Video Asset Management

Session-scoped media pipeline: ingest → timeline → markers → detect → render → deliver.
8 Python modules in `C:\NB11\resolve-tools\`, flat layout (no packages).

## Directory Layout

```
C:\NB11\resolve-tools\       # Scripts, tests, docs
C:\NB11\resolve-ingest\      # Drop zone: vrcam/ studcam/ mic/ envaud/ mrrender/
C:\NB11\resolve-staging\     # Processed files + _session.json manifests + _sessions.json registry
C:\NB11\resolve-archive\     # Original file backups (per-session subdirs)
C:\NB11\resolve-delivery\    # Rendered output + delivery_manifest.json + analytics.json
```

## Shell & Python

- Use `py -3.12` — never bare `python`
- No requirement to cd into Resolve install dir (unlike edbot.py)
- Resolve must be running for any Resolve-connected operation
- All scripts support `--no-resolve` or dry-run modes for offline work

## Running Tests

```
cd C:\NB11\resolve-tools
py -3.12 -m pytest tests/ -v
```

All 53 tests run without Resolve, ffprobe, or ffmpeg. They test data structures, contracts, and validation logic only. See `docs/test-guide.md` for details.

## Two-Tier ID System (CRITICAL — get this right)

- **SessionID**: `{HUMAN_NAME}_{YYYYMMDD}_{SEQ:03d}` → e.g. `KEYNOTE_20250220_001`
- **FeedID**: `{SessionID}_{FEEDTYPE}-{INDEX:02d}` → e.g. `KEYNOTE_20250220_001_VRCAM-03`
- SessionID is a frozen dataclass with `__str__`; used as directory names everywhere
- Sequence counter lives in `C:\NB11\resolve-staging\_sessions.json`

## Clip Colors (Resolve-specific names, case-sensitive)

| Intent       | Color  |
|-------------|--------|
| unreviewed  | Blue   |
| select      | Green  |
| needs_review| Yellow |
| reject      | Red    |
| broll       | Purple |
| needs_fix   | Orange |

## Feed Types

Five feed types map from ingest subdirectory names (lowercase → uppercase):
`vrcam→VRCAM`, `studcam→STUDCAM`, `mic→MIC`, `envaud→ENVAUD`, `mrrender→MRRENDER`

## Module Dependency (only non-obvious one)

- `resolve_deliver.py` imports `RENDER_PRESETS` from `resolve_template.py`
- `resolve_mcp_server.py` lazy-imports all other modules inside try/except
- Everything else imports only from `resolve_common.py`

## What I Get Wrong Between Sessions

1. **Path prefixes**: Directories are `resolve-ingest`, `resolve-staging`, etc. (hyphenated), NOT `ingest`, `staging`.
2. **CLIP_COLORS["broll"] is "Purple"**, not "Cyan". Check the dict.
3. **SyncOffset.offset is float (seconds)**, not int frames. SyncOffset.feed_id is str, not FeedID object.
4. **FeedMetadata fields are all primitives** (str, float). No nested objects.
5. **check_template() returns a dict** `{"missing_bins": [...], "extra_bins": [...], "ok": bool}`, NOT a list. Don't iterate it directly.
6. **GetSubFolderList() can return None** in Resolve API. Always guard: `(folder.GetSubFolderList() or [])`.
7. **connect_resolve() calls sys.exit(1) on failure**. Scripts that want graceful degradation must catch SystemExit.
8. **SESSIONS_REGISTRY is in STAGING_DIR** (`resolve-staging/_sessions.json`), not TOOLS_DIR.
9. **Smart bin creation is not supported** by Resolve scripting API (free or Studio). setup_smart_bins() only prints.
10. **MKV remux has two-stage fallback**: stream copy first (10min timeout), then re-encode H.264 CRF 18 (30min timeout).
11. **VFR detection threshold is 5%** difference between r_frame_rate and avg_frame_rate. Files are rejected, not warned.
12. **Watch mode batches on 30s gap**, not file count. Ctrl+C flushes pending.

## CLI Quick Reference

| Script              | Modes                                        |
|--------------------|----------------------------------------------|
| resolve_ingest.py  | `--watch` `--once` `--file PATH` `--list`    |
| resolve_scope.py   | `--list` `--build` `--build-feed` `--combine`|
| resolve_template.py| `--setup` `--check` `--fix`                  |
| resolve_markers.py | `--process` `--preview` `[--session]`        |
| resolve_detect_test.py | `--test FILE` `--results` `--inject JSON`|
| resolve_deliver.py | `--render` `--manifest-only` `--status` `--list`|
| resolve_mcp_server.py | `--serve` `--test TOOL` `--audit`         |

All ingest/scope/deliver modes require `--session NAME` or a session ID argument.

## Detailed Reference

- `docs/architecture.md` — Module map, what each script does, cross-module dependencies
- `docs/resolve-api-notes.md` — Resolve scripting API quirks and patterns
- `docs/test-guide.md` — Test suite guide, what each file covers, edge cases
- `docs/plans/2026-02-22-resolve-asset-management-design.md` — Approved design
- `docs/plans/2026-02-22-resolve-asset-management-plan.md` — Implementation plan (11 tasks)
