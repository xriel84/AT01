"""Scan Google Drive for video files.

Uses the Google Drive API v3 to list video files in a folder or
across the entire Drive. Returns metadata without downloading.

Requires a credentials.json or token.json for OAuth2 authentication.
"""

import json
import os
from pathlib import Path
from typing import Any

VIDEO_MIME_TYPES = [
    "video/mp4", "video/quicktime", "video/x-msvideo", "video/x-matroska",
    "video/webm", "video/x-flv", "video/x-ms-wmv", "video/mpeg",
    "video/mp2t", "video/3gpp",
]

# Build the MIME type query fragment once
_MIME_QUERY = " or ".join(f"mimeType='{m}'" for m in VIDEO_MIME_TYPES)


def _get_drive_service(credentials_path: str | None = None, token_path: str | None = None):
    """Build and return an authenticated Google Drive API service.

    Args:
        credentials_path: Path to OAuth2 credentials.json (for initial auth).
        token_path: Path to cached token.json (reused on subsequent calls).
    """
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request as AuthRequest
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

    creds = None
    token_file = Path(token_path) if token_path else Path("temp/gdrive_token.json")
    creds_file = Path(credentials_path) if credentials_path else Path("temp/gdrive_credentials.json")

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(AuthRequest())
        else:
            if not creds_file.exists():
                return None, f"credentials file not found: {creds_file}"
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
            creds = flow.run_local_server(port=0)

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json())

    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return service, None


def scan_drive(
    folder_id: str | None = None,
    credentials_path: str | None = None,
    token_path: str | None = None,
    max_results: int = 100,
) -> dict[str, Any]:
    """Scan Google Drive for video files.

    Args:
        folder_id: Optional Drive folder ID to scope the scan.
        credentials_path: Path to OAuth2 credentials.json.
        token_path: Path to cached token.json.
        max_results: Maximum number of results (default 100).

    Returns:
        Dict with keys: source, videos, total_count, total_size_mb.
    """
    service, err = _get_drive_service(credentials_path, token_path)
    if err:
        return {"error": err, "code": "AUTH_ERROR"}

    query_parts = [f"({_MIME_QUERY})", "trashed=false"]
    if folder_id:
        query_parts.append(f"'{folder_id}' in parents")

    query = " and ".join(query_parts)

    videos = []
    page_token = None

    try:
        while len(videos) < max_results:
            page_size = min(100, max_results - len(videos))
            resp = service.files().list(
                q=query,
                pageSize=page_size,
                fields="nextPageToken, files(id,name,mimeType,size,createdTime,modifiedTime,parents)",
                pageToken=page_token,
            ).execute()

            for f in resp.get("files", []):
                size_bytes = int(f.get("size", 0))
                videos.append({
                    "id": f["id"],
                    "name": f["name"],
                    "mime_type": f["mimeType"],
                    "size_mb": round(size_bytes / (1024 * 1024), 2),
                    "created": f.get("createdTime"),
                    "modified": f.get("modifiedTime"),
                    "parents": f.get("parents", []),
                    "source": "google_drive",
                })

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    except Exception as exc:
        return {"error": f"Drive API error: {exc}", "code": "API_ERROR"}

    total_size = sum(v["size_mb"] for v in videos)

    return {
        "source": "google_drive",
        "folder_id": folder_id,
        "videos": videos,
        "total_count": len(videos),
        "total_size_mb": round(total_size, 2),
    }
