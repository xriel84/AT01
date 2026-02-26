"""Video catalog — orchestrates scanning, probing, and frame analysis.

Combines drive_scanner, dropbox_scanner, video_prober, and frame_scanner
into a unified catalog. Stores results as JSON for querying.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CATALOG_PATH = Path("temp/video_catalog.json")


def _load_catalog(catalog_path: Path | None = None) -> dict[str, Any]:
    """Load existing catalog from disk or return empty catalog."""
    cp = catalog_path or CATALOG_PATH
    if cp.exists():
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "version": 1,
        "created": datetime.now(timezone.utc).isoformat(),
        "updated": None,
        "entries": {},
    }


def _save_catalog(catalog: dict[str, Any], catalog_path: Path | None = None) -> str:
    """Save catalog to disk. Returns the file path."""
    cp = catalog_path or CATALOG_PATH
    cp.parent.mkdir(parents=True, exist_ok=True)
    catalog["updated"] = datetime.now(timezone.utc).isoformat()
    cp.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return str(cp)


def catalog_entry_from_probe(probe: dict[str, Any], source: str = "local") -> dict[str, Any]:
    """Create a catalog entry from a video_prober result."""
    return {
        "filename": probe.get("filename"),
        "path": probe.get("path"),
        "source": source,
        "duration_sec": probe.get("duration_sec"),
        "width": probe.get("width"),
        "height": probe.get("height"),
        "fps": probe.get("fps"),
        "video_codec": probe.get("video_codec"),
        "audio_codec": probe.get("audio_codec"),
        "bitrate_kbps": probe.get("bitrate_kbps"),
        "file_size_mb": probe.get("file_size_mb"),
        "format_name": probe.get("format_name"),
        "scenes": None,
        "frame_labels": None,
        "added": datetime.now(timezone.utc).isoformat(),
    }


def catalog_entry_from_cloud(cloud_meta: dict[str, Any]) -> dict[str, Any]:
    """Create a catalog entry from a cloud scanner result (Drive/Dropbox)."""
    return {
        "filename": cloud_meta.get("name"),
        "path": cloud_meta.get("path") or cloud_meta.get("id"),
        "source": cloud_meta.get("source", "cloud"),
        "duration_sec": None,
        "width": None,
        "height": None,
        "fps": None,
        "video_codec": None,
        "audio_codec": None,
        "bitrate_kbps": None,
        "file_size_mb": cloud_meta.get("size_mb"),
        "format_name": None,
        "cloud_id": cloud_meta.get("id"),
        "cloud_modified": cloud_meta.get("modified"),
        "scenes": None,
        "frame_labels": None,
        "added": datetime.now(timezone.utc).isoformat(),
    }


def ingest_local(
    directory: str,
    recursive: bool = True,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Scan a local directory, probe each video, and add to catalog.

    Returns dict with keys: added, skipped, total, catalog_path.
    """
    from video_prober import scan_local_dir

    scan_result = scan_local_dir(directory, recursive=recursive)
    if scan_result.get("error"):
        return scan_result

    catalog = _load_catalog(catalog_path)
    added = 0
    skipped = 0

    for video in scan_result["videos"]:
        key = video.get("path", video.get("filename"))
        if key in catalog["entries"]:
            skipped += 1
            continue
        catalog["entries"][key] = catalog_entry_from_probe(video, source="local")
        added += 1

    saved = _save_catalog(catalog, catalog_path)

    return {
        "added": added,
        "skipped": skipped,
        "total": len(catalog["entries"]),
        "catalog_path": saved,
    }


def ingest_drive(
    folder_id: str | None = None,
    credentials_path: str | None = None,
    token_path: str | None = None,
    max_results: int = 100,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Scan Google Drive and add video entries to catalog.

    Returns dict with keys: added, skipped, total, catalog_path.
    """
    from drive_scanner import scan_drive

    scan_result = scan_drive(
        folder_id=folder_id,
        credentials_path=credentials_path,
        token_path=token_path,
        max_results=max_results,
    )
    if scan_result.get("error"):
        return scan_result

    catalog = _load_catalog(catalog_path)
    added = 0
    skipped = 0

    for video in scan_result["videos"]:
        key = f"gdrive:{video['id']}"
        if key in catalog["entries"]:
            skipped += 1
            continue
        catalog["entries"][key] = catalog_entry_from_cloud(video)
        added += 1

    saved = _save_catalog(catalog, catalog_path)

    return {
        "added": added,
        "skipped": skipped,
        "total": len(catalog["entries"]),
        "catalog_path": saved,
    }


def ingest_dropbox(
    folder_path: str = "",
    access_token: str | None = None,
    recursive: bool = True,
    max_results: int = 100,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Scan Dropbox and add video entries to catalog.

    Returns dict with keys: added, skipped, total, catalog_path.
    """
    from dropbox_scanner import scan_dropbox

    scan_result = scan_dropbox(
        folder_path=folder_path,
        access_token=access_token,
        recursive=recursive,
        max_results=max_results,
    )
    if scan_result.get("error"):
        return scan_result

    catalog = _load_catalog(catalog_path)
    added = 0
    skipped = 0

    for video in scan_result["videos"]:
        key = f"dropbox:{video['id']}"
        if key in catalog["entries"]:
            skipped += 1
            continue
        catalog["entries"][key] = catalog_entry_from_cloud(video)
        added += 1

    saved = _save_catalog(catalog, catalog_path)

    return {
        "added": added,
        "skipped": skipped,
        "total": len(catalog["entries"]),
        "catalog_path": saved,
    }


def enrich_with_frames(
    entry_key: str,
    labels: list[str] | None = None,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Run frame analysis (scenes + CLIP) on a catalog entry and update it.

    Only works for local files (source=local with a valid path).
    Returns the updated entry or error.
    """
    from frame_scanner import scan_frames

    catalog = _load_catalog(catalog_path)
    entry = catalog["entries"].get(entry_key)
    if not entry:
        return {"error": f"entry not found: {entry_key}", "code": "NOT_FOUND"}
    if entry.get("source") != "local":
        return {"error": "frame analysis only available for local files", "code": "NOT_LOCAL"}

    video_path = entry.get("path")
    if not video_path or not Path(video_path).exists():
        return {"error": f"video file not found: {video_path}", "code": "FILE_NOT_FOUND"}

    result = scan_frames(video_path, labels=labels)
    if result.get("error"):
        return result

    entry["scenes"] = result.get("scenes")
    entry["frame_labels"] = [
        f.get("labels", []) for f in result.get("frames", [])
    ]
    entry["scene_count"] = result.get("scene_count")

    _save_catalog(catalog, catalog_path)

    return {
        "entry_key": entry_key,
        "scene_count": result.get("scene_count"),
        "frames_labeled": len(result.get("frames", [])),
        "status": "enriched",
    }


def get_catalog(catalog_path: Path | None = None) -> dict[str, Any]:
    """Return the full catalog."""
    return _load_catalog(catalog_path)


def search_catalog(
    query: str,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Search catalog entries by filename or frame label.

    Returns matching entries.
    """
    catalog = _load_catalog(catalog_path)
    query_lower = query.lower()
    matches = []

    for key, entry in catalog["entries"].items():
        # Search filename
        if query_lower in (entry.get("filename") or "").lower():
            matches.append({"key": key, "match_type": "filename", **entry})
            continue

        # Search frame labels
        frame_labels = entry.get("frame_labels") or []
        for frame_group in frame_labels:
            for lbl in frame_group:
                if query_lower in (lbl.get("label") or "").lower():
                    matches.append({"key": key, "match_type": "frame_label", "matched_label": lbl["label"], **entry})
                    break
            else:
                continue
            break

    return {
        "query": query,
        "results": matches,
        "count": len(matches),
    }
