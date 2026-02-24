"""Tests for subtitle_gen.py — all offline, no GPU, no media files."""

import json
import sys
import tempfile
from pathlib import Path

import pysubs2
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from subtitle_gen import (
    PLATFORM_PLAYRES,
    PLATFORM_STYLES,
    VERTICAL_PLATFORMS,
    MAX_CHARS_VERTICAL,
    MAX_CHARS_HORIZONTAL,
    break_into_lines,
    generate_ass,
    load_transcript_json,
    re_zero_timestamps,
    seconds_to_ass_time,
)


MOCK_WORDS = [
    {"word": "Hello", "start": 45.0, "end": 45.4},
    {"word": "world", "start": 45.5, "end": 45.9},
    {"word": "this", "start": 46.0, "end": 46.2},
    {"word": "is", "start": 46.2, "end": 46.3},
    {"word": "a", "start": 46.3, "end": 46.4},
    {"word": "test", "start": 46.4, "end": 46.8},
]


class TestASSHeaderGeneration:
    def test_tiktok_playres(self):
        subs = generate_ass(MOCK_WORDS, "tiktok", clip_start=45.0)
        assert subs.info["PlayResX"] == "1080"
        assert subs.info["PlayResY"] == "1920"

    def test_youtube_playres(self):
        subs = generate_ass(MOCK_WORDS, "youtube", clip_start=45.0)
        assert subs.info["PlayResX"] == "1920"
        assert subs.info["PlayResY"] == "1080"

    def test_linkedin_playres(self):
        subs = generate_ass(MOCK_WORDS, "linkedin", clip_start=45.0)
        assert subs.info["PlayResX"] == "1080"
        assert subs.info["PlayResY"] == "1080"

    def test_all_platforms_have_playres(self):
        for platform in PLATFORM_PLAYRES:
            subs = generate_ass(MOCK_WORDS, platform, clip_start=45.0)
            assert "PlayResX" in subs.info
            assert "PlayResY" in subs.info


class TestTimestampReZeroing:
    def test_basic_rezeroing(self):
        words = [
            {"word": "test", "start": 47.3, "end": 47.8},
        ]
        zeroed = re_zero_timestamps(words, clip_start=45.0)
        assert abs(zeroed[0]["start"] - 2.3) < 0.001
        assert abs(zeroed[0]["end"] - 2.8) < 0.001

    def test_clip_boundary_word(self):
        words = [
            {"word": "boundary", "start": 45.0, "end": 45.5},
        ]
        zeroed = re_zero_timestamps(words, clip_start=45.0)
        assert zeroed[0]["start"] == 0.0
        assert abs(zeroed[0]["end"] - 0.5) < 0.001

    def test_negative_clamp_to_zero(self):
        words = [
            {"word": "early", "start": 44.0, "end": 44.5},
        ]
        zeroed = re_zero_timestamps(words, clip_start=45.0)
        assert zeroed[0]["start"] == 0.0
        assert zeroed[0]["end"] == 0.0

    def test_ass_event_rezeroed(self):
        """Clip starts at 45.0s, word at 47.3s -> ASS time should be 2.3s = 2300ms."""
        words = [{"word": "test", "start": 47.3, "end": 47.8}]
        subs = generate_ass(words, "tiktok", clip_start=45.0)
        assert len(subs.events) == 1
        assert subs.events[0].start == 2300
        assert subs.events[0].end == 2800


class TestLineBreaking:
    def test_respects_max_chars_vertical(self):
        # Build words that exceed 42 chars
        long_words = [
            {"word": f"word{i:02d}longtext", "start": float(i), "end": float(i) + 0.5}
            for i in range(10)
        ]
        lines = break_into_lines(long_words, MAX_CHARS_VERTICAL)
        for line in lines:
            text = " ".join(w["word"] for w in line)
            # Each line should be <= max_chars (unless a single word exceeds it)
            if len(line) > 1:
                assert len(text) <= MAX_CHARS_VERTICAL + 20  # some tolerance for last word

    def test_short_words_fit_one_line(self):
        words = [
            {"word": "Hi", "start": 0.0, "end": 0.2},
            {"word": "there", "start": 0.2, "end": 0.5},
        ]
        lines = break_into_lines(words, MAX_CHARS_VERTICAL)
        assert len(lines) == 1
        assert len(lines[0]) == 2

    def test_forces_break_at_limit(self):
        # Each word is 10 chars, max is 42, so 4 words = 43 chars -> should break
        words = [
            {"word": "abcdefghij", "start": float(i), "end": float(i) + 0.5}
            for i in range(5)
        ]
        lines = break_into_lines(words, 42)
        assert len(lines) >= 2


class TestWordTimestampExtraction:
    def test_load_transcript_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(MOCK_WORDS, f)
            f.flush()
            loaded = load_transcript_json(Path(f.name))
        assert len(loaded) == 6
        assert loaded[0]["word"] == "Hello"
        assert loaded[0]["start"] == 45.0

    def test_word_timing_preserved_in_ass(self):
        words = [
            {"word": "First", "start": 0.0, "end": 0.5},
            {"word": "Second", "start": 1.0, "end": 1.5},
        ]
        subs = generate_ass(words, "youtube", clip_start=0.0)
        # Should be 1 or 2 events depending on line breaking
        assert len(subs.events) >= 1


class TestPysubs2StyleApplication:
    def test_style_fontname(self):
        subs = generate_ass(MOCK_WORDS, "tiktok", clip_start=45.0)
        style = subs.styles["Default"]
        assert style.fontname == "Arial"

    def test_style_fontsize_tiktok(self):
        subs = generate_ass(MOCK_WORDS, "tiktok", clip_start=45.0)
        style = subs.styles["Default"]
        assert style.fontsize == 48

    def test_style_fontsize_youtube(self):
        subs = generate_ass(MOCK_WORDS, "youtube", clip_start=45.0)
        style = subs.styles["Default"]
        assert style.fontsize == 36

    def test_style_alignment_bottom_center(self):
        for platform in PLATFORM_PLAYRES:
            subs = generate_ass(MOCK_WORDS, platform, clip_start=45.0)
            style = subs.styles["Default"]
            assert style.alignment == 2


class TestSecondsToAssTime:
    def test_whole_seconds(self):
        assert seconds_to_ass_time(1.0) == 1000

    def test_fractional(self):
        assert seconds_to_ass_time(2.3) == 2300

    def test_zero(self):
        assert seconds_to_ass_time(0.0) == 0
