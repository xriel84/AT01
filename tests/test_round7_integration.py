"""Round 7 integration tests — end-to-end pipeline, cache/session state,
speed benchmarks, error handling, and cross-tool interactions.

25 tests. All tool calls mocked — no GPU, no ffmpeg, no disk I/O in CI.
Real-data tests (TestRealVideo) skip when fixtures unavailable.
"""

import json
import sys
import time
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Tools path
_tools_dir = str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from fastapi.testclient import TestClient

from agents.edbot.server import app, _cache, _session, ALLOWED_VIDEO_DIRS


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
    return TestClient(app)


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

MOCK_CHUNKS_RESULT = {
    "source": "integration_test.mp4",
    "duration": 120.0,
    "chunks": [
        {"id": 0, "start": 0.0, "end": 15.0, "text": "Jensen Huang presented the new NVIDIA GPU architecture at SIGGRAPH",
         "word_count": 10, "silence_ratio": 0.1, "has_speech": True},
        {"id": 1, "start": 15.0, "end": 30.0, "text": "The performance gains were impressive across all benchmarks",
         "word_count": 8, "silence_ratio": 0.2, "has_speech": True},
        {"id": 2, "start": 30.0, "end": 45.0, "text": "",
         "word_count": 0, "silence_ratio": 1.0, "has_speech": False},
        {"id": 3, "start": 45.0, "end": 60.0, "text": "Real-time ray tracing enables photorealistic rendering",
         "word_count": 6, "silence_ratio": 0.15, "has_speech": True},
        {"id": 4, "start": 60.0, "end": 75.0, "text": "",
         "word_count": 0, "silence_ratio": 1.0, "has_speech": False},
        {"id": 5, "start": 75.0, "end": 90.0, "text": "The future of computing is accelerated by AI workloads",
         "word_count": 9, "silence_ratio": 0.05, "has_speech": True},
        {"id": 6, "start": 90.0, "end": 105.0, "text": "NVIDIA CUDA platform continues to lead in parallel processing",
         "word_count": 8, "silence_ratio": 0.1, "has_speech": True},
        {"id": 7, "start": 105.0, "end": 120.0, "text": "Thank you for attending this presentation today",
         "word_count": 7, "silence_ratio": 0.3, "has_speech": True},
    ],
}

MOCK_SILENCE_MAP = {
    "source": "integration_test.mp4",
    "duration": 120.0,
    "threshold_db": -50.0,
    "gaps": [
        {"start": 30.0, "end": 45.0, "duration": 15.0},
        {"start": 60.0, "end": 75.0, "duration": 15.0},
    ],
    "speech": [
        {"start": 0.0, "end": 30.0, "duration": 30.0},
        {"start": 45.0, "end": 60.0, "duration": 15.0},
        {"start": 75.0, "end": 120.0, "duration": 45.0},
    ],
    "stats": {
        "total_silence": 30.0,
        "total_speech": 90.0,
        "silence_percentage": 25.0,
        "gap_count": 2,
    },
}

MOCK_CROP_RESULT = {
    "status": "success",
    "action": "portrait_crop",
    "input": "C:/AT01/input/integration_test.mp4",
    "output": "C:/AT01/output/integration_test_portrait.mp4",
    "method": "center",
    "duration_in": 120.0,
    "duration_out": 120.0,
    "crop_filter": "crop=ih*9/16:ih",
    "ffmpeg_cmd": "ffmpeg -i ...",
    "elapsed_seconds": 2.5,
    "error": None,
}

MOCK_SPEAKER_RESULT = {
    "source": "integration_test.mp4",
    "method": "energy",
    "speakers": ["SPEAKER_0"],
    "segments": [
        {"start": 0.0, "end": 120.0, "speaker": "SPEAKER_0"},
    ],
    "chunk_speakers": {
        "0": "SPEAKER_0", "1": "SPEAKER_0", "3": "SPEAKER_0",
        "5": "SPEAKER_0", "6": "SPEAKER_0", "7": "SPEAKER_0",
    },
}


# ---------------------------------------------------------------------------
# 1. End-to-end pipeline: transcribe → chapters → search
# ---------------------------------------------------------------------------

class TestEndToEndPipeline:
    """Full pipeline integration: transcribe → silence → chapters → search."""

    @patch("agents.edbot.server.transcribe_video", return_value=MOCK_CHUNKS_RESULT)
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_transcribe_populates_cache_and_session(self, mock_exists, mock_tv, client):
        """Transcribe sets cache.chunks, cache.last_input, session.video_path, session.chunks."""
        resp = client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "output_dir": "output",
        })
        assert resp.status_code == 200
        assert _cache["chunks"] is not None
        assert _cache["last_input"] == "C:/AT01/input/integration_test.mp4"
        assert _session["video_path"] == "C:/AT01/input/integration_test.mp4"
        assert len(_session["chunks"]) == 8

    @patch("agents.edbot.server.detect_silence", return_value=MOCK_SILENCE_MAP)
    def test_silence_populates_cache_and_session(self, mock_ds, client):
        """Silence detection sets cache.silence_map and session.silence_map."""
        resp = client.post("/api/silence", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "output_dir": "output",
        })
        assert resp.status_code == 200
        assert _cache["silence_map"] is not None
        assert _session["silence_map"] is not None
        assert _cache["silence_map"]["stats"]["gap_count"] == 2

    @patch("agents.edbot.server.transcribe_video", return_value=MOCK_CHUNKS_RESULT)
    @patch("agents.edbot.server.detect_silence", return_value=MOCK_SILENCE_MAP)
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_full_pipeline_transcribe_silence_chapters(self, mock_exists, mock_ds, mock_tv, client):
        """Transcribe + silence → chapters uses both cached datasets."""
        # Step 1: transcribe
        client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "output_dir": "output",
        })
        # Step 2: silence detect
        client.post("/api/silence", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "output_dir": "output",
        })
        # Step 3: chapters (uses cached chunks + silence_map)
        resp = client.get("/api/chapters")
        assert resp.status_code == 200
        data = resp.json()
        assert "chapters" in data
        assert len(data["chapters"]) >= 1
        # Each chapter should have required fields
        for ch in data["chapters"]:
            assert "chapter_id" in ch
            assert "start" in ch
            assert "end" in ch
            assert "chunk_ids" in ch
            assert "title" in ch
            assert ch["end"] > ch["start"]

    @patch("agents.edbot.server.transcribe_video", return_value=MOCK_CHUNKS_RESULT)
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_chapters_without_silence_map_uses_fallback(self, mock_exists, mock_tv, client):
        """Chapters without silence_map falls back to silence_ratio detection."""
        client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "output_dir": "output",
        })
        # No silence detection — chapters should still work
        resp = client.get("/api/chapters")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["chapters"]) >= 1
        # Verify chapters from fallback cover all chunks
        all_chunk_ids = set()
        for ch in data["chapters"]:
            all_chunk_ids.update(ch["chunk_ids"])
        expected_ids = {c["id"] for c in MOCK_CHUNKS_RESULT["chunks"]}
        assert all_chunk_ids == expected_ids


# ---------------------------------------------------------------------------
# 2. Cache and session state management
# ---------------------------------------------------------------------------

class TestCacheSessionState:
    """Verify cache isolation, session state, and cross-endpoint data flow."""

    def test_empty_cache_returns_404(self, client):
        """Chunks and silence_map return 404 when cache is empty."""
        assert client.get("/api/chunks").status_code == 404
        assert client.get("/api/silence_map").status_code == 404

    def test_chapters_without_transcribe_returns_400(self, client):
        """Chapters endpoint requires prior transcription."""
        resp = client.get("/api/chapters")
        assert resp.status_code == 400

    @patch("agents.edbot.server.transcribe_video", return_value=MOCK_CHUNKS_RESULT)
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_session_tracks_video_path(self, mock_exists, mock_tv, client):
        """Session stores video_path from transcribe for downstream use."""
        client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "output_dir": "output",
        })
        resp = client.get("/api/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["video_path"] == "C:/AT01/input/integration_test.mp4"
        assert data["has_chunks"] is True

    @patch("agents.edbot.server.transcribe_video")
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_second_transcribe_overwrites_cache(self, mock_exists, mock_tv, client):
        """A second transcribe call replaces the cached data."""
        first = {**MOCK_CHUNKS_RESULT, "source": "first.mp4"}
        second = {**MOCK_CHUNKS_RESULT, "source": "second.mp4"}
        mock_tv.side_effect = [first, second]

        client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/first.mp4",
            "output_dir": "output",
        })
        assert _cache["chunks"]["source"] == "first.mp4"

        client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/second.mp4",
            "output_dir": "output",
        })
        assert _cache["chunks"]["source"] == "second.mp4"

    @patch("agents.edbot.server.transcribe_video", return_value=MOCK_CHUNKS_RESULT)
    @patch("agents.edbot.server.detect_silence", return_value=MOCK_SILENCE_MAP)
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_session_state_accumulates(self, mock_exists, mock_ds, mock_tv, client):
        """Session state accumulates across endpoints within a pipeline run."""
        client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "output_dir": "output",
        })
        assert _session["video_path"] is not None
        assert _session["chunks"] is not None
        assert _session["silence_map"] is None  # not yet

        client.post("/api/silence", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "output_dir": "output",
        })
        assert _session["silence_map"] is not None

        client.get("/api/chapters")
        assert _session["chapters"] is not None


# ---------------------------------------------------------------------------
# 3. Error handling and validation
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Validate error responses for bad inputs and missing prerequisites."""

    def test_transcribe_file_not_found(self, client):
        """Transcribe with non-existent file returns FILE_NOT_FOUND."""
        resp = client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/does_not_exist.mp4",
            "output_dir": "output",
        })
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "FILE_NOT_FOUND"

    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_transcribe_unsupported_extension(self, mock_exists, client):
        """Transcribe with non-media file returns INVALID_INPUT."""
        resp = client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/readme.txt",
            "output_dir": "output",
        })
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_INPUT"

    @patch("agents.edbot.server.transcribe_video", return_value={"error": "whisper crashed", "source": "bad.mp4"})
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_transcribe_tool_error(self, mock_exists, mock_tv, client):
        """Tool-level error returns TOOL_ERROR with message."""
        resp = client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/bad.mp4",
            "output_dir": "output",
        })
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == "TOOL_ERROR"

    def test_portrait_crop_invalid_method(self, client):
        """Portrait crop with invalid method returns INVALID_INPUT."""
        resp = client.post("/api/portrait_crop", json={
            "input_path": "C:/AT01/input/test.mp4",
            "method": "invalid_method",
        })
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_INPUT"

    def test_portrait_crop_no_input_no_session(self, client):
        """Portrait crop without input_path or session returns NO_SESSION."""
        resp = client.post("/api/portrait_crop", json={
            "method": "center",
        })
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "NO_SESSION"

    def test_speakers_no_session(self, client):
        """Speakers endpoint without video in session returns NO_SESSION."""
        resp = client.get("/api/speakers")
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "NO_SESSION"

    def test_label_speakers_no_map(self, client):
        """Label speakers without prior detection returns NO_SPEAKERS."""
        resp = client.post("/api/label_speakers", json={
            "labels": {"SPEAKER_0": "Ari"},
        })
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "NO_SPEAKERS"

    def test_label_speakers_invalid_key(self, client):
        """Label speakers with bad key format returns INVALID_INPUT."""
        _session["speaker_map"] = MOCK_SPEAKER_RESULT.copy()
        resp = client.post("/api/label_speakers", json={
            "labels": {"BAD_KEY": "Ari"},
        })
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# 4. Portrait crop integration
# ---------------------------------------------------------------------------

class TestPortraitCropIntegration:
    """Portrait crop with session fallback and method validation."""

    @patch("agents.edbot.server.portrait_crop", return_value=MOCK_CROP_RESULT)
    @patch("agents.edbot.server.transcribe_video", return_value=MOCK_CHUNKS_RESULT)
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_crop_uses_session_video_path(self, mock_exists, mock_tv, mock_crop, client):
        """Portrait crop falls back to session video_path when no input_path given."""
        # First transcribe to set session
        client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "output_dir": "output",
        })
        # Crop without explicit input_path
        resp = client.post("/api/portrait_crop", json={
            "method": "center",
            "output_dir": "output",
        })
        assert resp.status_code == 200
        mock_crop.assert_called_once()
        # Verify it used the session video path
        call_args = mock_crop.call_args
        assert call_args[0][0] == "C:/AT01/input/integration_test.mp4"

    @patch("agents.edbot.server.portrait_crop")
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_crop_with_trim_params(self, mock_exists, mock_crop, client):
        """Portrait crop passes start/end trim parameters through."""
        trim_result = {**MOCK_CROP_RESULT, "duration_out": 10.0}
        mock_crop.return_value = trim_result
        resp = client.post("/api/portrait_crop", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "method": "center",
            "output_dir": "output",
            "start": 5.0,
            "end": 15.0,
        })
        assert resp.status_code == 200
        call_args = mock_crop.call_args
        assert call_args[1]["start"] == 5.0
        assert call_args[1]["end"] == 15.0


# ---------------------------------------------------------------------------
# 5. Speaker detection + labeling integration
# ---------------------------------------------------------------------------

class TestSpeakerIntegration:
    """Speaker detection and label update flow."""

    @patch("agents.edbot.server.detect_speakers", return_value=MOCK_SPEAKER_RESULT)
    @patch("agents.edbot.server.transcribe_video", return_value=MOCK_CHUNKS_RESULT)
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_speakers_after_transcribe(self, mock_exists, mock_tv, mock_ds, client):
        """Speaker detection works after transcribe populates session."""
        client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "output_dir": "output",
        })
        resp = client.get("/api/speakers")
        assert resp.status_code == 200
        data = resp.json()
        assert "speakers" in data
        assert "segments" in data
        assert _session["speaker_map"] is not None

    @patch("agents.edbot.server.detect_speakers", return_value=MOCK_SPEAKER_RESULT)
    @patch("agents.edbot.server.transcribe_video", return_value=MOCK_CHUNKS_RESULT)
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_label_speakers_updates_session(self, mock_exists, mock_tv, mock_ds, client):
        """Label speakers replaces SPEAKER_N with human names in session."""
        client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "output_dir": "output",
        })
        client.get("/api/speakers")
        resp = client.post("/api/label_speakers", json={
            "labels": {"SPEAKER_0": "Jensen"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "Jensen" in data["speakers"]
        assert data["segments"][0]["speaker"] == "Jensen"


# ---------------------------------------------------------------------------
# 6. Speed benchmarks (mocked — validates execution path timing)
# ---------------------------------------------------------------------------

class TestSpeedBenchmarks:
    """Verify endpoint response times stay within bounds (mocked tools)."""

    @patch("agents.edbot.server.transcribe_video", return_value=MOCK_CHUNKS_RESULT)
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_transcribe_endpoint_responds_under_1s(self, mock_exists, mock_tv, client):
        """Transcribe endpoint (mocked tool) responds within 1 second."""
        start = time.perf_counter()
        resp = client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "output_dir": "output",
        })
        elapsed = time.perf_counter() - start
        assert resp.status_code == 200
        assert elapsed < 1.0, f"transcribe endpoint took {elapsed:.2f}s (expected <1s)"

    @patch("agents.edbot.server.transcribe_video", return_value=MOCK_CHUNKS_RESULT)
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_chapter_detection_instant(self, mock_exists, mock_tv, client):
        """Chapter detection on cached data completes in <500ms."""
        client.post("/api/transcribe", json={
            "input_path": "C:/AT01/input/integration_test.mp4",
            "output_dir": "output",
        })
        start = time.perf_counter()
        resp = client.get("/api/chapters")
        elapsed = time.perf_counter() - start
        assert resp.status_code == 200
        assert elapsed < 0.5, f"chapter detection took {elapsed:.2f}s (expected <500ms)"

    def test_health_endpoint_instant(self, client):
        """Health check responds in <200ms."""
        start = time.perf_counter()
        resp = client.get("/api/health")
        elapsed = time.perf_counter() - start
        assert resp.status_code == 200
        assert elapsed < 0.2, f"health check took {elapsed:.2f}s (expected <200ms)"

    def test_session_endpoint_instant(self, client):
        """Session state responds in <200ms."""
        start = time.perf_counter()
        resp = client.get("/api/session")
        elapsed = time.perf_counter() - start
        assert resp.status_code == 200
        assert elapsed < 0.2, f"session took {elapsed:.2f}s (expected <200ms)"


# ---------------------------------------------------------------------------
# 7. Real video integration (skips when fixtures unavailable)
# ---------------------------------------------------------------------------

class TestRealVideo:
    """Integration tests using real video data. Skip when no video available.

    These tests unskip when a real video is placed in C:/AT01/input/ and
    the pipeline generates temp/chunks.json and temp/silence_map.json.
    """

    @pytest.fixture
    def real_video_path(self):
        """Find a real video file in the input directory."""
        input_dir = Path("C:/AT01/input")
        if not input_dir.exists():
            pytest.skip("C:/AT01/input/ directory not found")
        extensions = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
        videos = [f for f in input_dir.iterdir() if f.suffix.lower() in extensions]
        if not videos:
            pytest.skip("No video files in C:/AT01/input/")
        return str(videos[0])

    @pytest.fixture
    def real_chunks(self):
        """Load real chunks.json from temp directory."""
        p = Path("C:/AT01/temp/chunks.json")
        if not p.exists():
            pytest.skip("Real chunks.json not available — run pipeline first")
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    @pytest.fixture
    def real_silence_map(self):
        """Load real silence_map.json from temp directory."""
        p = Path("C:/AT01/temp/silence_map.json")
        if not p.exists():
            pytest.skip("Real silence_map.json not available — run pipeline first")
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def test_real_chunks_schema(self, real_chunks):
        """Real chunks have valid schema with required fields."""
        assert "chunks" in real_chunks or isinstance(real_chunks, list)
        chunks = real_chunks.get("chunks", real_chunks) if isinstance(real_chunks, dict) else real_chunks
        assert len(chunks) > 0
        for ch in chunks:
            assert "id" in ch
            assert "start" in ch
            assert "end" in ch
            assert "text" in ch
            assert ch["end"] >= ch["start"]

    def test_real_silence_map_schema(self, real_silence_map):
        """Real silence map has valid schema."""
        assert "gaps" in real_silence_map
        assert "speech" in real_silence_map
        assert "stats" in real_silence_map
        assert real_silence_map["stats"]["total_silence"] + real_silence_map["stats"]["total_speech"] == pytest.approx(
            real_silence_map["duration"], abs=1.0
        )

    def test_real_chapters_from_data(self, real_chunks, real_silence_map):
        """Real data produces chapters with valid structure."""
        from chapter_detect import detect_chapters
        chunks = real_chunks.get("chunks", real_chunks) if isinstance(real_chunks, dict) else real_chunks
        chapters = detect_chapters(chunks, silence_map=real_silence_map)
        assert len(chapters) >= 1
        for ch in chapters:
            assert ch["duration"] >= 0
            assert ch["end"] > ch["start"]
            assert len(ch["chunk_ids"]) >= 1
