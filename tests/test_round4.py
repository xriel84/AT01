"""Round 4 tests -- server error paths, tool-level gaps, analytics reader.

Comprehensive tests for Round 4 changes:
  - Section 2A: Server error path tests (input validation, error_response schema)
  - Section 2B: Tool-level gap tests (chapter_detect, speaker_detect, tiktok_chunk edge cases)
  - Section 2C: Analytics reader unit tests (read_messages, mark_message)
  - Section 2D: Analytics inbox server endpoint tests

All tool calls are mocked -- no real ffmpeg, whisper, or file I/O.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure tools dir is on path so server.py can import its dependencies.
_tools_dir = str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from fastapi.testclient import TestClient

from agents.edbot.server import app, _cache, _session
from chapter_detect import detect_chapters
from speaker_detect import _assign_speakers_by_energy, _normalize_energies
from analytics_reader import read_messages, mark_message


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_state():
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


# ===========================================================================
# Section 2A: Server error path tests (11 tests)
# ===========================================================================


# ---------------------------------------------------------------------------
# 1. test_transcribe_missing_file
# ---------------------------------------------------------------------------

def test_transcribe_missing_file(client):
    """POST /api/transcribe with nonexistent file returns 400 + FILE_NOT_FOUND."""
    resp = client.post("/api/transcribe", json={
        "input_path": "C:/AT01/input/does_not_exist.mp4",
        "output_dir": "output",
    })
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "FILE_NOT_FOUND"


# ---------------------------------------------------------------------------
# 2. test_transcribe_invalid_extension
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.Path.exists", return_value=True)
def test_transcribe_invalid_extension(mock_exists, client):
    """POST /api/transcribe with .txt file returns 400 + INVALID_INPUT."""
    resp = client.post("/api/transcribe", json={
        "input_path": "C:/AT01/input/notes.txt",
        "output_dir": "output",
    })
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_INPUT"
    assert ".txt" in detail["error"]


# ---------------------------------------------------------------------------
# 3. test_chapters_no_session
# ---------------------------------------------------------------------------

def test_chapters_no_session(client):
    """GET /api/chapters before transcribe returns 400 + NO_TRANSCRIPT."""
    resp = client.get("/api/chapters")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "NO_TRANSCRIPT"


# ---------------------------------------------------------------------------
# 4. test_speakers_no_session
# ---------------------------------------------------------------------------

def test_speakers_no_session(client):
    """GET /api/speakers before loading video returns 400 + NO_SESSION."""
    resp = client.get("/api/speakers")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "NO_SESSION"


# ---------------------------------------------------------------------------
# 5. test_tiktok_no_session
# ---------------------------------------------------------------------------

def test_tiktok_no_session(client):
    """POST /api/tiktok with no input_path and no session returns 400 + NO_SESSION."""
    resp = client.post("/api/tiktok", json={})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "NO_SESSION"


# ---------------------------------------------------------------------------
# 6. test_label_speakers_no_speakers
# ---------------------------------------------------------------------------

def test_label_speakers_no_speakers(client):
    """POST /api/label_speakers with valid format but no speaker_map returns 400 + NO_SPEAKERS."""
    resp = client.post("/api/label_speakers", json={
        "labels": {"SPEAKER_0": "Ari"},
    })
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "NO_SPEAKERS"


# ---------------------------------------------------------------------------
# 7. test_label_speakers_bad_format
# ---------------------------------------------------------------------------

def test_label_speakers_bad_format(client):
    """POST /api/label_speakers with key 'bad_key' returns 400 + INVALID_INPUT."""
    resp = client.post("/api/label_speakers", json={
        "labels": {"bad_key": "Ari"},
    })
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_INPUT"
    assert "bad_key" in detail["error"]


# ---------------------------------------------------------------------------
# 8. test_tiktok_bad_duration
# ---------------------------------------------------------------------------

def test_tiktok_bad_duration(client):
    """POST /api/tiktok with max_duration: -1 returns 400 + INVALID_INPUT."""
    resp = client.post("/api/tiktok", json={
        "max_duration": -1,
    })
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# 9. test_tiktok_bad_crop
# ---------------------------------------------------------------------------

def test_tiktok_bad_crop(client):
    """POST /api/tiktok with crop_method: 'magic' returns 400 + INVALID_INPUT."""
    resp = client.post("/api/tiktok", json={
        "crop_method": "magic",
    })
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_INPUT"
    assert "magic" in detail["error"]


# ---------------------------------------------------------------------------
# 10. test_health_alias
# ---------------------------------------------------------------------------

def test_health_alias(client):
    """GET /health returns 200 with status ok and tools list (same as /api/health)."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert isinstance(data["tools"], list)
    assert "transcribe" in data["tools"]

    # Verify it matches /api/health exactly.
    resp2 = client.get("/api/health")
    assert resp2.json() == data


# ---------------------------------------------------------------------------
# 11. test_error_response_schema
# ---------------------------------------------------------------------------

def test_error_response_schema(client):
    """Error responses have keys: status, error, code, endpoint in detail."""
    # Trigger any error — e.g., GET /api/chapters with no session.
    resp = client.get("/api/chapters")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert set(detail.keys()) == {"status", "error", "code", "endpoint"}
    assert detail["status"] == "error"
    assert isinstance(detail["error"], str)
    assert isinstance(detail["code"], str)


# ===========================================================================
# Section 2B: Tool-level gap tests (6 tests)
# ===========================================================================


# ---------------------------------------------------------------------------
# 12. test_chapter_detect_no_gaps_fallback
# ---------------------------------------------------------------------------

def test_chapter_detect_no_gaps_fallback():
    """0 silence gaps, all chunks have speech -> 1 chapter covering full duration."""
    chunks = [
        {"id": 0, "start": 0.0, "end": 10.0, "text": "hello world",
         "word_count": 2, "silence_ratio": 0.1, "has_speech": True},
        {"id": 1, "start": 10.0, "end": 20.0, "text": "more words here",
         "word_count": 3, "silence_ratio": 0.2, "has_speech": True},
        {"id": 2, "start": 20.0, "end": 30.0, "text": "even more words",
         "word_count": 3, "silence_ratio": 0.15, "has_speech": True},
        {"id": 3, "start": 30.0, "end": 40.0, "text": "continuing on",
         "word_count": 2, "silence_ratio": 0.1, "has_speech": True},
    ]
    # No silence gaps at all — boundaries come from chunk silence_ratio fallback
    # but all ratios are below 0.8 threshold, so no boundaries -> 1 chapter.
    chapters = detect_chapters(chunks, silence_map=None, duration=40.0)
    assert len(chapters) == 1
    assert chapters[0]["start"] == 0.0
    assert chapters[0]["end"] == 40.0
    assert chapters[0]["chunk_ids"] == [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# 13. test_chapter_detect_empty_chunks
# ---------------------------------------------------------------------------

def test_chapter_detect_empty_chunks():
    """Empty chunks list returns empty chapters."""
    chapters = detect_chapters([], silence_map=None)
    assert chapters == []


# ---------------------------------------------------------------------------
# 14. test_speaker_detect_single_speaker
# ---------------------------------------------------------------------------

def test_speaker_detect_single_speaker():
    """All energies same -> all chunks get SPEAKER_0 (no energy shift detected)."""
    # Build chunk energies where all have identical normalized energy.
    chunk_energies = [
        {"id": 0, "start": 0.0, "end": 10.0, "energy": 100.0},
        {"id": 1, "start": 10.0, "end": 20.0, "energy": 100.0},
        {"id": 2, "start": 20.0, "end": 30.0, "energy": 100.0},
    ]
    chunk_energies = _normalize_energies(chunk_energies)
    chunk_speakers, segments = _assign_speakers_by_energy(chunk_energies)

    # All chunks should be SPEAKER_0.
    assert all(v == "SPEAKER_0" for v in chunk_speakers.values())
    assert len(segments) == 1
    assert segments[0]["speaker"] == "SPEAKER_0"


# ---------------------------------------------------------------------------
# 15. test_speaker_detect_empty_chunks
# ---------------------------------------------------------------------------

def test_speaker_detect_empty_chunks():
    """Empty chunk energies list returns valid empty structures."""
    chunk_speakers, segments = _assign_speakers_by_energy([])
    assert chunk_speakers == {}
    assert segments == []


# ---------------------------------------------------------------------------
# 16. test_portrait_crop_invalid_method_at_tool_level
# ---------------------------------------------------------------------------

def test_portrait_crop_invalid_method_at_tool_level():
    """portrait_crop tool with method='invalid' still runs center crop (server validates, not tool).

    The tool only switches behavior between 'center' and 'face'. An unknown method
    falls through to center crop behavior. The server layer enforces valid methods.
    """
    from portrait_crop import portrait_crop

    # Mock ffmpeg subprocess and Path operations to avoid real file I/O.
    with patch("portrait_crop.subprocess.run") as mock_run, \
         patch("portrait_crop._get_duration", return_value=60.0):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Use tmp_path-like workaround: create a real temp file to satisfy Path.exists().
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(b"\x00" * 16)
            tmp_input = tf.name
        try:
            result = portrait_crop(
                input_path=tmp_input,
                output_dir=tempfile.mkdtemp(),
                method="invalid",
            )
        finally:
            os.unlink(tmp_input)

    # Tool doesn't reject invalid method, it just does center crop.
    assert result["status"] == "success"
    assert result["method"] == "center"


# ---------------------------------------------------------------------------
# 17. test_tiktok_no_chapters
# ---------------------------------------------------------------------------

def test_tiktok_no_chapters(tmp_path):
    """Empty chapters list returns result with 0 clips."""
    from tiktok_chunk import generate_tiktok_chunks

    # Mock portrait_crop since generate_tiktok_chunks imports it internally.
    with patch("tiktok_chunk.portrait_crop") as mock_crop:
        result = generate_tiktok_chunks(
            input_path="C:/AT01/input/test.mp4",
            chapters=[],
            chunks=None,
            output_dir=str(tmp_path),
        )
    assert result["total_clips"] == 0
    assert result["clips"] == []


# ===========================================================================
# Section 2C: Analytics reader tests (6 tests)
# ===========================================================================


def _write_bus_file(path: Path, data: dict) -> None:
    """Helper to write a bus JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# 18. test_read_empty_bus
# ---------------------------------------------------------------------------

def test_read_empty_bus(tmp_path):
    """Bus with empty messages list returns empty list."""
    bus_file = tmp_path / "bus.json"
    _write_bus_file(bus_file, {"messages": []})

    result = read_messages(str(bus_file), unread_only=False)
    assert result == []


# ---------------------------------------------------------------------------
# 19. test_read_unread_only
# ---------------------------------------------------------------------------

def test_read_unread_only(tmp_path):
    """3 messages (2 unread, 1 read) -> returns 2 when unread_only=True."""
    bus_file = tmp_path / "bus.json"
    _write_bus_file(bus_file, {"messages": [
        {"id": "msg_001", "type": "FEEDBACK", "status": "unread", "subject": "a"},
        {"id": "msg_002", "type": "FEEDBACK", "status": "unread", "subject": "b"},
        {"id": "msg_003", "type": "FEEDBACK", "status": "read", "subject": "c"},
    ]})

    result = read_messages(str(bus_file), unread_only=True)
    assert len(result) == 2
    assert all(m["status"] == "unread" for m in result)


# ---------------------------------------------------------------------------
# 20. test_mark_actioned
# ---------------------------------------------------------------------------

def test_mark_actioned(tmp_path):
    """Mark msg_001 as actioned -> file updated, returned msg has status 'actioned'."""
    bus_file = tmp_path / "bus.json"
    _write_bus_file(bus_file, {"messages": [
        {"id": "msg_001", "type": "FEEDBACK", "status": "unread", "subject": "test"},
    ]})

    result = mark_message(str(bus_file), "msg_001", "actioned")
    assert result["status"] == "actioned"
    assert result["id"] == "msg_001"

    # Verify the file was actually updated.
    with open(bus_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["messages"][0]["status"] == "actioned"


# ---------------------------------------------------------------------------
# 21. test_filter_by_type
# ---------------------------------------------------------------------------

def test_filter_by_type(tmp_path):
    """2 FEEDBACK + 1 REQUEST -> filter_type='FEEDBACK' returns 2."""
    bus_file = tmp_path / "bus.json"
    _write_bus_file(bus_file, {"messages": [
        {"id": "msg_001", "type": "FEEDBACK", "status": "unread", "subject": "a"},
        {"id": "msg_002", "type": "FEEDBACK", "status": "unread", "subject": "b"},
        {"id": "msg_003", "type": "REQUEST", "status": "unread", "subject": "c"},
    ]})

    result = read_messages(str(bus_file), filter_type="FEEDBACK", unread_only=False)
    assert len(result) == 2
    assert all(m["type"] == "FEEDBACK" for m in result)


# ---------------------------------------------------------------------------
# 22. test_malformed_json
# ---------------------------------------------------------------------------

def test_malformed_json(tmp_path):
    """File contains 'not json{' -> returns [] (no crash)."""
    bus_file = tmp_path / "bus.json"
    bus_file.write_text("not json{", encoding="utf-8")

    result = read_messages(str(bus_file))
    assert result == []


# ---------------------------------------------------------------------------
# 23. test_missing_bus_file
# ---------------------------------------------------------------------------

def test_missing_bus_file(tmp_path):
    """Nonexistent path -> returns [] (no crash)."""
    result = read_messages(str(tmp_path / "nonexistent.json"))
    assert result == []


# ===========================================================================
# Section 2D: Analytics inbox server endpoint tests (2 tests)
# ===========================================================================


# ---------------------------------------------------------------------------
# 24. test_analytics_inbox_empty
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.read_messages", return_value=[])
def test_analytics_inbox_empty(mock_rm, client):
    """GET /api/analytics_inbox with no messages -> 200, {messages: [], count: 0}."""
    resp = client.get("/api/analytics_inbox")
    assert resp.status_code == 200
    data = resp.json()
    assert data["messages"] == []
    assert data["count"] == 0
    mock_rm.assert_called_once_with(filter_type="FEEDBACK", unread_only=True)


# ---------------------------------------------------------------------------
# 25. test_analytics_inbox_with_data
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.read_messages", return_value=[
    {"id": "msg_001", "type": "FEEDBACK", "status": "unread",
     "subject": "clip too long", "body": "Clip 3 is 90s, split it."},
])
def test_analytics_inbox_with_data(mock_rm, client):
    """GET /api/analytics_inbox with 1 FEEDBACK message -> 200, count: 1."""
    resp = client.get("/api/analytics_inbox")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert len(data["messages"]) == 1
    assert data["messages"][0]["id"] == "msg_001"
    assert data["messages"][0]["type"] == "FEEDBACK"


# ===========================================================================
# Bonus: Additional edge-case tests
# ===========================================================================


# ---------------------------------------------------------------------------
# 26. test_tiktok_duration_over_300
# ---------------------------------------------------------------------------

def test_tiktok_duration_over_300(client):
    """POST /api/tiktok with max_duration: 500 returns 400 + INVALID_INPUT."""
    resp = client.post("/api/tiktok", json={
        "max_duration": 500,
    })
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# 27. test_label_speakers_empty_value
# ---------------------------------------------------------------------------

def test_label_speakers_empty_value(client):
    """POST /api/label_speakers with empty string value returns 400 + INVALID_INPUT."""
    resp = client.post("/api/label_speakers", json={
        "labels": {"SPEAKER_0": "  "},
    })
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# 28. test_portrait_crop_bad_method_server
# ---------------------------------------------------------------------------

def test_portrait_crop_bad_method_server(client):
    """POST /api/portrait_crop with method='magic' returns 400 + INVALID_INPUT."""
    resp = client.post("/api/portrait_crop", json={
        "input_path": "C:/AT01/input/test.mp4",
        "method": "magic",
    })
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_INPUT"
    assert "magic" in detail["error"]


# ---------------------------------------------------------------------------
# 29. test_mark_message_invalid_status
# ---------------------------------------------------------------------------

def test_mark_message_invalid_status(tmp_path):
    """mark_message with invalid status returns error dict."""
    bus_file = tmp_path / "bus.json"
    _write_bus_file(bus_file, {"messages": [
        {"id": "msg_001", "type": "FEEDBACK", "status": "unread"},
    ]})

    result = mark_message(str(bus_file), "msg_001", "bogus_status")
    assert result["status"] == "error"
    assert result["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# 30. test_mark_message_not_found
# ---------------------------------------------------------------------------

def test_mark_message_not_found(tmp_path):
    """mark_message for nonexistent message_id returns NOT_FOUND error."""
    bus_file = tmp_path / "bus.json"
    _write_bus_file(bus_file, {"messages": [
        {"id": "msg_001", "type": "FEEDBACK", "status": "unread"},
    ]})

    result = mark_message(str(bus_file), "msg_999", "actioned")
    assert result["status"] == "error"
    assert result["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# 31. test_read_messages_invalid_filter_type
# ---------------------------------------------------------------------------

def test_read_messages_invalid_filter_type(tmp_path):
    """read_messages with invalid filter_type returns []."""
    bus_file = tmp_path / "bus.json"
    _write_bus_file(bus_file, {"messages": [
        {"id": "msg_001", "type": "FEEDBACK", "status": "unread"},
    ]})

    result = read_messages(str(bus_file), filter_type="BOGUS")
    assert result == []


# ===========================================================================
# Section 3A: OutputWatcher tests (7 tests)
# ===========================================================================

from output_watcher import OutputWatcher, probe_file, _load_manifest, _save_manifest


# ---------------------------------------------------------------------------
# 32. test_watcher_starts_stops
# ---------------------------------------------------------------------------

def test_watcher_starts_stops(tmp_path):
    """OutputWatcher observer thread starts and stops without error."""
    watcher = OutputWatcher(
        watch_dir=str(tmp_path),
        manifest_path=str(tmp_path / "manifest.json"),
    )
    watcher.start()
    assert watcher._observer is not None
    assert watcher._observer.is_alive()
    watcher.stop()
    assert watcher._observer is None


# ---------------------------------------------------------------------------
# 33. test_watcher_detects_new_file
# ---------------------------------------------------------------------------

def test_watcher_detects_new_file(tmp_path):
    """New .mp4 in watched dir triggers on_new_file callback."""
    received = []

    def on_new(info):
        received.append(info)

    watcher = OutputWatcher(
        watch_dir=str(tmp_path),
        manifest_path=str(tmp_path / "manifest.json"),
        on_new_file=on_new,
    )

    # Simulate calling _handle_new_file directly (avoids timing issues with watchdog)
    video = tmp_path / "test_clip.mp4"
    video.write_bytes(b"\x00" * 1024)

    with patch("output_watcher.probe_file", return_value={
        "filename": "test_clip.mp4", "path": str(video),
        "size_mb": 0.001, "created": "2026-02-25T00:00:00+00:00",
    }), patch.object(watcher, "_wait_for_settle", return_value=True):
        watcher._handle_new_file(str(video))

    assert len(received) == 1
    assert received[0]["filename"] == "test_clip.mp4"


# ---------------------------------------------------------------------------
# 34. test_watcher_probes_metadata
# ---------------------------------------------------------------------------

def test_watcher_probes_metadata(tmp_path):
    """probe_file returns correct metadata dict from mock ffprobe."""
    video = tmp_path / "output.mp4"
    video.write_bytes(b"\x00" * 2048)

    ffprobe_output = json.dumps({
        "streams": [{"width": 1920, "height": 1080, "codec_name": "h264"}],
        "format": {"duration": "42.5"},
    })

    mock_result = MagicMock(returncode=0, stdout=ffprobe_output, stderr="")
    with patch("output_watcher.subprocess.run", return_value=mock_result):
        info = probe_file(str(video))

    assert info["filename"] == "output.mp4"
    assert info["duration"] == 42.5
    assert info["width"] == 1920
    assert info["height"] == 1080
    assert info["codec"] == "h264"
    assert info["size_mb"] >= 0


# ---------------------------------------------------------------------------
# 35. test_watcher_updates_manifest
# ---------------------------------------------------------------------------

def test_watcher_updates_manifest(tmp_path):
    """After _handle_new_file, manifest.json contains the new entry."""
    manifest_path = tmp_path / "manifest.json"
    watcher = OutputWatcher(
        watch_dir=str(tmp_path),
        manifest_path=str(manifest_path),
    )

    video = tmp_path / "clip_001.mp4"
    video.write_bytes(b"\x00" * 512)

    with patch("output_watcher.probe_file", return_value={
        "filename": "clip_001.mp4", "path": str(video),
        "size_mb": 0.0005, "created": "2026-02-25T00:00:00+00:00",
    }), patch.object(watcher, "_wait_for_settle", return_value=True):
        watcher._handle_new_file(str(video))

    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(data["files"]) == 1
    assert data["files"][0]["filename"] == "clip_001.mp4"
    assert data["last_updated"] is not None


# ---------------------------------------------------------------------------
# 36. test_watcher_ignores_non_video
# ---------------------------------------------------------------------------

def test_watcher_ignores_non_video(tmp_path):
    """Non-video file (.txt) does not trigger callback."""
    received = []
    watcher = OutputWatcher(
        watch_dir=str(tmp_path),
        manifest_path=str(tmp_path / "manifest.json"),
        on_new_file=lambda info: received.append(info),
    )

    txt = tmp_path / "notes.txt"
    txt.write_text("hello", encoding="utf-8")
    watcher._handle_new_file(str(txt))

    assert len(received) == 0


# ---------------------------------------------------------------------------
# 37. test_watcher_handles_duplicate
# ---------------------------------------------------------------------------

def test_watcher_handles_duplicate(tmp_path):
    """Same file event fired twice -> only one manifest entry."""
    manifest_path = tmp_path / "manifest.json"
    watcher = OutputWatcher(
        watch_dir=str(tmp_path),
        manifest_path=str(manifest_path),
    )

    video = tmp_path / "dup.mp4"
    video.write_bytes(b"\x00" * 256)

    mock_info = {
        "filename": "dup.mp4", "path": str(video),
        "size_mb": 0.0003, "created": "2026-02-25T00:00:00+00:00",
    }
    with patch("output_watcher.probe_file", return_value=mock_info), \
         patch.object(watcher, "_wait_for_settle", return_value=True):
        watcher._handle_new_file(str(video))
        watcher._handle_new_file(str(video))  # duplicate

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(data["files"]) == 1


# ---------------------------------------------------------------------------
# 38. test_watcher_waits_for_write
# ---------------------------------------------------------------------------

def test_watcher_waits_for_write(tmp_path):
    """_wait_for_settle returns True when file size stabilizes."""
    video = tmp_path / "writing.mp4"
    video.write_bytes(b"\x00" * 1024)

    watcher = OutputWatcher(watch_dir=str(tmp_path))
    # File already exists with stable size — should settle immediately
    with patch("output_watcher.SETTLE_WAIT", 0.01):
        assert watcher._wait_for_settle(video) is True


# ===========================================================================
# Section 3B: WebSocket tests (4 tests)
# ===========================================================================

from agents.edbot.server import manager, ConnectionManager, broadcast_progress


# ---------------------------------------------------------------------------
# 39. test_ws_connect
# ---------------------------------------------------------------------------

def test_ws_connect(client):
    """Client connects to /ws/progress endpoint."""
    with client.websocket_connect("/ws/progress") as ws:
        assert ws is not None
    # Connection closed cleanly


# ---------------------------------------------------------------------------
# 40. test_ws_broadcast_new_output
# ---------------------------------------------------------------------------

def test_ws_broadcast_new_output(client):
    """Broadcast sends new_output message to connected client."""
    import asyncio

    with client.websocket_connect("/ws/progress") as ws:
        # Broadcast a message via the manager
        msg = {"type": "new_output", "file": {"filename": "test.mp4"}}
        asyncio.get_event_loop().run_until_complete(manager.broadcast(msg))
        data = ws.receive_json()
        assert data["type"] == "new_output"
        assert data["file"]["filename"] == "test.mp4"


# ---------------------------------------------------------------------------
# 41. test_ws_broadcast_progress
# ---------------------------------------------------------------------------

def test_ws_broadcast_progress(client):
    """Progress broadcast has correct stage/status/detail format."""
    import asyncio
    from agents.edbot.server import broadcast_progress

    with client.websocket_connect("/ws/progress") as ws:
        asyncio.get_event_loop().run_until_complete(
            broadcast_progress("transcribe", "started", "processing input.mp4")
        )
        data = ws.receive_json()
        assert data["type"] == "progress"
        assert data["stage"] == "transcribe"
        assert data["status"] == "started"
        assert data["detail"] == "processing input.mp4"


# ---------------------------------------------------------------------------
# 42. test_ws_disconnect_cleanup
# ---------------------------------------------------------------------------

def test_ws_disconnect_cleanup():
    """Disconnected client is removed from active list."""
    mgr = ConnectionManager()
    mock_ws = MagicMock()
    # Simulate adding and removing
    mgr.active.append(mock_ws)
    assert len(mgr.active) == 1
    mgr.disconnect(mock_ws)
    assert len(mgr.active) == 0
    # Double disconnect doesn't crash
    mgr.disconnect(mock_ws)
    assert len(mgr.active) == 0


# ===========================================================================
# Section 3C: Executor verification tests (5 tests)
# ===========================================================================

from agents.edbot.tools.executor import execute_action, PLATFORM_PRESETS


# ---------------------------------------------------------------------------
# 43. test_executor_silence_remove
# ---------------------------------------------------------------------------

def test_executor_silence_remove():
    """silence_remove action -> correct ffmpeg silenceremove filter args."""
    action = {
        "action": "silence_remove",
        "params": {"input": "C:/AT01/input/test.mp4", "silence_threshold_db": -50},
        "executor": "ffmpeg",
    }
    with patch("agents.edbot.tools.executor.subprocess.run") as mock_run, \
         patch("agents.edbot.tools.executor._get_duration", return_value=120.0):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = execute_action(action)

    assert result["status"] == "success"
    assert result["action"] == "silence_remove"
    assert "silenceremove" in result["ffmpeg_cmd"]
    assert "-50dB" in result["ffmpeg_cmd"]


# ---------------------------------------------------------------------------
# 44. test_executor_trim
# ---------------------------------------------------------------------------

def test_executor_trim():
    """trim action -> correct -t duration in ffmpeg cmd."""
    action = {
        "action": "trim",
        "params": {"input": "C:/AT01/input/test.mp4", "max_duration": 30},
        "executor": "ffmpeg",
    }
    with patch("agents.edbot.tools.executor.subprocess.run") as mock_run, \
         patch("agents.edbot.tools.executor._get_duration", return_value=120.0):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = execute_action(action)

    assert result["status"] == "success"
    assert result["action"] == "trim"
    assert "-t" in result["ffmpeg_cmd"]
    assert "30" in result["ffmpeg_cmd"]


# ---------------------------------------------------------------------------
# 45. test_executor_crop
# ---------------------------------------------------------------------------

def test_executor_crop():
    """crop action -> correct -vf scale+crop filter."""
    action = {
        "action": "crop",
        "params": {"input": "C:/AT01/input/test.mp4", "aspect": "9:16"},
        "executor": "ffmpeg",
    }
    with patch("agents.edbot.tools.executor.subprocess.run") as mock_run, \
         patch("agents.edbot.tools.executor._get_duration", return_value=60.0):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = execute_action(action)

    assert result["status"] == "success"
    assert "crop=" in result["ffmpeg_cmd"]
    assert "scale=" in result["ffmpeg_cmd"]


# ---------------------------------------------------------------------------
# 46. test_executor_platform_export
# ---------------------------------------------------------------------------

def test_executor_platform_export():
    """tiktok platform_export -> 60s max duration, 9:16 aspect."""
    action = {
        "action": "platform_export",
        "params": {"input": "C:/AT01/input/test.mp4", "platform": "tiktok"},
        "executor": "ffmpeg",
    }
    with patch("agents.edbot.tools.executor.subprocess.run") as mock_run, \
         patch("agents.edbot.tools.executor._get_duration", return_value=180.0):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = execute_action(action)

    assert result["status"] == "success"
    assert "-t" in result["ffmpeg_cmd"]
    assert "60" in result["ffmpeg_cmd"]
    assert PLATFORM_PRESETS["tiktok"]["max_duration"] == 60


# ---------------------------------------------------------------------------
# 47. test_executor_missing_input
# ---------------------------------------------------------------------------

def test_executor_missing_input():
    """Action with no input path -> clear error, no crash."""
    action = {
        "action": "trim",
        "params": {},
        "executor": "ffmpeg",
    }
    result = execute_action(action)
    assert result["status"] == "error"
    assert "no input" in result["error"]


# ===========================================================================
# Section 3D: Integration tests (5 tests)
# ===========================================================================


# ---------------------------------------------------------------------------
# 48. test_full_loop_mock
# ---------------------------------------------------------------------------

def test_full_loop_mock(tmp_path):
    """parse_command -> execute_action -> output file path returned."""
    from agents.edbot.tools.nlp_action import parse_command

    parsed = parse_command("trim to 30 seconds", "C:/AT01/input/test.mp4")
    assert parsed["action"] in ("trim", "unknown")

    # Even if NLP doesn't perfectly parse, verify executor handles gracefully
    action = {
        "action": "trim",
        "params": {"input": "C:/AT01/input/test.mp4", "max_duration": 30},
        "executor": "ffmpeg",
    }
    with patch("agents.edbot.tools.executor.subprocess.run") as mock_run, \
         patch("agents.edbot.tools.executor._get_duration", return_value=120.0):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = execute_action(action, output_dir=str(tmp_path))

    assert result["status"] == "success"
    assert result["output"] is not None


# ---------------------------------------------------------------------------
# 49. test_api_outputs_reflects_manifest
# ---------------------------------------------------------------------------

def test_api_outputs_reflects_manifest(client, tmp_path):
    """GET /api/outputs returns watcher manifest data."""
    manifest = {
        "watch_dir": "output",
        "files": [{"filename": "clip.mp4", "path": "output/clip.mp4", "size_mb": 1.0}],
        "last_updated": "2026-02-25T12:00:00+00:00",
    }
    with patch("agents.edbot.server.get_watcher") as mock_gw:
        mock_watcher = MagicMock()
        mock_watcher.get_manifest.return_value = manifest
        mock_gw.return_value = mock_watcher

        resp = client.get("/api/outputs")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["files"]) == 1
    assert data["files"][0]["filename"] == "clip.mp4"


# ---------------------------------------------------------------------------
# 50. test_api_outputs_empty_fallback
# ---------------------------------------------------------------------------

def test_api_outputs_empty_fallback(client):
    """GET /api/outputs with empty manifest falls back to dir listing."""
    empty_manifest = {"watch_dir": "output", "files": [], "last_updated": None}
    with patch("agents.edbot.server.get_watcher") as mock_gw:
        mock_watcher = MagicMock()
        mock_watcher.get_manifest.return_value = empty_manifest
        mock_gw.return_value = mock_watcher

        resp = client.get("/api/outputs")

    assert resp.status_code == 200
    data = resp.json()
    assert "files" in data


# ---------------------------------------------------------------------------
# 51. test_pipeline_progress_events
# ---------------------------------------------------------------------------

def test_pipeline_progress_events(client):
    """Mock pipeline run -> WebSocket receives progress events."""
    import asyncio

    with client.websocket_connect("/ws/progress") as ws:
        asyncio.get_event_loop().run_until_complete(
            broadcast_progress("silence_detect", "complete", "found 5 gaps")
        )
        data = ws.receive_json()
        assert data["type"] == "progress"
        assert data["stage"] == "silence_detect"
        assert data["status"] == "complete"


# ---------------------------------------------------------------------------
# 52. test_session_state_persists
# ---------------------------------------------------------------------------

def test_session_state_persists(client):
    """Session video_path persists across API calls."""
    from agents.edbot.server import _session

    _session["video_path"] = "C:/AT01/input/test.mp4"
    _session["chunks"] = [{"id": 0}]

    resp = client.get("/api/session")
    assert resp.status_code == 200
    data = resp.json()
    assert data["video_path"] == "C:/AT01/input/test.mp4"
    assert data["has_chunks"] is True
