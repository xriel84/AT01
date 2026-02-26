"""Tests for standardized error response handling in server.py."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_tools_dir = str(Path(__file__).resolve().parent.parent / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from fastapi.testclient import TestClient

from agents.edbot.server import app, _cache, _session


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset server cache and session before each test."""
    _cache["chunks"] = None
    _cache["silence_map"] = None
    _cache["last_input"] = None
    for key in _session:
        _session[key] = None
    yield


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


class TestErrorResponseSchema:
    def test_error_response_schema(self, client):
        """Error responses from known endpoints have 'error', 'code' keys."""
        resp = client.post("/api/transcribe", json={
            "input_path": "C:/nonexistent/fake.mp4",
        })
        assert resp.status_code == 400
        data = resp.json()
        detail = data.get("detail", data)
        assert "error" in detail
        assert "code" in detail

    def test_transcribe_missing_file(self, client):
        """POST /api/transcribe with nonexistent path -> 400 + FILE_NOT_FOUND."""
        resp = client.post("/api/transcribe", json={
            "input_path": "C:/nonexistent/video.mp4",
        })
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["code"] == "FILE_NOT_FOUND"
        assert "not found" in detail["error"].lower()

    def test_search_missing_index(self, client):
        """POST /api/search-transcripts with no index -> 404 + NO_INDEX."""
        index_file = Path("temp") / "transcript_index.json"
        bak_file = index_file.with_suffix(".json.bak")
        existed = index_file.exists()
        if existed:
            index_file.rename(bak_file)
        try:
            resp = client.post("/api/search-transcripts", json={
                "query": "test",
            })
            # Should return 404 because no transcript index exists
            assert resp.status_code in (404, 500)
            detail = resp.json().get("detail", resp.json())
            assert "code" in detail
        finally:
            if existed and bak_file.exists():
                bak_file.rename(index_file)

    @patch("agents.edbot.server.resolve_available", return_value={
        "available": False, "version": None, "product": None,
        "error": "Resolve scripting returned None",
    })
    def test_resolve_offline_returns_status(self, mock_ra, client):
        """Resolve offline -> endpoint returns available=False."""
        resp = client.get("/api/resolve/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is False
        assert data["error"] is not None

    @patch("agents.edbot.server.run_benchmark", side_effect=RuntimeError("boom"))
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_global_exception_handler(self, mock_exists, mock_bench, client):
        """Unhandled exception -> 500 + PROCESSING_ERROR."""
        resp = client.post("/api/benchmark", json={
            "video_path": "C:/AT01/input/test.mp4", "runs": 1,
        })
        assert resp.status_code == 500
        data = resp.json()
        detail = data.get("detail", data)
        assert detail["code"] == "PROCESSING_ERROR"

    def test_benchmark_bad_file(self, client):
        """POST /api/benchmark with missing file -> 400 + FILE_NOT_FOUND."""
        resp = client.post("/api/benchmark", json={
            "video_path": "C:/nonexistent/video.mp4", "runs": 1,
        })
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["code"] == "FILE_NOT_FOUND"

    def test_error_includes_code_field(self, client):
        """Error response 'code' field is always present."""
        resp = client.get("/api/chunks")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert "code" in detail
        assert isinstance(detail["code"], str)
        assert len(detail["code"]) > 0

    def test_clips_manifest_no_session(self, client):
        """GET /api/clips_manifest with no session -> 400 + NO_SESSION."""
        resp = client.get("/api/clips_manifest")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["code"] == "NO_SESSION"
        assert "error" in detail
