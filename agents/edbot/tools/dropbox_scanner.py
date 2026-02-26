"""Scan Dropbox for video files.

Uses the Dropbox Python SDK to list video files in a folder or
recursively from root. Returns metadata without downloading.

Requires a Dropbox access token (app or user token).
"""

import os
from pathlib import PurePosixPath
from typing import Any

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv",
    ".wmv", ".mpg", ".mpeg", ".ts", ".mts", ".3gp",
}


def _get_dropbox_client(access_token: str | None = None):
    """Build and return a Dropbox client.

    Args:
        access_token: Dropbox access token. Falls back to
                      DROPBOX_ACCESS_TOKEN env var.
    """
    import dropbox

    token = access_token or os.environ.get("DROPBOX_ACCESS_TOKEN")
    if not token:
        return None, "no access token — set DROPBOX_ACCESS_TOKEN or pass access_token"

    try:
        dbx = dropbox.Dropbox(token)
        dbx.users_get_current_account()
        return dbx, None
    except Exception as exc:
        return None, f"Dropbox auth failed: {exc}"


def scan_dropbox(
    folder_path: str = "",
    access_token: str | None = None,
    recursive: bool = True,
    max_results: int = 100,
) -> dict[str, Any]:
    """Scan Dropbox for video files.

    Args:
        folder_path: Dropbox folder path (e.g. "/Videos"). Empty string = root.
        access_token: Dropbox access token (or set DROPBOX_ACCESS_TOKEN env var).
        recursive: Whether to scan subfolders.
        max_results: Maximum number of results (default 100).

    Returns:
        Dict with keys: source, folder_path, videos, total_count, total_size_mb.
    """
    import dropbox

    dbx, err = _get_dropbox_client(access_token)
    if err:
        return {"error": err, "code": "AUTH_ERROR"}

    videos = []

    try:
        result = dbx.files_list_folder(folder_path, recursive=recursive)

        while True:
            for entry in result.entries:
                if len(videos) >= max_results:
                    break

                if not isinstance(entry, dropbox.files.FileMetadata):
                    continue

                ext = PurePosixPath(entry.name).suffix.lower()
                if ext not in VIDEO_EXTENSIONS:
                    continue

                videos.append({
                    "id": entry.id,
                    "name": entry.name,
                    "path": entry.path_display,
                    "size_mb": round(entry.size / (1024 * 1024), 2),
                    "modified": entry.server_modified.isoformat() if entry.server_modified else None,
                    "content_hash": entry.content_hash,
                    "source": "dropbox",
                })

            if not result.has_more or len(videos) >= max_results:
                break
            result = dbx.files_list_folder_continue(result.cursor)

    except Exception as exc:
        return {"error": f"Dropbox API error: {exc}", "code": "API_ERROR"}

    total_size = sum(v["size_mb"] for v in videos)

    return {
        "source": "dropbox",
        "folder_path": folder_path or "/",
        "videos": videos,
        "total_count": len(videos),
        "total_size_mb": round(total_size, 2),
    }
