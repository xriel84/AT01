"""Live speed tests — require CUDA GPU. Skip-decorated for CI safety.

Run manually on ENKI64 with GPU:
    py -3.12 -m pytest agents/edbot/tests/test_speed_live.py -v
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

try:
    import torch
    _CUDA = torch.cuda.is_available()
except ImportError:
    _CUDA = False

skip_no_cuda = pytest.mark.skipif(not _CUDA, reason="CUDA required")
gpu_tier_2 = pytest.mark.gpu_tier_2

_TEST_VIDEO_SHORT = Path(r"C:\AT01\input\test_with_silence.mov")
_TEST_VIDEO_LONG = Path(r"C:\AT01\input\IMG_5769.MOV")


@skip_no_cuda
@gpu_tier_2
class TestGpuCheckLive:
    """Live tests for gpu_check module."""

    def test_check_gpu_returns_valid_vram(self):
        from gpu_check import check_gpu
        result = check_gpu()
        assert result["cuda_available"] is True
        assert result["total_vram_mb"] > 0
        assert result["free_vram_mb"] > 0
        assert result["free_vram_mb"] <= result["total_vram_mb"]

    def test_resolve_detection_matches_reality(self):
        from gpu_check import check_gpu
        import subprocess
        result = check_gpu()
        # Verify against direct process check
        proc = subprocess.run(
            ["powershell", "-Command", "Get-Process -Name 'Resolve' -ErrorAction SilentlyContinue"],
            capture_output=True, text=True, timeout=5,
        )
        actual_running = bool(proc.stdout.strip())
        assert result["resolve_running"] == actual_running

    def test_recommend_returns_valid_config(self):
        from gpu_check import recommend_whisper_config
        rec = recommend_whisper_config()
        assert rec["model_size"] in ("large-v3", "medium", "small")
        assert rec["compute_type"] in ("float16", "int8_float16", "int8")
        assert rec["device"] in ("cuda", "cpu")
        assert "reason" in rec


@skip_no_cuda
@gpu_tier_2
class TestTranscribeLive:
    """Live transcription speed tests."""

    @pytest.mark.skipif(not _TEST_VIDEO_SHORT.exists(), reason="test video not found")
    def test_short_file_no_regression(self):
        """test_with_silence.mov (60s) should still transcribe <15s."""
        from transcribe import transcribe_video
        t0 = time.perf_counter()
        result = transcribe_video(str(_TEST_VIDEO_SHORT), "temp")
        elapsed = time.perf_counter() - t0
        assert "error" not in result
        assert elapsed < 15, f"Short file took {elapsed:.1f}s (target <15s)"
        assert "config_used" in result

    @pytest.mark.skipif(not _TEST_VIDEO_LONG.exists(), reason="test video not found")
    def test_long_file_with_chunking(self):
        """IMG_5769.MOV (7 min) should transcribe <30s with chunking."""
        from transcribe import transcribe_video
        t0 = time.perf_counter()
        result = transcribe_video(str(_TEST_VIDEO_LONG), "temp")
        elapsed = time.perf_counter() - t0
        assert "error" not in result
        assert result.get("chunked") is True
        assert result.get("chunk_count", 0) >= 4
        assert elapsed < 120, f"Long file took {elapsed:.1f}s (target <30s ideal, hard limit 120s with Resolve)"
        assert "config_used" in result

    @pytest.mark.skipif(not _TEST_VIDEO_LONG.exists(), reason="test video not found")
    def test_full_pipeline_long_file(self):
        """Full pipeline for IMG_5769.MOV should be <60s."""
        from transcribe import transcribe_video
        from silence_detect import detect_silence
        from chapter_detect import detect_chapters

        t0 = time.perf_counter()
        tr = transcribe_video(str(_TEST_VIDEO_LONG), "temp")
        detect_silence(str(_TEST_VIDEO_LONG), output_dir="temp")
        detect_chapters(tr.get("chunks", []))
        elapsed = time.perf_counter() - t0
        assert elapsed < 150, f"Full pipeline took {elapsed:.1f}s (target <60s ideal, hard limit 150s with Resolve)"

    @pytest.mark.skipif(not _TEST_VIDEO_SHORT.exists(), reason="test video not found")
    def test_benchmark_captures_new_fields(self):
        """benchmark.py should capture gpu_config and chunking info."""
        from benchmark import run_benchmark
        result = run_benchmark(str(_TEST_VIDEO_SHORT), runs=1)
        assert "gpu_config" in result
        assert "whisper_recommendation" in result
        assert "config_used" in result.get("transcribe", {})
