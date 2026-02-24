# Test Guide — resolve-tools

## Running Tests

```bash
cd C:\NB11\resolve-tools
py -3.12 -m pytest tests/ -v          # Full suite (53 tests)
py -3.12 -m pytest tests/ -v -x       # Stop on first failure
py -3.12 -m pytest tests/test_common.py -v  # Single file
py -3.12 -m pytest tests/test_markers.py::TestPairMarkers::test_overlapping_uses_outermost -v  # Single test
```

**No external dependencies needed.** All 53 tests run without Resolve, ffprobe, or ffmpeg. They test data structures, contracts, and validation logic only.

## Test File Summary

| File | Tests | What It Covers |
|------|-------|----------------|
| test_common.py | 15 | SessionID/FeedID formatting, CLIP_COLORS, paths, ensure_dirs, registry, hash, validation, sidecar I/O |
| test_ingest.py | 4 | scan_ingest_dir mapping, feed sidecar fields, session manifest fields |
| test_scope.py | 3 | build_timeline/build_multi_timeline input validation (rejects empty/None) |
| test_template.py | 5 | EXPECTED_BINS, COLOR_SMART_BINS, FEED_SMART_BINS, RENDER_PRESETS constants |
| test_markers.py | 4 | pair_markers: basic pair, multiple pairs, unpaired green, overlapping (depth) |
| test_detect.py | 6 | Detector registry, detector names, DetectionResult fields, stubs return [], JSON serialization |
| test_deliver.py | 5 | build_manifest fields, social_metadata placeholders, feedback_loop defaults, analytics schema, deliverable entry |
| test_mcp.py | 4 | format_audit_entry, not_implemented_response, read tool registry, write tool registry |
| test_integration.py | 7 | Cross-module contracts: ingest→scope, delivery manifest round-trip, MCP registry, ID determinism |

## Tests That Touch Filesystem

Only 8 tests create temp files (all use `tempfile.TemporaryDirectory`, auto-cleaned):

- **test_common.py:** TestEnsureDirs (creates real dirs under C:\NB11\resolve-ingest\), TestSidecarIO, TestSessionIO
- **test_ingest.py:** TestScanIngestDir (creates temp dir with subdirs and empty media files)
- **test_integration.py:** TestIngestToScopeContract, TestDeliverManifestSchema (temp dir JSON round-trips)

**Note:** TestEnsureDirs creates actual directories at `C:\NB11\resolve-ingest\{vrcam,studcam,...}`. These are the real project directories, not temp dirs.

## What Each Test File Validates

### test_common.py — Foundation Contracts
- SessionID string format: `KEYNOTE_20250220_001` (zero-padded seq)
- FeedID string format: `KEYNOTE_20250220_001_VRCAM-03` (zero-padded index)
- All 6 CLIP_COLORS keys present
- All paths under PROJECT_ROOT
- FEED_SUBDIRS = {"vrcam", "studcam", "mic", "envaud", "mrrender"}
- next_session_seq: new session = 1, existing seq 3 = returns 4
- deterministic_feed_hash: same input → same hash, different input → different hash
- validate_video: .txt file → rejected with "unsupported" error
- Sidecar/manifest JSON round-trips

### test_ingest.py — Ingest Logic
- scan_ingest_dir: maps "vrcam" subdir → "VRCAM" feed type
- scan_ingest_dir: ignores unknown subdirs (e.g., "randomdir")
- build_feed_sidecar: has feed_id, session_id, feed_type, duration, codec, resolution, fps, validation_status
- build_session_manifest: has session_id, human_name, feed_count, feed_list, sync_method="TBD"

### test_scope.py — Scope Validation Only
- build_timeline raises ValueError on empty string session_id
- build_timeline raises ValueError on None session_id
- build_multi_timeline raises ValueError without name parameter

### test_markers.py — Pair Algorithm
- Green(100) + Red(200) → [(100, 200)]
- Green(100)+Red(200), Green(500)+Red(700) → 2 pairs
- Green only, no Red → [] (skipped with warning)
- Overlapping: Green(100), Green(150), Red(200), Red(250) → [(100, 250)] (outermost)

### test_integration.py — Cross-Module Contracts
- Ingest manifest has fields scope needs (session_id, feed_list, feed_count)
- Feed sidecar duration > 0
- Delivery manifest JSON round-trips with social_metadata, analytics_hooks, feedback_loop
- All 8 MCP read tools registered
- All 8 MCP write tools registered
- SessionID is deterministic across calls
- deterministic_feed_hash is deterministic across calls

## Known Coverage Gaps

These are **intentional** — they require Resolve or ffmpeg which aren't available in CI:

1. No actual Resolve API tests (timeline creation, clip import, marker operations)
2. No ffprobe/ffmpeg tests (codec detection, remux, detection analysis)
3. No actual pipeline execution (ingest → scope → markers → deliver end-to-end)
4. No render output validation
5. No error recovery tests (partial failures, corrupted files, permissions)

## Adding New Tests

Pattern: all test files use `sys.path.insert(0, ...)` to import from parent directory.

```python
import unittest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

class TestMyFeature(unittest.TestCase):
    def test_something(self):
        from resolve_common import SomeClass
        # ...

if __name__ == "__main__":
    unittest.main()
```
