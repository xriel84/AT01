"""Tests for dropbox_scanner — Dropbox video scanning."""

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from dropbox_scanner import scan_dropbox, VIDEO_EXTENSIONS


class TestScanDropbox:
    """Tests for scan_dropbox function."""

    @patch("dropbox_scanner._get_dropbox_client")
    def test_auth_error_no_token(self, mock_client):
        mock_client.return_value = (None, "no access token — set DROPBOX_ACCESS_TOKEN or pass access_token")
        result = scan_dropbox()
        assert result["code"] == "AUTH_ERROR"
        assert "access token" in result["error"]

    @patch("dropbox_scanner._get_dropbox_client")
    def test_empty_folder(self, mock_client):
        import dropbox
        mock_dbx = MagicMock()
        mock_result = MagicMock()
        mock_result.entries = []
        mock_result.has_more = False
        mock_dbx.files_list_folder.return_value = mock_result
        mock_client.return_value = (mock_dbx, None)

        result = scan_dropbox()
        assert result["source"] == "dropbox"
        assert result["total_count"] == 0
        assert result["videos"] == []

    @patch("dropbox_scanner._get_dropbox_client")
    def test_finds_videos(self, mock_client):
        import dropbox

        file1 = MagicMock(spec=dropbox.files.FileMetadata)
        file1.name = "clip.mp4"
        file1.id = "id:abc"
        file1.path_display = "/Videos/clip.mp4"
        file1.size = 10485760
        file1.server_modified = datetime(2026, 1, 1)
        file1.content_hash = "hash1"

        file2 = MagicMock(spec=dropbox.files.FileMetadata)
        file2.name = "take.mov"
        file2.id = "id:def"
        file2.path_display = "/Videos/take.mov"
        file2.size = 52428800
        file2.server_modified = datetime(2026, 2, 1)
        file2.content_hash = "hash2"

        # Non-video file
        file3 = MagicMock(spec=dropbox.files.FileMetadata)
        file3.name = "notes.txt"

        # Folder entry
        folder = MagicMock(spec=dropbox.files.FolderMetadata)
        folder.name = "subfolder"

        mock_dbx = MagicMock()
        mock_result = MagicMock()
        mock_result.entries = [file1, file2, file3, folder]
        mock_result.has_more = False
        mock_dbx.files_list_folder.return_value = mock_result
        mock_client.return_value = (mock_dbx, None)

        result = scan_dropbox()
        assert result["total_count"] == 2
        assert result["videos"][0]["name"] == "clip.mp4"
        assert result["videos"][0]["size_mb"] == 10.0
        assert result["videos"][0]["source"] == "dropbox"
        assert result["videos"][1]["name"] == "take.mov"

    @patch("dropbox_scanner._get_dropbox_client")
    def test_max_results(self, mock_client):
        import dropbox

        entries = []
        for i in range(10):
            f = MagicMock(spec=dropbox.files.FileMetadata)
            f.name = f"v{i}.mp4"
            f.id = f"id:{i}"
            f.path_display = f"/v{i}.mp4"
            f.size = 1000
            f.server_modified = datetime(2026, 1, 1)
            f.content_hash = f"h{i}"
            entries.append(f)

        mock_dbx = MagicMock()
        mock_result = MagicMock()
        mock_result.entries = entries
        mock_result.has_more = False
        mock_dbx.files_list_folder.return_value = mock_result
        mock_client.return_value = (mock_dbx, None)

        result = scan_dropbox(max_results=3)
        assert result["total_count"] == 3

    @patch("dropbox_scanner._get_dropbox_client")
    def test_folder_path(self, mock_client):
        mock_dbx = MagicMock()
        mock_result = MagicMock()
        mock_result.entries = []
        mock_result.has_more = False
        mock_dbx.files_list_folder.return_value = mock_result
        mock_client.return_value = (mock_dbx, None)

        result = scan_dropbox(folder_path="/MyVideos")
        assert result["folder_path"] == "/MyVideos"

    @patch("dropbox_scanner._get_dropbox_client")
    def test_api_error(self, mock_client):
        mock_dbx = MagicMock()
        mock_dbx.files_list_folder.side_effect = Exception("network error")
        mock_client.return_value = (mock_dbx, None)

        result = scan_dropbox()
        assert result["code"] == "API_ERROR"
        assert "network error" in result["error"]

    def test_video_extensions(self):
        assert ".mp4" in VIDEO_EXTENSIONS
        assert ".mov" in VIDEO_EXTENSIONS
        assert ".txt" not in VIDEO_EXTENSIONS

    @patch("dropbox_scanner._get_dropbox_client")
    def test_pagination(self, mock_client):
        import dropbox

        f1 = MagicMock(spec=dropbox.files.FileMetadata)
        f1.name = "a.mp4"
        f1.id = "id:1"
        f1.path_display = "/a.mp4"
        f1.size = 1000
        f1.server_modified = datetime(2026, 1, 1)
        f1.content_hash = "h1"

        f2 = MagicMock(spec=dropbox.files.FileMetadata)
        f2.name = "b.mp4"
        f2.id = "id:2"
        f2.path_display = "/b.mp4"
        f2.size = 2000
        f2.server_modified = datetime(2026, 1, 1)
        f2.content_hash = "h2"

        mock_dbx = MagicMock()
        page1 = MagicMock()
        page1.entries = [f1]
        page1.has_more = True
        page1.cursor = "cur1"

        page2 = MagicMock()
        page2.entries = [f2]
        page2.has_more = False

        mock_dbx.files_list_folder.return_value = page1
        mock_dbx.files_list_folder_continue.return_value = page2
        mock_client.return_value = (mock_dbx, None)

        result = scan_dropbox()
        assert result["total_count"] == 2

    @patch("dropbox_scanner._get_dropbox_client")
    def test_root_folder_default(self, mock_client):
        mock_dbx = MagicMock()
        mock_result = MagicMock()
        mock_result.entries = []
        mock_result.has_more = False
        mock_dbx.files_list_folder.return_value = mock_result
        mock_client.return_value = (mock_dbx, None)

        result = scan_dropbox()
        assert result["folder_path"] == "/"
