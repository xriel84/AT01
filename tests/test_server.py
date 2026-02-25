"""Tests for EdBot FastAPI server — all tool calls mocked.

Uses FastAPI TestClient (httpx-backed). No real ffmpeg, whisper, or file I/O
from the underlying tools.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure tools dir is on path so server.py can import its dependencies.
_tools_dir = str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from fastapi.testclient import TestClient

from agents.edbot.server import app, _cache, _session, ALLOWED_VIDEO_DIRS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
    """Create a TestClient for the FastAPI app."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Mock return data
# ---------------------------------------------------------------------------

MOCK_CHUNKS = {
    "source": "test.mp4",
    "duration": 30.0,
    "chunks": [
        {"id": 0, "start": 0.0, "end": 10.0, "text": "hello world",
         "word_count": 2, "silence_ratio": 0.5, "has_speech": True},
        {"id": 1, "start": 10.0, "end": 20.0, "text": "",
         "word_count": 0, "silence_ratio": 1.0, "has_speech": False},
        {"id": 2, "start": 20.0, "end": 30.0, "text": "goodbye",
         "word_count": 1, "silence_ratio": 0.7, "has_speech": True},
    ],
}

MOCK_SILENCE_MAP = {
    "source": "test.mp4",
    "duration": 30.0,
    "threshold_db": -30.0,
    "gaps": [{"start": 10.0, "end": 20.0, "duration": 10.0}],
    "speech": [
        {"start": 0.0, "end": 10.0, "duration": 10.0},
        {"start": 20.0, "end": 30.0, "duration": 10.0},
    ],
    "stats": {
        "total_silence": 10.0,
        "total_speech": 20.0,
        "silence_percentage": 33.3,
        "gap_count": 1,
    },
}

MOCK_ACTION = {
    "action": "silence_remove",
    "params": {
        "input": "test.mp4",
        "output": "output",
        "platform": None,
        "max_duration": None,
        "aspect": None,
        "silence_threshold_db": -30,
        "caption_style": "default",
    },
    "executor": "ffmpeg",
    "confidence": 0.95,
}

MOCK_EXECUTE_RESULT = {
    "status": "success",
    "action": "silence_remove",
    "input": "test.mp4",
    "output": "output/test_silence_remove.mp4",
    "duration_in": 30.0,
    "duration_out": 20.0,
    "ffmpeg_cmd": "ffmpeg -i test.mp4 ...",
    "elapsed_seconds": 1.234,
    "error": None,
}


# ---------------------------------------------------------------------------
# 1. test_health
# ---------------------------------------------------------------------------

def test_health(client):
    """GET /api/health returns status ok and tool list."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert isinstance(data["tools"], list)
    assert "transcribe" in data["tools"]
    assert "silence_detect" in data["tools"]
    assert "nlp_action" in data["tools"]
    assert "executor" in data["tools"]


# ---------------------------------------------------------------------------
# 2. test_transcribe_endpoint
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.transcribe_video", return_value=MOCK_CHUNKS)
@patch("agents.edbot.server.Path.exists", return_value=True)
def test_transcribe_endpoint(mock_exists, mock_tv, client):
    """POST /api/transcribe returns chunks data."""
    resp = client.post("/api/transcribe", json={
        "input_path": "C:/AT01/input/test.mp4",
        "output_dir": "output",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "test.mp4"
    assert len(data["chunks"]) == 3
    mock_tv.assert_called_once_with("C:/AT01/input/test.mp4", "output")


# ---------------------------------------------------------------------------
# 3. test_silence_endpoint
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.detect_silence", return_value=MOCK_SILENCE_MAP)
def test_silence_endpoint(mock_ds, client):
    """POST /api/silence returns silence map."""
    resp = client.post("/api/silence", json={
        "input_path": "C:/AT01/input/test.mp4",
        "output_dir": "output",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "test.mp4"
    assert len(data["gaps"]) == 1
    assert data["stats"]["gap_count"] == 1
    mock_ds.assert_called_once_with("C:/AT01/input/test.mp4", output_dir="output")


# ---------------------------------------------------------------------------
# 4. test_parse_endpoint
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.parse_command", return_value=MOCK_ACTION)
def test_parse_endpoint(mock_pc, client):
    """POST /api/parse returns action JSON."""
    resp = client.post("/api/parse", json={
        "text": "remove the silence",
        "input_path": "test.mp4",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "silence_remove"
    assert data["confidence"] == 0.95
    mock_pc.assert_called_once_with("remove the silence", "test.mp4")


# ---------------------------------------------------------------------------
# 5. test_execute_endpoint
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.execute_action", return_value=MOCK_EXECUTE_RESULT)
def test_execute_endpoint(mock_ea, client):
    """POST /api/execute returns execution result."""
    resp = client.post("/api/execute", json={
        "action": MOCK_ACTION,
        "input_path": "test.mp4",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["action"] == "silence_remove"
    mock_ea.assert_called_once_with(MOCK_ACTION, "test.mp4")


# ---------------------------------------------------------------------------
# 6. test_chunks_cache
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.transcribe_video", return_value=MOCK_CHUNKS)
@patch("agents.edbot.server.Path.exists", return_value=True)
def test_chunks_cache(mock_exists, mock_tv, client):
    """GET /api/chunks returns cached data after transcribe."""
    # Before transcribe — 404
    resp = client.get("/api/chunks")
    assert resp.status_code == 404

    # Run transcribe to populate cache
    client.post("/api/transcribe", json={
        "input_path": "test.mp4",
        "output_dir": "output",
    })

    # Now cache should be populated
    resp = client.get("/api/chunks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "test.mp4"
    assert len(data["chunks"]) == 3


# ---------------------------------------------------------------------------
# 7. test_outputs_list
# ---------------------------------------------------------------------------

def test_outputs_list(client):
    """GET /api/outputs returns file list (may be empty)."""
    resp = client.get("/api/outputs")
    assert resp.status_code == 200
    data = resp.json()
    assert "files" in data
    assert isinstance(data["files"], list)


# ---------------------------------------------------------------------------
# 8. test_video_serve
# ---------------------------------------------------------------------------

def test_video_serve(client):
    """GET /video/{path} serves a file from an allowed directory."""
    # Create a temp file in a temp directory, then add that dir to allowed list
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        test_file = tmpdir_path / "test.mp4"
        test_file.write_bytes(b"\x00" * 1024)  # 1KB dummy file

        # Temporarily add the temp dir to allowed dirs
        ALLOWED_VIDEO_DIRS.append(tmpdir_path)
        try:
            # Use absolute path
            resp = client.get(f"/video/{str(test_file)}")
            assert resp.status_code == 200
            assert len(resp.content) == 1024
        finally:
            ALLOWED_VIDEO_DIRS.pop()


# ---------------------------------------------------------------------------
# 9. test_video_path_traversal
# ---------------------------------------------------------------------------

def test_video_path_traversal(client):
    """Path traversal attempts are rejected (403 or 404, never 200)."""
    # Direct ".." — HTTP client may normalize this, but server still rejects
    resp = client.get("/video/../../etc/passwd")
    assert resp.status_code in (403, 404)

    # URL-encoded dots bypass client normalization and reach our handler
    resp2 = client.get("/video/%2e%2e/%2e%2e/etc/passwd")
    assert resp2.status_code in (403, 404)

    # Absolute path outside allowed dirs
    resp3 = client.get("/video/C:/Windows/System32/config/SAM")
    assert resp3.status_code in (403, 404)


# ---------------------------------------------------------------------------
# 10. test_cors_headers
# ---------------------------------------------------------------------------

def test_cors_headers(client):
    """CORS allow-origin header is present on responses."""
    resp = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == "*"


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------

def test_silence_map_cache_empty(client):
    """GET /api/silence_map returns 404 when cache is empty."""
    resp = client.get("/api/silence_map")
    assert resp.status_code == 404


@patch("agents.edbot.server.detect_silence", return_value=MOCK_SILENCE_MAP)
def test_silence_map_cache_populated(mock_ds, client):
    """GET /api/silence_map returns data after silence detection."""
    client.post("/api/silence", json={
        "input_path": "test.mp4",
        "output_dir": "output",
    })
    resp = client.get("/api/silence_map")
    assert resp.status_code == 200
    assert resp.json()["source"] == "test.mp4"


@patch("agents.edbot.server.execute_action", return_value={
    "status": "error", "error": "ffmpeg crashed",
    "action": "trim", "input": "x.mp4", "output": None,
    "duration_in": None, "duration_out": None,
    "ffmpeg_cmd": None, "elapsed_seconds": 0.1,
})
def test_execute_error_returns_500(mock_ea, client):
    """POST /api/execute with failed action returns 500."""
    resp = client.post("/api/execute", json={
        "action": {"action": "trim", "params": {}, "executor": "ffmpeg"},
        "input_path": "x.mp4",
    })
    assert resp.status_code == 500


def test_viewer_root(client):
    """GET / returns HTML (either viewer or placeholder)."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_video_range_request(client):
    """GET /video/{path} with Range header returns 206 partial content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        test_file = tmpdir_path / "range_test.mp4"
        test_file.write_bytes(b"A" * 2048)

        ALLOWED_VIDEO_DIRS.append(tmpdir_path)
        try:
            resp = client.get(
                f"/video/{str(test_file)}",
                headers={"Range": "bytes=0-511"},
            )
            assert resp.status_code == 206
            assert len(resp.content) == 512
            assert "bytes 0-511/2048" in resp.headers.get("content-range", "")
        finally:
            ALLOWED_VIDEO_DIRS.pop()
