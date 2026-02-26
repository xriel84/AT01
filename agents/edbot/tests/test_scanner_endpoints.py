"""Tests for scanner API endpoints in server.py."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# POST /api/scan/local
# ---------------------------------------------------------------------------

class TestScanLocal:
    """Tests for POST /api/scan/local endpoint."""

    def test_dir_not_found(self):
        resp = client.post("/api/scan/local", json={"directory": "C:/nonexistent_dir_xyz"})
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"]["error"]

    @patch("server.ingest_local")
    def test_successful_scan(self, mock_ingest, tmp_path):
        mock_ingest.return_value = {"added": 3, "skipped": 0, "total": 3, "catalog_path": "temp/catalog.json"}
        d = tmp_path / "videos"
        d.mkdir()
        resp = client.post("/api/scan/local", json={"directory": str(d)})
        assert resp.status_code == 200
        assert resp.json()["added"] == 3

    @patch("server.ingest_local")
    def test_scan_error(self, mock_ingest, tmp_path):
        mock_ingest.return_value = {"error": "permission denied", "code": "PROCESSING_ERROR"}
        d = tmp_path / "vids"
        d.mkdir()
        resp = client.post("/api/scan/local", json={"directory": str(d)})
        assert resp.status_code == 500

    def test_not_a_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        resp = client.post("/api/scan/local", json={"directory": str(f)})
        assert resp.status_code == 400
        assert "not a directory" in resp.json()["detail"]["error"]


# ---------------------------------------------------------------------------
# POST /api/scan/drive
# ---------------------------------------------------------------------------

class TestScanDrive:
    """Tests for POST /api/scan/drive endpoint."""

    @patch("server.ingest_drive")
    def test_successful_scan(self, mock_ingest):
        mock_ingest.return_value = {"added": 5, "skipped": 0, "total": 5, "catalog_path": "temp/catalog.json"}
        resp = client.post("/api/scan/drive", json={})
        assert resp.status_code == 200
        assert resp.json()["added"] == 5

    @patch("server.ingest_drive")
    def test_auth_error(self, mock_ingest):
        mock_ingest.return_value = {"error": "no credentials", "code": "AUTH_ERROR"}
        resp = client.post("/api/scan/drive", json={})
        assert resp.status_code == 401

    @patch("server.ingest_drive")
    def test_with_folder_id(self, mock_ingest):
        mock_ingest.return_value = {"added": 1, "skipped": 0, "total": 1, "catalog_path": "temp/catalog.json"}
        resp = client.post("/api/scan/drive", json={"folder_id": "abc123"})
        assert resp.status_code == 200
        mock_ingest.assert_called_once()
        call_kwargs = mock_ingest.call_args
        assert call_kwargs[1]["folder_id"] == "abc123" or call_kwargs[0][0] == "abc123"


# ---------------------------------------------------------------------------
# POST /api/scan/dropbox
# ---------------------------------------------------------------------------

class TestScanDropbox:
    """Tests for POST /api/scan/dropbox endpoint."""

    @patch("server.ingest_dropbox")
    def test_successful_scan(self, mock_ingest):
        mock_ingest.return_value = {"added": 2, "skipped": 0, "total": 2, "catalog_path": "temp/catalog.json"}
        resp = client.post("/api/scan/dropbox", json={})
        assert resp.status_code == 200
        assert resp.json()["added"] == 2

    @patch("server.ingest_dropbox")
    def test_auth_error(self, mock_ingest):
        mock_ingest.return_value = {"error": "no token", "code": "AUTH_ERROR"}
        resp = client.post("/api/scan/dropbox", json={})
        assert resp.status_code == 401

    @patch("server.ingest_dropbox")
    def test_with_folder_path(self, mock_ingest):
        mock_ingest.return_value = {"added": 0, "skipped": 0, "total": 0, "catalog_path": "temp/catalog.json"}
        resp = client.post("/api/scan/dropbox", json={"folder_path": "/Videos"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/probe
# ---------------------------------------------------------------------------

class TestProbe:
    """Tests for POST /api/probe endpoint."""

    def test_file_not_found(self):
        resp = client.post("/api/probe", json={"video_path": "C:/nonexistent_xyz.mp4"})
        assert resp.status_code == 400

    @patch("server.probe_video")
    def test_successful_probe(self, mock_probe, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00")
        mock_probe.return_value = {
            "filename": "test.mp4",
            "duration_sec": 60.0,
            "width": 1920,
            "height": 1080,
        }
        resp = client.post("/api/probe", json={"video_path": str(video)})
        assert resp.status_code == 200
        assert resp.json()["duration_sec"] == 60.0

    @patch("server.probe_video")
    def test_probe_error(self, mock_probe, tmp_path):
        video = tmp_path / "bad.mp4"
        video.write_bytes(b"\x00")
        mock_probe.return_value = {"error": "corrupt file", "code": "PROBE_ERROR"}
        resp = client.post("/api/probe", json={"video_path": str(video)})
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/scan/frames
# ---------------------------------------------------------------------------

class TestScanFrames:
    """Tests for POST /api/scan/frames endpoint."""

    def test_file_not_found(self):
        resp = client.post("/api/scan/frames", json={"video_path": "C:/nonexistent_xyz.mp4"})
        assert resp.status_code == 400

    @patch("server.scan_frames")
    def test_successful_scan(self, mock_scan, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00")
        mock_scan.return_value = {
            "video_path": str(video),
            "scenes": [{"start_sec": 0, "end_sec": 5}],
            "frames": [{"labels": [{"label": "person", "score": 0.9}]}],
            "scene_count": 1,
        }
        resp = client.post("/api/scan/frames", json={"video_path": str(video)})
        assert resp.status_code == 200
        assert resp.json()["scene_count"] == 1

    @patch("server.scan_frames")
    def test_scan_error(self, mock_scan, tmp_path):
        video = tmp_path / "bad.mp4"
        video.write_bytes(b"\x00")
        mock_scan.return_value = {"error": "codec error", "code": "SCENE_ERROR"}
        resp = client.post("/api/scan/frames", json={"video_path": str(video)})
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/catalog
# ---------------------------------------------------------------------------

class TestCatalog:
    """Tests for GET /api/catalog endpoint."""

    @patch("server.get_catalog")
    def test_returns_catalog(self, mock_get):
        mock_get.return_value = {"version": 1, "entries": {"a": {}}, "created": "now", "updated": "now"}
        resp = client.get("/api/catalog")
        assert resp.status_code == 200
        assert "entries" in resp.json()


# ---------------------------------------------------------------------------
# POST /api/catalog/search
# ---------------------------------------------------------------------------

class TestCatalogSearch:
    """Tests for POST /api/catalog/search endpoint."""

    @patch("server.search_catalog")
    def test_search(self, mock_search):
        mock_search.return_value = {"query": "test", "results": [], "count": 0}
        resp = client.post("/api/catalog/search", json={"query": "test"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_empty_query(self):
        resp = client.post("/api/catalog/search", json={"query": ""})
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"]["error"]

    @patch("server.search_catalog")
    def test_search_with_results(self, mock_search):
        mock_search.return_value = {
            "query": "interview",
            "results": [{"key": "a", "filename": "interview.mp4", "match_type": "filename"}],
            "count": 1,
        }
        resp = client.post("/api/catalog/search", json={"query": "interview"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
