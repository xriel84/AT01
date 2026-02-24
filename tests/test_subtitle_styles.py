"""Tests for subtitle style presets — validates ASS output for all 5 platforms."""

import sys
import tempfile
from pathlib import Path

import pysubs2
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from subtitle_gen import (
    PLATFORM_PLAYRES,
    PLATFORM_STYLES,
    generate_ass,
)


MOCK_WORDS = [
    {"word": "Test", "start": 0.0, "end": 0.5},
    {"word": "subtitle", "start": 0.5, "end": 1.0},
    {"word": "output", "start": 1.0, "end": 1.5},
]


class TestAllPlatformsProduceValidASS:
    @pytest.mark.parametrize("platform", list(PLATFORM_PLAYRES.keys()))
    def test_generates_valid_ass(self, platform):
        subs = generate_ass(MOCK_WORDS, platform)
        assert isinstance(subs, pysubs2.SSAFile)
        assert len(subs.events) >= 1
        assert "Default" in subs.styles

    @pytest.mark.parametrize("platform", list(PLATFORM_PLAYRES.keys()))
    def test_saves_and_reloads(self, platform):
        subs = generate_ass(MOCK_WORDS, platform)
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w") as f:
            subs.save(f.name)
            reloaded = pysubs2.load(f.name)
        assert len(reloaded.events) == len(subs.events)


class TestASSColorFormat:
    """ASS colors use &HAABBGGRR format, not RGB."""

    @pytest.mark.parametrize("platform", list(PLATFORM_STYLES.keys()))
    def test_primary_color_format(self, platform):
        color_str = PLATFORM_STYLES[platform]["primarycolor"]
        assert color_str.startswith("&H"), f"{platform} primarycolor must start with &H"
        assert len(color_str) == 10, f"{platform} primarycolor must be 10 chars (&HAABBGGRR)"

    @pytest.mark.parametrize("platform", list(PLATFORM_STYLES.keys()))
    def test_outline_color_format(self, platform):
        color_str = PLATFORM_STYLES[platform]["outlinecolor"]
        assert color_str.startswith("&H")
        assert len(color_str) == 10

    @pytest.mark.parametrize("platform", list(PLATFORM_STYLES.keys()))
    def test_back_color_format(self, platform):
        color_str = PLATFORM_STYLES[platform]["backcolor"]
        assert color_str.startswith("&H")
        assert len(color_str) == 10


class TestAlignment:
    """All platforms use alignment 2 (bottom-center)."""

    @pytest.mark.parametrize("platform", list(PLATFORM_STYLES.keys()))
    def test_alignment_is_2(self, platform):
        assert PLATFORM_STYLES[platform]["alignment"] == 2

    @pytest.mark.parametrize("platform", list(PLATFORM_STYLES.keys()))
    def test_style_alignment_in_ass(self, platform):
        subs = generate_ass(MOCK_WORDS, platform)
        style = subs.styles["Default"]
        assert style.alignment == 2


class TestMarginV:
    def test_tiktok_marginv(self):
        assert PLATFORM_STYLES["tiktok"]["marginv"] == 120

    def test_reels_marginv(self):
        assert PLATFORM_STYLES["reels"]["marginv"] == 120

    def test_shorts_marginv(self):
        assert PLATFORM_STYLES["shorts"]["marginv"] == 120

    def test_youtube_marginv(self):
        assert PLATFORM_STYLES["youtube"]["marginv"] == 50

    def test_linkedin_marginv(self):
        assert PLATFORM_STYLES["linkedin"]["marginv"] == 80

    @pytest.mark.parametrize("platform", list(PLATFORM_STYLES.keys()))
    def test_marginv_applied_to_style(self, platform):
        subs = generate_ass(MOCK_WORDS, platform)
        style = subs.styles["Default"]
        assert style.marginv == PLATFORM_STYLES[platform]["marginv"]
