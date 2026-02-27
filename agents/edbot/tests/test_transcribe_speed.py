"""Tests for transcribe.py speed optimizations — chunking, fallback, GPU-aware config."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from transcribe import (
    transcribe_video, _resolve_config, _transcribe_with_fallback,
    _merge_chunked_words, _bucket_words,
    _CHUNK_THRESHOLD_SEC, _CHUNK_SIZE_SEC, _CHUNK_OVERLAP_SEC,
)


class TestResolveConfig:
    """Tests for _resolve_config — GPU-aware config selection."""

    def test_explicit_overrides(self):
        """All params specified → use them directly."""
        cfg = _resolve_config("medium", "int8", "cpu")
        assert cfg == {"model_size": "medium", "compute_type": "int8", "device": "cpu"}

    @patch("transcribe.recommend_whisper_config")
    def test_auto_detect(self, mock_rec):
        """No overrides → auto-detect from GPU."""
        mock_rec.return_value = {
            "model_size": "large-v3",
            "compute_type": "float16",
            "device": "cuda",
        }
        cfg = _resolve_config(None, None, None)
        assert cfg["model_size"] == "large-v3"
        assert cfg["compute_type"] == "float16"

    @patch("transcribe.recommend_whisper_config")
    def test_partial_override(self, mock_rec):
        """Some params specified, rest auto-detected."""
        mock_rec.return_value = {
            "model_size": "large-v3",
            "compute_type": "float16",
            "device": "cuda",
        }
        cfg = _resolve_config("medium", None, None)
        assert cfg["model_size"] == "medium"
        assert cfg["compute_type"] == "float16"
        assert cfg["device"] == "cuda"


class TestTranscribeWithFallback:
    """Tests for _transcribe_with_fallback — CUDA error fallback chain."""

    @patch("transcribe.transcribe_clip")
    def test_first_try_succeeds(self, mock_clip):
        """No errors → use requested config."""
        mock_clip.return_value = [{"word": "hello", "start": 0.0, "end": 0.5}]
        config = {"model_size": "large-v3", "compute_type": "float16", "device": "cuda"}
        words, used = _transcribe_with_fallback(Path("test.wav"), config)
        assert len(words) == 1
        assert used["model_size"] == "large-v3"
        assert used["compute_type"] == "float16"

    @patch("transcribe.transcribe_clip")
    def test_fallback_on_cuda_error(self, mock_clip):
        """CUDA error on float16 → falls back to int8_float16."""
        mock_clip.side_effect = [
            RuntimeError("CUDA out of memory"),
            [{"word": "hello", "start": 0.0, "end": 0.5}],
        ]
        config = {"model_size": "large-v3", "compute_type": "float16", "device": "cuda"}
        words, used = _transcribe_with_fallback(Path("test.wav"), config)
        assert len(words) == 1
        assert used["compute_type"] == "int8_float16"

    @patch("transcribe.transcribe_clip")
    def test_full_fallback_chain(self, mock_clip):
        """CUDA errors all the way → ends up on cpu/small."""
        mock_clip.side_effect = [
            RuntimeError("CUDA out of memory"),        # float16
            RuntimeError("CUDA error: exit 127"),       # int8_float16
            RuntimeError("cublas error"),               # medium/int8_float16
            [{"word": "hello", "start": 0.0, "end": 0.5}],  # small/cpu
        ]
        config = {"model_size": "large-v3", "compute_type": "float16", "device": "cuda"}
        words, used = _transcribe_with_fallback(Path("test.wav"), config)
        assert used["model_size"] == "small"
        assert used["device"] == "cpu"

    @patch("transcribe.transcribe_clip")
    def test_non_cuda_error_raises(self, mock_clip):
        """Non-CUDA error → raises immediately, no fallback."""
        mock_clip.side_effect = FileNotFoundError("model not found")
        config = {"model_size": "large-v3", "compute_type": "float16", "device": "cuda"}
        with pytest.raises(FileNotFoundError):
            _transcribe_with_fallback(Path("test.wav"), config)

    @patch("transcribe.transcribe_clip")
    def test_all_fallbacks_fail(self, mock_clip):
        """All configs fail with CUDA errors → RuntimeError."""
        mock_clip.side_effect = RuntimeError("CUDA out of memory")
        config = {"model_size": "large-v3", "compute_type": "float16", "device": "cuda"}
        with pytest.raises(RuntimeError, match="all fallback configs failed"):
            _transcribe_with_fallback(Path("test.wav"), config)


class TestMergeChunkedWords:
    """Tests for _merge_chunked_words — overlap deduplication."""

    def test_single_chunk(self):
        """Single chunk → no merging needed."""
        words = [{"word": "hello", "start": 0.0, "end": 0.5}]
        merged = _merge_chunked_words([(words, 0.0)], overlap_sec=5.0)
        assert len(merged) == 1
        assert merged[0]["word"] == "hello"

    def test_two_chunks_no_overlap_words(self):
        """Two chunks where second chunk words are after overlap zone."""
        chunk1 = [{"word": "hello", "start": 0.0, "end": 0.5}, {"word": "world", "start": 80.0, "end": 80.5}]
        chunk2 = [{"word": "how", "start": 10.0, "end": 10.5}, {"word": "are", "start": 20.0, "end": 20.5}]
        merged = _merge_chunked_words([(chunk1, 0.0), (chunk2, 90.0)], overlap_sec=5.0)
        # chunk2 words shifted by 90: how@100, are@110
        assert any(w["word"] == "hello" for w in merged)
        assert any(w["word"] == "how" for w in merged)
        assert any(w["word"] == "are" for w in merged)

    def test_deduplication_in_overlap(self):
        """Words in overlap zone with matching text are deduplicated."""
        chunk1 = [{"word": "hello", "start": 85.0, "end": 85.5}]
        # chunk2 offset=90, overlap zone=[90,95]. Word "hello" at start=0 → shifted to 90
        chunk2 = [{"word": "hello", "start": 0.0, "end": 0.5}, {"word": "world", "start": 6.0, "end": 6.5}]
        merged = _merge_chunked_words([(chunk1, 0.0), (chunk2, 90.0)], overlap_sec=5.0)
        # "hello" from chunk1 at 85.0 is kept, "hello" from chunk2 at 90.0 is deduped
        # "world" from chunk2 at 96.0 is kept (after overlap zone)
        hello_count = sum(1 for w in merged if w["word"] == "hello")
        assert hello_count == 1  # Only one "hello"
        assert any(w["word"] == "world" for w in merged)

    def test_empty_chunks(self):
        merged = _merge_chunked_words([], overlap_sec=5.0)
        assert merged == []

    def test_timestamps_sorted(self):
        """Merged words are sorted by start time."""
        chunk1 = [{"word": "a", "start": 0.0, "end": 0.5}]
        chunk2 = [{"word": "b", "start": 10.0, "end": 10.5}]
        merged = _merge_chunked_words([(chunk1, 0.0), (chunk2, 90.0)], overlap_sec=5.0)
        starts = [w["start"] for w in merged]
        assert starts == sorted(starts)


class TestTranscribeVideoChunking:
    """Tests for transcribe_video chunking behavior."""

    @patch("transcribe._transcribe_single")
    @patch("transcribe._get_duration", return_value=120.0)
    def test_short_file_no_chunking(self, mock_dur, mock_single, tmp_path):
        """File <3 min → calls _transcribe_single, not chunked."""
        mock_single.return_value = {
            "source": "short.mp4", "duration": 120.0, "chunks": [],
            "config_used": {"model_size": "large-v3", "compute_type": "float16", "device": "cuda"},
            "chunked": False,
        }
        result = transcribe_video(str(tmp_path / "short.mp4"), str(tmp_path))
        mock_single.assert_called_once()
        assert result["chunked"] is False

    @patch("transcribe._transcribe_chunked")
    @patch("transcribe._get_duration", return_value=450.0)
    def test_long_file_triggers_chunking(self, mock_dur, mock_chunked, tmp_path):
        """File >3 min → calls _transcribe_chunked."""
        mock_chunked.return_value = {
            "source": "long.mp4", "duration": 450.0, "chunks": [],
            "config_used": {"model_size": "large-v3", "compute_type": "int8_float16", "device": "cuda"},
            "chunked": True, "chunk_count": 5,
        }
        result = transcribe_video(str(tmp_path / "long.mp4"), str(tmp_path))
        mock_chunked.assert_called_once()
        assert result["chunked"] is True
        assert result["chunk_count"] == 5

    @patch("transcribe._get_duration", return_value=None)
    @patch("transcribe._extract_audio", return_value=True)
    @patch("transcribe._transcribe_with_fallback")
    @patch("transcribe._write_outputs")
    def test_unknown_duration_no_chunking(self, mock_write, mock_fallback, mock_audio, mock_dur, tmp_path):
        """Duration unknown → falls back to single mode."""
        mock_fallback.return_value = ([], {"model_size": "large-v3", "compute_type": "float16", "device": "cuda"})
        result = transcribe_video(str(tmp_path / "unknown.mp4"), str(tmp_path))
        assert result.get("chunked") is False

    @patch("transcribe.transcribe_clip")
    @patch("transcribe._extract_audio", return_value=True)
    @patch("transcribe._get_duration", return_value=60.0)
    @patch("transcribe._write_outputs")
    def test_config_used_in_output(self, mock_write, mock_dur, mock_audio, mock_clip, tmp_path):
        """config_used field is present in output."""
        mock_clip.return_value = [{"word": "test", "start": 0.0, "end": 0.5}]
        result = transcribe_video(
            str(tmp_path / "test.mp4"), str(tmp_path),
            model_size="medium", compute_type="int8", device="cpu",
        )
        assert "config_used" in result
        assert result["config_used"]["model_size"] == "medium"

    @patch("transcribe.transcribe_clip")
    @patch("transcribe._extract_audio", return_value=False)
    @patch("transcribe._get_duration", return_value=60.0)
    def test_audio_extraction_failure(self, mock_dur, mock_audio, mock_clip, tmp_path):
        """Audio extraction fails → error returned."""
        result = transcribe_video(str(tmp_path / "bad.mp4"), str(tmp_path))
        assert "error" in result


class TestChunkCalculation:
    """Tests for chunking math."""

    def test_chunk_threshold(self):
        assert _CHUNK_THRESHOLD_SEC == 180

    def test_chunk_size(self):
        assert _CHUNK_SIZE_SEC == 90

    def test_overlap(self):
        assert _CHUNK_OVERLAP_SEC == 5

    def test_7min_file_chunk_count(self):
        """7 min file → ~5 chunks at 90s each."""
        duration = 420.0  # 7 minutes
        chunk_starts = []
        t = 0.0
        while t < duration:
            chunk_starts.append(t)
            t += _CHUNK_SIZE_SEC
        assert len(chunk_starts) == 5  # 0, 90, 180, 270, 360
