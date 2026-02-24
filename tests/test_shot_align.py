"""Tests for shot_align.py -- transcript matching and offset calculation.

All tests use mock word lists. No actual audio files needed.
Does NOT require faster-whisper, librosa, or GPU.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add resolve-tools to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "resolve-tools"))

from shot_align import (
    AlignmentResult,
    WordTiming,
    calculate_offset_from_matches,
    find_longest_common_subsequence,
    TRANSCRIPT_CONFIDENCE_THRESHOLD,
)


# ---------------------------------------------------------------------------
# WordTiming
# ---------------------------------------------------------------------------


class TestWordTiming:
    def test_basic_creation(self):
        w = WordTiming(word="hello", start=1.0, end=1.5)
        assert w.word == "hello"
        assert w.start == 1.0
        assert w.end == 1.5


# ---------------------------------------------------------------------------
# AlignmentResult
# ---------------------------------------------------------------------------


class TestAlignmentResult:
    def test_basic_creation(self):
        r = AlignmentResult(
            file_a="a.mp4",
            file_b="b.mp4",
            offset_seconds=2.5,
            confidence=0.85,
            method="transcript",
            matched_words=100,
        )
        assert r.offset_seconds == 2.5
        assert r.confidence == 0.85
        assert r.method == "transcript"

    def test_error_result(self):
        r = AlignmentResult(
            file_a="a.mp4",
            file_b="b.mp4",
            offset_seconds=0.0,
            confidence=0.0,
            method="audio_fingerprint",
            error="librosa not installed",
        )
        assert r.error is not None


# ---------------------------------------------------------------------------
# Longest common subsequence
# ---------------------------------------------------------------------------


class TestFindLongestCommonSubsequence:
    def _make_words(self, texts: list[str], start_offset: float = 0.0) -> list[WordTiming]:
        """Helper: create WordTimings from a list of strings."""
        words = []
        t = start_offset
        for text in texts:
            words.append(WordTiming(word=text, start=t, end=t + 0.3))
            t += 0.5
        return words

    def test_identical_transcripts(self):
        words = ["the", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog"]
        a = self._make_words(words, start_offset=0.0)
        b = self._make_words(words, start_offset=0.0)
        matches, confidence = find_longest_common_subsequence(a, b)
        assert len(matches) == 9
        assert confidence == 1.0

    def test_offset_transcripts(self):
        """Same words but B starts 5 seconds later in the recording."""
        words = ["hello", "world", "this", "is", "a", "test", "of", "alignment"]
        a = self._make_words(words, start_offset=10.0)
        b = self._make_words(words, start_offset=15.0)
        matches, confidence = find_longest_common_subsequence(a, b)
        assert len(matches) == 8
        assert confidence == 1.0

    def test_partial_overlap(self):
        """A has extra words at start, B has extra words at end."""
        a = self._make_words(["intro", "words", "hello", "world", "test", "data", "here"])
        b = self._make_words(["hello", "world", "test", "data", "here", "outro", "words"])
        matches, confidence = find_longest_common_subsequence(a, b)
        assert len(matches) == 5  # "hello world test data here"
        assert confidence > 0.5

    def test_no_overlap(self):
        a = self._make_words(["alpha", "beta", "gamma", "delta", "epsilon"])
        b = self._make_words(["one", "two", "three", "four", "five"])
        matches, confidence = find_longest_common_subsequence(a, b)
        assert len(matches) == 0
        assert confidence == 0.0

    def test_empty_inputs(self):
        a: list[WordTiming] = []
        b = self._make_words(["hello", "world"])
        matches, confidence = find_longest_common_subsequence(a, b)
        assert len(matches) == 0
        assert confidence == 0.0

    def test_short_match_below_window(self):
        """Match shorter than min_window should not be found."""
        a = self._make_words(["the", "cat", "sat", "on", "mat"])
        b = self._make_words(["a", "dog", "the", "cat", "ran"])
        # Only "the cat" matches (2 words) — below default min_window of 5
        matches, confidence = find_longest_common_subsequence(a, b, min_window=5)
        assert len(matches) == 0

    def test_lower_min_window_catches_short_match(self):
        a = self._make_words(["the", "cat", "sat", "on", "mat"])
        b = self._make_words(["a", "dog", "the", "cat", "sat"])
        matches, confidence = find_longest_common_subsequence(a, b, min_window=3)
        assert len(matches) >= 3


# ---------------------------------------------------------------------------
# Offset calculation
# ---------------------------------------------------------------------------


class TestCalculateOffset:
    def _make_words(self, texts: list[str], start_offset: float = 0.0) -> list[WordTiming]:
        words = []
        t = start_offset
        for text in texts:
            words.append(WordTiming(word=text, start=t, end=t + 0.3))
            t += 0.5
        return words

    def test_zero_offset(self):
        words = ["hello", "world", "test"]
        a = self._make_words(words, start_offset=5.0)
        b = self._make_words(words, start_offset=5.0)
        matches = [(0, 0), (1, 1), (2, 2)]
        offset = calculate_offset_from_matches(a, b, matches)
        assert offset == 0.0

    def test_positive_offset(self):
        """B starts 10 seconds later than A."""
        words = ["hello", "world", "test"]
        a = self._make_words(words, start_offset=5.0)
        b = self._make_words(words, start_offset=15.0)
        matches = [(0, 0), (1, 1), (2, 2)]
        offset = calculate_offset_from_matches(a, b, matches)
        assert abs(offset - 10.0) < 0.001

    def test_negative_offset(self):
        """B starts 3 seconds earlier than A."""
        words = ["hello", "world", "test"]
        a = self._make_words(words, start_offset=10.0)
        b = self._make_words(words, start_offset=7.0)
        matches = [(0, 0), (1, 1), (2, 2)]
        offset = calculate_offset_from_matches(a, b, matches)
        assert abs(offset - (-3.0)) < 0.001

    def test_empty_matches(self):
        a = self._make_words(["hello"])
        b = self._make_words(["world"])
        offset = calculate_offset_from_matches(a, b, [])
        assert offset == 0.0

    def test_self_alignment_zero(self):
        """Aligning a transcript with itself should give offset ~0."""
        words = ["the", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog"]
        a = self._make_words(words, start_offset=0.0)
        b = self._make_words(words, start_offset=0.0)
        matches, _ = find_longest_common_subsequence(a, b)
        offset = calculate_offset_from_matches(a, b, matches)
        assert abs(offset) < 0.001


# ---------------------------------------------------------------------------
# Confidence threshold
# ---------------------------------------------------------------------------


class TestConfidenceThreshold:
    def test_threshold_exists(self):
        assert TRANSCRIPT_CONFIDENCE_THRESHOLD > 0
        assert TRANSCRIPT_CONFIDENCE_THRESHOLD < 1.0

    def test_good_match_exceeds_threshold(self):
        """A perfect match should exceed the fallback threshold."""
        words = ["hello", "world", "this", "is", "a", "test"]
        a = [WordTiming(w, i * 0.5, i * 0.5 + 0.3) for i, w in enumerate(words)]
        b = [WordTiming(w, i * 0.5, i * 0.5 + 0.3) for i, w in enumerate(words)]
        _, confidence = find_longest_common_subsequence(a, b)
        assert confidence >= TRANSCRIPT_CONFIDENCE_THRESHOLD
