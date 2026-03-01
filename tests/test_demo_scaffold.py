"""Tests for S24 demo scaffold — library API, frontend files, demo data."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Ensure tools are importable
_tools_dir = str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from agents.edbot.server import app

client = TestClient(app)

STATIC_DIR = Path(__file__).resolve().parent.parent / "agents" / "edbot" / "static"


# ---------------------------------------------------------------------------
# Demo library JSON validation
# ---------------------------------------------------------------------------

class TestDemoLibraryFile:
    """Validate the demo-library.json file structure and schema."""

    def test_demo_library_exists(self):
        """demo-library.json must exist in static dir."""
        assert (STATIC_DIR / "demo-library.json").exists()

    def test_demo_library_valid_json(self):
        """demo-library.json must be valid JSON."""
        with open(STATIC_DIR / "demo-library.json", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_demo_library_has_entries(self):
        """demo-library.json must have at least 3 entries."""
        with open(STATIC_DIR / "demo-library.json", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) >= 3

    def test_demo_library_entry_schema(self):
        """Each entry must have required fields."""
        with open(STATIC_DIR / "demo-library.json", encoding="utf-8") as f:
            data = json.load(f)
        required_fields = {"filename", "duration", "whisper_segments"}
        for entry in data:
            assert required_fields.issubset(entry.keys()), \
                f"Entry {entry.get('filename', '?')} missing fields: {required_fields - entry.keys()}"

    def test_demo_library_segments_schema(self):
        """Each whisper_segment must have start, end, text."""
        with open(STATIC_DIR / "demo-library.json", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data:
            for seg in entry["whisper_segments"]:
                assert "start" in seg, f"Segment missing 'start' in {entry['filename']}"
                assert "end" in seg, f"Segment missing 'end' in {entry['filename']}"
                assert "text" in seg, f"Segment missing 'text' in {entry['filename']}"
                assert isinstance(seg["start"], (int, float))
                assert isinstance(seg["end"], (int, float))
                assert seg["end"] > seg["start"]

    def test_demo_library_has_source_marker(self):
        """All entries must have source: demo-scaffold marker."""
        with open(STATIC_DIR / "demo-library.json", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data:
            assert entry.get("source") == "demo-scaffold", \
                f"Entry {entry['filename']} missing source: demo-scaffold"


# ---------------------------------------------------------------------------
# Library API endpoint tests
# ---------------------------------------------------------------------------

class TestLibraryAPI:
    """Test /api/library endpoints."""

    def test_get_library(self):
        """GET /api/library returns entries array."""
        resp = client.get("/api/library")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert "count" in data
        assert isinstance(data["entries"], list)
        assert data["count"] == len(data["entries"])

    def test_get_library_demo_mode_flag(self):
        """GET /api/library includes demo_mode flag when using demo data."""
        resp = client.get("/api/library")
        data = resp.json()
        assert "demo_mode" in data
        assert isinstance(data["demo_mode"], bool)

    def test_get_library_chapters(self):
        """GET /api/library/chapters returns chapter data per file."""
        resp = client.get("/api/library/chapters")
        assert resp.status_code == 200
        data = resp.json()
        assert "files" in data
        assert "total_chapters" in data
        assert isinstance(data["files"], list)
        if data["files"]:
            f = data["files"][0]
            assert "filename" in f
            assert "chapters" in f
            assert isinstance(f["chapters"], list)

    def test_get_library_chapters_have_required_fields(self):
        """Each chapter must have chapter_id, start, end, duration, title."""
        resp = client.get("/api/library/chapters")
        data = resp.json()
        for file_data in data["files"]:
            for ch in file_data["chapters"]:
                assert "chapter_id" in ch
                assert "start" in ch
                assert "end" in ch
                assert "duration" in ch
                assert "title" in ch
                assert ch["end"] > ch["start"]
                assert ch["duration"] > 0

    def test_library_search_with_results(self):
        """GET /api/library/search?q=<term> returns matching results."""
        resp = client.get("/api/library/search?q=chapter")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "query" in data
        assert "count" in data
        assert data["count"] > 0, "Expected results for 'chapter' in demo data"

    def test_library_search_no_results(self):
        """GET /api/library/search?q=<nonexistent> returns empty."""
        resp = client.get("/api/library/search?q=xyznonexistent999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["results"] == []

    def test_library_search_empty_query(self):
        """GET /api/library/search?q= returns empty results."""
        resp = client.get("/api/library/search?q=")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_library_search_match_structure(self):
        """Each search result match has correct fields."""
        resp = client.get("/api/library/search?q=VR")
        data = resp.json()
        assert data["count"] > 0
        result = data["results"][0]
        assert "filename" in result
        assert "match_count" in result
        assert "matches" in result
        assert isinstance(result["matches"], list)
        for m in result["matches"]:
            assert "field" in m
            assert "text" in m

    def test_library_search_case_insensitive(self):
        """Search is case-insensitive."""
        r1 = client.get("/api/library/search?q=scrooge")
        r2 = client.get("/api/library/search?q=Scrooge")
        assert r1.json()["count"] == r2.json()["count"]
        assert r1.json()["count"] > 0


# ---------------------------------------------------------------------------
# Frontend file existence + structure tests
# ---------------------------------------------------------------------------

class TestFrontendFiles:
    """Verify all frontend HTML files exist and are well-formed."""

    @pytest.mark.parametrize("filename", [
        "index.html",
        "chapter-viewer.html",
        "command-console.html",
        "nlp-search.html",
    ])
    def test_frontend_file_exists(self, filename):
        """Frontend HTML file must exist in static dir."""
        assert (STATIC_DIR / filename).exists(), f"{filename} missing from {STATIC_DIR}"

    @pytest.mark.parametrize("filename", [
        "index.html",
        "chapter-viewer.html",
        "command-console.html",
        "nlp-search.html",
    ])
    def test_frontend_file_valid_html(self, filename):
        """Frontend file must contain basic HTML structure."""
        content = (STATIC_DIR / filename).read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content or "<!doctype html>" in content
        assert "<html" in content
        assert "</html>" in content
        assert "<head>" in content
        assert "<body>" in content

    @pytest.mark.parametrize("filename", [
        "index.html",
        "chapter-viewer.html",
        "command-console.html",
        "nlp-search.html",
    ])
    def test_frontend_file_has_demo_banner(self, filename):
        """Each frontend must have a DEMO MODE indicator."""
        content = (STATIC_DIR / filename).read_text(encoding="utf-8")
        assert "demoBanner" in content or "demo-banner" in content

    @pytest.mark.parametrize("path", [
        "/frontend/index.html",
        "/frontend/chapter-viewer.html",
        "/frontend/command-console.html",
        "/frontend/nlp-search.html",
    ])
    def test_frontend_served_via_mount(self, path):
        """Frontend files must be accessible via /frontend/* route."""
        resp = client.get(path)
        assert resp.status_code == 200

    def test_index_links_all_pages(self):
        """index.html must link to all three tool pages."""
        content = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        assert "chapter-viewer.html" in content
        assert "command-console.html" in content
        assert "nlp-search.html" in content
        assert "/docs" in content

    def test_chapter_viewer_fetches_library(self):
        """chapter-viewer.html must fetch from /api/library."""
        content = (STATIC_DIR / "chapter-viewer.html").read_text(encoding="utf-8")
        assert "/api/library" in content

    def test_command_console_posts_to_resolve(self):
        """command-console.html must POST to /api/resolve/command."""
        content = (STATIC_DIR / "command-console.html").read_text(encoding="utf-8")
        assert "/api/resolve/command" in content

    def test_nlp_search_fetches_library_search(self):
        """nlp-search.html must fetch from /api/library/search."""
        content = (STATIC_DIR / "nlp-search.html").read_text(encoding="utf-8")
        assert "/api/library/search" in content
