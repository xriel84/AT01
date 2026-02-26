"""Tests for video_cataloger — catalog orchestration."""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from video_cataloger import (
    _load_catalog, _save_catalog, catalog_entry_from_probe,
    catalog_entry_from_cloud, ingest_local, ingest_drive,
    ingest_dropbox, enrich_with_frames, get_catalog, search_catalog,
)


# ---------------------------------------------------------------------------
# Catalog helpers
# ---------------------------------------------------------------------------

class TestCatalogHelpers:
    """Tests for catalog load/save and entry creation."""

    def test_load_empty_catalog(self, tmp_path):
        catalog = _load_catalog(tmp_path / "nope.json")
        assert catalog["version"] == 1
        assert catalog["entries"] == {}

    def test_save_and_load(self, tmp_path):
        cp = tmp_path / "catalog.json"
        catalog = _load_catalog(cp)
        catalog["entries"]["test"] = {"filename": "test.mp4"}
        _save_catalog(catalog, cp)

        loaded = _load_catalog(cp)
        assert "test" in loaded["entries"]
        assert loaded["updated"] is not None

    def test_entry_from_probe(self):
        probe = {
            "filename": "clip.mp4",
            "path": "/videos/clip.mp4",
            "duration_sec": 60.0,
            "width": 1920,
            "height": 1080,
            "fps": 24.0,
            "video_codec": "h264",
            "audio_codec": "aac",
            "bitrate_kbps": 5000,
            "file_size_mb": 50.0,
            "format_name": "mp4",
        }
        entry = catalog_entry_from_probe(probe)
        assert entry["filename"] == "clip.mp4"
        assert entry["source"] == "local"
        assert entry["duration_sec"] == 60.0
        assert entry["scenes"] is None

    def test_entry_from_cloud(self):
        cloud = {
            "id": "abc123",
            "name": "take1.mov",
            "size_mb": 100.0,
            "source": "google_drive",
            "modified": "2026-01-01T00:00:00Z",
        }
        entry = catalog_entry_from_cloud(cloud)
        assert entry["filename"] == "take1.mov"
        assert entry["source"] == "google_drive"
        assert entry["cloud_id"] == "abc123"
        assert entry["duration_sec"] is None

    def test_corrupt_catalog_file(self, tmp_path):
        cp = tmp_path / "bad.json"
        cp.write_text("not json!!!")
        catalog = _load_catalog(cp)
        assert catalog["version"] == 1
        assert catalog["entries"] == {}


# ---------------------------------------------------------------------------
# ingest_local
# ---------------------------------------------------------------------------

class TestIngestLocal:
    """Tests for ingest_local function."""

    @patch("video_prober.scan_local_dir")
    def test_ingest_adds_entries(self, mock_scan, tmp_path):
        mock_scan.return_value = {
            "videos": [
                {"path": "/v/a.mp4", "filename": "a.mp4", "duration_sec": 10, "file_size_mb": 1},
                {"path": "/v/b.mov", "filename": "b.mov", "duration_sec": 20, "file_size_mb": 2},
            ],
        }
        cp = tmp_path / "cat.json"
        result = ingest_local("/v", catalog_path=cp)
        assert result["added"] == 2
        assert result["skipped"] == 0
        assert result["total"] == 2

    @patch("video_prober.scan_local_dir")
    def test_ingest_skips_duplicates(self, mock_scan, tmp_path):
        mock_scan.return_value = {
            "videos": [{"path": "/v/a.mp4", "filename": "a.mp4", "duration_sec": 10, "file_size_mb": 1}],
        }
        cp = tmp_path / "cat.json"
        ingest_local("/v", catalog_path=cp)
        result = ingest_local("/v", catalog_path=cp)
        assert result["added"] == 0
        assert result["skipped"] == 1
        assert result["total"] == 1

    @patch("video_prober.scan_local_dir")
    def test_ingest_error(self, mock_scan, tmp_path):
        mock_scan.return_value = {"error": "dir not found", "code": "DIR_NOT_FOUND"}
        result = ingest_local("/nope", catalog_path=tmp_path / "cat.json")
        assert result["code"] == "DIR_NOT_FOUND"


# ---------------------------------------------------------------------------
# ingest_drive
# ---------------------------------------------------------------------------

class TestIngestDrive:
    """Tests for ingest_drive function."""

    @patch("drive_scanner.scan_drive")
    def test_ingest_drive_adds(self, mock_scan, tmp_path):
        mock_scan.return_value = {
            "videos": [
                {"id": "f1", "name": "a.mp4", "size_mb": 10, "source": "google_drive", "modified": "2026-01-01"},
            ],
        }
        cp = tmp_path / "cat.json"
        result = ingest_drive(catalog_path=cp)
        assert result["added"] == 1
        assert result["total"] == 1

    @patch("drive_scanner.scan_drive")
    def test_ingest_drive_auth_error(self, mock_scan, tmp_path):
        mock_scan.return_value = {"error": "no creds", "code": "AUTH_ERROR"}
        result = ingest_drive(catalog_path=tmp_path / "cat.json")
        assert result["code"] == "AUTH_ERROR"


# ---------------------------------------------------------------------------
# ingest_dropbox
# ---------------------------------------------------------------------------

class TestIngestDropbox:
    """Tests for ingest_dropbox function."""

    @patch("dropbox_scanner.scan_dropbox")
    def test_ingest_dropbox_adds(self, mock_scan, tmp_path):
        mock_scan.return_value = {
            "videos": [
                {"id": "id:1", "name": "b.mov", "size_mb": 20, "source": "dropbox", "modified": "2026-02-01"},
            ],
        }
        cp = tmp_path / "cat.json"
        result = ingest_dropbox(catalog_path=cp)
        assert result["added"] == 1

    @patch("dropbox_scanner.scan_dropbox")
    def test_ingest_dropbox_auth_error(self, mock_scan, tmp_path):
        mock_scan.return_value = {"error": "no token", "code": "AUTH_ERROR"}
        result = ingest_dropbox(catalog_path=tmp_path / "cat.json")
        assert result["code"] == "AUTH_ERROR"


# ---------------------------------------------------------------------------
# enrich_with_frames
# ---------------------------------------------------------------------------

class TestEnrichWithFrames:
    """Tests for enrich_with_frames function."""

    def test_entry_not_found(self, tmp_path):
        cp = tmp_path / "cat.json"
        _save_catalog({"version": 1, "entries": {}, "created": "now", "updated": None}, cp)
        result = enrich_with_frames("nonexistent", catalog_path=cp)
        assert result["code"] == "NOT_FOUND"

    def test_cloud_entry_rejected(self, tmp_path):
        cp = tmp_path / "cat.json"
        cat = {"version": 1, "entries": {"gdrive:f1": {"source": "google_drive"}}, "created": "now", "updated": None}
        _save_catalog(cat, cp)
        result = enrich_with_frames("gdrive:f1", catalog_path=cp)
        assert result["code"] == "NOT_LOCAL"

    @patch("frame_scanner.scan_frames")
    def test_enriches_local_entry(self, mock_scan, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00")
        cp = tmp_path / "cat.json"
        cat = {
            "version": 1,
            "entries": {str(video): {"source": "local", "path": str(video), "scenes": None, "frame_labels": None}},
            "created": "now",
            "updated": None,
        }
        _save_catalog(cat, cp)

        mock_scan.return_value = {
            "scenes": [{"start_sec": 0, "end_sec": 5}],
            "frames": [{"labels": [{"label": "person", "score": 0.9}]}],
            "scene_count": 1,
        }

        result = enrich_with_frames(str(video), catalog_path=cp)
        assert result["status"] == "enriched"
        assert result["scene_count"] == 1


# ---------------------------------------------------------------------------
# search_catalog
# ---------------------------------------------------------------------------

class TestSearchCatalog:
    """Tests for search_catalog function."""

    def test_search_by_filename(self, tmp_path):
        cp = tmp_path / "cat.json"
        cat = {
            "version": 1,
            "entries": {
                "a": {"filename": "interview_take1.mp4", "frame_labels": None},
                "b": {"filename": "broll_outdoor.mp4", "frame_labels": None},
            },
            "created": "now",
            "updated": None,
        }
        _save_catalog(cat, cp)

        result = search_catalog("interview", catalog_path=cp)
        assert result["count"] == 1
        assert result["results"][0]["key"] == "a"

    def test_search_by_frame_label(self, tmp_path):
        cp = tmp_path / "cat.json"
        cat = {
            "version": 1,
            "entries": {
                "a": {"filename": "clip.mp4", "frame_labels": [[{"label": "person talking to camera", "score": 0.9}]]},
            },
            "created": "now",
            "updated": None,
        }
        _save_catalog(cat, cp)

        result = search_catalog("talking", catalog_path=cp)
        assert result["count"] == 1
        assert result["results"][0]["match_type"] == "frame_label"

    def test_search_no_results(self, tmp_path):
        cp = tmp_path / "cat.json"
        cat = {"version": 1, "entries": {"a": {"filename": "test.mp4", "frame_labels": None}}, "created": "now", "updated": None}
        _save_catalog(cat, cp)
        result = search_catalog("nonexistent", catalog_path=cp)
        assert result["count"] == 0

    def test_search_case_insensitive(self, tmp_path):
        cp = tmp_path / "cat.json"
        cat = {"version": 1, "entries": {"a": {"filename": "Interview.MP4", "frame_labels": None}}, "created": "now", "updated": None}
        _save_catalog(cat, cp)
        result = search_catalog("INTERVIEW", catalog_path=cp)
        assert result["count"] == 1


# ---------------------------------------------------------------------------
# get_catalog
# ---------------------------------------------------------------------------

class TestGetCatalog:
    """Tests for get_catalog function."""

    def test_returns_catalog(self, tmp_path):
        cp = tmp_path / "cat.json"
        cat = {"version": 1, "entries": {"a": {}}, "created": "now", "updated": None}
        _save_catalog(cat, cp)
        result = get_catalog(catalog_path=cp)
        assert "a" in result["entries"]
