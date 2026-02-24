"""Tests for clip timing edge cases — re-zeroing math, word extraction, boundaries."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from subtitle_gen import (
    break_into_lines,
    re_zero_timestamps,
    seconds_to_ass_time,
)


class TestExtractClipWords:
    """Test word extraction from known transcripts."""

    def test_basic_word_list(self):
        words = [
            {"word": "Hello", "start": 10.0, "end": 10.5},
            {"word": "world", "start": 10.5, "end": 11.0},
        ]
        zeroed = re_zero_timestamps(words, clip_start=10.0)
        assert zeroed[0]["word"] == "Hello"
        assert zeroed[0]["start"] == 0.0
        assert zeroed[1]["word"] == "world"
        assert abs(zeroed[1]["start"] - 0.5) < 0.001

    def test_preserves_word_text(self):
        words = [
            {"word": "Special-chars!", "start": 5.0, "end": 5.5},
            {"word": "123", "start": 5.5, "end": 6.0},
        ]
        zeroed = re_zero_timestamps(words, clip_start=5.0)
        assert zeroed[0]["word"] == "Special-chars!"
        assert zeroed[1]["word"] == "123"


class TestReZeroingEdgeCases:
    def test_clip_boundary_exact(self):
        """Word starts exactly at clip boundary."""
        words = [{"word": "exact", "start": 100.0, "end": 100.5}]
        zeroed = re_zero_timestamps(words, clip_start=100.0)
        assert zeroed[0]["start"] == 0.0
        assert abs(zeroed[0]["end"] - 0.5) < 0.001

    def test_mid_word_split(self):
        """Word starts before clip start (partial word)."""
        words = [{"word": "partial", "start": 9.5, "end": 10.5}]
        zeroed = re_zero_timestamps(words, clip_start=10.0)
        # Start clamps to 0.0, end is 0.5
        assert zeroed[0]["start"] == 0.0
        assert abs(zeroed[0]["end"] - 0.5) < 0.001

    def test_large_offset(self):
        """Clip is deep into the source file."""
        words = [
            {"word": "deep", "start": 3600.5, "end": 3601.0},
        ]
        zeroed = re_zero_timestamps(words, clip_start=3600.0)
        assert abs(zeroed[0]["start"] - 0.5) < 0.001
        assert abs(zeroed[0]["end"] - 1.0) < 0.001

    def test_zero_clip_start_is_noop(self):
        """clip_start=0 should leave timestamps unchanged."""
        words = [
            {"word": "unchanged", "start": 5.0, "end": 5.5},
        ]
        zeroed = re_zero_timestamps(words, clip_start=0.0)
        assert zeroed[0]["start"] == 5.0
        assert zeroed[0]["end"] == 5.5

    def test_millisecond_precision(self):
        """Verify sub-second precision is preserved."""
        words = [{"word": "precise", "start": 10.123, "end": 10.456}]
        zeroed = re_zero_timestamps(words, clip_start=10.0)
        assert abs(zeroed[0]["start"] - 0.123) < 0.001
        assert abs(zeroed[0]["end"] - 0.456) < 0.001

    def test_ass_time_conversion_after_rezero(self):
        """Full pipeline: re-zero then convert to ASS milliseconds."""
        words = [{"word": "test", "start": 47.3, "end": 47.8}]
        zeroed = re_zero_timestamps(words, clip_start=45.0)
        start_ms = seconds_to_ass_time(zeroed[0]["start"])
        end_ms = seconds_to_ass_time(zeroed[0]["end"])
        assert start_ms == 2300
        assert end_ms == 2800


class TestEmptyWordList:
    def test_empty_words_rezero(self):
        result = re_zero_timestamps([], clip_start=10.0)
        assert result == []

    def test_empty_words_line_break(self):
        result = break_into_lines([], max_chars=42)
        assert result == []

    def test_single_word(self):
        words = [{"word": "alone", "start": 0.0, "end": 0.5}]
        lines = break_into_lines(words, max_chars=42)
        assert len(lines) == 1
        assert len(lines[0]) == 1
