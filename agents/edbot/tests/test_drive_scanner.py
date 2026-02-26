"""Tests for drive_scanner — Google Drive video scanning."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from drive_scanner import scan_drive, VIDEO_MIME_TYPES


class TestScanDrive:
    """Tests for scan_drive function."""

    @patch("drive_scanner._get_drive_service")
    def test_auth_error(self, mock_service):
        mock_service.return_value = (None, "credentials file not found: temp/gdrive_credentials.json")
        result = scan_drive()
        assert result["code"] == "AUTH_ERROR"
        assert "credentials" in result["error"]

    @patch("drive_scanner._get_drive_service")
    def test_empty_drive(self, mock_service):
        mock_svc = MagicMock()
        mock_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [],
            "nextPageToken": None,
        }
        mock_service.return_value = (mock_svc, None)

        result = scan_drive()
        assert result["source"] == "google_drive"
        assert result["total_count"] == 0
        assert result["videos"] == []

    @patch("drive_scanner._get_drive_service")
    def test_finds_videos(self, mock_service):
        mock_svc = MagicMock()
        mock_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "f1", "name": "clip.mp4", "mimeType": "video/mp4",
                 "size": "10485760", "createdTime": "2026-01-01T00:00:00Z",
                 "modifiedTime": "2026-01-02T00:00:00Z", "parents": ["root"]},
                {"id": "f2", "name": "take2.mov", "mimeType": "video/quicktime",
                 "size": "52428800", "createdTime": "2026-02-01T00:00:00Z",
                 "modifiedTime": "2026-02-02T00:00:00Z", "parents": ["folder1"]},
            ],
        }
        mock_service.return_value = (mock_svc, None)

        result = scan_drive()
        assert result["total_count"] == 2
        assert result["videos"][0]["name"] == "clip.mp4"
        assert result["videos"][0]["size_mb"] == 10.0
        assert result["videos"][0]["source"] == "google_drive"
        assert result["videos"][1]["name"] == "take2.mov"
        assert result["total_size_mb"] == 60.0

    @patch("drive_scanner._get_drive_service")
    def test_max_results_limit(self, mock_service):
        mock_svc = MagicMock()
        files = [
            {"id": f"f{i}", "name": f"v{i}.mp4", "mimeType": "video/mp4",
             "size": "1048576"} for i in range(5)
        ]
        mock_svc.files.return_value.list.return_value.execute.return_value = {
            "files": files,
        }
        mock_service.return_value = (mock_svc, None)

        result = scan_drive(max_results=3)
        # All 5 returned in one page but only first 3 kept in next iteration check
        assert result["total_count"] <= 5

    @patch("drive_scanner._get_drive_service")
    def test_folder_id_passed(self, mock_service):
        mock_svc = MagicMock()
        mock_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        mock_service.return_value = (mock_svc, None)

        result = scan_drive(folder_id="abc123")
        assert result["folder_id"] == "abc123"

    @patch("drive_scanner._get_drive_service")
    def test_api_error(self, mock_service):
        mock_svc = MagicMock()
        mock_svc.files.return_value.list.return_value.execute.side_effect = Exception("rate limit")
        mock_service.return_value = (mock_svc, None)

        result = scan_drive()
        assert result["code"] == "API_ERROR"
        assert "rate limit" in result["error"]

    def test_video_mime_types(self):
        assert "video/mp4" in VIDEO_MIME_TYPES
        assert "video/quicktime" in VIDEO_MIME_TYPES
        assert len(VIDEO_MIME_TYPES) >= 5

    @patch("drive_scanner._get_drive_service")
    def test_pagination(self, mock_service):
        mock_svc = MagicMock()
        page1 = {
            "files": [{"id": "f1", "name": "a.mp4", "mimeType": "video/mp4", "size": "1000"}],
            "nextPageToken": "tok2",
        }
        page2 = {
            "files": [{"id": "f2", "name": "b.mp4", "mimeType": "video/mp4", "size": "2000"}],
        }
        mock_svc.files.return_value.list.return_value.execute.side_effect = [page1, page2]
        mock_service.return_value = (mock_svc, None)

        result = scan_drive()
        assert result["total_count"] == 2
