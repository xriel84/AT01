"""EdBot output watcher — monitors output folder for new video files.

Uses watchdog to detect new .mp4/.mkv/.webm files in output dir.
On new file: probe with ffprobe, update manifest.json, push event
to registered callback functions (used by server.py WebSocket).

No external API calls. Local filesystem only.
"""

import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WATCH_DIR = "output"
DEFAULT_MANIFEST = "output/manifest.json"
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".webm")
SETTLE_WAIT = 1.0  # seconds to wait for file writes to finish
SETTLE_RETRIES = 3


# ---------------------------------------------------------------------------
# ffprobe helper
# ---------------------------------------------------------------------------

def probe_file(filepath: str) -> dict[str, Any]:
    """Probe a video file with ffprobe and return metadata dict.

    Returns dict with: filename, path, duration, size_mb, width, height,
    codec, created.  On ffprobe failure, returns minimal metadata (name + size).
    """
    p = Path(filepath)
    stat = p.stat()
    base_info: dict[str, Any] = {
        "filename": p.name,
        "path": str(p),
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "created": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
    }

    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name",
        "-show_entries", "format=duration",
        "-of", "json",
        str(p),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.warning("ffprobe failed for %s: %s", filepath, result.stderr[:200])
            return base_info

        data = json.loads(result.stdout)
        stream = (data.get("streams") or [{}])[0]
        fmt = data.get("format") or {}

        base_info["duration"] = float(fmt["duration"]) if "duration" in fmt else None
        base_info["width"] = stream.get("width")
        base_info["height"] = stream.get("height")
        base_info["codec"] = stream.get("codec_name")

    except FileNotFoundError:
        logger.warning("ffprobe not found — returning minimal metadata for %s", filepath)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, ValueError, OSError) as exc:
        logger.warning("ffprobe error for %s: %s", filepath, exc)

    return base_info


# ---------------------------------------------------------------------------
# Manifest management
# ---------------------------------------------------------------------------

def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load manifest from disk, or return empty structure."""
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"watch_dir": DEFAULT_WATCH_DIR, "files": [], "last_updated": None}


def _save_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    """Write manifest to disk."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest["last_updated"] = datetime.now(tz=timezone.utc).isoformat()
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


# ---------------------------------------------------------------------------
# File event handler
# ---------------------------------------------------------------------------

class _VideoHandler(FileSystemEventHandler):
    """Handles watchdog events for new video files."""

    def __init__(self, watcher: "OutputWatcher"):
        super().__init__()
        self._watcher = watcher

    def on_created(self, event):
        if not isinstance(event, FileCreatedEvent):
            return
        self._watcher._handle_new_file(event.src_path)

    def on_moved(self, event):
        if not isinstance(event, FileMovedEvent):
            return
        self._watcher._handle_new_file(event.dest_path)


# ---------------------------------------------------------------------------
# OutputWatcher
# ---------------------------------------------------------------------------

class OutputWatcher:
    """Watches an output directory for new video files.

    On detection: waits for write to settle, probes metadata with ffprobe,
    updates manifest.json, and fires the on_new_file callback.
    """

    def __init__(
        self,
        watch_dir: str = DEFAULT_WATCH_DIR,
        manifest_path: str = DEFAULT_MANIFEST,
        extensions: tuple[str, ...] = VIDEO_EXTENSIONS,
        on_new_file: Optional[Callable[[dict[str, Any]], None]] = None,
    ):
        self.watch_dir = Path(watch_dir)
        self.manifest_path = Path(manifest_path)
        self.extensions = extensions
        self.on_new_file = on_new_file

        self._observer: Optional[Observer] = None
        self._lock = threading.Lock()
        self._seen: set[str] = set()

        # Pre-populate seen set from existing manifest
        manifest = _load_manifest(self.manifest_path)
        for entry in manifest.get("files", []):
            self._seen.add(entry.get("filename", ""))

    def start(self) -> None:
        """Start watching. Non-blocking (runs observer thread)."""
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        handler = _VideoHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.watch_dir), recursive=False)
        self._observer.start()
        logger.info("OutputWatcher started on %s", self.watch_dir)

    def stop(self) -> None:
        """Stop watching. Joins observer thread."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info("OutputWatcher stopped")

    def get_manifest(self) -> dict[str, Any]:
        """Return current manifest as dict."""
        return _load_manifest(self.manifest_path)

    def _handle_new_file(self, filepath: str) -> None:
        """Process a newly detected file (called from handler thread)."""
        p = Path(filepath)

        # Filter by extension
        if p.suffix.lower() not in self.extensions:
            return

        # Deduplicate
        with self._lock:
            if p.name in self._seen:
                return
            self._seen.add(p.name)

        # Wait for file to settle (still being written)
        if not self._wait_for_settle(p):
            return

        # Probe metadata
        file_info = probe_file(str(p))

        # Update manifest
        with self._lock:
            manifest = _load_manifest(self.manifest_path)
            # Double-check not already in manifest
            existing = {e["filename"] for e in manifest.get("files", [])}
            if p.name not in existing:
                manifest.setdefault("files", []).append(file_info)
                manifest["watch_dir"] = str(self.watch_dir)
                _save_manifest(self.manifest_path, manifest)

        # Fire callback
        if self.on_new_file is not None:
            try:
                self.on_new_file(file_info)
            except Exception as exc:
                logger.warning("on_new_file callback error: %s", exc)

    def _wait_for_settle(self, filepath: Path) -> bool:
        """Wait until file size stabilizes. Returns True if settled."""
        for _ in range(SETTLE_RETRIES):
            try:
                size1 = filepath.stat().st_size
            except OSError:
                return False
            time.sleep(SETTLE_WAIT)
            try:
                size2 = filepath.stat().st_size
            except OSError:
                return False
            if size1 == size2 and size2 > 0:
                return True
        return True  # Proceed anyway after max retries
