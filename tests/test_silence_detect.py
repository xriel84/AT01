"""Tests for silence_detect.py — all offline, no real ffmpeg calls."""

import json
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from silence_detect import (
    detect_silence,
    _parse_silence_stderr,
    _build_speech_segments,
    _compute_stats,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

SAMPLE_STDERR = """\
[silencedetect @ 0x55] silence_start: 1.504
[silencedetect @ 0x55] silence_end: 3.256 | silence_duration: 1.752
[silencedetect @ 0x55] silence_start: 7.891
[silencedetect @ 0x55] silence_end: 9.143 | silence_duration: 1.252
"""

FFPROBE_STDOUT = json.dumps({"format": {"duration": "20.0"}})


def _mock_subprocess_run(cmd, **kwargs):
    """Route subprocess.run calls to appropriate mock responses."""
    prog = cmd[0] if cmd else ""
    if prog == "ffmpeg":
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr=SAMPLE_STDERR)
    if prog == "ffprobe":
        return CompletedProcess(args=cmd, returncode=0, stdout=FFPROBE_STDOUT, stderr="")
    return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")


def _mock_subprocess_run_no_silence(cmd, **kwargs):
    """Mock where ffmpeg finds no silence at all."""
    prog = cmd[0] if cmd else ""
    if prog == "ffmpeg":
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="no silence here\n")
    if prog == "ffprobe":
        return CompletedProcess(args=cmd, returncode=0, stdout=FFPROBE_STDOUT, stderr="")
    return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")


def _mock_subprocess_run_ffmpeg_fail(cmd, **kwargs):
    """Mock where ffmpeg returns non-zero exit code."""
    prog = cmd[0] if cmd else ""
    if prog == "ffmpeg":
        return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="error")
    if prog == "ffprobe":
        return CompletedProcess(args=cmd, returncode=0, stdout=FFPROBE_STDOUT, stderr="")
    return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParseFfmpegOutput:
    """test_parse_ffmpeg_output — verify stderr parsing extracts correct gaps."""

    def test_two_gaps_extracted(self):
        gaps, trailing = _parse_silence_stderr(SAMPLE_STDERR)

        assert len(gaps) == 2
        assert trailing == []

        assert gaps[0]["start"] == pytest.approx(1.504)
        assert gaps[0]["end"] == pytest.approx(3.256)
        assert gaps[0]["duration"] == pytest.approx(1.752)

        assert gaps[1]["start"] == pytest.approx(7.891)
        assert gaps[1]["end"] == pytest.approx(9.143)
        assert gaps[1]["duration"] == pytest.approx(1.252)


class TestSpeechInversion:
    """test_speech_inversion — verify speech segments are correct inverse of gaps."""

    def test_known_gaps_produce_correct_speech(self):
        gaps = [
            {"start": 1.5, "end": 3.2, "duration": 1.7},
            {"start": 7.8, "end": 9.1, "duration": 1.3},
        ]
        duration = 20.0

        speech = _build_speech_segments(gaps, duration)

        assert len(speech) == 3

        # Before first gap: [0, 1.5]
        assert speech[0]["start"] == pytest.approx(0.0)
        assert speech[0]["end"] == pytest.approx(1.5)
        assert speech[0]["duration"] == pytest.approx(1.5)

        # Between gaps: [3.2, 7.8]
        assert speech[1]["start"] == pytest.approx(3.2)
        assert speech[1]["end"] == pytest.approx(7.8)
        assert speech[1]["duration"] == pytest.approx(4.6)

        # After last gap: [9.1, 20.0]
        assert speech[2]["start"] == pytest.approx(9.1)
        assert speech[2]["end"] == pytest.approx(20.0)
        assert speech[2]["duration"] == pytest.approx(10.9)


class TestStatsCalculation:
    """test_stats_calculation — verify stats from known gaps."""

    def test_stats_values(self):
        gaps = [
            {"start": 1.5, "end": 3.2, "duration": 1.7},
            {"start": 7.8, "end": 9.1, "duration": 1.3},
        ]
        duration = 20.0

        stats = _compute_stats(gaps, duration)

        assert stats["total_silence"] == pytest.approx(3.0)
        assert stats["total_speech"] == pytest.approx(17.0)
        assert stats["silence_percentage"] == 15.0
        assert stats["gap_count"] == 2

    def test_zero_duration(self):
        stats = _compute_stats([], 0.0)

        assert stats["total_silence"] == 0.0
        assert stats["total_speech"] == 0.0
        assert stats["silence_percentage"] == 0.0
        assert stats["gap_count"] == 0


class TestThresholdParameter:
    """test_threshold_parameter — verify threshold passes through to ffmpeg command."""

    @patch("silence_detect.subprocess.run", side_effect=_mock_subprocess_run)
    def test_threshold_in_cmd(self, mock_sub, tmp_path):
        video = tmp_path / "input.mp4"
        video.write_text("fake")

        detect_silence(str(video), threshold_db=-40.0, output_dir=str(tmp_path))

        # Find the ffmpeg call (first call).
        ffmpeg_call = None
        for call in mock_sub.call_args_list:
            cmd = call[0][0]
            if cmd[0] == "ffmpeg":
                ffmpeg_call = cmd
                break

        assert ffmpeg_call is not None, "ffmpeg was not called"
        af_arg = ffmpeg_call[ffmpeg_call.index("-af") + 1]
        assert "noise=-40.0dB" in af_arg


class TestOutputFileWritten:
    """test_output_file_written — verify silence_map.json exists after run."""

    @patch("silence_detect.subprocess.run", side_effect=_mock_subprocess_run)
    def test_json_file_exists(self, mock_sub, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = detect_silence(str(video), output_dir=str(out))

        map_path = out / "silence_map.json"
        assert map_path.exists(), "silence_map.json was not written"

        # Validate it is parseable JSON with expected keys.
        with open(map_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "source" in data
        assert "duration" in data
        assert "gaps" in data
        assert "speech" in data
        assert "stats" in data
        assert data["source"] == "clip.mp4"
        assert data["duration"] == 20.0

        # Also verify the return value matches file content.
        assert result == data


class TestNoSilence:
    """test_no_silence — empty stderr produces empty gaps, full-duration speech."""

    @patch("silence_detect.subprocess.run", side_effect=_mock_subprocess_run_no_silence)
    def test_no_gaps(self, mock_sub, tmp_path):
        video = tmp_path / "clean.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = detect_silence(str(video), output_dir=str(out))

        assert result["gaps"] == []
        assert len(result["speech"]) == 1
        assert result["speech"][0]["start"] == 0.0
        assert result["speech"][0]["end"] == 20.0
        assert result["speech"][0]["duration"] == 20.0
        assert result["stats"]["total_silence"] == 0.0
        assert result["stats"]["gap_count"] == 0


class TestFfmpegFailure:
    """test_ffmpeg_failure — non-zero return code produces error dict."""

    @patch("silence_detect.subprocess.run", side_effect=_mock_subprocess_run_ffmpeg_fail)
    def test_error_returned(self, mock_sub, tmp_path):
        video = tmp_path / "bad.mp4"
        video.write_text("fake")

        result = detect_silence(str(video), output_dir=str(tmp_path))

        assert "error" in result
        assert result["error"] == "silence detection failed"
        assert result["source"] == "bad.mp4"
