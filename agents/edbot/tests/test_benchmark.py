"""Tests for benchmark.py — all external calls mocked."""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_tools_dir = str(Path(__file__).resolve().parent.parent / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

# Pre-import benchmark so the module exists for patching
import benchmark  # noqa: F401

MOCK_CHUNKS = [
    {"id": 0, "start": 0.0, "end": 10.0, "text": "hello the world"},
    {"id": 1, "start": 10.0, "end": 20.0, "text": "the quick fox"},
]

MOCK_TRANSCRIBE = {"source": "test.mp4", "duration": 20.0, "chunks": MOCK_CHUNKS}
MOCK_SILENCE = {"gaps": [{"start": 5.0, "end": 6.0}], "stats": {"gap_count": 1}}
MOCK_CHAPTERS = [{"title": "Intro", "start": 0.0, "end": 10.0}]
MOCK_INDEX = {"terms": {"the": [{"file": "test", "chunk": 0}]}}
MOCK_SEARCH = [{"file": "test", "chunk": 0, "score": 1.0}]


@pytest.fixture(autouse=True)
def _patch_all():
    """Mock all external tool calls by patching source modules."""
    with (
        patch("transcribe.transcribe_video", return_value=MOCK_TRANSCRIBE),
        patch("silence_detect.detect_silence", return_value=MOCK_SILENCE),
        patch("chapter_detect.detect_chapters", return_value=MOCK_CHAPTERS),
        patch("transcript_index.build_index", return_value=MOCK_INDEX),
        patch("transcript_index.search_index", return_value=MOCK_SEARCH),
    ):
        yield


class TestBenchmark:
    def test_benchmark_returns_all_stages(self):
        """Result dict has all 5 stage keys."""
        from benchmark import run_benchmark
        with patch.object(Path, "exists", return_value=True):
            result = run_benchmark("C:/fake/video.mov", runs=1)
        assert "error" not in result
        for key in ("transcribe", "search", "silence_detect", "chapter_detect", "full_pipeline"):
            assert key in result, f"Missing stage: {key}"

    def test_benchmark_pass_fail_logic(self):
        """mean < target -> pass=True."""
        from benchmark import run_benchmark
        with patch.object(Path, "exists", return_value=True):
            result = run_benchmark("C:/fake/video.mov", runs=1)
        for key in ("transcribe", "search", "silence_detect", "chapter_detect", "full_pipeline"):
            stage = result[key]
            assert stage["pass"] == (stage["mean_s"] < stage["target_s"])

    def test_benchmark_multiple_runs(self):
        """runs=3 -> each stage timed 3 times (mocked, so mean_s near 0)."""
        from benchmark import run_benchmark
        with patch.object(Path, "exists", return_value=True):
            result = run_benchmark("C:/fake/video.mov", runs=3)
        assert result["runs"] == 3
        for key in ("transcribe", "search", "silence_detect", "chapter_detect", "full_pipeline"):
            assert result[key]["pass"] is True

    def test_benchmark_missing_video(self):
        """Returns error dict when file doesn't exist."""
        from benchmark import run_benchmark
        result = run_benchmark("C:/nonexistent/video.mov", runs=1)
        assert "error" in result

    def test_benchmark_result_schema(self):
        """All required keys present in each stage result."""
        from benchmark import run_benchmark
        with patch.object(Path, "exists", return_value=True):
            result = run_benchmark("C:/fake/video.mov", runs=1)
        for key in ("transcribe", "search", "silence_detect", "chapter_detect", "full_pipeline"):
            stage = result[key]
            assert "mean_s" in stage
            assert "target_s" in stage
            assert "pass" in stage
            assert isinstance(stage["mean_s"], (int, float))
            assert isinstance(stage["target_s"], (int, float))
            assert isinstance(stage["pass"], bool)

    def test_benchmark_timestamp_format(self):
        """ISO 8601 timestamp in result."""
        from benchmark import run_benchmark
        with patch.object(Path, "exists", return_value=True):
            result = run_benchmark("C:/fake/video.mov", runs=1)
        assert "timestamp" in result
        datetime.fromisoformat(result["timestamp"])

    def test_benchmark_video_path_in_result(self):
        """video_path and runs stored in result."""
        from benchmark import run_benchmark
        with patch.object(Path, "exists", return_value=True):
            result = run_benchmark("C:/fake/video.mov", runs=2)
        assert result["video_path"] == "C:/fake/video.mov"
        assert result["runs"] == 2

    def test_benchmark_single_run_minimum(self):
        """runs < 1 is clamped to 1."""
        from benchmark import run_benchmark
        with patch.object(Path, "exists", return_value=True):
            result = run_benchmark("C:/fake/video.mov", runs=0)
        assert result["runs"] == 1


class TestBenchmarkEndpoint:
    """Test /api/benchmark endpoint via TestClient."""

    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from agents.edbot.server import app
        return TestClient(app)

    @patch("agents.edbot.server.run_benchmark", return_value={
        "transcribe": {"mean_s": 5.0, "target_s": 30, "pass": True},
        "search": {"mean_s": 0.01, "target_s": 0.1, "pass": True},
        "silence_detect": {"mean_s": 3.0, "target_s": 10, "pass": True},
        "chapter_detect": {"mean_s": 0.5, "target_s": 5, "pass": True},
        "full_pipeline": {"mean_s": 10.0, "target_s": 60, "pass": True},
        "video_path": "test.mp4", "runs": 1,
        "timestamp": "2026-02-26T00:00:00+00:00",
    })
    @patch("agents.edbot.server.Path.exists", return_value=True)
    def test_benchmark_endpoint_post(self, mock_exists, mock_bench, client):
        """POST /api/benchmark returns 200 with valid body."""
        resp = client.post("/api/benchmark", json={
            "video_path": "C:/AT01/input/test.mp4", "runs": 1,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "transcribe" in data

    def test_benchmark_endpoint_missing_path(self, client):
        """POST /api/benchmark without video_path returns 422."""
        resp = client.post("/api/benchmark", json={})
        assert resp.status_code == 422
