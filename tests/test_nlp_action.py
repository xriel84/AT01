"""Tests for nlp_action.py — pure-Python NLP keyword parser.

No external dependencies, no mocks, no subprocess.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from nlp_action import parse_command


# ---------------------------------------------------------------------------
# 13 required test cases (parametrized)
# ---------------------------------------------------------------------------

class TestParseCommand:
    """Core parse_command behaviour — 13 spec'd inputs."""

    def test_remove_silence(self):
        r = parse_command("remove silence")
        assert r["action"] == "silence_remove"
        assert r["confidence"] >= 0.9

    def test_cut_the_silence(self):
        r = parse_command("cut the silence out")
        assert r["action"] == "silence_remove"

    def test_make_tiktok(self):
        r = parse_command("make a 60 second tiktok")
        assert r["action"] == "platform_export"
        assert r["params"]["platform"] == "tiktok"
        assert r["params"]["max_duration"] == 60

    def test_make_short(self):
        r = parse_command("make a short")
        assert r["action"] == "platform_export"
        assert r["params"]["platform"] == "youtube_shorts"

    def test_make_instagram_reel(self):
        r = parse_command("make me an instagram reel")
        assert r["action"] == "platform_export"
        assert r["params"]["platform"] == "ig_reels"

    def test_trim_30s(self):
        r = parse_command("trim to 30s")
        assert r["action"] == "trim"
        assert r["params"]["max_duration"] == 30

    def test_add_captions(self):
        r = parse_command("add captions")
        assert r["action"] == "caption_burn"

    def test_crop_vertical(self):
        r = parse_command("crop vertical")
        assert r["action"] == "crop"
        assert r["params"]["aspect"] == "9:16"

    def test_crop_square(self):
        r = parse_command("crop square")
        assert r["action"] == "crop"
        assert r["params"]["aspect"] == "1:1"

    def test_export_for_youtube(self):
        r = parse_command("export for youtube")
        assert r["action"] == "platform_export"
        assert r["params"]["platform"] == "youtube_long"

    def test_transcribe(self):
        r = parse_command("transcribe this video")
        assert r["action"] == "transcribe"

    def test_unknown_command(self):
        r = parse_command("do something weird")
        assert r["action"] == "unknown"
        assert r["confidence"] <= 0.4

    def test_90_second_reel(self):
        r = parse_command("make a 90 second reel for instagram")
        assert r["action"] == "platform_export"
        assert r["params"]["platform"] == "ig_reels"
        assert r["params"]["max_duration"] == 90


# ---------------------------------------------------------------------------
# Additional coverage
# ---------------------------------------------------------------------------

class TestReturnSchema:
    """Every result must contain the full schema keys."""

    REQUIRED_TOP = {"action", "params", "executor", "confidence"}
    REQUIRED_PARAMS = {
        "input", "output", "platform", "max_duration",
        "aspect", "silence_threshold_db", "caption_style",
    }

    @pytest.mark.parametrize("text", [
        "remove silence",
        "make a short",
        "do something weird",
        "transcribe",
    ])
    def test_schema_keys_present(self, text: str):
        r = parse_command(text)
        assert self.REQUIRED_TOP <= r.keys()
        assert self.REQUIRED_PARAMS <= r["params"].keys()


class TestInputOutputPassthrough:
    """input_path and output_dir are forwarded into params."""

    def test_paths_forwarded(self):
        r = parse_command(
            "trim to 10s",
            input_path="/tmp/clip.mp4",
            output_dir="/tmp/out",
        )
        assert r["params"]["input"] == "/tmp/clip.mp4"
        assert r["params"]["output"] == "/tmp/out"

    def test_paths_default_none(self):
        r = parse_command("trim to 10s")
        assert r["params"]["input"] is None
        assert r["params"]["output"] is None


class TestExecutorSelection:
    """Default executor is ffmpeg; resolve actions get 'resolve'."""

    def test_ffmpeg_default(self):
        r = parse_command("remove silence")
        assert r["executor"] == "ffmpeg"

    def test_transcribe_uses_ffmpeg(self):
        r = parse_command("transcribe")
        assert r["executor"] == "ffmpeg"


class TestDefaults:
    """Constant defaults are always present."""

    def test_silence_threshold(self):
        r = parse_command("remove silence")
        assert r["params"]["silence_threshold_db"] == -50

    def test_caption_style(self):
        r = parse_command("add captions")
        assert r["params"]["caption_style"] == "default"


class TestDurationOverride:
    """Duration extraction applies after the action match."""

    def test_minutes_duration(self):
        r = parse_command("make a 2min tiktok")
        assert r["params"]["max_duration"] == 120

    def test_seconds_override(self):
        r = parse_command("make a 45sec tiktok")
        assert r["params"]["max_duration"] == 45


class TestPlatformAspectDefaults:
    """Platform-matched exports carry the right aspect ratio."""

    @pytest.mark.parametrize("text,expected_aspect", [
        ("make a tiktok", "9:16"),
        ("make a short", "9:16"),
        ("make a reel", "9:16"),
        ("export for youtube", "16:9"),
    ])
    def test_aspect_by_platform(self, text: str, expected_aspect: str):
        r = parse_command(text)
        assert r["params"]["aspect"] == expected_aspect
