"""Tests for silence_remove.py — all offline, no GPU, no media files."""

import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from silence_remove import (
    MIN_CLIP_DURATION,
    build_auto_editor_cmd,
    process_clip,
    remove_silence,
)


class TestBuildAutoEditorCmd:
    def test_flag_construction(self):
        cmd = build_auto_editor_cmd(Path("in/clip.mp4"), Path("out/clip.mp4"))
        assert cmd[0] == "auto-editor"
        assert "--margin" in cmd
        assert cmd[cmd.index("--margin") + 1] == "0.15s"
        assert "--no-open" in cmd
        assert "--output" in cmd
        assert cmd[cmd.index("--output") + 1] == str(Path("out/clip.mp4"))

    def test_exact_command_structure(self):
        cmd = build_auto_editor_cmd(Path("a.mp4"), Path("b.mp4"))
        assert cmd == [
            "auto-editor", str(Path("a.mp4")),
            "--margin", "0.15s",
            "--no-open",
            "--output", str(Path("b.mp4")),
        ]


class TestMinClipDuration:
    def test_all_platforms_present(self):
        for p in ("tiktok", "reels", "shorts", "youtube", "linkedin"):
            assert p in MIN_CLIP_DURATION

    def test_social_is_6(self):
        for p in ("tiktok", "reels", "shorts"):
            assert MIN_CLIP_DURATION[p] == 6

    def test_youtube_is_15(self):
        assert MIN_CLIP_DURATION["youtube"] == 15

    def test_linkedin_is_10(self):
        assert MIN_CLIP_DURATION["linkedin"] == 10


class TestProcessClipErrorFallback:
    @patch("silence_remove.subprocess.run")
    @patch("silence_remove.get_duration", return_value=30.0)
    def test_failure_copies_original(self, mock_dur, mock_run):
        mock_run.side_effect = FileNotFoundError("auto-editor not found")
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "input.mp4"
            out_path = Path(tmpdir) / "output.mp4"
            in_path.write_bytes(b"fake video data")

            result = process_clip(in_path, out_path)

            assert result["status"] == "failed"
            assert result["filename"] == "input.mp4"
            assert result["original_duration"] == 30.0
            assert result["cleaned_duration"] == 30.0
            assert result["pct_removed"] == 0.0
            assert out_path.exists()  # original was copied

    @patch("silence_remove.subprocess.run")
    @patch("silence_remove.get_duration", return_value=30.0)
    def test_timeout_copies_original(self, mock_dur, mock_run):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="auto-editor", timeout=600)
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "clip.mp4"
            out_path = Path(tmpdir) / "clip_out.mp4"
            in_path.write_bytes(b"fake")

            result = process_clip(in_path, out_path)
            assert result["status"] == "failed"
            assert out_path.exists()


class TestProcessClipSuccess:
    @patch("silence_remove.subprocess.run")
    @patch("silence_remove.get_duration")
    def test_successful_process(self, mock_dur, mock_run):
        # First call = original duration, second = cleaned duration
        mock_dur.side_effect = [60.0, 45.0]
        mock_run.return_value = MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "clip.mp4"
            out_path = Path(tmpdir) / "clip_out.mp4"
            in_path.write_bytes(b"fake")
            out_path.write_bytes(b"fake cleaned")

            result = process_clip(in_path, out_path)

            assert result["status"] == "processed"
            assert result["original_duration"] == 60.0
            assert result["cleaned_duration"] == 45.0
            assert result["pct_removed"] == 25.0


class TestRemoveSilence:
    @patch("silence_remove.process_clip")
    def test_summary_dict_calculation(self, mock_process):
        mock_process.side_effect = [
            {"filename": "a.mp4", "original_duration": 30.0, "cleaned_duration": 20.0,
             "pct_removed": 33.3, "status": "processed"},
            {"filename": "b.mp4", "original_duration": 10.0, "cleaned_duration": 4.0,
             "pct_removed": 60.0, "status": "processed"},  # will be skipped (4s < 6s)
            {"filename": "c.mp4", "original_duration": 25.0, "cleaned_duration": 25.0,
             "pct_removed": 0.0, "status": "failed"},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            in_dir = Path(tmpdir) / "in"
            out_dir = Path(tmpdir) / "out"
            in_dir.mkdir()
            for name in ("a.mp4", "b.mp4", "c.mp4"):
                (in_dir / name).write_bytes(b"fake")

            summary = remove_silence(in_dir, out_dir, platform="tiktok")

            assert summary["processed"] == 1  # only a.mp4
            assert summary["skipped"] == 1    # b.mp4 too short
            assert summary["failed"] == 1     # c.mp4
            assert summary["total_saved_seconds"] == 10.0

    @patch("silence_remove.process_clip")
    def test_youtube_min_duration_filtering(self, mock_process):
        mock_process.return_value = {
            "filename": "clip.mp4", "original_duration": 20.0, "cleaned_duration": 12.0,
            "pct_removed": 40.0, "status": "processed",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            in_dir = Path(tmpdir) / "in"
            out_dir = Path(tmpdir) / "out"
            in_dir.mkdir()
            (in_dir / "clip.mp4").write_bytes(b"fake")

            summary = remove_silence(in_dir, out_dir, platform="youtube")
            # 12s < 15s min for youtube
            assert summary["skipped"] == 1
            assert summary["processed"] == 0

    @patch("silence_remove.subprocess.run")
    @patch("silence_remove.get_duration", return_value=0.0)
    def test_mock_subprocess_exact_command(self, mock_dur, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "test.mp4"
            out_path = Path(tmpdir) / "test_out.mp4"
            in_path.write_bytes(b"fake")
            out_path.write_bytes(b"fake")

            process_clip(in_path, out_path)

            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "auto-editor"
            assert "--margin" in call_args
            assert "0.15s" in call_args
            assert "--no-open" in call_args
