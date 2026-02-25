"""Tests for portrait_crop.py — all offline, no real ffmpeg/mediapipe calls."""

import json
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from portrait_crop import (
    portrait_crop,
    _get_duration,
    _safe_output_path,
    _crop_with_face_detect,
    _result_dict,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_ffmpeg_success(cmd, **kwargs):
    """Mock subprocess.run that succeeds for ffmpeg and returns duration for ffprobe."""
    prog = cmd[0] if cmd else ""
    if prog == "ffprobe":
        return CompletedProcess(
            args=cmd, returncode=0, stdout='{"format":{"duration":"120.5"}}', stderr="",
        )
    if prog == "ffmpeg":
        # Create the output file so _get_duration can find it.
        # Find output path: last arg before or the arg just before -y,
        # or just the last arg.
        for i, arg in enumerate(cmd):
            if arg == "-y" and i + 1 < len(cmd):
                out_path = Path(cmd[i + 1])
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("fake output")
                break
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")


def _mock_ffmpeg_fail(cmd, **kwargs):
    """Mock where ffmpeg returns non-zero exit code."""
    prog = cmd[0] if cmd else ""
    if prog == "ffprobe":
        return CompletedProcess(
            args=cmd, returncode=0, stdout='{"format":{"duration":"120.5"}}', stderr="",
        )
    return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="encode failed")


def _mock_ffprobe_only(cmd, **kwargs):
    """Mock that handles ffprobe but fails ffmpeg."""
    prog = cmd[0] if cmd else ""
    if prog == "ffprobe":
        return CompletedProcess(
            args=cmd, returncode=0, stdout='{"format":{"duration":"60.0"}}', stderr="",
        )
    return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="ffmpeg error")


# ---------------------------------------------------------------------------
# Tests: Center crop builds correct ffmpeg command
# ---------------------------------------------------------------------------


class TestCenterCropCommand:
    """Test that center crop method builds the correct ffmpeg command."""

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_basic_center_crop_command(self, mock_sub, tmp_path):
        """Center crop command uses crop=ih*9/16:ih filter."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        assert result["status"] == "success"
        assert result["crop_filter"] == "crop=ih*9/16:ih"
        assert "crop=ih*9/16:ih" in result["ffmpeg_cmd"]

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_center_crop_copies_audio(self, mock_sub, tmp_path):
        """ffmpeg command includes -c:a copy to pass through audio."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        assert "-c:a copy" in result["ffmpeg_cmd"]

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_center_crop_uses_overwrite(self, mock_sub, tmp_path):
        """ffmpeg command includes -y for overwrite."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        assert " -y " in result["ffmpeg_cmd"]

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_method_is_center(self, mock_sub, tmp_path):
        """Default method is reported as 'center'."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        assert result["method"] == "center"


# ---------------------------------------------------------------------------
# Tests: Start/end trimming
# ---------------------------------------------------------------------------


class TestStartEndTrimming:
    """Test that start/end parameters add -ss and -t to ffmpeg command."""

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_start_adds_ss_before_input(self, mock_sub, tmp_path):
        """--start places -ss before -i for fast seeking."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out), start=10.0)

        cmd = result["ffmpeg_cmd"]
        # -ss should appear before -i.
        ss_pos = cmd.index("-ss")
        i_pos = cmd.index("-i")
        assert ss_pos < i_pos, "-ss must appear before -i for fast seeking"
        assert "-ss 10.0" in cmd

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_start_and_end_adds_duration(self, mock_sub, tmp_path):
        """When both start and end are given, -t is computed as end - start."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out), start=10.0, end=30.0)

        cmd = result["ffmpeg_cmd"]
        assert "-ss 10.0" in cmd
        assert "-t 20.0" in cmd

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_end_only_adds_t(self, mock_sub, tmp_path):
        """When only end is given, -t equals end value."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out), end=15.0)

        cmd = result["ffmpeg_cmd"]
        assert "-t 15.0" in cmd
        assert "-ss" not in cmd

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_no_start_end_no_time_flags(self, mock_sub, tmp_path):
        """Without start/end, no -ss or -t flags appear."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        cmd = result["ffmpeg_cmd"]
        assert "-ss" not in cmd
        assert " -t " not in cmd


# ---------------------------------------------------------------------------
# Tests: Output filename pattern
# ---------------------------------------------------------------------------


class TestOutputFilenamePattern:
    """Test that output files follow {stem}_portrait{ext} pattern."""

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_portrait_suffix_in_output(self, mock_sub, tmp_path):
        """Output filename is {stem}_portrait{ext}."""
        video = tmp_path / "IMG_5769.MOV"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        output_path = Path(result["output"])
        assert output_path.name == "IMG_5769_portrait.MOV"

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_preserves_extension(self, mock_sub, tmp_path):
        """Output keeps the same extension as input."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        output_path = Path(result["output"])
        assert output_path.suffix == ".mp4"

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_output_in_specified_dir(self, mock_sub, tmp_path):
        """Output file is placed in the specified output directory."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "custom_output"

        result = portrait_crop(str(video), output_dir=str(out))

        output_path = Path(result["output"])
        assert output_path.parent == out


# ---------------------------------------------------------------------------
# Tests: Safe output path (no overwrite)
# ---------------------------------------------------------------------------


class TestSafeOutputPath:
    """Test that _safe_output_path avoids overwriting existing files."""

    def test_first_candidate_when_no_conflict(self, tmp_path):
        """When no file exists, returns base name."""
        result = _safe_output_path(tmp_path, "clip", "portrait", ".mp4")
        assert result == tmp_path / "clip_portrait.mp4"

    def test_increments_counter_on_conflict(self, tmp_path):
        """When base name exists, adds _1 suffix."""
        existing = tmp_path / "clip_portrait.mp4"
        existing.write_text("existing")

        result = _safe_output_path(tmp_path, "clip", "portrait", ".mp4")
        assert result == tmp_path / "clip_portrait_1.mp4"

    def test_increments_counter_multiple_conflicts(self, tmp_path):
        """When _1 also exists, tries _2."""
        (tmp_path / "clip_portrait.mp4").write_text("existing")
        (tmp_path / "clip_portrait_1.mp4").write_text("existing")

        result = _safe_output_path(tmp_path, "clip", "portrait", ".mp4")
        assert result == tmp_path / "clip_portrait_2.mp4"

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_portrait_crop_avoids_overwrite(self, mock_sub, tmp_path):
        """Full portrait_crop call avoids overwriting existing output."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"
        out.mkdir()

        # Pre-create the expected output file.
        existing = out / "clip_portrait.mp4"
        existing.write_text("do not overwrite")

        result = portrait_crop(str(video), output_dir=str(out))

        output_path = Path(result["output"])
        assert output_path.name == "clip_portrait_1.mp4"
        # Original file should be untouched.
        assert existing.read_text() == "do not overwrite"


# ---------------------------------------------------------------------------
# Tests: Mediapipe import failure handled gracefully
# ---------------------------------------------------------------------------


class TestMediapipeImportFailure:
    """Test that mediapipe import failure is handled gracefully."""

    def test_crop_with_face_detect_returns_none(self, tmp_path):
        """_crop_with_face_detect returns None when mediapipe not installed."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out.mp4"

        result = _crop_with_face_detect(video, out)
        assert result is None

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_face_method_falls_back_to_center(self, mock_sub, tmp_path):
        """When method='face' but mediapipe unavailable, falls back to center."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out), method="face")

        # Should succeed with center fallback.
        assert result["status"] == "success"
        assert result["method"] == "center"
        assert result["crop_filter"] == "crop=ih*9/16:ih"

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_face_fallback_still_trims(self, mock_sub, tmp_path):
        """Face method fallback to center still respects start/end trimming."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(
            str(video), output_dir=str(out), method="face",
            start=5.0, end=25.0,
        )

        assert result["status"] == "success"
        assert "-ss 5.0" in result["ffmpeg_cmd"]
        assert "-t 20.0" in result["ffmpeg_cmd"]


# ---------------------------------------------------------------------------
# Tests: Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test graceful error handling for bad inputs and ffmpeg failures."""

    def test_missing_input_file(self, tmp_path):
        """Non-existent input file returns error result."""
        result = portrait_crop(
            str(tmp_path / "nonexistent.mp4"),
            output_dir=str(tmp_path / "out"),
        )

        assert result["status"] == "error"
        assert "not found" in result["error"]
        assert result["action"] == "portrait_crop"

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_fail)
    def test_ffmpeg_failure(self, mock_sub, tmp_path):
        """ffmpeg non-zero exit returns error with stderr."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        assert result["status"] == "error"
        assert "ffmpeg exited 1" in result["error"]
        assert result["ffmpeg_cmd"] is not None

    @patch("portrait_crop.subprocess.run", side_effect=FileNotFoundError("ffmpeg not found"))
    def test_ffmpeg_not_found(self, mock_sub, tmp_path):
        """FileNotFoundError (no ffmpeg binary) returns error."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        assert result["status"] == "error"
        assert "ffmpeg not found" in result["error"]

    @patch("portrait_crop.subprocess.run", side_effect=OSError("disk full"))
    def test_os_error(self, mock_sub, tmp_path):
        """OSError during ffmpeg returns error."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        assert result["status"] == "error"
        assert "disk full" in result["error"]


# ---------------------------------------------------------------------------
# Tests: Result schema (all required keys present)
# ---------------------------------------------------------------------------


class TestResultSchema:
    """Test that result dict has all required keys with correct types."""

    REQUIRED_KEYS = {
        "status", "action", "input", "output", "method",
        "duration_in", "duration_out", "crop_filter",
        "ffmpeg_cmd", "elapsed_seconds", "error",
    }

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_success_result_has_all_keys(self, mock_sub, tmp_path):
        """Successful result contains all required keys."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        for key in self.REQUIRED_KEYS:
            assert key in result, f"Missing key: {key}"

    def test_error_result_has_all_keys(self, tmp_path):
        """Error result also contains all required keys."""
        result = portrait_crop(
            str(tmp_path / "nonexistent.mp4"),
            output_dir=str(tmp_path / "out"),
        )

        for key in self.REQUIRED_KEYS:
            assert key in result, f"Missing key: {key}"

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_action_is_portrait_crop(self, mock_sub, tmp_path):
        """action field is always 'portrait_crop'."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        assert result["action"] == "portrait_crop"

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_elapsed_seconds_is_float(self, mock_sub, tmp_path):
        """elapsed_seconds is a non-negative float."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        assert isinstance(result["elapsed_seconds"], float)
        assert result["elapsed_seconds"] >= 0

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_success_has_no_error(self, mock_sub, tmp_path):
        """Successful result has error=None."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        assert result["error"] is None

    def test_error_has_error_message(self, tmp_path):
        """Error result has non-None error string."""
        result = portrait_crop(
            str(tmp_path / "nonexistent.mp4"),
            output_dir=str(tmp_path / "out"),
        )

        assert result["error"] is not None
        assert isinstance(result["error"], str)

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_input_path_matches(self, mock_sub, tmp_path):
        """input field matches the provided input path."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        assert result["input"] == str(video)

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_ffmpeg_cmd_is_string(self, mock_sub, tmp_path):
        """ffmpeg_cmd is a string (from shlex.join)."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        assert isinstance(result["ffmpeg_cmd"], str)
        assert result["ffmpeg_cmd"].startswith("ffmpeg")


# ---------------------------------------------------------------------------
# Tests: Method selection (center vs face fallback)
# ---------------------------------------------------------------------------


class TestMethodSelection:
    """Test method parameter handling."""

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_default_method_is_center(self, mock_sub, tmp_path):
        """Default method parameter is 'center'."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out))

        assert result["method"] == "center"

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_explicit_center_method(self, mock_sub, tmp_path):
        """Explicitly passing method='center' works."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out), method="center")

        assert result["method"] == "center"
        assert result["status"] == "success"

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_face_method_without_mediapipe(self, mock_sub, tmp_path):
        """method='face' without mediapipe falls back to center and succeeds."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = portrait_crop(str(video), output_dir=str(out), method="face")

        # Falls back to center.
        assert result["status"] == "success"
        assert result["method"] == "center"

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    @patch("portrait_crop._crop_with_face_detect")
    def test_face_method_used_when_available(self, mock_face, mock_sub, tmp_path):
        """When face detection returns a result, it is used instead of center."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"
        out.mkdir()

        # Simulate successful face detection.
        out_file = out / "clip_portrait.mp4"
        out_file.write_text("face cropped output")

        mock_face.return_value = {
            "method": "face",
            "crop_filter": "crop=607:1080:400:0",
            "ffmpeg_cmd": "ffmpeg -i clip.mp4 -vf crop=607:1080:400:0 -c:a copy -y out.mp4",
        }

        result = portrait_crop(str(video), output_dir=str(out), method="face")

        assert result["status"] == "success"
        assert result["method"] == "face"
        assert result["crop_filter"] == "crop=607:1080:400:0"


# ---------------------------------------------------------------------------
# Tests: _get_duration helper
# ---------------------------------------------------------------------------


class TestGetDuration:
    """Test the _get_duration ffprobe helper."""

    @patch("portrait_crop.subprocess.run")
    def test_returns_float_on_success(self, mock_sub, tmp_path):
        """ffprobe success returns duration as float."""
        mock_sub.return_value = CompletedProcess(
            args=[], returncode=0,
            stdout='{"format":{"duration":"45.678"}}', stderr="",
        )

        result = _get_duration(tmp_path / "clip.mp4")
        assert result == pytest.approx(45.678)

    @patch("portrait_crop.subprocess.run")
    def test_returns_none_on_failure(self, mock_sub, tmp_path):
        """ffprobe failure returns None."""
        mock_sub.return_value = CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error",
        )

        result = _get_duration(tmp_path / "clip.mp4")
        assert result is None

    @patch("portrait_crop.subprocess.run", side_effect=FileNotFoundError)
    def test_returns_none_on_missing_ffprobe(self, mock_sub, tmp_path):
        """Missing ffprobe binary returns None."""
        result = _get_duration(tmp_path / "clip.mp4")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: _result_dict builder
# ---------------------------------------------------------------------------


class TestResultDictBuilder:
    """Test the _result_dict helper function."""

    def test_all_keys_populated(self):
        """_result_dict returns a dict with all required keys."""
        result = _result_dict(
            status="success",
            input_path="/input.mp4",
            output_path="/output.mp4",
            method="center",
            duration_in=120.0,
            duration_out=60.0,
            crop_filter="crop=ih*9/16:ih",
            ffmpeg_cmd="ffmpeg -i input.mp4 ...",
            elapsed_seconds=1.2345,
            error=None,
        )

        assert result["status"] == "success"
        assert result["action"] == "portrait_crop"
        assert result["input"] == "/input.mp4"
        assert result["output"] == "/output.mp4"
        assert result["method"] == "center"
        assert result["duration_in"] == 120.0
        assert result["duration_out"] == 60.0
        assert result["crop_filter"] == "crop=ih*9/16:ih"
        assert result["ffmpeg_cmd"] == "ffmpeg -i input.mp4 ..."
        assert result["elapsed_seconds"] == 1.234  # rounded to 3 decimal places
        assert result["error"] is None

    def test_elapsed_seconds_rounded(self):
        """elapsed_seconds is rounded to 3 decimal places."""
        result = _result_dict(
            status="error",
            input_path="/in.mp4",
            output_path=None,
            method="center",
            duration_in=None,
            duration_out=None,
            crop_filter=None,
            ffmpeg_cmd=None,
            elapsed_seconds=1.23456789,
            error="test error",
        )

        assert result["elapsed_seconds"] == 1.235


# ---------------------------------------------------------------------------
# Tests: Output directory creation
# ---------------------------------------------------------------------------


class TestOutputDirectoryCreation:
    """Test that output directory is created when it does not exist."""

    @patch("portrait_crop.subprocess.run", side_effect=_mock_ffmpeg_success)
    def test_creates_nested_output_dir(self, mock_sub, tmp_path):
        """Non-existent nested output directory is created automatically."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "deep" / "nested" / "output"

        result = portrait_crop(str(video), output_dir=str(out))

        assert result["status"] == "success"
        assert out.exists()
