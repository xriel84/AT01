"""Tests for video_prober — ffprobe metadata extraction."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from video_prober import probe_video, scan_local_dir, VIDEO_EXTENSIONS


# ---------------------------------------------------------------------------
# probe_video
# ---------------------------------------------------------------------------

class TestProbeVideo:
    """Tests for probe_video function."""

    def test_file_not_found(self, tmp_path):
        result = probe_video(str(tmp_path / "nonexistent.mp4"))
        assert result["error"] == f"file not found: {tmp_path / 'nonexistent.mp4'}"
        assert result["code"] == "FILE_NOT_FOUND"

    def test_not_a_video(self, tmp_path):
        txt = tmp_path / "readme.txt"
        txt.write_text("hello")
        result = probe_video(str(txt))
        assert result["code"] == "INVALID_INPUT"

    @patch("video_prober.subprocess.run")
    def test_successful_probe(self, mock_run, tmp_path):
        mp4 = tmp_path / "test.mp4"
        mp4.write_bytes(b"\x00" * 1024)

        ffprobe_output = {
            "format": {
                "duration": "60.5",
                "bit_rate": "5000000",
                "format_name": "mov,mp4,m4a,3gp",
            },
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "24000/1001",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                },
            ],
        }
        mock_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(ffprobe_output)
        )

        result = probe_video(str(mp4))
        assert result["duration_sec"] == 60.5
        assert result["width"] == 1920
        assert result["height"] == 1080
        assert result["video_codec"] == "h264"
        assert result["audio_codec"] == "aac"
        assert result["audio_channels"] == 2
        assert result["fps"] == 23.976
        assert result["bitrate_kbps"] == 5000
        assert result["format_name"] == "mov,mp4,m4a,3gp"
        assert result["filename"] == "test.mp4"

    @patch("video_prober.subprocess.run")
    def test_ffprobe_failure(self, mock_run, tmp_path):
        mp4 = tmp_path / "bad.mp4"
        mp4.write_bytes(b"\x00")
        mock_run.return_value = MagicMock(returncode=1, stderr="Invalid data")
        result = probe_video(str(mp4))
        assert result["code"] == "PROBE_ERROR"

    @patch("video_prober.subprocess.run", side_effect=FileNotFoundError)
    def test_ffprobe_missing(self, mock_run, tmp_path):
        mp4 = tmp_path / "test.mp4"
        mp4.write_bytes(b"\x00")
        result = probe_video(str(mp4))
        assert result["code"] == "FFPROBE_MISSING"

    @patch("video_prober.subprocess.run", side_effect=subprocess.TimeoutExpired("ffprobe", 30))
    def test_ffprobe_timeout(self, mock_run, tmp_path):
        mp4 = tmp_path / "slow.mp4"
        mp4.write_bytes(b"\x00")
        result = probe_video(str(mp4))
        assert result["code"] == "TIMEOUT"

    @patch("video_prober.subprocess.run")
    def test_fps_whole_number(self, mock_run, tmp_path):
        mp4 = tmp_path / "test.mov"
        mp4.write_bytes(b"\x00" * 100)
        ffprobe_output = {
            "format": {"duration": "10"},
            "streams": [{"codec_type": "video", "r_frame_rate": "30/1", "width": 640, "height": 480}],
        }
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(ffprobe_output))
        result = probe_video(str(mp4))
        assert result["fps"] == 30.0

    @patch("video_prober.subprocess.run")
    def test_missing_audio_stream(self, mock_run, tmp_path):
        mp4 = tmp_path / "noaudio.mp4"
        mp4.write_bytes(b"\x00" * 100)
        ffprobe_output = {
            "format": {"duration": "5"},
            "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720, "r_frame_rate": "25/1"}],
        }
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(ffprobe_output))
        result = probe_video(str(mp4))
        assert result["audio_codec"] is None
        assert result["audio_channels"] is None

    def test_video_extensions_set(self):
        assert ".mp4" in VIDEO_EXTENSIONS
        assert ".mov" in VIDEO_EXTENSIONS
        assert ".mkv" in VIDEO_EXTENSIONS
        assert ".txt" not in VIDEO_EXTENSIONS


# ---------------------------------------------------------------------------
# scan_local_dir
# ---------------------------------------------------------------------------

class TestScanLocalDir:
    """Tests for scan_local_dir function."""

    def test_dir_not_found(self, tmp_path):
        result = scan_local_dir(str(tmp_path / "nope"))
        assert result["code"] == "DIR_NOT_FOUND"

    def test_not_a_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        result = scan_local_dir(str(f))
        assert result["code"] == "INVALID_INPUT"

    @patch("video_prober.probe_video")
    def test_scans_video_files(self, mock_probe, tmp_path):
        (tmp_path / "a.mp4").write_bytes(b"\x00")
        (tmp_path / "b.mov").write_bytes(b"\x00")
        (tmp_path / "c.txt").write_text("not a video")

        mock_probe.side_effect = [
            {"filename": "a.mp4", "duration_sec": 10, "file_size_mb": 1.0},
            {"filename": "b.mov", "duration_sec": 20, "file_size_mb": 2.0},
        ]

        result = scan_local_dir(str(tmp_path))
        assert result["total_count"] == 2
        assert result["total_size_mb"] == 3.0
        assert result["total_duration_sec"] == 30.0

    @patch("video_prober.probe_video")
    def test_skips_errored_probes(self, mock_probe, tmp_path):
        (tmp_path / "bad.mp4").write_bytes(b"\x00")
        mock_probe.return_value = {"error": "corrupt", "code": "PROBE_ERROR"}
        result = scan_local_dir(str(tmp_path))
        assert result["total_count"] == 0

    def test_empty_directory(self, tmp_path):
        result = scan_local_dir(str(tmp_path))
        assert result["total_count"] == 0
        assert result["videos"] == []
