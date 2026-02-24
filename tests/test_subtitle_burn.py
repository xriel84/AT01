"""Tests for subtitle_burn.py — all offline, no GPU, no media files."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from subtitle_burn import (
    PLATFORM_RESOLUTION,
    ass_path_for_ffmpeg,
    build_ffmpeg_cmd,
    build_output_path,
    burn_subtitle,
)


class TestForwardSlashPaths:
    def test_backslashes_converted(self):
        result = ass_path_for_ffmpeg(Path("C:\\Users\\test\\subs\\clip_tiktok.ass"))
        assert "\\" not in result
        assert "/" in result

    def test_forward_slashes_unchanged(self):
        result = ass_path_for_ffmpeg(Path("C:/Users/test/subs/clip.ass"))
        assert "\\" not in result

    def test_ffmpeg_cmd_has_forward_slashes(self):
        cmd = build_ffmpeg_cmd(
            Path("C:\\in\\clip.mp4"),
            Path("C:\\subs\\clip_tiktok.ass"),
            Path("C:\\out\\clip.mp4"),
        )
        # Find the -vf arg
        vf_idx = cmd.index("-vf")
        vf_val = cmd[vf_idx + 1]
        assert "\\" not in vf_val, f"FFmpeg -vf must use forward slashes: {vf_val}"
        assert vf_val.startswith("ass=")


class TestFFmpegCodecFlags:
    def test_h264_nvenc_present(self):
        cmd = build_ffmpeg_cmd(Path("in.mp4"), Path("sub.ass"), Path("out.mp4"))
        assert "-c:v" in cmd
        idx = cmd.index("-c:v")
        assert cmd[idx + 1] == "h264_nvenc"

    def test_preset_p4(self):
        cmd = build_ffmpeg_cmd(Path("in.mp4"), Path("sub.ass"), Path("out.mp4"))
        assert "-preset" in cmd
        assert cmd[cmd.index("-preset") + 1] == "p4"

    def test_cq_18(self):
        cmd = build_ffmpeg_cmd(Path("in.mp4"), Path("sub.ass"), Path("out.mp4"))
        assert "-cq" in cmd
        assert cmd[cmd.index("-cq") + 1] == "18"

    def test_fps_30(self):
        cmd = build_ffmpeg_cmd(Path("in.mp4"), Path("sub.ass"), Path("out.mp4"))
        assert "-r" in cmd
        assert cmd[cmd.index("-r") + 1] == "30"

    def test_pix_fmt(self):
        cmd = build_ffmpeg_cmd(Path("in.mp4"), Path("sub.ass"), Path("out.mp4"))
        assert "-pix_fmt" in cmd
        assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"

    def test_audio_codec(self):
        cmd = build_ffmpeg_cmd(Path("in.mp4"), Path("sub.ass"), Path("out.mp4"))
        assert "-c:a" in cmd
        assert cmd[cmd.index("-c:a") + 1] == "aac"
        assert "-b:a" in cmd
        assert cmd[cmd.index("-b:a") + 1] == "192k"
        assert "-ar" in cmd
        assert cmd[cmd.index("-ar") + 1] == "48000"

    def test_faststart(self):
        cmd = build_ffmpeg_cmd(Path("in.mp4"), Path("sub.ass"), Path("out.mp4"))
        assert "-movflags" in cmd
        assert cmd[cmd.index("-movflags") + 1] == "+faststart"

    def test_overwrite_flag(self):
        cmd = build_ffmpeg_cmd(Path("in.mp4"), Path("sub.ass"), Path("out.mp4"))
        assert "-y" in cmd

    def test_vbr_rc(self):
        cmd = build_ffmpeg_cmd(Path("in.mp4"), Path("sub.ass"), Path("out.mp4"))
        assert "-rc" in cmd
        assert cmd[cmd.index("-rc") + 1] == "vbr"


class TestOutputPathConstruction:
    def test_basic_output_path(self):
        result = build_output_path(Path("clips/my_clip.mp4"), "tiktok", Path("output"))
        assert result == Path("output/my_clip_tiktok_subtitled.mp4")

    def test_youtube_output_path(self):
        result = build_output_path(Path("c.mp4"), "youtube", Path("out"))
        assert result == Path("out/c_youtube_subtitled.mp4")


class TestBurnSubtitleMocked:
    @patch("subtitle_burn.probe_output")
    @patch("subtitle_burn.subprocess.run")
    def test_successful_burn(self, mock_run, mock_probe):
        mock_run.return_value = MagicMock(returncode=0)
        mock_probe.return_value = {
            "width": 1080, "height": 1920, "codec": "h264", "fps": 30.0, "duration": 15.0,
        }

        result = burn_subtitle(Path("in.mp4"), Path("sub.ass"), Path("out.mp4"))
        assert result["status"] == "ok"
        assert result["probe"]["width"] == 1080
        assert result["probe"]["codec"] == "h264"
        mock_run.assert_called_once()

    @patch("subtitle_burn.subprocess.run")
    def test_failed_burn(self, mock_run):
        import subprocess as sp
        mock_run.side_effect = sp.CalledProcessError(1, "ffmpeg")

        result = burn_subtitle(Path("in.mp4"), Path("sub.ass"), Path("out.mp4"))
        assert result["status"] == "failed"
        assert result["probe"] is None

    @patch("subtitle_burn.probe_output")
    @patch("subtitle_burn.subprocess.run")
    def test_exact_ffmpeg_command(self, mock_run, mock_probe):
        mock_run.return_value = MagicMock(returncode=0)
        mock_probe.return_value = None

        burn_subtitle(
            Path("C:/clips/test.mp4"),
            Path("C:/subs/test_tiktok.ass"),
            Path("C:/out/test.mp4"),
        )

        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "ffmpeg"
        assert "-y" in call_args
        assert "h264_nvenc" in call_args
        # Verify ASS path uses forward slashes
        vf_idx = call_args.index("-vf")
        assert "\\" not in call_args[vf_idx + 1]


class TestPlatformResolutions:
    def test_all_platforms_present(self):
        for p in ("tiktok", "reels", "shorts", "youtube", "linkedin"):
            assert p in PLATFORM_RESOLUTION

    def test_tiktok_resolution(self):
        assert PLATFORM_RESOLUTION["tiktok"] == {"w": 1080, "h": 1920}

    def test_youtube_resolution(self):
        assert PLATFORM_RESOLUTION["youtube"] == {"w": 1920, "h": 1080}
