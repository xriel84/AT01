"""Integration tests for S24 — library→viewer schema, demo-pipeline.ps1, API wiring."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_tools_dir = str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from library_generator import build_library_entry
from agents.edbot.server import app

client = TestClient(app)

STATIC_DIR = Path(__file__).resolve().parent.parent / "agents" / "edbot" / "static"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


# ---------------------------------------------------------------------------
# Library generator → viewer schema compatibility
# ---------------------------------------------------------------------------

class TestLibraryViewerSchema:
    """Verify library_generator output matches what viewers consume."""

    VIEWER_REQUIRED_FIELDS = {"filename", "duration", "whisper_segments"}
    SEGMENT_REQUIRED_FIELDS = {"start", "end", "text"}

    def test_build_entry_has_viewer_fields(self, tmp_path):
        """build_library_entry output must contain all viewer-required fields."""
        video = tmp_path / "test.mp4"
        video.write_bytes(b"")
        with patch("library_generator.probe_video") as mock_probe:
            mock_probe.return_value = {
                "duration": 120.5,
                "resolution": "1920x1080",
                "codec": "h264",
                "width": 1920,
                "height": 1080,
            }
            entry = build_library_entry(video)
        missing = self.VIEWER_REQUIRED_FIELDS - entry.keys()
        assert not missing, f"Entry missing viewer fields: {missing}"

    def test_build_entry_segments_have_viewer_fields(self, tmp_path):
        """Each whisper_segment must have start, end, text for viewers."""
        video = tmp_path / "test.mp4"
        video.write_bytes(b"")
        chunks = {"chunks": [
            {"id": 0, "start": 0.0, "end": 5.0, "text": "Hello",
             "word_count": 1, "silence_ratio": 0.1, "has_speech": True},
        ]}
        (tmp_path / "test_chunks.json").write_text(
            json.dumps(chunks), encoding="utf-8"
        )
        with patch("library_generator.probe_video") as mock_probe:
            mock_probe.return_value = {
                "duration": 5.0, "resolution": "1920x1080",
                "codec": "h264", "width": 1920, "height": 1080,
            }
            entry = build_library_entry(video)
        assert len(entry["whisper_segments"]) == 1
        seg = entry["whisper_segments"][0]
        missing = self.SEGMENT_REQUIRED_FIELDS - seg.keys()
        assert not missing, f"Segment missing fields: {missing}"

    def test_demo_library_matches_generator_schema(self):
        """demo-library.json must match library_generator output schema exactly."""
        with open(STATIC_DIR / "demo-library.json", encoding="utf-8") as f:
            entries = json.load(f)
        for entry in entries:
            missing = self.VIEWER_REQUIRED_FIELDS - entry.keys()
            assert not missing, f"{entry['filename']} missing: {missing}"
            assert isinstance(entry["duration"], (int, float))
            assert isinstance(entry["whisper_segments"], list)
            for seg in entry["whisper_segments"]:
                seg_missing = self.SEGMENT_REQUIRED_FIELDS - seg.keys()
                assert not seg_missing, f"Segment in {entry['filename']} missing: {seg_missing}"

    def test_api_library_entries_match_viewer_schema(self):
        """GET /api/library entries must have viewer-required fields."""
        resp = client.get("/api/library")
        data = resp.json()
        for entry in data["entries"]:
            missing = self.VIEWER_REQUIRED_FIELDS - entry.keys()
            assert not missing, f"{entry.get('filename', '?')} missing: {missing}"

    def test_api_chapters_match_chapter_detect_schema(self):
        """GET /api/library/chapters output matches chapter_detect output schema."""
        resp = client.get("/api/library/chapters")
        data = resp.json()
        chapter_fields = {"chapter_id", "start", "end", "duration", "title"}
        for file_data in data["files"]:
            for ch in file_data["chapters"]:
                missing = chapter_fields - ch.keys()
                assert not missing, f"Chapter missing fields: {missing}"
                assert isinstance(ch["chapter_id"], int)
                assert isinstance(ch["start"], (int, float))
                assert isinstance(ch["end"], (int, float))
                assert ch["end"] >= ch["start"]


# ---------------------------------------------------------------------------
# Demo pipeline script validation
# ---------------------------------------------------------------------------

class TestDemoPipelineScript:
    """Verify demo-pipeline.ps1 exists and has correct structure."""

    def test_script_exists(self):
        """demo-pipeline.ps1 must exist in scripts/."""
        assert (SCRIPTS_DIR / "demo-pipeline.ps1").exists()

    def test_script_has_param_block(self):
        """Script must have a param() block for CLI flags."""
        content = (SCRIPTS_DIR / "demo-pipeline.ps1").read_text(encoding="utf-8")
        assert "param(" in content

    def test_script_calls_ensure_server(self):
        """Script must call ensure-server.ps1."""
        content = (SCRIPTS_DIR / "demo-pipeline.ps1").read_text(encoding="utf-8")
        assert "ensure-server.ps1" in content

    def test_script_has_skip_pipeline_flag(self):
        """Script must support -SkipPipeline flag."""
        content = (SCRIPTS_DIR / "demo-pipeline.ps1").read_text(encoding="utf-8")
        assert "SkipPipeline" in content

    def test_script_has_library_path_flag(self):
        """Script must support -LibraryPath flag."""
        content = (SCRIPTS_DIR / "demo-pipeline.ps1").read_text(encoding="utf-8")
        assert "LibraryPath" in content

    def test_script_opens_viewers(self):
        """Script must open frontend viewer URLs."""
        content = (SCRIPTS_DIR / "demo-pipeline.ps1").read_text(encoding="utf-8")
        assert "index.html" in content
        assert "chapter-viewer.html" in content
        assert "command-console.html" in content

    def test_script_has_no_browser_flag(self):
        """Script must support -NoBrowser flag."""
        content = (SCRIPTS_DIR / "demo-pipeline.ps1").read_text(encoding="utf-8")
        assert "NoBrowser" in content

    def test_script_verifies_endpoints(self):
        """Script must verify key endpoints after starting."""
        content = (SCRIPTS_DIR / "demo-pipeline.ps1").read_text(encoding="utf-8")
        assert "/api/health" in content or "/health" in content
        assert "/api/library" in content


# ---------------------------------------------------------------------------
# Demo checklist validation
# ---------------------------------------------------------------------------

class TestDemoChecklist:
    """Verify demo-checklist-t1.md exists and covers key items."""

    def test_checklist_exists(self):
        """demo-checklist-t1.md must exist in docs/."""
        assert (DOCS_DIR / "demo-checklist-t1.md").exists()

    def test_checklist_has_presentation_date(self):
        """Checklist must reference the boss presentation date."""
        content = (DOCS_DIR / "demo-checklist-t1.md").read_text(encoding="utf-8")
        assert "2026-03-17" in content

    def test_checklist_has_demo_screens(self):
        """Checklist must list the demo screen sequence."""
        content = (DOCS_DIR / "demo-checklist-t1.md").read_text(encoding="utf-8")
        assert "Dashboard" in content
        assert "Chapter Viewer" in content
        assert "Command Console" in content

    def test_checklist_has_fallback_plans(self):
        """Checklist must have fallback plans section."""
        content = (DOCS_DIR / "demo-checklist-t1.md").read_text(encoding="utf-8")
        assert "Fallback" in content

    def test_checklist_references_demo_runner(self):
        """Checklist must reference the demo-pipeline.ps1 runner."""
        content = (DOCS_DIR / "demo-checklist-t1.md").read_text(encoding="utf-8")
        assert "demo-pipeline.ps1" in content


# ---------------------------------------------------------------------------
# API wiring integration
# ---------------------------------------------------------------------------

class TestAPIWiring:
    """End-to-end API wiring: library → chapters → search roundtrip."""

    def test_library_then_chapters_file_match(self):
        """Library filenames must appear in chapters response."""
        lib = client.get("/api/library").json()
        chaps = client.get("/api/library/chapters").json()
        lib_files = {e["filename"] for e in lib["entries"]}
        chap_files = {f["filename"] for f in chaps["files"]}
        # Every file with segments should have chapters
        for entry in lib["entries"]:
            if entry.get("whisper_segments"):
                assert entry["filename"] in chap_files, \
                    f"{entry['filename']} has segments but no chapters"

    def test_search_result_files_in_library(self):
        """Search result filenames must exist in library."""
        lib = client.get("/api/library").json()
        lib_files = {e["filename"] for e in lib["entries"]}
        search = client.get("/api/library/search?q=the").json()
        for result in search["results"]:
            assert result["filename"] in lib_files, \
                f"Search returned {result['filename']} not in library"

    def test_chapter_count_reasonable(self):
        """Each file should have at least 1 chapter and not more than 100."""
        chaps = client.get("/api/library/chapters").json()
        for file_data in chaps["files"]:
            count = len(file_data["chapters"])
            assert 1 <= count <= 100, \
                f"{file_data['filename']} has {count} chapters (unreasonable)"

    def test_chapters_cover_full_duration(self):
        """Chapters should span from near start to near end of file."""
        chaps = client.get("/api/library/chapters").json()
        lib = client.get("/api/library").json()
        lib_dur = {e["filename"]: e["duration"] for e in lib["entries"]}
        for file_data in chaps["files"]:
            chapters = file_data["chapters"]
            if not chapters:
                continue
            first_start = chapters[0]["start"]
            last_end = chapters[-1]["end"]
            total = lib_dur.get(file_data["filename"], 0)
            if total > 0:
                # First chapter should start within first 30s
                assert first_start < 30.0, \
                    f"{file_data['filename']}: first chapter starts at {first_start}s"
                # Last chapter should end within reasonable range
                assert last_end > total * 0.5, \
                    f"{file_data['filename']}: chapters only cover to {last_end}s of {total}s"
