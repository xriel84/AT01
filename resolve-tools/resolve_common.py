"""resolve_common.py -- Types, constants, and ID system for NB11 Resolve tools.

Foundation module. Every other resolve_*.py script imports from here.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(r"C:\NB11")
INGEST_DIR = PROJECT_ROOT / "resolve-ingest"
STAGING_DIR = PROJECT_ROOT / "resolve-staging"
ARCHIVE_DIR = PROJECT_ROOT / "resolve-archive"
DELIVERY_DIR = PROJECT_ROOT / "resolve-delivery"
TOOLS_DIR = PROJECT_ROOT / "resolve-tools"
SESSIONS_REGISTRY = STAGING_DIR / "_sessions.json"


# ---------------------------------------------------------------------------
# Feed taxonomy
# ---------------------------------------------------------------------------

FEED_SUBDIRS: set[str] = {"vrcam", "studcam", "mic", "envaud", "mrrender"}

FEED_TYPE_MAP: dict[str, str] = {
    "vrcam": "VRCAM",
    "studcam": "STUDCAM",
    "mic": "MIC",
    "envaud": "ENVAUD",
    "mrrender": "MRRENDER",
}

SUPPORTED_VIDEO_EXTS: set[str] = {".mp4", ".mov", ".mkv", ".avi", ".mxf", ".webm"}
SUPPORTED_AUDIO_EXTS: set[str] = {".wav", ".flac", ".aac", ".mp3", ".ogg"}


# ---------------------------------------------------------------------------
# Clip color labels (Resolve marker / clip color names)
# ---------------------------------------------------------------------------

CLIP_COLORS: dict[str, str] = {
    "unreviewed": "Blue",
    "select": "Green",
    "needs_review": "Yellow",
    "reject": "Red",
    "broll": "Purple",
    "needs_fix": "Orange",
}


# ---------------------------------------------------------------------------
# ID dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionID:
    """Identifies a single capture session.

    String form: ``{human_name}_{date}_{seq:03d}``
    Example:     ``KEYNOTE_20250220_001``
    """

    human_name: str
    date: str  # YYYYMMDD
    seq: int

    def __str__(self) -> str:
        return f"{self.human_name}_{self.date}_{self.seq:03d}"


@dataclass(frozen=True)
class FeedID:
    """Identifies a single feed within a session.

    String form: ``{session}_{feed_type}-{index:02d}``
    Example:     ``KEYNOTE_20250220_001_VRCAM-03``
    """

    session: SessionID
    feed_type: str  # e.g. VRCAM, STUDCAM, MIC, ENVAUD, MRRENDER
    index: int

    def __str__(self) -> str:
        return f"{self.session}_{self.feed_type}-{self.index:02d}"


# ---------------------------------------------------------------------------
# Feed metadata
# ---------------------------------------------------------------------------

@dataclass
class FeedMetadata:
    """Metadata collected during ingest for a single feed file."""

    feed_id: str
    session_id: str
    feed_type: str
    source_path: str
    original_filename: str
    creation_date: str
    duration: float = 0.0
    codec: str = ""
    resolution: str = ""
    fps: float = 0.0
    validation_status: str = ""
    ingest_timestamp: str = ""


# ---------------------------------------------------------------------------
# Sync types
# ---------------------------------------------------------------------------

@dataclass
class SyncOffset:
    """Offset for aligning a feed to the session timeline."""

    feed_id: str
    offset: float = 0.0  # seconds


class SyncStrategy(ABC):
    """Abstract base for feed-synchronisation strategies."""

    @abstractmethod
    def align(self, feeds: list[FeedMetadata]) -> list[SyncOffset]:
        """Return a SyncOffset for each feed, expressing its offset from a
        common zero point."""
        ...


class TBDSync(SyncStrategy):
    """Placeholder strategy -- returns zero offsets for every feed."""

    def align(self, feeds: list[FeedMetadata]) -> list[SyncOffset]:
        return [SyncOffset(feed_id=f.feed_id, offset=0.0) for f in feeds]


# Module-level default strategy instance
sync_strategy: SyncStrategy = TBDSync()


# ---------------------------------------------------------------------------
# Resolve scripting path
# ---------------------------------------------------------------------------

RESOLVE_MODULES_PATH = r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"


# ---------------------------------------------------------------------------
# Directory management
# ---------------------------------------------------------------------------

def ensure_dirs() -> None:
    """Create all standard project directories and ingest subdirectories."""
    for d in (INGEST_DIR, STAGING_DIR, ARCHIVE_DIR, DELIVERY_DIR, TOOLS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    for sub in FEED_SUBDIRS:
        (INGEST_DIR / sub).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Session registry (JSON-backed sequence counter)
# ---------------------------------------------------------------------------

def load_session_registry() -> dict:
    """Load the session registry from disk.  Returns {} if the file is missing."""
    if SESSIONS_REGISTRY.exists():
        with open(SESSIONS_REGISTRY, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_session_registry(registry: dict) -> None:
    """Persist *registry* to the SESSIONS_REGISTRY JSON file."""
    SESSIONS_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    with open(SESSIONS_REGISTRY, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)


def next_session_seq(human_name: str, date: str, *, registry: dict | None = None) -> int:
    """Return the next sequence number for *human_name* + *date*.

    If *registry* is provided it is used directly (useful for testing);
    otherwise the on-disk registry is loaded.
    """
    if registry is None:
        registry = load_session_registry()
    key = f"{human_name}_{date}"
    current = registry.get(key, 0)
    return current + 1


def register_session(session_id: SessionID) -> None:
    """Increment the on-disk registry for *session_id*."""
    registry = load_session_registry()
    key = f"{session_id.human_name}_{session_id.date}"
    registry[key] = session_id.seq
    save_session_registry(registry)


# ---------------------------------------------------------------------------
# Deterministic feed hashing
# ---------------------------------------------------------------------------

def deterministic_feed_hash(source_path: str, creation_date: str, file_size: int) -> str:
    """SHA-256 of ``"{source_path}|{creation_date}|{file_size}"``, first 16 hex chars."""
    payload = f"{source_path}|{creation_date}|{file_size}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def get_file_creation_date(path: str) -> str:
    """Return the file creation date (st_ctime) as YYYYMMDD."""
    ts = os.stat(path).st_ctime
    return datetime.fromtimestamp(ts).strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# Video validation (ffprobe-based)
# ---------------------------------------------------------------------------

def validate_video(path: str) -> dict:
    """Validate a media file using ffprobe.

    Returns a dict with keys: validation_status, codec, width, height, fps,
    duration, is_vfr, needs_remux, error.
    """
    result: dict = {
        "validation_status": "",
        "codec": "",
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "duration": 0.0,
        "is_vfr": False,
        "needs_remux": False,
        "error": "",
    }

    ext = os.path.splitext(path)[1].lower()
    all_supported = SUPPORTED_VIDEO_EXTS | SUPPORTED_AUDIO_EXTS
    if ext not in all_supported:
        result["validation_status"] = "rejected"
        result["error"] = f"Unsupported extension: {ext}"
        return result

    # Audio-only files are valid without ffprobe video stream checks
    if ext in SUPPORTED_AUDIO_EXTS:
        try:
            probe_cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", path,
            ]
            proc = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0:
                info = json.loads(proc.stdout)
                fmt = info.get("format", {})
                result["duration"] = float(fmt.get("duration", 0.0))
                result["codec"] = fmt.get("format_name", "")
            result["validation_status"] = "valid"
        except Exception as exc:
            result["validation_status"] = "valid"
            result["error"] = str(exc)
        return result

    # Video files -- probe streams
    try:
        probe_cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", path,
        ]
        proc = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            result["validation_status"] = "rejected"
            result["error"] = f"ffprobe failed: {proc.stderr.strip()}"
            return result

        info = json.loads(proc.stdout)
        fmt = info.get("format", {})
        result["duration"] = float(fmt.get("duration", 0.0))

        # Find first video stream
        video_stream = None
        for s in info.get("streams", []):
            if s.get("codec_type") == "video":
                video_stream = s
                break

        if video_stream is None:
            # No video stream -- treat as audio-only, still valid
            result["validation_status"] = "valid"
            result["codec"] = fmt.get("format_name", "")
            return result

        result["codec"] = video_stream.get("codec_name", "")
        result["width"] = int(video_stream.get("width", 0))
        result["height"] = int(video_stream.get("height", 0))

        # Parse frame rates for VFR detection
        r_frame_rate = video_stream.get("r_frame_rate", "0/1")
        avg_frame_rate = video_stream.get("avg_frame_rate", "0/1")

        def _parse_rate(rate_str: str) -> float:
            if "/" in rate_str:
                num, den = rate_str.split("/")
                den_f = float(den)
                return float(num) / den_f if den_f != 0 else 0.0
            return float(rate_str) if rate_str else 0.0

        r_fps = _parse_rate(r_frame_rate)
        avg_fps = _parse_rate(avg_frame_rate)
        result["fps"] = avg_fps if avg_fps > 0 else r_fps

        # VFR detection: >5% difference between r_frame_rate and avg_frame_rate
        if r_fps > 0 and avg_fps > 0:
            diff_pct = abs(r_fps - avg_fps) / max(r_fps, avg_fps)
            if diff_pct > 0.05:
                result["is_vfr"] = True
                result["validation_status"] = "rejected_vfr"
                result["error"] = (
                    f"Variable frame rate detected: r={r_fps:.2f} avg={avg_fps:.2f} "
                    f"({diff_pct:.1%} diff)"
                )
                return result

        # MKV needs remux
        if ext == ".mkv":
            result["needs_remux"] = True

        result["validation_status"] = "valid"

    except FileNotFoundError:
        result["validation_status"] = "rejected"
        result["error"] = "ffprobe not found on PATH"
    except Exception as exc:
        result["validation_status"] = "rejected"
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# MKV remux
# ---------------------------------------------------------------------------

def remux_mkv_to_mp4(src: str, dst: str) -> bool:
    """Remux *src* MKV to *dst* MP4 via stream copy; re-encode on failure.

    Returns True on success, False on failure.
    """
    # Attempt 1: stream copy
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-c", "copy", dst],
            capture_output=True, text=True, timeout=600,
        )
        if proc.returncode == 0:
            return True
    except Exception:
        pass

    # Attempt 2: re-encode fallback
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-c:v", "libx264", "-crf", "18",
             "-c:a", "aac", "-b:a", "192k", dst],
            capture_output=True, text=True, timeout=1800,
        )
        return proc.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Sidecar JSON I/O
# ---------------------------------------------------------------------------

def write_sidecar(path: str | Path, data: dict) -> None:
    """Write *data* as pretty-printed JSON to *path*."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def read_sidecar(path: str | Path) -> dict:
    """Read and return a sidecar JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Session manifest I/O
# ---------------------------------------------------------------------------

def write_session_manifest(path: str | Path, data: dict) -> None:
    """Write a session manifest (``_session.json``) to *path*."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def read_session_manifest(path: str | Path) -> dict:
    """Read and return a session manifest JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_all_sessions() -> list[dict]:
    """Scan STAGING_DIR subdirectories for ``_session.json`` files.

    Returns a list of parsed session manifest dicts.
    """
    sessions: list[dict] = []
    if not STAGING_DIR.exists():
        return sessions
    for entry in STAGING_DIR.iterdir():
        if entry.is_dir():
            manifest = entry / "_session.json"
            if manifest.exists():
                sessions.append(read_session_manifest(manifest))
    return sessions


# ---------------------------------------------------------------------------
# DaVinci Resolve connection
# ---------------------------------------------------------------------------

def connect_resolve():
    """Import the DaVinci Resolve scripting module and return the Resolve object.

    Adds RESOLVE_MODULES_PATH to sys.path if not already present, then
    imports ``DaVinciResolveScript`` and calls ``scriptapp("Resolve")``.
    Exits with helpful messages on failure.
    """
    if RESOLVE_MODULES_PATH not in sys.path:
        sys.path.insert(0, RESOLVE_MODULES_PATH)

    try:
        import DaVinciResolveScript as dvr  # type: ignore[import-not-found]
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


# ---------------------------------------------------------------------------
# Resolve bin helpers
# ---------------------------------------------------------------------------

def find_or_create_bin(media_pool, parent_folder, bin_name: str):
    """Find an existing subfolder named *bin_name* under *parent_folder*,
    or create it via ``AddSubFolder``.

    Returns the folder object.
    """
    for sub in (parent_folder.GetSubFolderList() or []):
        if sub.GetName() == bin_name:
            return sub
    return media_pool.AddSubFolder(parent_folder, bin_name)


def get_session_clips(media_pool, session_id: str) -> list:
    """Navigate to ``RAW FOOTAGE / {session_id}`` bin and return its clip list.

    Returns an empty list if the bin path does not exist.
    Never scans outside the scoped bin.
    """
    root = media_pool.GetRootFolder()
    # Find "RAW FOOTAGE" bin
    raw_folder = None
    for sub in (root.GetSubFolderList() or []):
        if sub.GetName() == "RAW FOOTAGE":
            raw_folder = sub
            break
    if raw_folder is None:
        return []

    # Find session bin
    session_folder = None
    for sub in (raw_folder.GetSubFolderList() or []):
        if sub.GetName() == session_id:
            session_folder = sub
            break
    if session_folder is None:
        return []

    return session_folder.GetClipList() or []
