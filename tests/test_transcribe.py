"""Tests for transcribe.py — all offline, no GPU, no media files."""

import json
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from transcribe import transcribe_video, _bucket_words


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

MOCK_WORDS = [
    {"word": "Welcome", "start": 0.5, "end": 0.9},
    {"word": "to", "start": 1.0, "end": 1.2},
    {"word": "the", "start": 1.3, "end": 1.5},
    {"word": "show", "start": 1.6, "end": 2.0},
    {"word": "today", "start": 2.1, "end": 2.5},
    {"word": "we", "start": 10.1, "end": 10.3},
    {"word": "discuss", "start": 10.4, "end": 10.9},
    {"word": "AI", "start": 11.0, "end": 11.3},
]

FFPROBE_STDOUT = json.dumps({"format": {"duration": "30.0"}})


def _mock_subprocess_run(cmd, **kwargs):
    """Route subprocess.run calls to appropriate mock responses."""
    prog = cmd[0] if cmd else ""
    if prog == "ffmpeg":
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    if prog == "ffprobe":
        return CompletedProcess(args=cmd, returncode=0, stdout=FFPROBE_STDOUT, stderr="")
    return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="unknown command")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChunksSchema:
    """test_chunks_schema — verify chunks.json structure matches spec."""

    @patch("transcribe.subprocess.run", side_effect=_mock_subprocess_run)
    @patch("transcribe.transcribe_clip", return_value=MOCK_WORDS)
    def test_chunks_schema(self, mock_tc, mock_sub, tmp_path):
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = transcribe_video(str(video), str(out))

        # Top-level keys.
        assert "source" in result
        assert "duration" in result
        assert "chunks" in result
        assert result["source"] == "input.mp4"
        assert result["duration"] == 30.0

        # Each chunk has required keys.
        required_keys = {"id", "start", "end", "text", "word_count",
                         "silence_ratio", "has_speech"}
        for chunk in result["chunks"]:
            assert required_keys.issubset(chunk.keys()), (
                f"Chunk {chunk.get('id')} missing keys: "
                f"{required_keys - set(chunk.keys())}"
            )

        # Chunk IDs are sequential starting from 0.
        ids = [c["id"] for c in result["chunks"]]
        assert ids == list(range(len(ids)))


class TestSilenceRatioCalc:
    """test_silence_ratio_calc — verify silence ratio computation."""

    def test_known_ratio(self):
        """Two words covering 3.0s of speech in a 10s chunk → silence 0.7."""
        words = [
            {"word": "hello", "start": 1.0, "end": 2.5},   # 1.5s
            {"word": "world", "start": 4.0, "end": 5.5},   # 1.5s
        ]
        # Total speech = 3.0s, chunk duration = 10s, silence = 7.0/10 = 0.7
        chunks = _bucket_words(words, 10.0)
        assert len(chunks) == 1
        assert abs(chunks[0]["silence_ratio"] - 0.7) < 1e-5

    def test_last_chunk_uses_remaining_duration(self):
        """Last chunk uses actual remaining time, not full 10s."""
        # Duration 15s → chunk 0 (0-10), chunk 1 (10-15).
        # Word in chunk 1 covers 2s of the 5s chunk → silence = 3/5 = 0.6.
        words = [
            {"word": "end", "start": 11.0, "end": 13.0},  # 2s in a 5s chunk
        ]
        chunks = _bucket_words(words, 15.0)
        assert len(chunks) == 2
        last = chunks[1]
        assert last["end"] == 15.0
        assert abs(last["silence_ratio"] - 0.6) < 1e-5


class TestChunkBoundaries:
    """test_chunk_boundaries — words near 10s boundary land in correct chunk."""

    @patch("transcribe.subprocess.run", side_effect=_mock_subprocess_run)
    @patch("transcribe.transcribe_clip")
    def test_boundary_words(self, mock_tc, mock_sub, tmp_path):
        boundary_words = [
            {"word": "before", "start": 9.9, "end": 10.0},
            {"word": "after", "start": 10.1, "end": 10.3},
        ]
        mock_tc.return_value = boundary_words

        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = transcribe_video(str(video), str(out))
        chunks = result["chunks"]

        # "before" at 9.9s → chunk 0 (floor(9.9/10) = 0).
        chunk0 = chunks[0]
        assert "before" in chunk0["text"]
        assert "after" not in chunk0["text"]

        # "after" at 10.1s → chunk 1 (floor(10.1/10) = 1).
        chunk1 = chunks[1]
        assert "after" in chunk1["text"]
        assert "before" not in chunk1["text"]


class TestEmptyVideo:
    """test_empty_video — no speech produces all-silent chunks."""

    @patch("transcribe.subprocess.run", side_effect=_mock_subprocess_run)
    @patch("transcribe.transcribe_clip", return_value=[])
    def test_empty_produces_silent_chunks(self, mock_tc, mock_sub, tmp_path):
        video = tmp_path / "silent.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = transcribe_video(str(video), str(out))

        assert result["duration"] == 30.0
        # 30s / 10 = 3 chunks.
        assert len(result["chunks"]) == 3

        for chunk in result["chunks"]:
            assert chunk["has_speech"] is False
            assert chunk["silence_ratio"] == 1.0
            assert chunk["word_count"] == 0
            assert chunk["text"] == ""


class TestOutputFilesWritten:
    """test_output_files_written — verify JSON files exist on disk."""

    @patch("transcribe.subprocess.run", side_effect=_mock_subprocess_run)
    @patch("transcribe.transcribe_clip", return_value=MOCK_WORDS)
    def test_files_exist(self, mock_tc, mock_sub, tmp_path):
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        transcribe_video(str(video), str(out))

        chunks_path = out / "chunks.json"
        transcript_path = out / "transcript.json"

        assert chunks_path.exists(), "chunks.json was not written"
        assert transcript_path.exists(), "transcript.json was not written"

        # Validate they are parseable JSON.
        with open(chunks_path, encoding="utf-8") as f:
            cdata = json.load(f)
        assert "chunks" in cdata

        with open(transcript_path, encoding="utf-8") as f:
            tdata = json.load(f)
        assert "words" in tdata
        assert len(tdata["words"]) == len(MOCK_WORDS)


class TestAudioExtractionFailure:
    """test_ffmpeg_failure — returns error dict on extraction failure."""

    @patch("transcribe.subprocess.run")
    def test_ffmpeg_failure_returns_error(self, mock_sub, tmp_path):
        mock_sub.return_value = CompletedProcess(
            args=[], returncode=1, stdout="", stderr="ffmpeg error"
        )
        video = tmp_path / "bad.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = transcribe_video(str(video), str(out))

        assert "error" in result
        assert result["error"] == "audio extraction failed"
        assert result["source"] == "bad.mp4"


class TestDurationFallback:
    """test_duration_fallback — uses max word end + 1.0 when ffprobe fails."""

    def _mock_run_ffprobe_fails(self, cmd, **kwargs):
        prog = cmd[0] if cmd else ""
        if prog == "ffmpeg":
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        if prog == "ffprobe":
            return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="fail")
        return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")

    @patch("transcribe.subprocess.run")
    @patch("transcribe.transcribe_clip")
    def test_fallback_duration(self, mock_tc, mock_sub, tmp_path):
        mock_sub.side_effect = self._mock_run_ffprobe_fails
        mock_tc.return_value = [
            {"word": "hi", "start": 0.5, "end": 1.0},
            {"word": "bye", "start": 7.0, "end": 7.8},
        ]

        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = transcribe_video(str(video), str(out))

        # Fallback: max end (7.8) + 1.0 = 8.8
        assert result["duration"] == 8.8
