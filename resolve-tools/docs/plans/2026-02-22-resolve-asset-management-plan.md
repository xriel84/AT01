# Resolve Video Asset Management — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a 7-script DaVinci Resolve asset management system with session-scoped ingest, timeline building, marker automation, detection testing, render delivery, and MCP server integration.

**Architecture:** Flat directory at `C:\NB11\resolve-tools\` with one shared module (`resolve_common.py`) and six domain scripts. Each script imports shared types/utilities from common. Resolve API access via `sys.path` manipulation (no requirement to run from Resolve install dir). All operations session-scoped via Two-Tier ID system.

**Tech Stack:** Python 3.12, DaVinci Resolve Studio scripting API, FFmpeg/ffprobe (in PATH), `mcp` Python SDK (for P4 MCP server). Zero cloud dependencies.

**Reference:** `C:\NB11\scripts\edbot.py` — proven Resolve connection pattern (lines 28-62), media pool import (lines 180-241), render (lines 297-353).

**Test Strategy:** Unit tests use `unittest.mock` to patch `DaVinciResolveScript` (Resolve must not be required for tests). FFmpeg detectors tested against a small generated test file. Tests live in `C:\NB11\resolve-tools\tests\`.

**Run all scripts:** `py -3.12 C:\NB11\resolve-tools\resolve_ingest.py --once --session TEST`

---

## Task 1: Shared Module — Types and Constants (`resolve_common.py`)

**Files:**
- Create: `C:\NB11\resolve-tools\resolve_common.py`
- Create: `C:\NB11\resolve-tools\tests\test_common.py`

**Step 1: Write failing test for SessionID**

```python
# tests/test_common.py
import unittest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestSessionID(unittest.TestCase):
    def test_str_format(self):
        from resolve_common import SessionID
        sid = SessionID(human_name="KEYNOTE", date="20250220", seq=1)
        self.assertEqual(str(sid), "KEYNOTE_20250220_001")

    def test_seq_zero_padded(self):
        from resolve_common import SessionID
        sid = SessionID(human_name="LIVEJAM", date="20250301", seq=42)
        self.assertEqual(str(sid), "LIVEJAM_20250301_042")


class TestFeedID(unittest.TestCase):
    def test_str_format(self):
        from resolve_common import SessionID, FeedID
        sid = SessionID(human_name="KEYNOTE", date="20250220", seq=1)
        fid = FeedID(session=sid, feed_type="VRCAM", index=3)
        self.assertEqual(str(fid), "KEYNOTE_20250220_001_VRCAM-03")

    def test_different_feed_types(self):
        from resolve_common import SessionID, FeedID
        sid = SessionID(human_name="DEMO", date="20250220", seq=1)
        for ft in ["VRCAM", "STUDCAM", "MIC", "ENVAUD", "MRRENDER"]:
            fid = FeedID(session=sid, feed_type=ft, index=1)
            self.assertIn(ft, str(fid))


class TestClipColors(unittest.TestCase):
    def test_all_colors_present(self):
        from resolve_common import CLIP_COLORS
        expected = {"unreviewed", "select", "needs_review", "reject", "broll", "needs_fix"}
        self.assertEqual(set(CLIP_COLORS.keys()), expected)


class TestPathConstants(unittest.TestCase):
    def test_paths_are_under_nb11(self):
        from resolve_common import PROJECT_ROOT, INGEST_DIR, STAGING_DIR, ARCHIVE_DIR, DELIVERY_DIR, TOOLS_DIR
        for p in [INGEST_DIR, STAGING_DIR, ARCHIVE_DIR, DELIVERY_DIR, TOOLS_DIR]:
            self.assertTrue(str(p).startswith(str(PROJECT_ROOT)))

    def test_feed_subdirs(self):
        from resolve_common import FEED_SUBDIRS
        self.assertEqual(FEED_SUBDIRS, {"vrcam", "studcam", "mic", "envaud", "mrrender"})


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_common.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resolve_common'`

**Step 3: Implement types and constants**

```python
# resolve_common.py
"""
resolve_common.py -- Shared types, ID system, and utilities for Resolve asset management.

All resolve-tools scripts import from this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path


# -- Path Constants -----------------------------------------------------------

PROJECT_ROOT = Path(r"C:\NB11")
INGEST_DIR   = PROJECT_ROOT / "resolve-ingest"
STAGING_DIR  = PROJECT_ROOT / "resolve-staging"
ARCHIVE_DIR  = PROJECT_ROOT / "resolve-archive"
DELIVERY_DIR = PROJECT_ROOT / "resolve-delivery"
TOOLS_DIR    = PROJECT_ROOT / "resolve-tools"

FEED_SUBDIRS = {"vrcam", "studcam", "mic", "envaud", "mrrender"}

FEED_TYPE_MAP = {
    "vrcam": "VRCAM",
    "studcam": "STUDCAM",
    "mic": "MIC",
    "envaud": "ENVAUD",
    "mrrender": "MRRENDER",
}

SUPPORTED_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".mxf", ".webm"}
SUPPORTED_AUDIO_EXTS = {".wav", ".mp3", ".aac", ".flac", ".ogg"}

CLIP_COLORS = {
    "unreviewed": "Blue",
    "select": "Green",
    "needs_review": "Yellow",
    "reject": "Red",
    "broll": "Purple",
    "needs_fix": "Orange",
}

SESSIONS_REGISTRY = STAGING_DIR / "_sessions.json"


# -- Two-Tier ID System ------------------------------------------------------

@dataclass
class SessionID:
    human_name: str
    date: str       # YYYYMMDD
    seq: int

    def __str__(self) -> str:
        return f"{self.human_name}_{self.date}_{self.seq:03d}"


@dataclass
class FeedID:
    session: SessionID
    feed_type: str  # VRCAM, STUDCAM, MIC, ENVAUD, MRRENDER
    index: int

    def __str__(self) -> str:
        return f"{self.session}_{self.feed_type}-{self.index:02d}"


@dataclass
class FeedMetadata:
    feed_id: str
    session_id: str
    feed_type: str
    source_path: str
    original_filename: str
    creation_date: str
    duration: float
    codec: str
    resolution: str
    fps: float
    validation_status: str
    ingest_timestamp: str


@dataclass
class SyncOffset:
    feed_id: str
    offset: float  # seconds


# -- Sync Hook Stub ----------------------------------------------------------

class SyncStrategy(ABC):
    @abstractmethod
    def align(self, feeds: list[FeedMetadata]) -> list[SyncOffset]:
        ...


class TBDSync(SyncStrategy):
    def align(self, feeds: list[FeedMetadata]) -> list[SyncOffset]:
        return [SyncOffset(feed_id=f.feed_id, offset=0.0) for f in feeds]


sync_strategy: SyncStrategy = TBDSync()
```

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_common.py -v`
Expected: All PASS

**Step 5: Commit**

```
git add resolve_common.py tests/test_common.py
git commit -m "feat(P0): add resolve_common types, ID system, and constants"
```

---

## Task 2: Shared Module — Utilities (`resolve_common.py` continued)

**Files:**
- Modify: `C:\NB11\resolve-tools\resolve_common.py`
- Modify: `C:\NB11\resolve-tools\tests\test_common.py`

**Step 1: Write failing tests for utility functions**

Append to `tests/test_common.py`:

```python
import tempfile
import json


class TestEnsureDirs(unittest.TestCase):
    def test_creates_ingest_subdirs(self):
        from resolve_common import ensure_dirs, INGEST_DIR, FEED_SUBDIRS
        ensure_dirs()
        for sub in FEED_SUBDIRS:
            self.assertTrue((INGEST_DIR / sub).is_dir())


class TestSessionRegistry(unittest.TestCase):
    def test_next_seq_new_session(self):
        from resolve_common import next_session_seq
        # With empty registry, first seq is 1
        seq = next_session_seq("TESTNAME", "20250220", registry={})
        self.assertEqual(seq, 1)

    def test_next_seq_existing_session(self):
        from resolve_common import next_session_seq
        registry = {"TESTNAME_20250220": 3}
        seq = next_session_seq("TESTNAME", "20250220", registry=registry)
        self.assertEqual(seq, 4)


class TestDeterministicFeedIndex(unittest.TestCase):
    def test_same_input_same_index(self):
        from resolve_common import deterministic_feed_hash
        h1 = deterministic_feed_hash("/path/to/file.mp4", "20250220", 123456)
        h2 = deterministic_feed_hash("/path/to/file.mp4", "20250220", 123456)
        self.assertEqual(h1, h2)

    def test_different_input_different_index(self):
        from resolve_common import deterministic_feed_hash
        h1 = deterministic_feed_hash("/path/to/a.mp4", "20250220", 100)
        h2 = deterministic_feed_hash("/path/to/b.mp4", "20250220", 200)
        self.assertNotEqual(h1, h2)


class TestValidateVideo(unittest.TestCase):
    def test_unsupported_extension_rejected(self):
        from resolve_common import validate_video
        result = validate_video("/fake/path/file.txt")
        self.assertEqual(result["validation_status"], "rejected")
        self.assertIn("unsupported", result["error"].lower())


class TestSidecarIO(unittest.TestCase):
    def test_write_and_read_sidecar(self):
        from resolve_common import write_sidecar, read_sidecar
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            data = {"feed_id": "TEST_20250220_001_VRCAM-01", "codec": "h264"}
            write_sidecar(path, data)
            loaded = read_sidecar(path)
            self.assertEqual(loaded["feed_id"], "TEST_20250220_001_VRCAM-01")


class TestSessionIO(unittest.TestCase):
    def test_write_and_read_session(self):
        from resolve_common import write_session_manifest, read_session_manifest
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "_session.json")
            data = {"session_id": "TEST_20250220_001", "feed_count": 2}
            write_session_manifest(path, data)
            loaded = read_session_manifest(path)
            self.assertEqual(loaded["session_id"], "TEST_20250220_001")
```

**Step 2: Run test to verify failures**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_common.py -v -k "TestEnsureDirs or TestSessionRegistry or TestDeterministicFeedIndex or TestValidateVideo or TestSidecarIO or TestSessionIO"`
Expected: FAIL — functions not defined

**Step 3: Implement utility functions**

Append to `resolve_common.py`:

```python
# -- Directory Setup ----------------------------------------------------------

def ensure_dirs() -> None:
    """Create all required directories if they don't exist."""
    for d in [INGEST_DIR, STAGING_DIR, ARCHIVE_DIR, DELIVERY_DIR, TOOLS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    for sub in FEED_SUBDIRS:
        (INGEST_DIR / sub).mkdir(exist_ok=True)


# -- Session Registry ---------------------------------------------------------

def load_session_registry() -> dict:
    """Load session sequence registry from disk."""
    if SESSIONS_REGISTRY.exists():
        with open(SESSIONS_REGISTRY, "r") as f:
            return json.load(f)
    return {}


def save_session_registry(registry: dict) -> None:
    """Save session sequence registry to disk."""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    with open(SESSIONS_REGISTRY, "w") as f:
        json.dump(registry, f, indent=2)


def next_session_seq(human_name: str, date: str, registry: dict | None = None) -> int:
    """Get next sequence number for a session name+date combo."""
    if registry is None:
        registry = load_session_registry()
    key = f"{human_name}_{date}"
    current = registry.get(key, 0)
    return current + 1


def register_session(session_id: SessionID) -> None:
    """Register a session in the persistent registry."""
    registry = load_session_registry()
    key = f"{session_id.human_name}_{session_id.date}"
    registry[key] = max(registry.get(key, 0), session_id.seq)
    save_session_registry(registry)


# -- Deterministic Feed Hashing -----------------------------------------------

def deterministic_feed_hash(source_path: str, creation_date: str, file_size: int) -> str:
    """Generate deterministic hash from file identity. Same input = same hash."""
    content = f"{source_path}|{creation_date}|{file_size}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# -- File Validation ----------------------------------------------------------

def get_file_creation_date(path: str) -> str:
    """Get file creation date as YYYYMMDD string."""
    stat = os.stat(path)
    ctime = stat.st_ctime
    return datetime.fromtimestamp(ctime).strftime("%Y%m%d")


def validate_video(path: str) -> dict:
    """Validate a video file using ffprobe. Returns metadata dict with validation_status."""
    ext = Path(path).suffix.lower()
    all_supported = SUPPORTED_VIDEO_EXTS | SUPPORTED_AUDIO_EXTS

    if ext not in all_supported:
        return {
            "validation_status": "rejected",
            "error": f"Unsupported format: {ext}",
            "path": path,
        }

    if not os.path.exists(path):
        return {
            "validation_status": "rejected",
            "error": "File not found",
            "path": path,
        }

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,duration",
                "-show_entries", "format=duration",
                "-of", "json", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        probe = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        return {
            "validation_status": "rejected",
            "error": f"ffprobe failed: {e}",
            "path": path,
        }

    streams = probe.get("streams", [])
    fmt = probe.get("format", {})

    # Audio-only files are valid (mic, envaud feeds)
    if not streams and ext in SUPPORTED_AUDIO_EXTS:
        duration = float(fmt.get("duration", 0))
        return {
            "validation_status": "valid",
            "codec": "audio",
            "width": 0,
            "height": 0,
            "fps": 0.0,
            "duration": duration,
            "is_vfr": False,
            "needs_remux": False,
            "path": path,
        }

    if not streams:
        return {
            "validation_status": "rejected",
            "error": "No video streams found",
            "path": path,
        }

    stream = streams[0]
    codec = stream.get("codec_name", "unknown")
    width = int(stream.get("width", 0))
    height = int(stream.get("height", 0))

    # Parse frame rates for VFR detection
    def parse_rate(rate_str: str) -> float:
        if not rate_str or rate_str == "0/0":
            return 0.0
        if "/" in rate_str:
            num, den = rate_str.split("/")
            return float(num) / float(den) if float(den) != 0 else 0.0
        return float(rate_str)

    r_fps = parse_rate(stream.get("r_frame_rate", "0/0"))
    avg_fps = parse_rate(stream.get("avg_frame_rate", "0/0"))

    # VFR detection: if r_frame_rate and avg_frame_rate differ by >5%, flag as VFR
    is_vfr = False
    if r_fps > 0 and avg_fps > 0:
        ratio = min(r_fps, avg_fps) / max(r_fps, avg_fps)
        is_vfr = ratio < 0.95

    duration = float(stream.get("duration", 0) or fmt.get("duration", 0))
    needs_remux = ext == ".mkv"

    status = "rejected_vfr" if is_vfr else "valid"

    return {
        "validation_status": status,
        "codec": codec,
        "width": width,
        "height": height,
        "fps": round(avg_fps, 3),
        "duration": duration,
        "is_vfr": is_vfr,
        "needs_remux": needs_remux,
        "path": path,
        "error": "Variable frame rate detected" if is_vfr else None,
    }


# -- Remux --------------------------------------------------------------------

def remux_mkv_to_mp4(src: str, dst: str) -> bool:
    """Remux MKV to MP4. Stream-copy first, re-encode if that fails."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)

    # Try stream copy first
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-c", "copy", dst],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode == 0 and os.path.exists(dst):
        return True

    # Fallback: re-encode
    if os.path.exists(dst):
        os.remove(dst)
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-c:v", "libx264", "-crf", "18", "-c:a", "aac", dst],
        capture_output=True, text=True, timeout=1800,
    )
    return result.returncode == 0 and os.path.exists(dst)


# -- Sidecar I/O -------------------------------------------------------------

def write_sidecar(path: str, data: dict) -> None:
    """Write feed sidecar JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def read_sidecar(path: str) -> dict:
    """Read feed sidecar JSON."""
    with open(path, "r") as f:
        return json.load(f)


def write_session_manifest(path: str, data: dict) -> None:
    """Write session manifest JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def read_session_manifest(path: str) -> dict:
    """Read session manifest JSON."""
    with open(path, "r") as f:
        return json.load(f)


# -- Session Listing ----------------------------------------------------------

def list_all_sessions() -> list[dict]:
    """Scan staging dir for all session manifests."""
    sessions = []
    if not STAGING_DIR.exists():
        return sessions
    for entry in sorted(STAGING_DIR.iterdir()):
        if entry.is_dir():
            manifest = entry / "_session.json"
            if manifest.exists():
                sessions.append(read_session_manifest(str(manifest)))
    return sessions


# -- Resolve Connection -------------------------------------------------------

RESOLVE_MODULES_PATH = (
    r"C:\ProgramData\Blackmagic Design"
    r"\DaVinci Resolve\Support\Developer\Scripting\Modules"
)


def connect_resolve():
    """Connect to running DaVinci Resolve instance.

    Manipulates sys.path so scripts can run from any directory.
    Returns resolve object or exits on failure.
    """
    if RESOLVE_MODULES_PATH not in sys.path:
        sys.path.insert(0, RESOLVE_MODULES_PATH)

    try:
        import DaVinciResolveScript as dvr
    except ImportError as e:
        print(f"[ERROR] Cannot import DaVinciResolveScript: {e}")
        print(f"        Modules path: {RESOLVE_MODULES_PATH}")
        print("        Check: RESOLVE_SCRIPT_API, RESOLVE_SCRIPT_LIB, PYTHONPATH env vars")
        sys.exit(1)

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        print("[ERROR] Resolve scriptapp returned None.")
        print("        Is DaVinci Resolve running?")
        print("        Check: Preferences > System > General > External Scripting = Local")
        sys.exit(1)

    version = resolve.GetVersionString()
    print(f"[OK] Connected to Resolve {version}")
    return resolve


# -- Resolve Media Pool Helpers -----------------------------------------------

def find_or_create_bin(media_pool, parent_folder, bin_name: str):
    """Find existing bin by name or create it. Returns folder object."""
    for folder in (parent_folder.GetSubFolderList() or []):
        if folder.GetName() == bin_name:
            return folder
    return media_pool.AddSubFolder(parent_folder, bin_name)


def get_session_clips(media_pool, session_id: str) -> list:
    """Get clips from a specific session's bin. Never scans unscoped."""
    root = media_pool.GetRootFolder()
    raw_bin = None
    for folder in (root.GetSubFolderList() or []):
        if folder.GetName() == "RAW FOOTAGE":
            raw_bin = folder
            break

    if raw_bin is None:
        return []

    session_bin = None
    for folder in (raw_bin.GetSubFolderList() or []):
        if folder.GetName() == session_id:
            session_bin = folder
            break

    if session_bin is None:
        return []

    return session_bin.GetClipList() or []
```

**Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_common.py -v`
Expected: All PASS (except TestEnsureDirs may need real filesystem — verify)

**Step 5: Commit**

```
git add resolve_common.py tests/test_common.py
git commit -m "feat(P0): add resolve_common utilities, validation, sidecar I/O, Resolve connection"
```

---

## Task 3: Ingest Script — File Validation + ID Generation (`resolve_ingest.py`)

**Files:**
- Create: `C:\NB11\resolve-tools\resolve_ingest.py`
- Create: `C:\NB11\resolve-tools\tests\test_ingest.py`

**Step 1: Write failing tests for ingest core logic**

```python
# tests/test_ingest.py
import unittest
import sys
import os
import tempfile
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestScanIngestDir(unittest.TestCase):
    def test_maps_subdirs_to_feed_types(self):
        from resolve_ingest import scan_ingest_dir
        with tempfile.TemporaryDirectory() as td:
            # Create feed type subdirs with dummy files
            vrcam = os.path.join(td, "vrcam")
            os.makedirs(vrcam)
            open(os.path.join(vrcam, "clip1.mp4"), "w").close()
            open(os.path.join(vrcam, "clip2.mp4"), "w").close()
            mic = os.path.join(td, "mic")
            os.makedirs(mic)
            open(os.path.join(mic, "audio1.wav"), "w").close()

            result = scan_ingest_dir(td)
            self.assertIn("VRCAM", result)
            self.assertEqual(len(result["VRCAM"]), 2)
            self.assertIn("MIC", result)
            self.assertEqual(len(result["MIC"]), 1)

    def test_ignores_unknown_subdirs(self):
        from resolve_ingest import scan_ingest_dir
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "randomdir"))
            open(os.path.join(td, "randomdir", "file.mp4"), "w").close()
            result = scan_ingest_dir(td)
            self.assertNotIn("randomdir", result)
            self.assertNotIn("RANDOMDIR", result)


class TestBuildFeedSidecar(unittest.TestCase):
    def test_sidecar_has_required_fields(self):
        from resolve_ingest import build_feed_sidecar
        sidecar = build_feed_sidecar(
            feed_id="TEST_20250220_001_VRCAM-01",
            session_id="TEST_20250220_001",
            feed_type="VRCAM",
            source_path=r"C:\test\clip.mp4",
            original_filename="clip.mp4",
            creation_date="20250220",
            validation={"duration": 30.5, "codec": "h264", "resolution": "1920x1080", "fps": 30.0, "validation_status": "valid"},
        )
        required = {"feed_id", "session_id", "feed_type", "source_path",
                     "original_filename", "creation_date", "duration",
                     "codec", "resolution", "fps", "validation_status", "ingest_timestamp"}
        self.assertTrue(required.issubset(set(sidecar.keys())))


class TestBuildSessionManifest(unittest.TestCase):
    def test_manifest_has_required_fields(self):
        from resolve_ingest import build_session_manifest
        manifest = build_session_manifest(
            session_id="TEST_20250220_001",
            human_name="TEST",
            feeds=["VRCAM-01", "MIC-01"],
        )
        self.assertEqual(manifest["session_id"], "TEST_20250220_001")
        self.assertEqual(manifest["human_name"], "TEST")
        self.assertEqual(manifest["feed_count"], 2)
        self.assertEqual(manifest["sync_method"], "TBD")
        self.assertIsNone(manifest["sync_offset_stub"])


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resolve_ingest'`

**Step 3: Implement ingest core (no Resolve API yet)**

```python
# resolve_ingest.py
"""
resolve_ingest.py -- Validated ingest pipeline for DaVinci Resolve.

Raw video goes in, Session ID-stamped clips come out in Resolve.

Usage:
    py -3.12 resolve_ingest.py --once --session KEYNOTE
    py -3.12 resolve_ingest.py --watch --session KEYNOTE
    py -3.12 resolve_ingest.py --file "C:\path\to\clip.mp4" --session KEYNOTE
    py -3.12 resolve_ingest.py --list
"""

from __future__ import annotations

import argparse
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from resolve_common import (
    INGEST_DIR, STAGING_DIR, ARCHIVE_DIR, FEED_SUBDIRS, FEED_TYPE_MAP,
    SUPPORTED_VIDEO_EXTS, SUPPORTED_AUDIO_EXTS,
    SessionID, FeedID, FeedMetadata,
    connect_resolve, ensure_dirs,
    validate_video, remux_mkv_to_mp4,
    next_session_seq, register_session, load_session_registry,
    deterministic_feed_hash,
    write_sidecar, write_session_manifest, read_session_manifest,
    list_all_sessions, find_or_create_bin, CLIP_COLORS,
)


def scan_ingest_dir(base_dir: str | Path | None = None) -> dict[str, list[str]]:
    """Scan ingest directory subdirs, map feed type to file paths."""
    base = Path(base_dir) if base_dir else INGEST_DIR
    result: dict[str, list[str]] = {}

    for sub in FEED_SUBDIRS:
        subdir = base / sub
        if not subdir.is_dir():
            continue
        feed_type = FEED_TYPE_MAP[sub]
        files = []
        for entry in sorted(subdir.iterdir()):
            if entry.is_file():
                ext = entry.suffix.lower()
                if ext in SUPPORTED_VIDEO_EXTS | SUPPORTED_AUDIO_EXTS:
                    files.append(str(entry))
        if files:
            result[feed_type] = files

    return result


def build_feed_sidecar(
    feed_id: str,
    session_id: str,
    feed_type: str,
    source_path: str,
    original_filename: str,
    creation_date: str,
    validation: dict,
) -> dict:
    """Build sidecar dict for a single feed."""
    return {
        "feed_id": feed_id,
        "session_id": session_id,
        "feed_type": feed_type,
        "source_path": source_path,
        "original_filename": original_filename,
        "creation_date": creation_date,
        "duration": validation.get("duration", 0.0),
        "codec": validation.get("codec", "unknown"),
        "resolution": f"{validation.get('width', 0)}x{validation.get('height', 0)}" if "width" in validation else validation.get("resolution", "0x0"),
        "fps": validation.get("fps", 0.0),
        "validation_status": validation.get("validation_status", "unknown"),
        "ingest_timestamp": datetime.now().isoformat(),
    }


def build_session_manifest(
    session_id: str,
    human_name: str,
    feeds: list[str],
) -> dict:
    """Build session-level manifest."""
    return {
        "session_id": session_id,
        "human_name": human_name,
        "feed_count": len(feeds),
        "feed_list": feeds,
        "sync_method": "TBD",
        "sync_offset_stub": None,
    }


def process_file(
    file_path: str,
    feed_type: str,
    session: SessionID,
    feed_counters: dict[str, int],
    resolve=None,
) -> dict | None:
    """Validate, copy, and catalog a single file. Returns sidecar dict or None on skip."""

    filename = os.path.basename(file_path)
    print(f"  [{feed_type}] {filename} ...", end=" ", flush=True)

    # Validate
    validation = validate_video(file_path)
    status = validation["validation_status"]

    if status == "rejected" or status == "rejected_vfr":
        error = validation.get("error", "unknown")
        print(f"REJECTED ({error})")
        return None

    # Remux MKV if needed
    working_path = file_path
    if validation.get("needs_remux"):
        mp4_name = Path(filename).stem + ".mp4"
        session_dir = STAGING_DIR / str(session)
        session_dir.mkdir(parents=True, exist_ok=True)
        mp4_path = str(session_dir / mp4_name)
        print("REMUX ...", end=" ", flush=True)
        if not remux_mkv_to_mp4(file_path, mp4_path):
            print("REMUX FAILED")
            return None
        working_path = mp4_path
        filename = mp4_name

    # Generate Feed ID
    creation_date = validation.get("creation_date") or datetime.fromtimestamp(os.stat(file_path).st_ctime).strftime("%Y%m%d")
    file_size = os.path.getsize(file_path)
    feed_hash = deterministic_feed_hash(file_path, creation_date, file_size)

    # Increment per-type counter
    counter_key = feed_type
    feed_counters[counter_key] = feed_counters.get(counter_key, 0) + 1
    feed_idx = feed_counters[counter_key]

    feed_id = FeedID(session=session, feed_type=feed_type, index=feed_idx)
    feed_id_str = str(feed_id)

    # Copy to staging (if not already remuxed there)
    session_dir = STAGING_DIR / str(session)
    session_dir.mkdir(parents=True, exist_ok=True)
    staged_path = session_dir / filename
    if working_path != str(staged_path):
        shutil.copy2(working_path, str(staged_path))

    # Write sidecar
    sidecar = build_feed_sidecar(
        feed_id=feed_id_str,
        session_id=str(session),
        feed_type=feed_type,
        source_path=file_path,
        original_filename=os.path.basename(file_path),
        creation_date=creation_date,
        validation=validation,
    )
    sidecar_path = session_dir / f"{feed_id_str}.json"
    write_sidecar(str(sidecar_path), sidecar)

    # Archive copy
    archive_dir = ARCHIVE_DIR / str(session)
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / os.path.basename(file_path)
    if not archive_path.exists():
        shutil.copy2(file_path, str(archive_path))

    print(f"OK → {feed_id_str}")
    return sidecar


def import_to_resolve(resolve, session_id: str, staged_files: list[str]) -> None:
    """Import staged files into Resolve media pool under session bin."""
    if resolve is None:
        print("  [SKIP] Resolve not connected, skipping import")
        return

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if project is None:
        print("  [WARN] No project open in Resolve")
        return

    mp = project.GetMediaPool()
    root = mp.GetRootFolder()

    # Create bin hierarchy: RAW FOOTAGE > {session_id}
    raw_bin = find_or_create_bin(mp, root, "RAW FOOTAGE")
    session_bin = find_or_create_bin(mp, raw_bin, session_id)
    mp.SetCurrentFolder(session_bin)

    # Import
    media_items = mp.ImportMedia(staged_files)
    if not media_items:
        print("  [WARN] ImportMedia returned empty — check file paths")
        return

    # Set clip color Blue (unreviewed)
    for item in media_items:
        item.SetClipColor(CLIP_COLORS["unreviewed"])

    print(f"  [OK] Imported {len(media_items)} clips to RAW FOOTAGE/{session_id}")


def ingest_batch(
    files_by_type: dict[str, list[str]],
    session_name: str,
    resolve=None,
) -> dict:
    """Process a batch of files into a session."""
    # Determine date from first file
    first_file = next(iter(next(iter(files_by_type.values()))))
    creation_date = datetime.fromtimestamp(os.stat(first_file).st_ctime).strftime("%Y%m%d")

    # Get next sequence number
    seq = next_session_seq(session_name, creation_date)
    session = SessionID(human_name=session_name, date=creation_date, seq=seq)
    register_session(session)

    session_id = str(session)
    print(f"\n{'='*60}")
    print(f"  SESSION: {session_id}")
    print(f"{'='*60}")

    feed_counters: dict[str, int] = {}
    sidecars: list[dict] = []
    staged_files: list[str] = []
    skipped = 0

    for feed_type, paths in files_by_type.items():
        for path in paths:
            sidecar = process_file(path, feed_type, session, feed_counters, resolve)
            if sidecar:
                sidecars.append(sidecar)
                # Find the staged file path
                staged = STAGING_DIR / session_id / sidecar["original_filename"]
                if sidecar["original_filename"].endswith(".mkv"):
                    staged = STAGING_DIR / session_id / (Path(sidecar["original_filename"]).stem + ".mp4")
                staged_files.append(str(staged))
            else:
                skipped += 1

    # Write session manifest
    feed_list = [s["feed_id"] for s in sidecars]
    manifest = build_session_manifest(session_id, session_name, feed_list)
    manifest_path = STAGING_DIR / session_id / "_session.json"
    write_session_manifest(str(manifest_path), manifest)

    # Import to Resolve
    if staged_files:
        import_to_resolve(resolve, session_id, staged_files)

    # Summary
    print(f"\n  Summary: {len(sidecars)} ingested, {skipped} skipped")
    print(f"  Staging: {STAGING_DIR / session_id}")
    print(f"  Archive: {ARCHIVE_DIR / session_id}")

    return {
        "session_id": session_id,
        "ingested": len(sidecars),
        "skipped": skipped,
        "feeds": feed_list,
    }


def watch_mode(session_name: str, resolve=None) -> None:
    """Continuous watch mode. Poll every 1s, batch on 30s gap."""
    print(f"[WATCH] Monitoring {INGEST_DIR} for session '{session_name}'")
    print("  Press Ctrl+C to stop\n")

    last_activity = 0.0
    pending: dict[str, list[str]] = {}

    while True:
        try:
            current = scan_ingest_dir()
            if current:
                pending = current
                last_activity = time.time()

            # If we have pending files and 30s have elapsed, process batch
            if pending and last_activity > 0 and (time.time() - last_activity) >= 30:
                ingest_batch(pending, session_name, resolve)
                pending = {}
                last_activity = 0.0

            time.sleep(1)
        except KeyboardInterrupt:
            if pending:
                print("\n[WATCH] Processing remaining files before exit...")
                ingest_batch(pending, session_name, resolve)
            print("\n[WATCH] Stopped.")
            break


def cmd_list() -> None:
    """Print all known sessions."""
    sessions = list_all_sessions()
    if not sessions:
        print("No sessions found.")
        return

    print(f"\n{'SESSION ID':<35} {'FEEDS':>6}  TYPES")
    print("-" * 60)
    for s in sessions:
        sid = s.get("session_id", "?")
        count = s.get("feed_count", 0)
        feeds = s.get("feed_list", [])
        # Extract unique feed types
        types = set()
        for f in feeds:
            parts = f.rsplit("_", 1)
            if len(parts) == 2:
                ft = parts[1].split("-")[0]
                types.add(ft)
        print(f"  {sid:<33} {count:>4}   {', '.join(sorted(types))}")


def main():
    parser = argparse.ArgumentParser(
        description="resolve_ingest -- Validated ingest pipeline for DaVinci Resolve"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--watch", action="store_true", help="Continuous watch mode")
    group.add_argument("--once", action="store_true", help="Process current files and exit")
    group.add_argument("--file", type=str, help="Single file ingest")
    group.add_argument("--list", action="store_true", help="Show all sessions")

    parser.add_argument("--session", type=str, help="Session name (required for ingest)")
    parser.add_argument("--no-resolve", action="store_true", help="Skip Resolve import (filesystem only)")

    args = parser.parse_args()

    if args.list:
        cmd_list()
        return

    if not args.session:
        parser.error("--session is required for ingest operations")

    ensure_dirs()

    resolve = None
    if not args.no_resolve:
        try:
            resolve = connect_resolve()
        except SystemExit:
            print("[WARN] Resolve not available, continuing filesystem-only")

    session_name = args.session.upper()

    if args.watch:
        watch_mode(session_name, resolve)
    elif args.once:
        files = scan_ingest_dir()
        if not files:
            print("No files found in ingest directory.")
            return
        ingest_batch(files, session_name, resolve)
    elif args.file:
        if not os.path.exists(args.file):
            print(f"[ERROR] File not found: {args.file}")
            return
        # Determine feed type from parent dir or prompt
        parent = Path(args.file).parent.name.lower()
        if parent in FEED_SUBDIRS:
            feed_type = parent.upper()
            if parent in {"vrcam", "studcam", "mic", "envaud", "mrrender"}:
                feed_type = {"vrcam": "VRCAM", "studcam": "STUDCAM", "mic": "MIC", "envaud": "ENVAUD", "mrrender": "MRRENDER"}[parent]
        else:
            feed_type = "VRCAM"  # Default, could prompt
            print(f"  [INFO] No feed type subdir detected, defaulting to {feed_type}")

        ingest_batch({feed_type: [args.file]}, session_name, resolve)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_ingest.py -v`
Expected: All PASS

**Step 5: Commit**

```
git add resolve_ingest.py tests/test_ingest.py
git commit -m "feat(P0): add resolve_ingest with validation, ID generation, batch processing"
```

---

## Task 4: Scope Script (`resolve_scope.py`)

**Files:**
- Create: `C:\NB11\resolve-tools\resolve_scope.py`
- Create: `C:\NB11\resolve-tools\tests\test_scope.py`

**Step 1: Write failing tests**

```python
# tests/test_scope.py
import unittest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBuildTimelineRefusesEmpty(unittest.TestCase):
    def test_refuses_empty_session_id(self):
        from resolve_scope import build_timeline
        with self.assertRaises(ValueError):
            build_timeline("", resolve=None)

    def test_refuses_none_session_id(self):
        from resolve_scope import build_timeline
        with self.assertRaises(ValueError):
            build_timeline(None, resolve=None)


class TestBuildMultiTimelineRequiresName(unittest.TestCase):
    def test_refuses_without_name(self):
        from resolve_scope import build_multi_timeline
        with self.assertRaises(ValueError):
            build_multi_timeline(["S1", "S2"], name="", resolve=None)


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_scope.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement resolve_scope.py**

```python
# resolve_scope.py
"""
resolve_scope.py -- Session-scoped timeline builder for DaVinci Resolve.

Every operation requires explicit session or feed scope.
No function may operate on "all clips" or default to unscoped media pool.

Usage:
    py -3.12 resolve_scope.py --list
    py -3.12 resolve_scope.py --build KEYNOTE_20250220_001
    py -3.12 resolve_scope.py --build-feed KEYNOTE_20250220_001_VRCAM-01
    py -3.12 resolve_scope.py --combine KEYNOTE_20250220_001 LIVEJAM_20250220_001 --name "Combined Show"
"""

from __future__ import annotations

import argparse
import os

from resolve_common import (
    STAGING_DIR,
    SessionID, FeedMetadata, SyncOffset,
    connect_resolve, list_all_sessions, read_session_manifest, read_sidecar,
    get_session_clips, find_or_create_bin, sync_strategy,
)


def list_sessions() -> None:
    """Print all Session IDs with feed counts and types."""
    sessions = list_all_sessions()
    if not sessions:
        print("No sessions found.")
        return

    print(f"\n  {'SESSION ID':<35} {'FEEDS':>6}  TYPES")
    print("  " + "-" * 58)
    for s in sessions:
        sid = s.get("session_id", "?")
        count = s.get("feed_count", 0)
        feeds = s.get("feed_list", [])
        types = set()
        for f in feeds:
            parts = f.rsplit("_", 1)
            if len(parts) == 2:
                ft = parts[1].split("-")[0]
                types.add(ft)
        print(f"  {sid:<33} {count:>4}   {', '.join(sorted(types))}")


def get_session_feeds(session_id: str) -> list[dict]:
    """Load all feed sidecars for a session."""
    session_dir = STAGING_DIR / session_id
    if not session_dir.is_dir():
        return []
    feeds = []
    for entry in sorted(session_dir.iterdir()):
        if entry.suffix == ".json" and entry.name != "_session.json":
            feeds.append(read_sidecar(str(entry)))
    return feeds


def get_staged_files(session_id: str) -> list[str]:
    """Get paths to staged media files for a session."""
    session_dir = STAGING_DIR / session_id
    if not session_dir.is_dir():
        return []
    files = []
    for entry in sorted(session_dir.iterdir()):
        if entry.suffix != ".json":
            files.append(str(entry))
    return files


def build_timeline(session_id: str, resolve=None) -> None:
    """Build timeline from ONE session. REFUSE empty/missing session_id."""
    if not session_id:
        raise ValueError("session_id is required. Cannot build unscoped timeline.")

    session_dir = STAGING_DIR / session_id
    if not session_dir.is_dir():
        print(f"[ERROR] Session not found: {session_id}")
        print(f"        Expected: {session_dir}")
        return

    manifest_path = session_dir / "_session.json"
    if not manifest_path.exists():
        print(f"[ERROR] No manifest for session: {session_id}")
        return

    manifest = read_session_manifest(str(manifest_path))
    feeds = get_session_feeds(session_id)
    staged = get_staged_files(session_id)

    print(f"\n  Building timeline for: {session_id}")
    print(f"  Feeds: {len(feeds)}, Files: {len(staged)}")

    if not staged:
        print("  [ERROR] No staged files found")
        return

    if resolve is None:
        print("  [SKIP] Resolve not connected — dry run")
        for f in feeds:
            print(f"    {f.get('feed_id', '?')} — {f.get('feed_type', '?')} — {f.get('duration', 0):.1f}s")
        return

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if project is None:
        print("  [ERROR] No project open in Resolve")
        return

    mp = project.GetMediaPool()
    root = mp.GetRootFolder()

    # Get or create TIMELINES bin
    timelines_bin = find_or_create_bin(mp, root, "TIMELINES")
    mp.SetCurrentFolder(timelines_bin)

    # Import clips from session bin (they should already be imported by ingest)
    clips = get_session_clips(mp, session_id)
    if not clips:
        # Try importing staged files directly
        session_bin_parent = find_or_create_bin(mp, root, "RAW FOOTAGE")
        session_bin = find_or_create_bin(mp, session_bin_parent, session_id)
        mp.SetCurrentFolder(session_bin)
        clips = mp.ImportMedia(staged)
        if not clips:
            print("  [ERROR] No clips available for timeline")
            return
        mp.SetCurrentFolder(timelines_bin)

    # Create timeline
    timeline_name = f"{session_id}_all"
    timeline = mp.CreateTimelineFromClips(timeline_name, clips)
    if timeline is None:
        timeline = mp.CreateEmptyTimeline(timeline_name)
        if timeline:
            mp.AppendToTimeline(clips)

    if timeline is None:
        print(f"  [ERROR] Failed to create timeline: {timeline_name}")
        return

    project.SetCurrentTimeline(timeline)
    item_count = len(timeline.GetItemListInTrack("video", 1) or [])
    print(f"  [OK] Timeline '{timeline_name}' — {item_count} clips")


def build_feed_timeline(feed_id: str, resolve=None) -> None:
    """Build timeline from a single feed within a session."""
    if not feed_id:
        raise ValueError("feed_id is required.")

    # Extract session_id from feed_id (everything before the last _TYPE-N)
    parts = feed_id.rsplit("_", 1)
    if len(parts) != 2:
        print(f"[ERROR] Invalid feed_id format: {feed_id}")
        return

    session_id = parts[0]
    session_dir = STAGING_DIR / session_id

    if not session_dir.is_dir():
        print(f"[ERROR] Session not found: {session_id}")
        return

    # Find this feed's sidecar
    sidecar_path = session_dir / f"{feed_id}.json"
    if not sidecar_path.exists():
        print(f"[ERROR] Feed sidecar not found: {sidecar_path}")
        return

    sidecar = read_sidecar(str(sidecar_path))
    original = sidecar.get("original_filename", "")

    # Find staged file
    staged_file = None
    for entry in session_dir.iterdir():
        if entry.suffix != ".json" and entry.name == original:
            staged_file = str(entry)
            break
        # Check remuxed name
        if entry.suffix != ".json" and entry.stem == os.path.splitext(original)[0]:
            staged_file = str(entry)
            break

    if not staged_file:
        print(f"  [ERROR] Staged file not found for feed {feed_id}")
        return

    print(f"\n  Building feed timeline: {feed_id}")
    print(f"  File: {staged_file}")

    if resolve is None:
        print("  [SKIP] Resolve not connected — dry run")
        return

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    mp = project.GetMediaPool()
    root = mp.GetRootFolder()

    timelines_bin = find_or_create_bin(mp, root, "TIMELINES")
    mp.SetCurrentFolder(timelines_bin)

    clips = mp.ImportMedia([staged_file])
    if not clips:
        print("  [ERROR] Import failed")
        return

    timeline_name = f"{feed_id}"
    timeline = mp.CreateTimelineFromClips(timeline_name, clips)
    if timeline:
        project.SetCurrentTimeline(timeline)
        print(f"  [OK] Timeline '{timeline_name}' created")


def build_multi_timeline(session_ids: list[str], name: str, resolve=None) -> None:
    """Cross-session combine with boundary markers. Requires human-provided name."""
    if not name:
        raise ValueError("Timeline name is required for cross-session combine.")

    if len(session_ids) < 2:
        print("[ERROR] Need at least 2 session IDs to combine")
        return

    for sid in session_ids:
        session_dir = STAGING_DIR / sid
        if not session_dir.is_dir():
            print(f"[ERROR] Session not found: {sid}")
            return

    print(f"\n  Building multi-session timeline: '{name}'")
    print(f"  Sessions: {', '.join(session_ids)}")

    if resolve is None:
        print("  [SKIP] Resolve not connected — dry run")
        for sid in session_ids:
            feeds = get_session_feeds(sid)
            print(f"    {sid}: {len(feeds)} feeds")
        return

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    mp = project.GetMediaPool()
    root = mp.GetRootFolder()

    timelines_bin = find_or_create_bin(mp, root, "TIMELINES")
    mp.SetCurrentFolder(timelines_bin)

    # Create empty timeline
    timeline = mp.CreateEmptyTimeline(name)
    if timeline is None:
        print(f"  [ERROR] Failed to create timeline: {name}")
        return

    project.SetCurrentTimeline(timeline)

    for i, sid in enumerate(session_ids):
        clips = get_session_clips(mp, sid)
        staged = get_staged_files(sid)

        if not clips and staged:
            raw_bin = find_or_create_bin(mp, root, "RAW FOOTAGE")
            sess_bin = find_or_create_bin(mp, raw_bin, sid)
            mp.SetCurrentFolder(sess_bin)
            clips = mp.ImportMedia(staged)
            mp.SetCurrentFolder(timelines_bin)

        if clips:
            mp.AppendToTimeline(clips)

        # Add boundary marker (Orange) at session transition
        if i < len(session_ids) - 1:
            # Get current end frame to place marker
            item_list = timeline.GetItemListInTrack("video", 1) or []
            if item_list:
                last_item = item_list[-1]
                end_frame = last_item.GetEnd()
                timeline.AddMarker(
                    end_frame, "Orange",
                    f"SESSION BOUNDARY",
                    f"End of {sid} / Start of {session_ids[i+1]}",
                    1,
                )

    total = len(timeline.GetItemListInTrack("video", 1) or [])
    print(f"  [OK] Timeline '{name}' — {total} clips from {len(session_ids)} sessions")


def main():
    parser = argparse.ArgumentParser(
        description="resolve_scope -- Session-scoped timeline builder"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List all sessions")
    group.add_argument("--build", type=str, metavar="SESSION_ID", help="Build timeline from one session")
    group.add_argument("--build-feed", type=str, metavar="FEED_ID", help="Build timeline from one feed")
    group.add_argument("--combine", nargs="+", metavar="SESSION_ID", help="Cross-session combine")

    parser.add_argument("--name", type=str, help="Timeline name (required for --combine)")
    parser.add_argument("--no-resolve", action="store_true", help="Skip Resolve (dry run)")

    args = parser.parse_args()

    if args.list:
        list_sessions()
        return

    resolve = None
    if not args.no_resolve:
        try:
            resolve = connect_resolve()
        except SystemExit:
            print("[WARN] Resolve not available, dry run mode")

    if args.build:
        build_timeline(args.build, resolve)
    elif args.build_feed:
        build_feed_timeline(args.build_feed, resolve)
    elif args.combine:
        if not args.name:
            parser.error("--name is required for --combine")
        build_multi_timeline(args.combine, args.name, resolve)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_scope.py -v`
Expected: All PASS

**Step 5: Commit**

```
git add resolve_scope.py tests/test_scope.py
git commit -m "feat(P0): add resolve_scope with session-scoped timeline building"
```

---

## Task 5: Project Template (`resolve_template.py`)

**Files:**
- Create: `C:\NB11\resolve-tools\resolve_template.py`
- Create: `C:\NB11\resolve-tools\tests\test_template.py`

**Step 1: Write failing tests**

```python
# tests/test_template.py
import unittest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBinStructure(unittest.TestCase):
    def test_expected_bins(self):
        from resolve_template import EXPECTED_BINS
        expected = {"RAW FOOTAGE", "SELECTS", "SUBCLIPS", "B-ROLL",
                    "GRAPHICS", "MUSIC & SFX", "TIMELINES", "EXPORTS"}
        self.assertEqual(set(EXPECTED_BINS), expected)


class TestSmartBinDefs(unittest.TestCase):
    def test_color_smart_bins(self):
        from resolve_template import COLOR_SMART_BINS
        self.assertIn("Unreviewed", COLOR_SMART_BINS)
        self.assertEqual(COLOR_SMART_BINS["Unreviewed"], "Blue")

    def test_feed_smart_bins(self):
        from resolve_template import FEED_SMART_BINS
        self.assertIn("VR Cameras", FEED_SMART_BINS)


class TestRenderPresets(unittest.TestCase):
    def test_all_presets_defined(self):
        from resolve_template import RENDER_PRESETS
        expected = {"YouTube 16:9", "TikTok 9:16", "IG Square 1:1", "Archive", "Thumbnail"}
        self.assertEqual(set(RENDER_PRESETS.keys()), expected)

    def test_youtube_preset_values(self):
        from resolve_template import RENDER_PRESETS
        yt = RENDER_PRESETS["YouTube 16:9"]
        self.assertEqual(yt["width"], 1920)
        self.assertEqual(yt["height"], 1080)


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_template.py -v`
Expected: FAIL

**Step 3: Implement resolve_template.py**

```python
# resolve_template.py
"""
resolve_template.py -- DaVinci Resolve project template setup.

One-command project setup: standardized bins, Smart Bins, render presets.

Usage:
    py -3.12 resolve_template.py --setup
    py -3.12 resolve_template.py --check
    py -3.12 resolve_template.py --fix
"""

from __future__ import annotations

import argparse

from resolve_common import connect_resolve, find_or_create_bin, TOOLS_DIR


EXPECTED_BINS = [
    "RAW FOOTAGE",
    "SELECTS",
    "SUBCLIPS",
    "B-ROLL",
    "GRAPHICS",
    "MUSIC & SFX",
    "TIMELINES",
    "EXPORTS",
]

COLOR_SMART_BINS = {
    "Unreviewed": "Blue",
    "Selects": "Green",
    "Needs Review": "Yellow",
    "Rejects": "Red",
    "B-Roll": "Purple",
    "Needs Fix": "Orange",
}

FEED_SMART_BINS = {
    "VR Cameras": "VRCAM",
    "Studio Cameras": "STUDCAM",
    "Audio": "MIC",
    "MR Renders": "MRRENDER",
}

RENDER_PRESETS = {
    "YouTube 16:9": {
        "width": 1920, "height": 1080, "codec": "H.264",
        "video_bitrate": 24000, "audio_codec": "aac", "audio_bitrate": 320,
        "format": "mp4",
    },
    "TikTok 9:16": {
        "width": 1080, "height": 1920, "codec": "H.264",
        "video_bitrate": 15000, "audio_codec": "aac", "audio_bitrate": 256,
        "format": "mp4",
    },
    "IG Square 1:1": {
        "width": 1080, "height": 1080, "codec": "H.264",
        "video_bitrate": 15000, "audio_codec": "aac", "audio_bitrate": 256,
        "format": "mp4",
    },
    "Archive": {
        "width": 0, "height": 0,  # source resolution
        "codec": "ProRes 422 HQ",
        "video_bitrate": 0, "audio_codec": "pcm",  "audio_bitrate": 0,
        "format": "mov",
    },
    "Thumbnail": {
        "width": 0, "height": 0,  # source resolution
        "codec": "PNG",
        "video_bitrate": 0, "audio_codec": "none", "audio_bitrate": 0,
        "format": "png",
    },
}


def setup_bins(resolve) -> list[str]:
    """Create bin structure. Returns list of created bin names."""
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("[ERROR] No project open")
        return []

    mp = project.GetMediaPool()
    root = mp.GetRootFolder()
    existing = {f.GetName() for f in (root.GetSubFolderList() or [])}
    created = []

    for bin_name in EXPECTED_BINS:
        if bin_name in existing:
            print(f"  [EXISTS] {bin_name}")
        else:
            folder = mp.AddSubFolder(root, bin_name)
            if folder:
                print(f"  [CREATED] {bin_name}")
                created.append(bin_name)
            else:
                print(f"  [FAILED] {bin_name}")

    return created


def setup_smart_bins(resolve) -> None:
    """Attempt to create Smart Bins. Print manual instructions if API doesn't support it."""
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        return

    mp = project.GetMediaPool()

    # Try API-based Smart Bin creation
    try:
        for name, color in COLOR_SMART_BINS.items():
            mp.AddSmartBin(name, f"Clip Color is {color}")
            print(f"  [SMART BIN] {name} (Color = {color})")

        for name, feed_type in FEED_SMART_BINS.items():
            mp.AddSmartBin(name, f"Feed Type contains {feed_type}")
            print(f"  [SMART BIN] {name} (Feed Type = {feed_type})")

    except (AttributeError, TypeError):
        print("\n  [INFO] Smart Bin API not available. Manual setup instructions:")
        print("  Media Pool > right-click > Add Smart Bin")
        print()
        for name, color in COLOR_SMART_BINS.items():
            print(f"    Name: {name}  |  Rule: Clip Color is {color}")
        for name, feed_type in FEED_SMART_BINS.items():
            print(f"    Name: {name}  |  Rule: Keyword contains {feed_type}")


def setup_render_presets(resolve) -> None:
    """Set up render presets. Export .setting files if API doesn't support preset saving."""
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        return

    print("\n  Render Presets:")
    for name, preset in RENDER_PRESETS.items():
        print(f"    {name}: {preset['width']}x{preset['height']} {preset['codec']} ({preset['format']})")

    # Resolve API doesn't have a direct "save render preset" function.
    # Print instructions for manual setup.
    print("\n  [INFO] Render presets must be configured manually in Deliver page:")
    print("  Deliver > Render Settings > save as preset")
    print()
    for name, p in RENDER_PRESETS.items():
        if p["width"] > 0:
            print(f"    '{name}': {p['width']}x{p['height']}, {p['codec']}, "
                  f"{p['video_bitrate']}kbps video, {p['audio_codec']} {p['audio_bitrate']}kbps audio")
        else:
            print(f"    '{name}': source resolution, {p['codec']}")


def check_template(resolve) -> list[str]:
    """Check if current project matches template. Returns list of issues."""
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("[ERROR] No project open")
        return ["no_project"]

    mp = project.GetMediaPool()
    root = mp.GetRootFolder()
    existing = {f.GetName() for f in (root.GetSubFolderList() or [])}

    issues = []
    for bin_name in EXPECTED_BINS:
        if bin_name not in existing:
            issues.append(f"Missing bin: {bin_name}")

    if issues:
        print(f"\n  Template drift: {len(issues)} issue(s)")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print("  [OK] Project matches template")

    return issues


def fix_template(resolve) -> None:
    """Fix drift: add missing bins, don't delete extras."""
    issues = check_template(resolve)
    if not issues:
        return

    missing_bins = [i.replace("Missing bin: ", "") for i in issues if i.startswith("Missing bin:")]
    if missing_bins:
        project = resolve.GetProjectManager().GetCurrentProject()
        mp = project.GetMediaPool()
        root = mp.GetRootFolder()
        for name in missing_bins:
            folder = mp.AddSubFolder(root, name)
            if folder:
                print(f"  [FIXED] Created: {name}")
            else:
                print(f"  [FAILED] Could not create: {name}")


def main():
    parser = argparse.ArgumentParser(
        description="resolve_template -- Project template setup"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--setup", action="store_true", help="Create full template")
    group.add_argument("--check", action="store_true", help="Verify template match")
    group.add_argument("--fix", action="store_true", help="Fix drift")

    args = parser.parse_args()
    resolve = connect_resolve()

    if args.setup:
        print("\n  Setting up project template...")
        setup_bins(resolve)
        setup_smart_bins(resolve)
        setup_render_presets(resolve)
        print("\n  [DONE] Template setup complete")
    elif args.check:
        check_template(resolve)
    elif args.fix:
        fix_template(resolve)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_template.py -v`
Expected: All PASS

**Step 5: Commit**

```
git add resolve_template.py tests/test_template.py
git commit -m "feat(P1): add resolve_template with bins, smart bins, render presets"
```

---

## Task 6: Marker Automation (`resolve_markers.py`)

**Files:**
- Create: `C:\NB11\resolve-tools\resolve_markers.py`
- Create: `C:\NB11\resolve-tools\tests\test_markers.py`

**Step 1: Write failing tests**

```python
# tests/test_markers.py
import unittest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestPairMarkers(unittest.TestCase):
    def test_basic_pair(self):
        from resolve_markers import pair_markers
        markers = {
            100: {"color": "Green", "name": "Start 1", "note": "", "duration": 1},
            200: {"color": "Red", "name": "End 1", "note": "", "duration": 1},
        }
        pairs = pair_markers(markers)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0], (100, 200))

    def test_multiple_pairs(self):
        from resolve_markers import pair_markers
        markers = {
            100: {"color": "Green", "name": "", "note": "", "duration": 1},
            200: {"color": "Red", "name": "", "note": "", "duration": 1},
            500: {"color": "Green", "name": "", "note": "", "duration": 1},
            700: {"color": "Red", "name": "", "note": "", "duration": 1},
        }
        pairs = pair_markers(markers)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0], (100, 200))
        self.assertEqual(pairs[1], (500, 700))

    def test_unpaired_green_skipped(self):
        from resolve_markers import pair_markers
        markers = {
            100: {"color": "Green", "name": "", "note": "", "duration": 1},
            # No red
        }
        pairs = pair_markers(markers)
        self.assertEqual(len(pairs), 0)

    def test_overlapping_uses_outermost(self):
        from resolve_markers import pair_markers
        markers = {
            100: {"color": "Green", "name": "", "note": "", "duration": 1},
            150: {"color": "Green", "name": "", "note": "", "duration": 1},
            200: {"color": "Red", "name": "", "note": "", "duration": 1},
            250: {"color": "Red", "name": "", "note": "", "duration": 1},
        }
        pairs = pair_markers(markers)
        # First green pairs with first red, second green pairs with second red
        # But per spec: overlapping = outermost boundaries
        # So we get (100, 250) as the outermost pair
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0], (100, 250))


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_markers.py -v`
Expected: FAIL

**Step 3: Implement resolve_markers.py**

```python
# resolve_markers.py
"""
resolve_markers.py -- Marker-pair subclip automation for DaVinci Resolve.

Converts human-placed Green/Red marker pairs into subclips with inherited metadata.

Usage:
    py -3.12 resolve_markers.py --process
    py -3.12 resolve_markers.py --preview
    py -3.12 resolve_markers.py --session KEYNOTE_20250220_001
"""

from __future__ import annotations

import argparse

from resolve_common import connect_resolve, find_or_create_bin, CLIP_COLORS


def pair_markers(markers: dict) -> list[tuple[int, int]]:
    """Extract Green→Red marker pairs from markers dict.

    markers: {frame: {"color": str, ...}} sorted by frame.
    Returns list of (start_frame, end_frame) tuples.

    Rules:
    - Green = start, Red = end
    - Unpaired markers: skip with warning
    - Overlapping pairs: use outermost boundaries
    """
    greens = []
    reds = []

    for frame in sorted(markers.keys()):
        color = markers[frame].get("color", "")
        if color == "Green":
            greens.append(frame)
        elif color == "Red":
            reds.append(frame)

    if not greens or not reds:
        if greens:
            print(f"  [WARN] {len(greens)} unpaired Green marker(s)")
        if reds:
            print(f"  [WARN] {len(reds)} unpaired Red marker(s)")
        return []

    # Detect overlapping: if greens and reds interleave in unexpected ways,
    # collapse to outermost boundaries
    pairs = []

    # Simple approach: match greens to reds in order
    # If counts don't match, we have overlapping/unpaired
    if len(greens) == len(reds):
        # Check for clean non-overlapping pairs
        clean = True
        for g, r in zip(greens, reds):
            if g >= r:
                clean = False
                break
        if clean:
            return list(zip(greens, reds))

    # Overlapping: use outermost boundaries
    # Find all regions where greens and reds define a span
    all_events = []
    for g in greens:
        all_events.append((g, "green"))
    for r in reds:
        all_events.append((r, "red"))
    all_events.sort(key=lambda x: x[0])

    depth = 0
    start = None
    for frame, kind in all_events:
        if kind == "green":
            if depth == 0:
                start = frame
            depth += 1
        elif kind == "red":
            depth -= 1
            if depth <= 0 and start is not None:
                pairs.append((start, frame))
                start = None
                depth = 0

    if start is not None:
        print(f"  [WARN] Unpaired Green marker at frame {start}")

    return pairs


def process_markers(resolve, preview: bool = False, session_id: str | None = None) -> None:
    """Read markers from active timeline, create subclips from Green/Red pairs."""
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("[ERROR] No project open")
        return

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        print("[ERROR] No active timeline")
        return

    tl_name = timeline.GetName()
    print(f"\n  Timeline: {tl_name}")

    # Scope check: if session_id provided, verify timeline belongs to that session
    if session_id and session_id not in tl_name:
        print(f"  [WARN] Timeline '{tl_name}' may not belong to session '{session_id}'")

    markers = timeline.GetMarkers()
    if not markers:
        print("  No markers found")
        return

    print(f"  Found {len(markers)} markers")
    pairs = pair_markers(markers)

    if not pairs:
        print("  No valid Green/Red pairs found")
        return

    print(f"  {len(pairs)} subclip(s) to create:")

    mp = project.GetMediaPool()
    root = mp.GetRootFolder()
    selects_bin = find_or_create_bin(mp, root, "SELECTS")

    for i, (start, end) in enumerate(pairs):
        duration_frames = end - start
        print(f"    [{i+1}] frames {start}-{end} ({duration_frames} frames)")

        if preview:
            continue

        # Get clips at the marker region
        items = timeline.GetItemListInTrack("video", 1) or []
        for item in items:
            item_start = item.GetStart()
            item_end = item.GetEnd()

            # If this item overlaps our marker pair range
            if item_start <= end and item_end >= start:
                clip_start = max(start, item_start)
                clip_end = min(end, item_end)

                # Create subclip
                pool_item = item.GetMediaPoolItem()
                if pool_item:
                    subclip_name = f"{tl_name}_select_{i+1:03d}"

                    # AddSubClip is not always available; use marker-based approach
                    try:
                        sub = mp.CreateSubClip(
                            pool_item, subclip_name,
                            clip_start, clip_end,
                        )
                        if sub:
                            sub.SetClipColor(CLIP_COLORS["select"])
                            # Move to SELECTS bin
                            mp.MoveClips([sub], selects_bin)
                            print(f"      → {subclip_name} [Green]")
                        else:
                            print(f"      → [WARN] CreateSubClip returned None")
                    except (AttributeError, TypeError) as e:
                        print(f"      → [WARN] SubClip API not available: {e}")

    if preview:
        print("\n  (Preview mode — no subclips created)")
    else:
        print(f"\n  [DONE] Created subclips in SELECTS bin")


def main():
    parser = argparse.ArgumentParser(
        description="resolve_markers -- Marker-pair subclip automation"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--process", action="store_true", help="Create subclips from marker pairs")
    group.add_argument("--preview", action="store_true", help="Dry run")

    parser.add_argument("--session", type=str, help="Scope to specific session")

    args = parser.parse_args()
    resolve = connect_resolve()

    process_markers(resolve, preview=args.preview, session_id=args.session)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_markers.py -v`
Expected: All PASS

**Step 5: Commit**

```
git add resolve_markers.py tests/test_markers.py
git commit -m "feat(P2): add resolve_markers with Green/Red pair extraction and subclip creation"
```

---

## Task 7: Detection Test Harness (`resolve_detect_test.py`)

**Files:**
- Create: `C:\NB11\resolve-tools\resolve_detect_test.py`
- Create: `C:\NB11\resolve-tools\tests\test_detect.py`

**Step 1: Write failing tests**

```python
# tests/test_detect.py
import unittest
import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestDetectorInterface(unittest.TestCase):
    def test_detector_has_name(self):
        from resolve_detect_test import SilenceDetector
        d = SilenceDetector()
        self.assertEqual(d.name, "silence")

    def test_all_detectors_registered(self):
        from resolve_detect_test import ALL_DETECTORS
        names = {d.name for d in ALL_DETECTORS}
        self.assertIn("silence", names)
        self.assertIn("scene_change", names)
        self.assertIn("black_frame", names)
        self.assertIn("audio_peak", names)
        self.assertIn("speaker_change", names)
        self.assertIn("breath", names)


class TestDetectionResult(unittest.TestCase):
    def test_dataclass_fields(self):
        from resolve_detect_test import DetectionResult
        r = DetectionResult(
            start_tc=1.0, end_tc=2.0, confidence=0.95,
            label="silence", detector_name="silence",
        )
        self.assertEqual(r.start_tc, 1.0)
        self.assertEqual(r.confidence, 0.95)


class TestStubDetectors(unittest.TestCase):
    def test_speaker_change_returns_empty(self):
        from resolve_detect_test import SpeakerChangeDetector
        d = SpeakerChangeDetector()
        results = d.detect("nonexistent.mp4")
        self.assertEqual(results, [])

    def test_breath_returns_empty(self):
        from resolve_detect_test import BreathDetector
        d = BreathDetector()
        results = d.detect("nonexistent.mp4")
        self.assertEqual(results, [])


class TestResultsSerialization(unittest.TestCase):
    def test_results_to_json(self):
        from resolve_detect_test import DetectionResult, results_to_json
        results = [
            DetectionResult(1.0, 2.0, 0.9, "silence", "silence"),
            DetectionResult(5.0, 5.5, 0.8, "scene", "scene_change"),
        ]
        j = results_to_json(results)
        parsed = json.loads(j)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["label"], "silence")


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_detect.py -v`
Expected: FAIL

**Step 3: Implement resolve_detect_test.py**

```python
# resolve_detect_test.py
"""
resolve_detect_test.py -- Detection library test harness for DaVinci Resolve.

Iterative testing of automated detection features (silence, scene change, etc.).
Results logged for human review.

Usage:
    py -3.12 resolve_detect_test.py --test "C:\path\to\video.mp4"
    py -3.12 resolve_detect_test.py --test "C:\path\to\video.mp4" --only silence,scene_change
    py -3.12 resolve_detect_test.py --results
    py -3.12 resolve_detect_test.py --inject results.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from resolve_common import TOOLS_DIR, connect_resolve


RESULTS_DIR = TOOLS_DIR / "detect_results"


@dataclass
class DetectionResult:
    start_tc: float
    end_tc: float
    confidence: float
    label: str
    detector_name: str


class Detector(ABC):
    name: str

    @abstractmethod
    def detect(self, media_path: str) -> list[DetectionResult]:
        ...


# -- FFmpeg-based Detectors ---------------------------------------------------

class SilenceDetector(Detector):
    name = "silence"

    def __init__(self, threshold_db: float = -30.0, min_duration: float = 0.5):
        self.threshold_db = threshold_db
        self.min_duration = min_duration

    def detect(self, media_path: str) -> list[DetectionResult]:
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-i", media_path, "-af",
                    f"silencedetect=noise={self.threshold_db}dB:d={self.min_duration}",
                    "-f", "null", "-",
                ],
                capture_output=True, text=True, timeout=300,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        output = result.stderr
        results = []
        starts = []

        for line in output.split("\n"):
            if "silence_start:" in line:
                parts = line.split("silence_start:")
                if len(parts) > 1:
                    try:
                        starts.append(float(parts[1].strip().split()[0]))
                    except (ValueError, IndexError):
                        pass
            elif "silence_end:" in line:
                parts = line.split("silence_end:")
                if len(parts) > 1:
                    try:
                        end = float(parts[1].strip().split()[0])
                        start = starts.pop(0) if starts else end - self.min_duration
                        results.append(DetectionResult(
                            start_tc=start, end_tc=end, confidence=0.9,
                            label="silence", detector_name=self.name,
                        ))
                    except (ValueError, IndexError):
                        pass

        return results


class SceneChangeDetector(Detector):
    name = "scene_change"

    def __init__(self, threshold: float = 0.3):
        self.threshold = threshold

    def detect(self, media_path: str) -> list[DetectionResult]:
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-i", media_path,
                    "-vf", f"select='gt(scene\\,{self.threshold})',showinfo",
                    "-f", "null", "-",
                ],
                capture_output=True, text=True, timeout=300,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        output = result.stderr
        results = []

        for line in output.split("\n"):
            if "pts_time:" in line:
                try:
                    pts_part = line.split("pts_time:")[1]
                    tc = float(pts_part.strip().split()[0])
                    results.append(DetectionResult(
                        start_tc=tc, end_tc=tc + 0.04,  # ~1 frame
                        confidence=0.8, label="scene_change",
                        detector_name=self.name,
                    ))
                except (ValueError, IndexError):
                    pass

        return results


class AudioPeakDetector(Detector):
    name = "audio_peak"

    def __init__(self, peak_threshold_db: float = -3.0):
        self.peak_threshold_db = peak_threshold_db

    def detect(self, media_path: str) -> list[DetectionResult]:
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-i", media_path,
                    "-af", "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.Peak_level",
                    "-f", "null", "-",
                ],
                capture_output=True, text=True, timeout=300,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        output = result.stderr
        results = []
        current_time = 0.0

        for line in output.split("\n"):
            if "pts_time:" in line:
                try:
                    current_time = float(line.split("pts_time:")[1].strip().split()[0])
                except (ValueError, IndexError):
                    pass
            elif "Peak_level" in line and "=" in line:
                try:
                    val = float(line.split("=")[1].strip())
                    if val >= self.peak_threshold_db:
                        results.append(DetectionResult(
                            start_tc=current_time,
                            end_tc=current_time + 0.1,
                            confidence=min(1.0, (val + 20) / 20),
                            label="audio_peak",
                            detector_name=self.name,
                        ))
                except (ValueError, IndexError):
                    pass

        return results


class BlackFrameDetector(Detector):
    name = "black_frame"

    def __init__(self, duration: float = 0.1, pix_th: float = 0.10):
        self.duration = duration
        self.pix_th = pix_th

    def detect(self, media_path: str) -> list[DetectionResult]:
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-i", media_path,
                    "-vf", f"blackdetect=d={self.duration}:pix_th={self.pix_th}",
                    "-f", "null", "-",
                ],
                capture_output=True, text=True, timeout=300,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        output = result.stderr
        results = []

        for line in output.split("\n"):
            if "black_start:" in line:
                try:
                    parts = {}
                    for segment in line.split():
                        if ":" in segment:
                            key, val = segment.split(":", 1)
                            parts[key] = val
                    start = float(parts.get("black_start", 0))
                    end = float(parts.get("black_end", 0))
                    results.append(DetectionResult(
                        start_tc=start, end_tc=end, confidence=0.95,
                        label="black_frame", detector_name=self.name,
                    ))
                except (ValueError, KeyError):
                    pass

        return results


# -- Stub Detectors (future implementation) -----------------------------------

class SpeakerChangeDetector(Detector):
    name = "speaker_change"

    def detect(self, media_path: str) -> list[DetectionResult]:
        # Placeholder: future pyannote or whisper-based implementation
        return []


class BreathDetector(Detector):
    name = "breath"

    def detect(self, media_path: str) -> list[DetectionResult]:
        # Placeholder: future audio transient analysis
        return []


# -- Registry -----------------------------------------------------------------

ALL_DETECTORS: list[Detector] = [
    SilenceDetector(),
    SceneChangeDetector(),
    AudioPeakDetector(),
    BlackFrameDetector(),
    SpeakerChangeDetector(),
    BreathDetector(),
]


def get_detectors(only: list[str] | None = None) -> list[Detector]:
    """Filter detectors by name."""
    if only is None:
        return ALL_DETECTORS
    return [d for d in ALL_DETECTORS if d.name in only]


# -- Results Serialization ----------------------------------------------------

def results_to_json(results: list[DetectionResult]) -> str:
    """Serialize detection results to JSON string."""
    return json.dumps([asdict(r) for r in results], indent=2)


def save_results(media_path: str, results: list[DetectionResult], timings: dict[str, float]) -> str:
    """Save results to JSON file. Returns file path."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(media_path).stem
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{stem}_{ts}.json"
    path = RESULTS_DIR / filename

    data = {
        "media_path": media_path,
        "timestamp": datetime.now().isoformat(),
        "detections": [asdict(r) for r in results],
        "timings": timings,
        "summary": {},
    }

    # Build summary by detector
    by_detector: dict[str, list] = {}
    for r in results:
        by_detector.setdefault(r.detector_name, []).append(r)

    for name, detections in by_detector.items():
        avg_conf = sum(d.confidence for d in detections) / len(detections) if detections else 0
        data["summary"][name] = {
            "count": len(detections),
            "avg_confidence": round(avg_conf, 3),
            "processing_time_sec": round(timings.get(name, 0), 2),
        }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    return str(path)


def run_test(media_path: str, only: list[str] | None = None) -> None:
    """Run detectors against a media file and display results."""
    if not os.path.exists(media_path):
        print(f"[ERROR] File not found: {media_path}")
        return

    detectors = get_detectors(only)
    print(f"\n  Testing: {media_path}")
    print(f"  Detectors: {', '.join(d.name for d in detectors)}")
    print()

    all_results: list[DetectionResult] = []
    timings: dict[str, float] = {}

    for detector in detectors:
        print(f"  [{detector.name}] ...", end=" ", flush=True)
        t0 = time.time()
        results = detector.detect(media_path)
        elapsed = time.time() - t0
        timings[detector.name] = elapsed
        all_results.extend(results)
        print(f"{len(results)} detections ({elapsed:.1f}s)")

    # Save
    path = save_results(media_path, all_results, timings)

    # Console summary
    print(f"\n  {'DETECTOR':<20} {'COUNT':>6} {'AVG CONF':>10} {'TIME':>8}")
    print("  " + "-" * 48)

    by_detector: dict[str, list] = {}
    for r in all_results:
        by_detector.setdefault(r.detector_name, []).append(r)

    for name in sorted(by_detector.keys()):
        dets = by_detector[name]
        avg_conf = sum(d.confidence for d in dets) / len(dets) if dets else 0
        t = timings.get(name, 0)
        print(f"  {name:<20} {len(dets):>6} {avg_conf:>10.3f} {t:>7.1f}s")

    print(f"\n  Results saved: {path}")


def show_results() -> None:
    """Show summary of past test runs."""
    if not RESULTS_DIR.exists():
        print("No results found.")
        return

    files = sorted(RESULTS_DIR.glob("*.json"))
    if not files:
        print("No results found.")
        return

    print(f"\n  {'FILE':<40} {'DETECTIONS':>11} {'DATE':>20}")
    print("  " + "-" * 75)

    for f in files:
        with open(f) as fp:
            data = json.load(fp)
        count = len(data.get("detections", []))
        ts = data.get("timestamp", "?")[:19]
        print(f"  {f.name:<40} {count:>11} {ts:>20}")


def inject_results(results_path: str, resolve=None) -> None:
    """Place detection results as Yellow markers in Resolve timeline."""
    with open(results_path) as f:
        data = json.load(f)

    detections = data.get("detections", [])
    if not detections:
        print("No detections to inject.")
        return

    if resolve is None:
        resolve = connect_resolve()

    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("[ERROR] No project open")
        return

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        print("[ERROR] No active timeline")
        return

    fps = float(timeline.GetSetting("timelineFrameRate") or 24)
    placed = 0

    for det in detections:
        frame = int(det["start_tc"] * fps)
        duration = max(1, int((det["end_tc"] - det["start_tc"]) * fps))
        note = f"[{det['detector_name']}] {det['label']} (conf: {det['confidence']:.2f})"

        timeline.AddMarker(frame, "Yellow", det["label"], note, duration)
        placed += 1

    print(f"  [OK] Placed {placed} Yellow markers on '{timeline.GetName()}'")


def main():
    parser = argparse.ArgumentParser(
        description="resolve_detect_test -- Detection library test harness"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--test", type=str, metavar="FILE", help="Run detectors against file")
    group.add_argument("--results", action="store_true", help="Show past test runs")
    group.add_argument("--inject", type=str, metavar="JSON", help="Inject results as Resolve markers")

    parser.add_argument("--only", type=str, help="Comma-separated detector names")

    args = parser.parse_args()

    if args.results:
        show_results()
    elif args.test:
        only = args.only.split(",") if args.only else None
        run_test(args.test, only)
    elif args.inject:
        inject_results(args.inject)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_detect.py -v`
Expected: All PASS

**Step 5: Commit**

```
git add resolve_detect_test.py tests/test_detect.py
git commit -m "feat(P2): add resolve_detect_test with 6 detectors and test harness"
```

---

## Task 8: Render Delivery (`resolve_deliver.py`)

**Files:**
- Create: `C:\NB11\resolve-tools\resolve_deliver.py`
- Create: `C:\NB11\resolve-tools\tests\test_deliver.py`

**Step 1: Write failing tests**

```python
# tests/test_deliver.py
import unittest
import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestManifestSchema(unittest.TestCase):
    def test_manifest_has_required_fields(self):
        from resolve_deliver import build_manifest
        manifest = build_manifest(
            session_id="TEST_20250220_001",
            timeline_name="test_timeline",
            duration_sec=120.5,
            feeds_used=["VRCAM-01", "STUDCAM-02"],
            deliverables=[],
        )
        required = {"session_id", "generated_at", "source_timeline",
                     "total_duration_sec", "feeds_used", "deliverables",
                     "social_metadata", "analytics_hooks", "feedback_loop"}
        self.assertTrue(required.issubset(set(manifest.keys())))

    def test_social_metadata_placeholders(self):
        from resolve_deliver import build_manifest
        manifest = build_manifest("S1", "tl", 60, [], [])
        sm = manifest["social_metadata"]
        self.assertIn("PLACEHOLDER", sm["title"])
        self.assertIn("PLACEHOLDER", sm["description"])

    def test_feedback_loop_defaults(self):
        from resolve_deliver import build_manifest
        manifest = build_manifest("S1", "tl", 60, [], [])
        fl = manifest["feedback_loop"]
        self.assertEqual(fl["status"], "pending_review")
        self.assertIsNone(fl["reviewer"])


class TestAnalyticsSchema(unittest.TestCase):
    def test_empty_analytics(self):
        from resolve_deliver import build_analytics
        analytics = build_analytics("TEST_20250220_001")
        self.assertEqual(analytics["session_id"], "TEST_20250220_001")
        self.assertEqual(analytics["platform_results"], [])


class TestDeliverableEntry(unittest.TestCase):
    def test_deliverable_fields(self):
        from resolve_deliver import build_deliverable_entry
        entry = build_deliverable_entry(
            platform="youtube",
            filename="test.mp4",
            resolution="1920x1080",
            duration_sec=120.5,
            file_size_bytes=50000000,
            codec="h264",
            render_preset="YouTube 16:9",
        )
        self.assertEqual(entry["platform"], "youtube")
        self.assertEqual(entry["render_preset"], "YouTube 16:9")


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_deliver.py -v`
Expected: FAIL

**Step 3: Implement resolve_deliver.py**

```python
# resolve_deliver.py
"""
resolve_deliver.py -- Render automation + delivery manifest for DaVinci Resolve.

Usage:
    py -3.12 resolve_deliver.py --render KEYNOTE_20250220_001
    py -3.12 resolve_deliver.py --render KEYNOTE_20250220_001 --platform youtube tiktok
    py -3.12 resolve_deliver.py --manifest-only KEYNOTE_20250220_001
    py -3.12 resolve_deliver.py --status
    py -3.12 resolve_deliver.py --list
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

from resolve_common import (
    DELIVERY_DIR, STAGING_DIR,
    connect_resolve, read_session_manifest, list_all_sessions,
)
from resolve_template import RENDER_PRESETS


PLATFORM_MAP = {
    "youtube":   "YouTube 16:9",
    "tiktok":    "TikTok 9:16",
    "instagram": "IG Square 1:1",
    "archive":   "Archive",
    "thumbnails": "Thumbnail",
}


def build_deliverable_entry(
    platform: str,
    filename: str,
    resolution: str,
    duration_sec: float,
    file_size_bytes: int,
    codec: str,
    render_preset: str,
) -> dict:
    """Build a single deliverable entry."""
    return {
        "platform": platform,
        "filename": filename,
        "resolution": resolution,
        "duration_sec": duration_sec,
        "file_size_bytes": file_size_bytes,
        "codec": codec,
        "render_preset": render_preset,
    }


def build_manifest(
    session_id: str,
    timeline_name: str,
    duration_sec: float,
    feeds_used: list[str],
    deliverables: list[dict],
) -> dict:
    """Build delivery manifest with placeholder social metadata."""
    ts = datetime.now().isoformat()
    return {
        "session_id": session_id,
        "generated_at": ts,
        "source_timeline": timeline_name,
        "total_duration_sec": duration_sec,
        "feeds_used": feeds_used,
        "deliverables": deliverables,
        "social_metadata": {
            "title": "[PLACEHOLDER - human entry]",
            "description": "[PLACEHOLDER - human entry]",
            "tags": [],
            "category": "[PLACEHOLDER]",
            "scheduled_publish": None,
            "series_name": None,
            "episode_number": None,
        },
        "analytics_hooks": {
            "tracking_id": f"{session_id}_{ts.replace(':', '').replace('-', '')[:15]}",
            "utm_source": "[PLACEHOLDER]",
            "utm_medium": "[PLACEHOLDER]",
            "utm_campaign": "[PLACEHOLDER]",
            "performance_log_path": f"resolve-delivery/{session_id}/_analytics.json",
        },
        "feedback_loop": {
            "status": "pending_review",
            "reviewer": None,
            "review_notes": None,
            "performance_data": None,
            "iteration_of": None,
            "superseded_by": None,
        },
    }


def build_analytics(session_id: str) -> dict:
    """Build empty analytics feedback file."""
    return {
        "session_id": session_id,
        "platform_results": [],
        "comparison_to_previous": None,
        "recommended_adjustments": None,
    }


def render_session(
    session_id: str,
    platforms: list[str] | None = None,
    resolve=None,
) -> dict:
    """Render session to specified platforms."""
    if platforms is None:
        platforms = list(PLATFORM_MAP.keys())

    session_dir = STAGING_DIR / session_id
    manifest_path = session_dir / "_session.json"
    if not manifest_path.exists():
        print(f"[ERROR] Session manifest not found: {manifest_path}")
        return {}

    manifest = read_session_manifest(str(manifest_path))
    feeds_used = manifest.get("feed_list", [])

    if resolve is None:
        resolve = connect_resolve()

    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("[ERROR] No project open")
        return {}

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        print("[ERROR] No active timeline")
        return {}

    tl_name = timeline.GetName()
    fps = float(timeline.GetSetting("timelineFrameRate") or 24)
    start_frame = timeline.GetStartFrame()
    end_frame = timeline.GetEndFrame()
    duration_sec = (end_frame - start_frame) / fps

    print(f"\n  Session: {session_id}")
    print(f"  Timeline: {tl_name} ({duration_sec:.1f}s @ {fps}fps)")
    print(f"  Platforms: {', '.join(platforms)}")

    deliverables = []

    for platform in platforms:
        preset_name = PLATFORM_MAP.get(platform)
        if not preset_name:
            print(f"  [WARN] Unknown platform: {platform}")
            continue

        preset = RENDER_PRESETS.get(preset_name)
        if not preset:
            print(f"  [WARN] No preset for: {preset_name}")
            continue

        output_dir = DELIVERY_DIR / session_id / platform
        output_dir.mkdir(parents=True, exist_ok=True)

        output_name = f"{session_id}_{platform}"
        ext = preset.get("format", "mp4")

        print(f"\n  [{platform}] Rendering {preset_name}...")

        # Configure render settings
        width = preset["width"] if preset["width"] > 0 else int(timeline.GetSetting("timelineResolutionWidth") or 1920)
        height = preset["height"] if preset["height"] > 0 else int(timeline.GetSetting("timelineResolutionHeight") or 1080)

        settings = {
            "SelectAllFrames": True,
            "TargetDir": str(output_dir),
            "CustomName": output_name,
            "FormatWidth": width,
            "FormatHeight": height,
            "ExportVideo": True,
            "ExportAudio": preset.get("audio_codec", "none") != "none",
        }

        if preset["codec"] == "H.264":
            settings["VideoFormat"] = "mp4"
            settings["VideoCodec"] = "H.264"
            settings["VideoBitRate"] = preset["video_bitrate"]
            settings["AudioCodec"] = "aac"
            settings["AudioBitRate"] = str(preset["audio_bitrate"])
            project.SetCurrentRenderFormatAndCodec("mp4", "H264")
        elif preset["codec"] == "ProRes 422 HQ":
            settings["VideoFormat"] = "mov"
            settings["VideoCodec"] = "ProRes422HQ"
            project.SetCurrentRenderFormatAndCodec("mov", "ProRes422HQ")
        elif preset["codec"] == "PNG":
            settings["VideoFormat"] = "png"
            settings["ExportAudio"] = False
            project.SetCurrentRenderFormatAndCodec("png", "PNG")

        project.SetRenderSettings(settings)
        project.SetCurrentRenderMode(1)

        job_id = project.AddRenderJob()
        if not job_id:
            print(f"  [ERROR] AddRenderJob failed for {platform}")
            continue

        project.StartRendering(job_id)
        while project.IsRenderingInProgress():
            time.sleep(1)
            status = project.GetRenderJobStatus(job_id)
            pct = status.get("CompletionPercentage", 0)
            print(f"\r  [{platform}] Rendering... {pct}%", end="", flush=True)

        status = project.GetRenderJobStatus(job_id)
        job_status = status.get("JobStatus", "unknown")
        print(f"\r  [{platform}] {job_status}                    ")

        output_path = output_dir / f"{output_name}.{ext}"
        if output_path.exists():
            size = output_path.stat().st_size
            deliverables.append(build_deliverable_entry(
                platform=platform,
                filename=output_path.name,
                resolution=f"{width}x{height}",
                duration_sec=duration_sec,
                file_size_bytes=size,
                codec=preset["codec"],
                render_preset=preset_name,
            ))
            print(f"  [{platform}] Output: {output_path} ({size / 1024 / 1024:.1f} MB)")

    # Write manifest
    delivery_manifest = build_manifest(
        session_id=session_id,
        timeline_name=tl_name,
        duration_sec=duration_sec,
        feeds_used=feeds_used,
        deliverables=deliverables,
    )
    manifest_out = DELIVERY_DIR / session_id / "_manifest.json"
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_out, "w") as f:
        json.dump(delivery_manifest, f, indent=2)

    # Write empty analytics
    analytics = build_analytics(session_id)
    analytics_out = DELIVERY_DIR / session_id / "_analytics.json"
    with open(analytics_out, "w") as f:
        json.dump(analytics, f, indent=2)

    print(f"\n  Manifest: {manifest_out}")
    print(f"  Analytics: {analytics_out}")

    return delivery_manifest


def manifest_only(session_id: str) -> None:
    """Generate manifest without rendering."""
    session_dir = STAGING_DIR / session_id
    manifest_path = session_dir / "_session.json"
    if not manifest_path.exists():
        print(f"[ERROR] Session not found: {session_id}")
        return

    session_manifest = read_session_manifest(str(manifest_path))
    feeds = session_manifest.get("feed_list", [])

    delivery_manifest = build_manifest(
        session_id=session_id,
        timeline_name="[not rendered]",
        duration_sec=0.0,
        feeds_used=feeds,
        deliverables=[],
    )

    out_dir = DELIVERY_DIR / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "_manifest.json"
    with open(out, "w") as f:
        json.dump(delivery_manifest, f, indent=2)

    analytics = build_analytics(session_id)
    analytics_out = out_dir / "_analytics.json"
    with open(analytics_out, "w") as f:
        json.dump(analytics, f, indent=2)

    print(f"  Manifest: {out}")


def show_status() -> None:
    """Show pending/completed deliveries."""
    if not DELIVERY_DIR.exists():
        print("No deliveries found.")
        return

    print(f"\n  {'SESSION':<35} {'STATUS':>15} {'DELIVERABLES':>13}")
    print("  " + "-" * 65)

    for entry in sorted(DELIVERY_DIR.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "_manifest.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                m = json.load(f)
            count = len(m.get("deliverables", []))
            status = m.get("feedback_loop", {}).get("status", "unknown")
            print(f"  {entry.name:<35} {status:>15} {count:>13}")
        else:
            print(f"  {entry.name:<35} {'no manifest':>15}")


def list_deliveries() -> None:
    """List all delivery sessions."""
    show_status()


def main():
    parser = argparse.ArgumentParser(
        description="resolve_deliver -- Render automation + delivery manifest"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--render", type=str, metavar="SESSION_ID", help="Render session")
    group.add_argument("--manifest-only", type=str, metavar="SESSION_ID", help="Manifest without render")
    group.add_argument("--status", action="store_true", help="Show delivery status")
    group.add_argument("--list", action="store_true", help="List all deliveries")

    parser.add_argument("--platform", nargs="+", help="Specific platforms to render")

    args = parser.parse_args()

    if args.status or args.list:
        show_status()
    elif args.manifest_only:
        manifest_only(args.manifest_only)
    elif args.render:
        render_session(args.render, args.platform)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_deliver.py -v`
Expected: All PASS

**Step 5: Commit**

```
git add resolve_deliver.py tests/test_deliver.py
git commit -m "feat(P3): add resolve_deliver with render dispatch and manifest generation"
```

---

## Task 9: MCP Server (`resolve_mcp_server.py`)

**Files:**
- Create: `C:\NB11\resolve-tools\resolve_mcp_server.py`
- Create: `C:\NB11\resolve-tools\tests\test_mcp.py`

**Step 1: Write failing tests**

```python
# tests/test_mcp.py
import unittest
import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestAuditLog(unittest.TestCase):
    def test_audit_entry_format(self):
        from resolve_mcp_server import format_audit_entry
        entry = format_audit_entry("resolve_list_sessions", {"limit": 10}, {"sessions": []})
        self.assertIn("resolve_list_sessions", entry)
        self.assertIn("limit", entry)

    def test_not_implemented_response(self):
        from resolve_mcp_server import not_implemented_response
        resp = not_implemented_response("resolve_ingest")
        self.assertEqual(resp["error"], "not_implemented")
        self.assertEqual(resp["tool"], "resolve_ingest")


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_mcp.py -v`
Expected: FAIL

**Step 3: Implement resolve_mcp_server.py**

```python
# resolve_mcp_server.py
"""
resolve_mcp_server.py -- MCP server exposing DaVinci Resolve operations to AI agents.

Transport: stdio
Framework: mcp Python SDK

Usage:
    py -3.12 resolve_mcp_server.py --serve
    py -3.12 resolve_mcp_server.py --test resolve_list_sessions
    py -3.12 resolve_mcp_server.py --audit
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from resolve_common import (
    TOOLS_DIR, STAGING_DIR, DELIVERY_DIR,
    connect_resolve, list_all_sessions, read_session_manifest, read_sidecar,
    get_session_clips, CLIP_COLORS,
)

AUDIT_LOG = TOOLS_DIR / "mcp_audit.log"


# -- Audit Logging ------------------------------------------------------------

def format_audit_entry(tool: str, params: dict, result: dict) -> str:
    """Format an audit log entry."""
    ts = datetime.now().isoformat()
    return json.dumps({
        "timestamp": ts,
        "tool": tool,
        "params": params,
        "result_summary": str(result)[:200],
    })


def log_audit(tool: str, params: dict, result: dict) -> None:
    """Append to audit log."""
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    entry = format_audit_entry(tool, params, result)
    with open(AUDIT_LOG, "a") as f:
        f.write(entry + "\n")


def not_implemented_response(tool: str) -> dict:
    """Standard response for tools whose backing scripts aren't built yet."""
    return {"error": "not_implemented", "tool": tool}


# -- Read Operations ----------------------------------------------------------

def resolve_list_sessions(**kwargs) -> dict:
    """List all Session IDs with feed counts, types, durations."""
    sessions = list_all_sessions()
    result = {"sessions": sessions, "count": len(sessions)}
    log_audit("resolve_list_sessions", kwargs, result)
    return result


def resolve_list_feeds(session_id: str) -> dict:
    """List all feeds in a session with metadata."""
    session_dir = STAGING_DIR / session_id
    if not session_dir.is_dir():
        result = {"error": f"Session not found: {session_id}"}
        log_audit("resolve_list_feeds", {"session_id": session_id}, result)
        return result

    feeds = []
    for entry in sorted(session_dir.iterdir()):
        if entry.suffix == ".json" and entry.name != "_session.json":
            feeds.append(read_sidecar(str(entry)))

    result = {"session_id": session_id, "feeds": feeds, "count": len(feeds)}
    log_audit("resolve_list_feeds", {"session_id": session_id}, result)
    return result


def resolve_get_metadata(feed_id: str) -> dict:
    """Full sidecar JSON for a feed."""
    # Extract session_id from feed_id
    parts = feed_id.rsplit("_", 1)
    if len(parts) != 2:
        return {"error": f"Invalid feed_id: {feed_id}"}

    session_id = parts[0]
    sidecar_path = STAGING_DIR / session_id / f"{feed_id}.json"
    if not sidecar_path.exists():
        return {"error": f"Sidecar not found: {sidecar_path}"}

    result = read_sidecar(str(sidecar_path))
    log_audit("resolve_get_metadata", {"feed_id": feed_id}, result)
    return result


def resolve_list_timelines() -> dict:
    """List all timelines with session scope info. Requires Resolve connection."""
    try:
        resolve = connect_resolve()
    except SystemExit:
        return {"error": "Resolve not available"}

    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}

    timelines = []
    count = project.GetTimelineCount()
    for i in range(1, count + 1):
        tl = project.GetTimelineByIndex(i)
        if tl:
            timelines.append({
                "name": tl.GetName(),
                "index": i,
            })

    result = {"timelines": timelines, "count": len(timelines)}
    log_audit("resolve_list_timelines", {}, result)
    return result


def resolve_query_markers(timeline_name: str = "", marker_type: str = "") -> dict:
    """Markers on timeline, optional filter by color."""
    try:
        resolve = connect_resolve()
    except SystemExit:
        return {"error": "Resolve not available"}

    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}

    timeline = project.GetCurrentTimeline()
    if not timeline:
        return {"error": "No active timeline"}

    markers = timeline.GetMarkers() or {}
    if marker_type:
        markers = {k: v for k, v in markers.items() if v.get("color") == marker_type}

    result = {"timeline": timeline.GetName(), "markers": markers, "count": len(markers)}
    log_audit("resolve_query_markers", {"timeline_name": timeline_name, "marker_type": marker_type}, result)
    return result


def resolve_render_status() -> dict:
    """Current render queue status."""
    try:
        resolve = connect_resolve()
    except SystemExit:
        return {"error": "Resolve not available"}

    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}

    is_rendering = project.IsRenderingInProgress()
    result = {"is_rendering": is_rendering}
    log_audit("resolve_render_status", {}, result)
    return result


def resolve_delivery_status(session_id: str = "") -> dict:
    """Manifest data for delivered sessions."""
    if session_id:
        manifest_path = DELIVERY_DIR / session_id / "_manifest.json"
        if not manifest_path.exists():
            return {"error": f"No delivery found for: {session_id}"}
        with open(manifest_path) as f:
            result = json.load(f)
        log_audit("resolve_delivery_status", {"session_id": session_id}, result)
        return result

    # List all deliveries
    deliveries = []
    if DELIVERY_DIR.exists():
        for entry in sorted(DELIVERY_DIR.iterdir()):
            manifest = entry / "_manifest.json"
            if manifest.exists():
                with open(manifest) as f:
                    deliveries.append(json.load(f))

    result = {"deliveries": deliveries, "count": len(deliveries)}
    log_audit("resolve_delivery_status", {}, result)
    return result


def resolve_search_clips(query: str) -> dict:
    """Search clips by metadata fields."""
    sessions = list_all_sessions()
    matches = []

    for session in sessions:
        sid = session.get("session_id", "")
        if query.lower() in sid.lower():
            matches.append(session)
            continue
        for feed_id in session.get("feed_list", []):
            if query.lower() in feed_id.lower():
                matches.append(session)
                break

    result = {"query": query, "matches": matches, "count": len(matches)}
    log_audit("resolve_search_clips", {"query": query}, result)
    return result


# -- Write Operations ---------------------------------------------------------

def resolve_ingest(path: str, session_name: str) -> dict:
    """Trigger ingest pipeline."""
    try:
        from resolve_ingest import scan_ingest_dir, ingest_batch
        files = scan_ingest_dir(path) if os.path.isdir(path) else {"VRCAM": [path]}
        result = ingest_batch(files, session_name)
        log_audit("resolve_ingest", {"path": path, "session_name": session_name}, result)
        return result
    except ImportError:
        return not_implemented_response("resolve_ingest")


def resolve_build_timeline(session_id: str) -> dict:
    """Build scoped timeline."""
    try:
        from resolve_scope import build_timeline
        resolve = connect_resolve()
        build_timeline(session_id, resolve)
        result = {"status": "ok", "session_id": session_id}
        log_audit("resolve_build_timeline", {"session_id": session_id}, result)
        return result
    except ImportError:
        return not_implemented_response("resolve_build_timeline")


def resolve_build_feed_timeline(feed_id: str) -> dict:
    """Single-feed timeline."""
    try:
        from resolve_scope import build_feed_timeline
        resolve = connect_resolve()
        build_feed_timeline(feed_id, resolve)
        result = {"status": "ok", "feed_id": feed_id}
        log_audit("resolve_build_feed_timeline", {"feed_id": feed_id}, result)
        return result
    except ImportError:
        return not_implemented_response("resolve_build_feed_timeline")


def resolve_add_marker(timeline_name: str, tc: float, color: str, note: str) -> dict:
    """Place marker on timeline."""
    try:
        resolve = connect_resolve()
    except SystemExit:
        return {"error": "Resolve not available"}

    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}

    timeline = project.GetCurrentTimeline()
    if not timeline:
        return {"error": "No active timeline"}

    fps = float(timeline.GetSetting("timelineFrameRate") or 24)
    frame = int(tc * fps)
    timeline.AddMarker(frame, color, note, "", 1)

    result = {"status": "ok", "frame": frame, "color": color}
    log_audit("resolve_add_marker", {"tc": tc, "color": color, "note": note}, result)
    return result


def resolve_process_markers(timeline_name: str = "") -> dict:
    """Run marker-pair subclip extraction."""
    try:
        from resolve_markers import process_markers
        resolve = connect_resolve()
        process_markers(resolve, preview=False)
        result = {"status": "ok"}
        log_audit("resolve_process_markers", {"timeline_name": timeline_name}, result)
        return result
    except ImportError:
        return not_implemented_response("resolve_process_markers")


def resolve_render(session_id: str, platforms: list[str] | None = None) -> dict:
    """Kick off render."""
    try:
        from resolve_deliver import render_session
        result = render_session(session_id, platforms)
        log_audit("resolve_render", {"session_id": session_id, "platforms": platforms}, result)
        return result
    except ImportError:
        return not_implemented_response("resolve_render")


def resolve_set_clip_color(clip_name: str, color: str) -> dict:
    """Update clip review status by color."""
    if color not in CLIP_COLORS.values():
        return {"error": f"Invalid color: {color}. Valid: {list(CLIP_COLORS.values())}"}

    try:
        resolve = connect_resolve()
    except SystemExit:
        return {"error": "Resolve not available"}

    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}

    mp = project.GetMediaPool()
    root = mp.GetRootFolder()

    # Search for clip by name in all bins
    def search_folder(folder):
        for clip in (folder.GetClipList() or []):
            if clip.GetName() == clip_name:
                return clip
        for sub in (folder.GetSubFolderList() or []):
            found = search_folder(sub)
            if found:
                return found
        return None

    clip = search_folder(root)
    if not clip:
        return {"error": f"Clip not found: {clip_name}"}

    clip.SetClipColor(color)
    result = {"status": "ok", "clip": clip_name, "color": color}
    log_audit("resolve_set_clip_color", {"clip_name": clip_name, "color": color}, result)
    return result


def resolve_promote_to_selects(clip_name: str) -> dict:
    """Move clip to SELECTS bin + set Green."""
    result = resolve_set_clip_color(clip_name, "Green")
    if "error" in result:
        return result

    try:
        resolve = connect_resolve()
        project = resolve.GetProjectManager().GetCurrentProject()
        mp = project.GetMediaPool()
        root = mp.GetRootFolder()

        from resolve_common import find_or_create_bin
        selects_bin = find_or_create_bin(mp, root, "SELECTS")

        # Find clip again
        def search_folder(folder):
            for clip in (folder.GetClipList() or []):
                if clip.GetName() == clip_name:
                    return clip
            for sub in (folder.GetSubFolderList() or []):
                found = search_folder(sub)
                if found:
                    return found
            return None

        clip = search_folder(root)
        if clip:
            mp.MoveClips([clip], selects_bin)

        result = {"status": "ok", "clip": clip_name, "promoted": True}
        log_audit("resolve_promote_to_selects", {"clip_name": clip_name}, result)
        return result
    except Exception as e:
        return {"error": str(e)}


# -- MCP Server ---------------------------------------------------------------

TOOLS = {
    # Read
    "resolve_list_sessions": resolve_list_sessions,
    "resolve_list_feeds": resolve_list_feeds,
    "resolve_get_metadata": resolve_get_metadata,
    "resolve_list_timelines": resolve_list_timelines,
    "resolve_query_markers": resolve_query_markers,
    "resolve_render_status": resolve_render_status,
    "resolve_delivery_status": resolve_delivery_status,
    "resolve_search_clips": resolve_search_clips,
    # Write
    "resolve_ingest": resolve_ingest,
    "resolve_build_timeline": resolve_build_timeline,
    "resolve_build_feed_timeline": resolve_build_feed_timeline,
    "resolve_add_marker": resolve_add_marker,
    "resolve_process_markers": resolve_process_markers,
    "resolve_render": resolve_render,
    "resolve_set_clip_color": resolve_set_clip_color,
    "resolve_promote_to_selects": resolve_promote_to_selects,
}


def start_mcp_server():
    """Start MCP server using stdio transport."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import Tool, TextContent, Resource
    except ImportError:
        print("[ERROR] mcp package not installed. Run: pip install mcp")
        return

    server = Server("resolve-mcp")

    @server.list_tools()
    async def list_tools():
        tool_defs = []
        for name, func in TOOLS.items():
            doc = func.__doc__ or name
            tool_defs.append(Tool(
                name=name,
                description=doc.strip().split("\n")[0],
                inputSchema={"type": "object", "properties": {}},
            ))
        return tool_defs

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name not in TOOLS:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        try:
            result = TOOLS[name](**arguments)
        except TypeError as e:
            result = {"error": f"Invalid arguments: {e}"}
        except Exception as e:
            result = {"error": str(e)}

        return [TextContent(type="text", text=json.dumps(result, default=str))]

    @server.list_resources()
    async def list_resources():
        return [
            Resource(uri="resolve://sessions", name="All sessions", mimeType="application/json"),
        ]

    @server.read_resource()
    async def read_resource(uri: str):
        if uri == "resolve://sessions":
            return json.dumps(resolve_list_sessions())
        if uri.startswith("resolve://session/"):
            sid = uri.split("/")[-1]
            return json.dumps(resolve_list_feeds(sid))
        if uri.startswith("resolve://delivery/"):
            sid = uri.split("/")[-1]
            return json.dumps(resolve_delivery_status(sid))
        if uri.startswith("resolve://analytics/"):
            sid = uri.split("/")[-1]
            analytics_path = DELIVERY_DIR / sid / "_analytics.json"
            if analytics_path.exists():
                with open(analytics_path) as f:
                    return f.read()
            return json.dumps({"error": "Analytics not found"})
        return json.dumps({"error": f"Unknown resource: {uri}"})

    import asyncio
    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


def test_tool(tool_name: str, args_json: str = "{}") -> None:
    """Test a single tool invocation."""
    if tool_name not in TOOLS:
        print(f"[ERROR] Unknown tool: {tool_name}")
        print(f"  Available: {', '.join(TOOLS.keys())}")
        return

    args = json.loads(args_json) if args_json else {}
    print(f"  Tool: {tool_name}")
    print(f"  Args: {json.dumps(args)}")

    result = TOOLS[tool_name](**args)
    print(f"  Result:\n{json.dumps(result, indent=2, default=str)}")


def show_audit() -> None:
    """Print recent audit log."""
    if not AUDIT_LOG.exists():
        print("No audit log found.")
        return

    with open(AUDIT_LOG) as f:
        lines = f.readlines()

    print(f"\n  Last 20 audit entries ({len(lines)} total):\n")
    for line in lines[-20:]:
        try:
            entry = json.loads(line)
            print(f"  [{entry['timestamp'][:19]}] {entry['tool']}")
        except json.JSONDecodeError:
            print(f"  {line.strip()}")


def main():
    parser = argparse.ArgumentParser(
        description="resolve_mcp_server -- MCP server for DaVinci Resolve"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--serve", action="store_true", help="Start MCP server (stdio)")
    group.add_argument("--test", type=str, metavar="TOOL", help="Test tool invocation")
    group.add_argument("--audit", action="store_true", help="Show audit log")

    parser.add_argument("--args", type=str, default="{}", help="JSON args for --test")

    args = parser.parse_args()

    if args.serve:
        start_mcp_server()
    elif args.test:
        test_tool(args.test, args.args)
    elif args.audit:
        show_audit()


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\test_mcp.py -v`
Expected: All PASS

**Step 5: Commit**

```
git add resolve_mcp_server.py tests/test_mcp.py
git commit -m "feat(P4): add resolve_mcp_server with 16 tools, resources, and audit log"
```

---

## Task 10: Integration Test + Directory Setup

**Files:**
- Create: `C:\NB11\resolve-tools\tests\test_integration.py`

**Step 1: Write integration tests (filesystem only, no Resolve)**

```python
# tests/test_integration.py
"""Integration tests for the full pipeline (filesystem operations only, no Resolve)."""
import unittest
import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestIngestToScopeContract(unittest.TestCase):
    """Verify ingest output is valid input for scope."""

    def test_session_manifest_readable_by_scope(self):
        from resolve_ingest import build_session_manifest
        from resolve_common import write_session_manifest, read_session_manifest

        manifest = build_session_manifest("TEST_20250220_001", "TEST", ["VRCAM-01", "MIC-01"])

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "_session.json")
            write_session_manifest(path, manifest)
            loaded = read_session_manifest(path)

            # Scope needs these fields
            self.assertIn("session_id", loaded)
            self.assertIn("feed_list", loaded)
            self.assertIn("feed_count", loaded)

    def test_feed_sidecar_has_duration(self):
        from resolve_ingest import build_feed_sidecar
        sidecar = build_feed_sidecar(
            feed_id="T_20250220_001_VRCAM-01",
            session_id="T_20250220_001",
            feed_type="VRCAM",
            source_path="test.mp4",
            original_filename="test.mp4",
            creation_date="20250220",
            validation={"duration": 30.5, "codec": "h264", "width": 1920, "height": 1080, "fps": 30.0, "validation_status": "valid"},
        )
        self.assertGreater(sidecar["duration"], 0)


class TestDeliverManifestSchema(unittest.TestCase):
    """Verify delivery manifest matches expected schema."""

    def test_manifest_round_trip(self):
        from resolve_deliver import build_manifest

        manifest = build_manifest("S1", "tl", 120.0, ["V-01"], [
            {"platform": "youtube", "filename": "out.mp4", "resolution": "1920x1080",
             "duration_sec": 120.0, "file_size_bytes": 5000000, "codec": "h264",
             "render_preset": "YouTube 16:9"},
        ])

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "_manifest.json")
            with open(path, "w") as f:
                json.dump(manifest, f)
            with open(path) as f:
                loaded = json.load(f)

            self.assertEqual(loaded["session_id"], "S1")
            self.assertEqual(len(loaded["deliverables"]), 1)
            self.assertIn("social_metadata", loaded)
            self.assertIn("analytics_hooks", loaded)
            self.assertIn("feedback_loop", loaded)


class TestMCPToolRegistry(unittest.TestCase):
    """Verify all expected MCP tools are registered."""

    def test_all_read_tools(self):
        from resolve_mcp_server import TOOLS
        read_tools = [
            "resolve_list_sessions", "resolve_list_feeds", "resolve_get_metadata",
            "resolve_list_timelines", "resolve_query_markers", "resolve_render_status",
            "resolve_delivery_status", "resolve_search_clips",
        ]
        for tool in read_tools:
            self.assertIn(tool, TOOLS)

    def test_all_write_tools(self):
        from resolve_mcp_server import TOOLS
        write_tools = [
            "resolve_ingest", "resolve_build_timeline", "resolve_build_feed_timeline",
            "resolve_add_marker", "resolve_process_markers", "resolve_render",
            "resolve_set_clip_color", "resolve_promote_to_selects",
        ]
        for tool in write_tools:
            self.assertIn(tool, TOOLS)


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run all tests**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\ -v`
Expected: All PASS

**Step 3: Create directory structure**

```powershell
py -3.12 -c "from resolve_common import ensure_dirs; ensure_dirs()"
```

**Step 4: Commit**

```
git add tests/test_integration.py
git commit -m "feat: add integration tests and create directory structure"
```

---

## Task 11: Final Verification

**Step 1: Run full test suite**

Run: `py -3.12 -m pytest C:\NB11\resolve-tools\tests\ -v --tb=short`
Expected: All PASS

**Step 2: Verify CLI help for all scripts**

Run each:
```
py -3.12 resolve_ingest.py --help
py -3.12 resolve_scope.py --help
py -3.12 resolve_template.py --help
py -3.12 resolve_markers.py --help
py -3.12 resolve_detect_test.py --help
py -3.12 resolve_deliver.py --help
py -3.12 resolve_mcp_server.py --help
```
Expected: Each prints usage without error.

**Step 3: Verify directory structure**

```
ls C:\NB11\resolve-ingest\
ls C:\NB11\resolve-staging\
ls C:\NB11\resolve-archive\
ls C:\NB11\resolve-delivery\
ls C:\NB11\resolve-tools\
```

**Step 4: Final commit**

```
git add -A
git commit -m "chore: complete resolve asset management system v1"
```
