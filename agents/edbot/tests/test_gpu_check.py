"""Tests for gpu_check — VRAM detection and whisper config recommendation."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from gpu_check import check_gpu, recommend_whisper_config


class TestCheckGpu:
    """Tests for check_gpu function."""

    @patch("gpu_check.subprocess.run")
    @patch("gpu_check.torch")
    def test_high_vram_no_resolve(self, mock_torch, mock_run):
        """48GB VRAM, no Resolve running."""
        mock_torch.cuda.is_available.return_value = True
        # 45GB free / 48GB total
        mock_torch.cuda.mem_get_info.return_value = (
            45 * 1024 * 1024 * 1024,
            48 * 1024 * 1024 * 1024,
        )
        mock_run.return_value = MagicMock(stdout="")  # No Resolve PID

        result = check_gpu()
        assert result["cuda_available"] is True
        assert result["total_vram_mb"] == 49152
        assert result["free_vram_mb"] == 46080
        assert result["resolve_running"] is False
        assert result["device"] == "cuda"

    @patch("gpu_check.subprocess.run")
    @patch("gpu_check.torch")
    def test_low_vram_with_resolve(self, mock_torch, mock_run):
        """2GB VRAM free, Resolve running."""
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.mem_get_info.return_value = (
            2 * 1024 * 1024 * 1024,
            48 * 1024 * 1024 * 1024,
        )
        mock_run.return_value = MagicMock(stdout="20424\n")  # Resolve PID

        result = check_gpu()
        assert result["cuda_available"] is True
        assert result["free_vram_mb"] == 2048
        assert result["resolve_running"] is True

    @patch("gpu_check.subprocess.run")
    @patch("gpu_check.torch")
    def test_no_cuda(self, mock_torch, mock_run):
        """No CUDA available."""
        mock_torch.cuda.is_available.return_value = False
        mock_run.return_value = MagicMock(stdout="")
        result = check_gpu()
        assert result["cuda_available"] is False
        assert result["device"] == "cpu"
        assert result["free_vram_mb"] == 0

    @patch("gpu_check.subprocess.run", side_effect=FileNotFoundError)
    @patch("gpu_check.torch")
    def test_resolve_check_fails_gracefully(self, mock_torch, mock_run):
        """PowerShell not available — resolve_running stays False."""
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.mem_get_info.return_value = (
            10 * 1024 * 1024 * 1024,
            48 * 1024 * 1024 * 1024,
        )
        result = check_gpu()
        assert result["resolve_running"] is False
        assert result["cuda_available"] is True


class TestRecommendWhisperConfig:
    """Tests for recommend_whisper_config function."""

    def test_plenty_vram_no_resolve(self):
        """8GB free, no Resolve → float16 + large-v3."""
        status = {"cuda_available": True, "free_vram_mb": 8192, "resolve_running": False}
        rec = recommend_whisper_config(status)
        assert rec["model_size"] == "large-v3"
        assert rec["compute_type"] == "float16"
        assert rec["device"] == "cuda"

    def test_moderate_vram(self):
        """4GB free → int8_float16 + large-v3."""
        status = {"cuda_available": True, "free_vram_mb": 4096, "resolve_running": False}
        rec = recommend_whisper_config(status)
        assert rec["model_size"] == "large-v3"
        assert rec["compute_type"] == "int8_float16"
        assert rec["device"] == "cuda"

    def test_low_vram(self):
        """2GB free → int8_float16 + medium."""
        status = {"cuda_available": True, "free_vram_mb": 2048, "resolve_running": True}
        rec = recommend_whisper_config(status)
        assert rec["model_size"] == "medium"
        assert rec["compute_type"] == "int8_float16"
        assert rec["device"] == "cuda"

    def test_very_low_vram(self):
        """1GB free → cpu + small."""
        status = {"cuda_available": True, "free_vram_mb": 1024, "resolve_running": True}
        rec = recommend_whisper_config(status)
        assert rec["model_size"] == "small"
        assert rec["compute_type"] == "int8"
        assert rec["device"] == "cpu"

    def test_no_cuda(self):
        """No CUDA → cpu + small."""
        status = {"cuda_available": False, "free_vram_mb": 0, "resolve_running": False}
        rec = recommend_whisper_config(status)
        assert rec["model_size"] == "small"
        assert rec["device"] == "cpu"

    def test_boundary_6gb(self):
        """Exactly 6GB free, no Resolve → float16 + large-v3."""
        status = {"cuda_available": True, "free_vram_mb": 6144, "resolve_running": False}
        rec = recommend_whisper_config(status)
        assert rec["compute_type"] == "float16"

    def test_boundary_6gb_with_resolve(self):
        """Exactly 6GB free, WITH Resolve → int8_float16 (not float16)."""
        status = {"cuda_available": True, "free_vram_mb": 6144, "resolve_running": True}
        rec = recommend_whisper_config(status)
        assert rec["compute_type"] == "int8_float16"

    def test_boundary_3gb(self):
        """Exactly 3GB free → int8_float16 + large-v3."""
        status = {"cuda_available": True, "free_vram_mb": 3072, "resolve_running": False}
        rec = recommend_whisper_config(status)
        assert rec["model_size"] == "large-v3"
        assert rec["compute_type"] == "int8_float16"

    def test_boundary_1_5gb(self):
        """Exactly 1.5GB free → int8_float16 + medium."""
        status = {"cuda_available": True, "free_vram_mb": 1536, "resolve_running": False}
        rec = recommend_whisper_config(status)
        assert rec["model_size"] == "medium"
