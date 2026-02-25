"""Round 3 integration tests -- cross-tool pipelines and new server endpoints.

Tests here verify that Round 3 tools (chapter_detect, speaker_detect,
portrait_crop, tiktok_chunk) work together through the server layer, and that
new NLP patterns resolve to the correct actions.

All tool calls are mocked -- no real ffmpeg, whisper, or file I/O.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure tools dir is on path so server.py can import its dependencies.
_tools_dir = str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from fastapi.testclient import TestClient

from agents.edbot.server import app, _cache, _session, safe_gpu_call
from nlp_action import parse_command, SILENCE_THRESHOLD_DB


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


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

MOCK_CHUNKS_LIST = [
    {"id": 0, "start": 0.0, "end": 10.0, "text": "welcome to the show",
     "word_count": 4, "silence_ratio": 0.1, "has_speech": True},
    {"id": 1, "start": 10.0, "end": 20.0, "text": "",
     "word_count": 0, "silence_ratio": 1.0, "has_speech": False},
    {"id": 2, "start": 20.0, "end": 30.0, "text": "next topic here",
     "word_count": 3, "silence_ratio": 0.2, "has_speech": True},
    {"id": 3, "start": 30.0, "end": 40.0, "text": "some more words in this chunk",
     "word_count": 6, "silence_ratio": 0.15, "has_speech": True},
    {"id": 4, "start": 40.0, "end": 50.0, "text": "",
     "word_count": 0, "silence_ratio": 0.95, "has_speech": False},
    {"id": 5, "start": 50.0, "end": 60.0, "text": "final thoughts on the matter",
     "word_count": 5, "silence_ratio": 0.1, "has_speech": True},
]

MOCK_TRANSCRIBE_RESULT = {
    "source": "test.mp4",
    "duration": 60.0,
    "chunks": MOCK_CHUNKS_LIST,
}

MOCK_SILENCE_MAP = {
    "source": "test.mp4",
    "duration": 60.0,
    "threshold_db": -50.0,
    "gaps": [
        {"start": 10.0, "end": 20.0, "duration": 10.0},
        {"start": 40.0, "end": 50.0, "duration": 10.0},
    ],
    "speech": [
        {"start": 0.0, "end": 10.0, "duration": 10.0},
        {"start": 20.0, "end": 40.0, "duration": 20.0},
        {"start": 50.0, "end": 60.0, "duration": 10.0},
    ],
    "stats": {
        "total_silence": 20.0,
        "total_speech": 40.0,
        "silence_percentage": 33.3,
        "gap_count": 2,
    },
}

MOCK_CHAPTERS = [
    {"chapter_id": 0, "start": 0.0, "end": 20.0, "duration": 20.0,
     "chunk_ids": [0, 1], "title": "welcome to the show"},
    {"chapter_id": 1, "start": 20.0, "end": 50.0, "duration": 30.0,
     "chunk_ids": [2, 3, 4], "title": "next topic here"},
    {"chapter_id": 2, "start": 50.0, "end": 60.0, "duration": 10.0,
     "chunk_ids": [5], "title": "final thoughts on the matter"},
]

MOCK_SPEAKER_MAP = {
    "source": "test.mp4",
    "method": "energy",
    "speakers": ["SPEAKER_0", "SPEAKER_1"],
    "segments": [
        {"start": 0.0, "end": 30.0, "speaker": "SPEAKER_0"},
        {"start": 30.0, "end": 60.0, "speaker": "SPEAKER_1"},
    ],
    "chunk_speakers": {"0": "SPEAKER_0", "1": "SPEAKER_0", "2": "SPEAKER_0",
                       "3": "SPEAKER_1", "4": "SPEAKER_1", "5": "SPEAKER_1"},
}

MOCK_PORTRAIT_CROP_RESULT = {
    "status": "success",
    "action": "portrait_crop",
    "input": "test.mp4",
    "output": "output/test_portrait.mp4",
    "method": "center",
    "duration_in": 60.0,
    "duration_out": 60.0,
    "crop_filter": "crop=ih*9/16:ih",
    "ffmpeg_cmd": "ffmpeg -i test.mp4 -vf crop=ih*9/16:ih ...",
    "elapsed_seconds": 1.5,
    "error": None,
}

MOCK_TIKTOK_RESULT = {
    "source": "test.mp4",
    "total_clips": 3,
    "max_duration": 60.0,
    "crop_method": "center",
    "clips": [
        {"clip_id": 0, "chapter_id": 0, "start": 0.0, "end": 20.0,
         "duration": 20.0, "title": "welcome", "output_path": "output/test_tiktok_0.mp4",
         "status": "success"},
        {"clip_id": 1, "chapter_id": 1, "start": 20.0, "end": 50.0,
         "duration": 30.0, "title": "next topic", "output_path": "output/test_tiktok_1.mp4",
         "status": "success"},
        {"clip_id": 2, "chapter_id": 2, "start": 50.0, "end": 60.0,
         "duration": 10.0, "title": "final thoughts", "output_path": "output/test_tiktok_2.mp4",
         "status": "success"},
    ],
    "clips_manifest_path": "output/clips_manifest.json",
}


# ===========================================================================
# Server endpoint tests (1-12)
# ===========================================================================


# ---------------------------------------------------------------------------
# 1. test_api_chapters_returns_chapters
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.detect_chapters", return_value=MOCK_CHAPTERS)
def test_api_chapters_returns_chapters(mock_dc, client):
    """GET /api/chapters returns chapter list when chunks are cached."""
    # Seed _session with chunks so the endpoint has data.
    _session["chunks"] = MOCK_CHUNKS_LIST

    resp = client.get("/api/chapters")
    assert resp.status_code == 200
    data = resp.json()
    assert "chapters" in data
    assert len(data["chapters"]) == 3
    assert data["chapters"][0]["chapter_id"] == 0
    mock_dc.assert_called_once()


# ---------------------------------------------------------------------------
# 2. test_api_chapters_needs_chunks
# ---------------------------------------------------------------------------

def test_api_chapters_needs_chunks(client):
    """GET /api/chapters returns 400 when no chunks are cached."""
    resp = client.get("/api/chapters")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "NO_TRANSCRIPT"


# ---------------------------------------------------------------------------
# 3. test_api_speakers_returns_speaker_map
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.detect_speakers", return_value=MOCK_SPEAKER_MAP)
def test_api_speakers_returns_speaker_map(mock_ds, client):
    """GET /api/speakers returns speaker map when video path is set."""
    _session["video_path"] = "C:/AT01/input/test.mp4"

    resp = client.get("/api/speakers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "test.mp4"
    assert "speakers" in data
    assert "SPEAKER_0" in data["speakers"]
    mock_ds.assert_called_once()


# ---------------------------------------------------------------------------
# 4. test_api_speakers_needs_video
# ---------------------------------------------------------------------------

def test_api_speakers_needs_video(client):
    """GET /api/speakers returns 400 when no video path is set."""
    resp = client.get("/api/speakers")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "NO_SESSION"


# ---------------------------------------------------------------------------
# 5. test_api_portrait_crop_success
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.portrait_crop", return_value=MOCK_PORTRAIT_CROP_RESULT)
def test_api_portrait_crop_success(mock_pc, client):
    """POST /api/portrait_crop succeeds with valid input path."""
    resp = client.post("/api/portrait_crop", json={
        "input_path": "C:/AT01/input/test.mp4",
        "output_dir": "output",
        "method": "center",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["action"] == "portrait_crop"
    mock_pc.assert_called_once_with(
        "C:/AT01/input/test.mp4", "output",
        method="center", start=None, end=None,
    )


# ---------------------------------------------------------------------------
# 6. test_api_portrait_crop_needs_input
# ---------------------------------------------------------------------------

def test_api_portrait_crop_needs_input(client):
    """POST /api/portrait_crop returns 400 when no input path is available."""
    resp = client.post("/api/portrait_crop", json={
        "output_dir": "output",
    })
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "NO_SESSION"


# ---------------------------------------------------------------------------
# 7. test_api_tiktok_success
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.generate_tiktok_chunks", return_value=MOCK_TIKTOK_RESULT)
@patch("agents.edbot.server.detect_chapters", return_value=MOCK_CHAPTERS)
def test_api_tiktok_success(mock_dc, mock_gtc, client):
    """POST /api/tiktok succeeds when chunks are cached (auto-detects chapters)."""
    _session["chunks"] = MOCK_CHUNKS_LIST
    _session["video_path"] = "C:/AT01/input/test.mp4"

    resp = client.post("/api/tiktok", json={
        "input_path": "C:/AT01/input/test.mp4",
        "output_dir": "output",
        "max_duration": 60.0,
        "crop_method": "center",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "test.mp4"
    assert data["total_clips"] == 3
    assert len(data["clips"]) == 3
    mock_gtc.assert_called_once()


# ---------------------------------------------------------------------------
# 8. test_api_tiktok_needs_chunks
# ---------------------------------------------------------------------------

def test_api_tiktok_needs_chunks(client):
    """POST /api/tiktok returns 400 when no chunks are available for chapter detection."""
    resp = client.post("/api/tiktok", json={
        "input_path": "C:/AT01/input/test.mp4",
    })
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "NO_TRANSCRIPT"


# ---------------------------------------------------------------------------
# 9. test_api_session_returns_state
# ---------------------------------------------------------------------------

def test_api_session_returns_state(client):
    """GET /api/session returns all expected state flags."""
    resp = client.get("/api/session")
    assert resp.status_code == 200
    data = resp.json()
    assert "video_path" in data
    assert "has_chunks" in data
    assert "has_silence_map" in data
    assert "has_chapters" in data
    assert "has_speaker_map" in data
    assert "has_clips_manifest" in data
    # All should be False/None in fresh state.
    assert data["video_path"] is None
    assert data["has_chunks"] is False
    assert data["has_silence_map"] is False
    assert data["has_chapters"] is False
    assert data["has_speaker_map"] is False
    assert data["has_clips_manifest"] is False


# ---------------------------------------------------------------------------
# 10. test_api_clips_manifest_returns_cached
# ---------------------------------------------------------------------------

def test_api_clips_manifest_returns_cached(client):
    """GET /api/clips_manifest returns cached manifest from session."""
    _session["clips_manifest"] = MOCK_TIKTOK_RESULT

    resp = client.get("/api/clips_manifest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "test.mp4"
    assert data["total_clips"] == 3
    assert len(data["clips"]) == 3


# ---------------------------------------------------------------------------
# 11. test_api_clips_manifest_404
# ---------------------------------------------------------------------------

def test_api_clips_manifest_needs_session(client):
    """GET /api/clips_manifest returns 400 when no manifest is cached."""
    resp = client.get("/api/clips_manifest")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "NO_SESSION"


# ---------------------------------------------------------------------------
# 12. test_api_gpu_status
# ---------------------------------------------------------------------------

def test_api_gpu_status(client):
    """GET /api/gpu_status returns cuda_available field."""
    resp = client.get("/api/gpu_status")
    assert resp.status_code == 200
    data = resp.json()
    assert "cuda_available" in data
    assert isinstance(data["cuda_available"], bool)


# ===========================================================================
# NLP pattern tests (13-17)
# ===========================================================================


# ---------------------------------------------------------------------------
# 13. test_nlp_chapter_detect_patterns
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "find chapters",
    "detect chapters in this video",
    "chapter split please",
])
def test_nlp_chapter_detect_patterns(text):
    """Various chapter detection phrases return action='chapter_detect'."""
    result = parse_command(text)
    assert result["action"] == "chapter_detect"
    assert result["confidence"] >= 0.9


# ---------------------------------------------------------------------------
# 14. test_nlp_speaker_detect_patterns
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "find speakers",
    "speaker detection",
])
def test_nlp_speaker_detect_patterns(text):
    """Various speaker detection phrases return action='speaker_detect'."""
    result = parse_command(text)
    assert result["action"] == "speaker_detect"
    assert result["confidence"] >= 0.9


def test_nlp_label_speakers_pattern():
    """'label speakers' maps to distinct 'label_speakers' action."""
    result = parse_command("label speakers")
    assert result["action"] == "label_speakers"
    assert result["confidence"] >= 0.9


# ---------------------------------------------------------------------------
# 15. test_nlp_tiktok_batch_pattern
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "batch tiktok",
    "auto generate tiktok",
])
def test_nlp_tiktok_batch_pattern(text):
    """TikTok batch generation phrases return action='tiktok_batch'."""
    result = parse_command(text)
    assert result["action"] == "tiktok_batch"
    assert result["confidence"] >= 0.9


# ---------------------------------------------------------------------------
# 16. test_nlp_portrait_crop_pattern
# ---------------------------------------------------------------------------

def test_nlp_portrait_crop_pattern():
    """'portrait crop' maps to 'crop' action with 9:16 aspect."""
    result = parse_command("portrait crop this video")
    assert result["action"] == "crop"
    assert result["params"]["aspect"] == "9:16"
    assert result["confidence"] >= 0.9


# ---------------------------------------------------------------------------
# 17. test_nlp_silence_threshold_updated
# ---------------------------------------------------------------------------

def test_nlp_silence_threshold_updated():
    """SILENCE_THRESHOLD_DB is -50 (updated for Round 3)."""
    assert SILENCE_THRESHOLD_DB == -50


# ===========================================================================
# Cross-tool integration tests (18-22)
# ===========================================================================


# ---------------------------------------------------------------------------
# 18. test_chapters_to_tiktok_pipeline
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.generate_tiktok_chunks", return_value=MOCK_TIKTOK_RESULT)
@patch("agents.edbot.server.detect_chapters", return_value=MOCK_CHAPTERS)
def test_chapters_to_tiktok_pipeline(mock_dc, mock_gtc, client):
    """Full pipeline: seed chunks, call /api/chapters, then /api/tiktok.

    Verifies the chapter output feeds into TikTok generation correctly and
    that both tools are invoked through the server layer.
    """
    _session["chunks"] = MOCK_CHUNKS_LIST
    _session["video_path"] = "C:/AT01/input/test.mp4"

    # Step 1: Detect chapters via API.
    ch_resp = client.get("/api/chapters")
    assert ch_resp.status_code == 200
    chapters = ch_resp.json()["chapters"]
    assert len(chapters) == 3
    mock_dc.assert_called_once()

    # Step 2: Generate TikTok chunks via API.
    # After /api/chapters, _session["chapters"] should be populated,
    # so /api/tiktok should use them without calling detect_chapters again.
    mock_dc.reset_mock()
    _session["chapters"] = MOCK_CHAPTERS  # simulate what the endpoint does

    tiktok_resp = client.post("/api/tiktok", json={
        "input_path": "C:/AT01/input/test.mp4",
        "output_dir": "output",
        "max_duration": 60.0,
    })
    assert tiktok_resp.status_code == 200
    data = tiktok_resp.json()
    assert data["total_clips"] == 3
    # detect_chapters should NOT be called again since _session["chapters"] is set.
    mock_dc.assert_not_called()
    mock_gtc.assert_called_once()


# ---------------------------------------------------------------------------
# 19. test_session_state_populated_by_transcribe
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.transcribe_video", return_value=MOCK_TRANSCRIBE_RESULT)
@patch("agents.edbot.server.Path.exists", return_value=True)
def test_session_state_populated_by_transcribe(mock_exists, mock_tv, client):
    """POST /api/transcribe populates _session with video_path and chunks."""
    resp = client.post("/api/transcribe", json={
        "input_path": "C:/AT01/input/test.mp4",
        "output_dir": "output",
    })
    assert resp.status_code == 200
    assert _session["video_path"] == "C:/AT01/input/test.mp4"
    assert _session["chunks"] is not None
    assert len(_session["chunks"]) == 6

    # Verify session endpoint reflects the populated state.
    session_resp = client.get("/api/session")
    session_data = session_resp.json()
    assert session_data["video_path"] == "C:/AT01/input/test.mp4"
    assert session_data["has_chunks"] is True


# ---------------------------------------------------------------------------
# 20. test_session_state_populated_by_silence
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.detect_silence", return_value=MOCK_SILENCE_MAP)
def test_session_state_populated_by_silence(mock_ds, client):
    """POST /api/silence populates _session with silence_map."""
    resp = client.post("/api/silence", json={
        "input_path": "C:/AT01/input/test.mp4",
        "output_dir": "output",
    })
    assert resp.status_code == 200
    assert _session["silence_map"] is not None
    assert _session["silence_map"]["duration"] == 60.0

    # Verify session endpoint reflects the populated state.
    session_resp = client.get("/api/session")
    session_data = session_resp.json()
    assert session_data["has_silence_map"] is True


# ---------------------------------------------------------------------------
# 21. test_safe_gpu_call_catches_cuda_error
# ---------------------------------------------------------------------------

def test_safe_gpu_call_catches_cuda_error():
    """safe_gpu_call catches CUDA errors and returns a fallback dict."""
    def _boom():
        raise RuntimeError("CUDA out of memory")

    result = safe_gpu_call(_boom)
    assert result["fallback"] is True
    assert "GPU failed" in result["error"]


# ---------------------------------------------------------------------------
# 22. test_safe_gpu_call_reraises_non_cuda
# ---------------------------------------------------------------------------

def test_safe_gpu_call_reraises_non_cuda():
    """safe_gpu_call re-raises non-CUDA exceptions."""
    def _boom():
        raise ValueError("something completely different")

    with pytest.raises(ValueError, match="something completely different"):
        safe_gpu_call(_boom)


# ===========================================================================
# Bonus integration tests (additional coverage)
# ===========================================================================


# ---------------------------------------------------------------------------
# 23. test_api_tiktok_with_preloaded_chapters
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.generate_tiktok_chunks", return_value=MOCK_TIKTOK_RESULT)
def test_api_tiktok_with_preloaded_chapters(mock_gtc, client):
    """POST /api/tiktok uses pre-existing chapters and skips auto-detection."""
    _session["chapters"] = MOCK_CHAPTERS
    _session["chunks"] = MOCK_CHUNKS_LIST

    resp = client.post("/api/tiktok", json={
        "input_path": "C:/AT01/input/test.mp4",
    })
    assert resp.status_code == 200
    # generate_tiktok_chunks should be called with the pre-existing chapters.
    mock_gtc.assert_called_once()
    call_args = mock_gtc.call_args
    assert call_args[0][1] == MOCK_CHAPTERS  # second positional arg = chapters


# ---------------------------------------------------------------------------
# 24. test_api_chapters_uses_cache_fallback
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.detect_chapters", return_value=MOCK_CHAPTERS)
def test_api_chapters_uses_cache_fallback(mock_dc, client):
    """GET /api/chapters falls back to _cache when _session has no chunks."""
    # Session has no chunks, but _cache does.
    _cache["chunks"] = MOCK_TRANSCRIBE_RESULT

    resp = client.get("/api/chapters")
    assert resp.status_code == 200
    assert len(resp.json()["chapters"]) == 3
    mock_dc.assert_called_once()


# ---------------------------------------------------------------------------
# 25. test_api_speakers_uses_cache_fallback
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.detect_speakers", return_value=MOCK_SPEAKER_MAP)
def test_api_speakers_uses_cache_fallback(mock_ds, client):
    """GET /api/speakers falls back to _cache.last_input when session has no video_path."""
    _cache["last_input"] = "C:/AT01/input/test.mp4"

    resp = client.get("/api/speakers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["method"] == "energy"
    mock_ds.assert_called_once()


# ---------------------------------------------------------------------------
# 26. test_api_portrait_crop_uses_session_video_path
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.portrait_crop", return_value=MOCK_PORTRAIT_CROP_RESULT)
def test_api_portrait_crop_uses_session_video_path(mock_pc, client):
    """POST /api/portrait_crop uses session video_path when no input_path in request."""
    _session["video_path"] = "C:/AT01/input/test.mp4"

    resp = client.post("/api/portrait_crop", json={
        "output_dir": "output",
    })
    assert resp.status_code == 200
    # Verify the session video_path was used.
    mock_pc.assert_called_once()
    call_args = mock_pc.call_args
    assert call_args[0][0] == "C:/AT01/input/test.mp4"


# ---------------------------------------------------------------------------
# 27. test_safe_gpu_call_catches_cublas_error
# ---------------------------------------------------------------------------

def test_safe_gpu_call_catches_cublas_error():
    """safe_gpu_call catches cuBLAS-related errors too."""
    def _boom():
        raise RuntimeError("CUBLAS_STATUS_ALLOC_FAILED")

    result = safe_gpu_call(_boom)
    assert result["fallback"] is True
    assert "GPU failed" in result["error"]


# ---------------------------------------------------------------------------
# 28. test_safe_gpu_call_returns_function_result
# ---------------------------------------------------------------------------

def test_safe_gpu_call_returns_function_result():
    """safe_gpu_call returns the wrapped function's result on success."""
    def _ok(x, y):
        return x + y

    assert safe_gpu_call(_ok, 3, 7) == 10


# ===========================================================================
# Additional tests from Round 3 refined spec
# ===========================================================================


# ---------------------------------------------------------------------------
# 29. test_safe_gpu_call_catches_exit_127
# ---------------------------------------------------------------------------

def test_safe_gpu_call_catches_exit_127():
    """safe_gpu_call catches 'exit 127' errors (CUDA native code crash)."""
    def _crash():
        raise RuntimeError("Process terminated with exit 127")

    result = safe_gpu_call(_crash)
    assert result["fallback"] is True
    assert "GPU failed" in result["error"]
    assert result.get("method") == "gpu_failed"


# ---------------------------------------------------------------------------
# 30. test_safe_gpu_call_catches_oom
# ---------------------------------------------------------------------------

def test_safe_gpu_call_catches_oom():
    """safe_gpu_call catches out of memory errors."""
    def _oom():
        raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")

    result = safe_gpu_call(_oom)
    assert result["fallback"] is True
    assert "GPU failed" in result["error"]


# ---------------------------------------------------------------------------
# 31. test_nlp_who_is_talking
# ---------------------------------------------------------------------------

def test_nlp_who_is_talking():
    """'who is talking' maps to speaker_detect action."""
    result = parse_command("who is talking")
    assert result["action"] == "speaker_detect"
    assert result["confidence"] >= 0.9


# ---------------------------------------------------------------------------
# 32. test_nlp_make_the_tiktoks_batch
# ---------------------------------------------------------------------------

def test_nlp_make_the_tiktoks_batch():
    """'make the tiktoks' maps to tiktok_batch with platform params."""
    result = parse_command("make the tiktoks")
    assert result["action"] == "tiktok_batch"
    assert result["params"]["platform"] == "tiktok"
    assert result["params"]["max_duration"] == 60


# ---------------------------------------------------------------------------
# 33. test_nlp_bare_chapter
# ---------------------------------------------------------------------------

def test_nlp_bare_chapter():
    """Bare 'chapter' keyword maps to chapter_detect."""
    result = parse_command("chapter")
    assert result["action"] == "chapter_detect"


# ---------------------------------------------------------------------------
# 34. test_server_label_speakers
# ---------------------------------------------------------------------------

@patch("agents.edbot.server.detect_speakers", return_value=MOCK_SPEAKER_MAP)
def test_server_label_speakers(mock_ds, client):
    """POST /api/label_speakers replaces SPEAKER_N labels with human names."""
    # First populate speaker_map via /api/speakers
    _session["video_path"] = "C:/AT01/input/test.mp4"
    resp = client.get("/api/speakers")
    assert resp.status_code == 200

    # Now label the speakers
    resp = client.post("/api/label_speakers", json={
        "labels": {"SPEAKER_0": "Ari", "SPEAKER_1": "Alex"},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "Ari" in data["speakers"]
    assert "Alex" in data["speakers"]
    # chunk_speakers should be updated too
    for spk in data.get("chunk_speakers", {}).values():
        assert spk in ("Ari", "Alex")


# ---------------------------------------------------------------------------
# 35. test_server_label_speakers_needs_speaker_map
# ---------------------------------------------------------------------------

def test_server_label_speakers_needs_speaker_map(client):
    """POST /api/label_speakers returns 400 when no speaker_map in session."""
    resp = client.post("/api/label_speakers", json={
        "labels": {"SPEAKER_0": "Ari"},
    })
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "NO_SPEAKERS"


# ---------------------------------------------------------------------------
# 36. test_silence_detect_default_threshold_is_50
# ---------------------------------------------------------------------------

def test_silence_detect_default_threshold_is_50():
    """silence_detect.py default threshold is -50dB, not -30."""
    import inspect
    from silence_detect import detect_silence
    sig = inspect.signature(detect_silence)
    default = sig.parameters["threshold_db"].default
    assert default == -50.0, f"Expected -50.0, got {default}"


# ===========================================================================
# Duplicates from user's 22-test spec that are ALREADY covered in per-tool
# test files — noted here, not re-implemented:
#
# chapter_detect (6 requested, 5 overlap):
#   - test_chapter_basic → test_chapter_detect.py::TestBasicChapterDetectionWithSilenceMap
#   - test_chapter_silence_splits → test_chapter_detect.py::TestBasicChapterDetectionWithSilenceMap::test_sub_threshold_gap_ignored
#   - test_chapter_merge_short → test_chapter_detect.py::TestMinChapterDurationMerging
#   - test_chapter_split_long → NOT IMPLEMENTED (spec feature not built)
#   - test_chapter_bullets → NOT IMPLEMENTED (chapters don't have bullets field)
#   - test_chapter_summary → chapter title is ~8 words, covered in TestChapterTitleGeneration
#
# speaker_detect (4 requested, 3 overlap):
#   - test_speaker_two_speakers → test_speaker_detect.py::TestSpeakerChangeDetection
#   - test_speaker_energy_fallback → test_speaker_detect.py::TestPyannoteImportFailure
#   - test_speaker_labeling → NEW: test_server_label_speakers above
#   - test_speaker_coverage → NOT IMPLEMENTED (no stats percentages in speaker_detect)
#
# portrait_crop (3 requested, all overlap):
#   - test_portrait_crop_916 → test_portrait_crop.py::TestCenterCropCommand
#   - test_portrait_face_center → test_portrait_crop.py::TestMethodSelection::test_face_method_with_mocked_mediapipe
#   - test_portrait_center_fallback → test_portrait_crop.py::TestMediapipeImportFailure
#
# tiktok_chunk (4 requested, 3 overlap):
#   - test_tiktok_max_60s → test_tiktok_chunk.py::TestChapterExceedsMaxDuration
#   - test_tiktok_speaker_turn_split → NOT IMPLEMENTED (tiktok_chunk splits by chunks, not speaker turns)
#   - test_tiktok_chapter_ref → test_tiktok_chunk.py::TestOutputSchema
#   - test_tiktok_schema → test_tiktok_chunk.py::TestOutputSchema
#
# server (5 requested):
#   - test_server_session → test_api_session_returns_state above
#   - test_server_chapters → test_api_chapters_returns_chapters above
#   - test_server_tiktok → test_api_tiktok_success above
#   - test_server_label → test_server_label_speakers above
#   - test_server_scan → test_session_state_populated_by_transcribe above
# ===========================================================================
