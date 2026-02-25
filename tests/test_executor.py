"""Tests for executor.py — all offline, no real ffmpeg calls.

Every ffmpeg/ffprobe subprocess.run call is mocked.
"""

import json
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from executor import execute_action, PLATFORM_PRESETS, _safe_output_path


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

FFPROBE_STDOUT = json.dumps({"format": {"duration": "420.5"}})
FFPROBE_STDOUT_OUT = json.dumps({"format": {"duration": "385.2"}})


def _mock_subprocess_run(cmd, **kwargs):
    """Route subprocess.run calls to appropriate mock responses."""
    prog = cmd[0] if cmd else ""
    if prog == "ffprobe":
        # Return different duration for output vs input based on path content.
        path_arg = cmd[-1]
        if "_silence_remove" in path_arg or "_trim" in path_arg or "_crop" in path_arg or "_platform_export" in path_arg:
            return CompletedProcess(args=cmd, returncode=0, stdout=FFPROBE_STDOUT_OUT, stderr="")
        return CompletedProcess(args=cmd, returncode=0, stdout=FFPROBE_STDOUT, stderr="")
    if prog == "ffmpeg":
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")


def _mock_subprocess_run_fail(cmd, **kwargs):
    """Mock where ffmpeg returns non-zero exit code."""
    prog = cmd[0] if cmd else ""
    if prog == "ffprobe":
        return CompletedProcess(args=cmd, returncode=0, stdout=FFPROBE_STDOUT, stderr="")
    if prog == "ffmpeg":
        return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="encoding failed")
    return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")


def _make_action(action_type: str, **params) -> dict:
    """Build a minimal action dict for testing."""
    return {
        "action": action_type,
        "params": {
            "input": None,
            "output": None,
            "platform": None,
            "max_duration": None,
            "aspect": None,
            "silence_threshold_db": -30,
            "caption_style": "default",
            **params,
        },
        "executor": "ffmpeg",
        "confidence": 0.95,
    }


# Required keys in every result dict.
RESULT_KEYS = {
    "status", "action", "input", "output",
    "duration_in", "duration_out", "ffmpeg_cmd",
    "elapsed_seconds", "error",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSilenceRemove:
    """test_silence_remove -- builds correct ffmpeg command."""

    @patch("executor.subprocess.run", side_effect=_mock_subprocess_run)
    def test_silence_remove(self, mock_sub, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        action = _make_action("silence_remove")
        result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert result["status"] == "success"
        assert result["action"] == "silence_remove"
        assert "silenceremove" in result["ffmpeg_cmd"]
        assert "-30dB" in result["ffmpeg_cmd"]
        assert result["error"] is None


class TestTrimSeconds:
    """test_trim_seconds -- -ss and -t flags correct."""

    @patch("executor.subprocess.run", side_effect=_mock_subprocess_run)
    def test_trim_with_duration(self, mock_sub, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        action = _make_action("trim", max_duration=30)
        result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert result["status"] == "success"
        assert result["action"] == "trim"
        assert "-t" in result["ffmpeg_cmd"]
        assert "30" in result["ffmpeg_cmd"]

    @patch("executor.subprocess.run", side_effect=_mock_subprocess_run)
    def test_trim_with_start_and_duration(self, mock_sub, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        action = _make_action("trim", max_duration=30, start=10)
        result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert result["status"] == "success"
        assert "-ss" in result["ffmpeg_cmd"]
        assert "10" in result["ffmpeg_cmd"]
        assert "-t" in result["ffmpeg_cmd"]


class TestCropVertical:
    """test_crop_vertical -- scale+crop filter chain."""

    @patch("executor.subprocess.run", side_effect=_mock_subprocess_run)
    def test_crop_9_16(self, mock_sub, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        action = _make_action("crop", aspect="9:16")
        result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert result["status"] == "success"
        assert result["action"] == "crop"
        assert "scale=" in result["ffmpeg_cmd"]
        assert "crop=" in result["ffmpeg_cmd"]


class TestPlatformExportTiktok:
    """test_platform_export_tiktok -- correct preset applied."""

    @patch("executor.subprocess.run", side_effect=_mock_subprocess_run)
    def test_tiktok_preset(self, mock_sub, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        action = _make_action("platform_export", platform="tiktok")
        result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert result["status"] == "success"
        assert result["action"] == "platform_export"
        # TikTok preset: libx264, crf 23, max 60s, 9:16
        assert "libx264" in result["ffmpeg_cmd"]
        assert "-crf" in result["ffmpeg_cmd"]
        assert "23" in result["ffmpeg_cmd"]
        assert "-t" in result["ffmpeg_cmd"]
        assert "60" in result["ffmpeg_cmd"]


class TestPlatformExportYoutube:
    """test_platform_export_youtube -- crf 18, no duration limit."""

    @patch("executor.subprocess.run", side_effect=_mock_subprocess_run)
    def test_youtube_long_preset(self, mock_sub, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        action = _make_action("platform_export", platform="youtube_long")
        result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert result["status"] == "success"
        # YouTube long: crf 18, no -t flag (no max_duration)
        assert "18" in result["ffmpeg_cmd"]
        assert "-t" not in result["ffmpeg_cmd"]


class TestOutputFilename:
    """test_output_filename -- stem_action pattern."""

    @patch("executor.subprocess.run", side_effect=_mock_subprocess_run)
    def test_output_name_pattern(self, mock_sub, tmp_path):
        video = tmp_path / "IMG_5769.mp4"
        video.write_text("fake")

        action = _make_action("trim", max_duration=30)
        result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert result["status"] == "success"
        output_path = Path(result["output"])
        assert output_path.name == "IMG_5769_trim.mp4"


class TestNoOverwrite:
    """test_no_overwrite -- appends _1 if exists."""

    def test_safe_output_appends_counter(self, tmp_path):
        # Create the base file so it already exists.
        existing = tmp_path / "clip_trim.mp4"
        existing.write_text("existing")

        out = _safe_output_path(tmp_path, "clip", "trim", ".mp4")
        assert out.name == "clip_trim_1.mp4"

    def test_safe_output_appends_2_when_1_exists(self, tmp_path):
        (tmp_path / "clip_trim.mp4").write_text("existing")
        (tmp_path / "clip_trim_1.mp4").write_text("existing")

        out = _safe_output_path(tmp_path, "clip", "trim", ".mp4")
        assert out.name == "clip_trim_2.mp4"


class TestInvalidAction:
    """test_invalid_action -- returns error dict."""

    def test_unsupported_action_returns_error(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        action = _make_action("color_grade")
        result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert result["status"] == "error"
        assert "unsupported action" in result["error"]

    def test_missing_keys_returns_error(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        action = {"action": "trim"}  # missing params and executor
        result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert result["status"] == "error"
        assert "missing required keys" in result["error"]


class TestMissingInput:
    """test_missing_input -- returns error dict."""

    def test_no_input_path(self, tmp_path):
        action = _make_action("trim", max_duration=30)
        # No input_path arg and params["input"] is None
        result = execute_action(action, output_dir=str(tmp_path))

        assert result["status"] == "error"
        assert "no input path" in result["error"]


class TestCaptionBurnWrapsExisting:
    """test_caption_burn_wraps_existing -- calls subtitle_burn."""

    @patch("executor.subprocess.run", side_effect=_mock_subprocess_run)
    def test_caption_burn_calls_burn_subtitle(self, mock_sub, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        ass_file = tmp_path / "clip.ass"
        ass_file.write_text("[Script Info]")

        action = _make_action("caption_burn")

        with patch("executor._burn_subtitle") as mock_burn:
            mock_burn.return_value = {"status": "ok", "filename": "clip.mp4", "probe": None}

            # Patch the import inside _execute_caption_burn
            result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert result["status"] == "success"
        assert result["action"] == "caption_burn"

    @patch("executor.subprocess.run", side_effect=_mock_subprocess_run)
    def test_caption_burn_with_custom_ass_path(self, mock_sub, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        ass_file = tmp_path / "custom.ass"
        ass_file.write_text("[Script Info]")

        action = _make_action("caption_burn", ass_path=str(ass_file))

        with patch("executor._burn_subtitle") as mock_burn:
            mock_burn.return_value = {"status": "ok", "filename": "clip.mp4", "probe": None}
            result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert result["status"] == "success"
        # Verify burn_subtitle was called with the custom ASS path.
        call_args = mock_burn.call_args
        assert str(call_args[0][1]) == str(ass_file)


class TestResultSchema:
    """test_result_schema -- all required keys present."""

    @patch("executor.subprocess.run", side_effect=_mock_subprocess_run)
    def test_success_has_all_keys(self, mock_sub, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        action = _make_action("trim", max_duration=10)
        result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert RESULT_KEYS <= set(result.keys()), f"Missing keys: {RESULT_KEYS - set(result.keys())}"

    def test_error_has_all_keys(self, tmp_path):
        action = _make_action("trim")
        result = execute_action(action, output_dir=str(tmp_path))

        assert RESULT_KEYS <= set(result.keys()), f"Missing keys: {RESULT_KEYS - set(result.keys())}"

    @patch("executor.subprocess.run", side_effect=_mock_subprocess_run_fail)
    def test_ffmpeg_failure_has_all_keys(self, mock_sub, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        action = _make_action("trim", max_duration=10)
        result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert RESULT_KEYS <= set(result.keys())
        assert result["status"] == "error"
        assert result["error"] is not None


class TestElapsedTime:
    """test_elapsed_time -- elapsed_seconds > 0."""

    @patch("executor.subprocess.run", side_effect=_mock_subprocess_run)
    def test_elapsed_is_non_negative(self, mock_sub, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")

        action = _make_action("trim", max_duration=10)
        result = execute_action(action, input_path=str(video), output_dir=str(tmp_path))

        assert result["elapsed_seconds"] >= 0
        assert isinstance(result["elapsed_seconds"], float)

    def test_elapsed_positive_on_error(self, tmp_path):
        action = _make_action("trim")
        result = execute_action(action, output_dir=str(tmp_path))

        assert result["elapsed_seconds"] >= 0


class TestTranscribeAction:
    """test_transcribe_action — wraps transcribe_video correctly."""

    @patch("executor._transcribe_video")
    def test_transcribe_calls_transcribe_video(self, mock_tv, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        mock_tv.return_value = {
            "source": "clip.mp4",
            "duration": 30.0,
            "chunks": [{"id": 0, "start": 0, "end": 10, "text": "hello"}],
        }

        action = _make_action("transcribe")
        result = execute_action(action, input_path=str(video), output_dir=str(out))

        assert result["status"] == "success"
        assert result["action"] == "transcribe"
        mock_tv.assert_called_once_with(str(video), str(out))
