"""Tests for model comparison benchmark — mocked, no GPU required."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))

from model_comparison import compute_word_overlap


# ---------------------------------------------------------------------------
# compute_word_overlap
# ---------------------------------------------------------------------------

class TestWordOverlap:

    def test_identical_texts(self):
        assert compute_word_overlap("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert compute_word_overlap("hello world", "foo bar") == 0.0

    def test_partial_overlap(self):
        result = compute_word_overlap("hello world foo", "hello world bar")
        # intersection = {hello, world}, union = {hello, world, foo, bar}
        assert abs(result - 0.5) < 0.01

    def test_both_empty(self):
        assert compute_word_overlap("", "") == 1.0

    def test_one_empty(self):
        assert compute_word_overlap("hello", "") == 0.0
        assert compute_word_overlap("", "hello") == 0.0

    def test_case_insensitive(self):
        assert compute_word_overlap("Hello World", "hello world") == 1.0

    def test_strips_punctuation(self):
        result = compute_word_overlap("Hello, world!", "hello world")
        assert result == 1.0

    def test_numbers_ignored(self):
        # regex [a-zA-Z]+ only captures letters
        result = compute_word_overlap("hello 123", "hello 456")
        assert result == 1.0

    def test_subset_text(self):
        result = compute_word_overlap("hello world extra", "hello world")
        # intersection = 2, union = 3
        assert abs(result - 2/3) < 0.01

    def test_large_overlap(self):
        text = "the quick brown fox jumps over the lazy dog"
        variant = "the quick brown cat jumps over the lazy dog"
        result = compute_word_overlap(text, variant)
        # Jaccard: 7 shared / 9 unique = 0.778
        assert result > 0.7
