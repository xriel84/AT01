"""Tests for footage_match.py -- filename parsing and grouping logic.

All tests use mock filenames. No actual video files needed.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# Add resolve-tools to path so we can import footage_match
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "resolve-tools"))

from footage_match import (
    group_by_pattern,
    group_by_proximity,
    match_footage,
    parse_camera_prefix,
    parse_custom_label,
    parse_filename,
    parse_obs_default,
    parse_take_numbering,
)


# ---------------------------------------------------------------------------
# Pattern parsers
# ---------------------------------------------------------------------------


class TestParseOBSDefault:
    def test_basic_obs_filename(self):
        result = parse_obs_default("2023-12-08 18-45-03.mp4")
        assert result is not None
        assert result["pattern"] == "obs_default"
        assert result["datetime"] == datetime(2023, 12, 8, 18, 45, 3)
        assert result["camera"] == "CAM1"

    def test_obs_with_camera_suffix(self):
        result = parse_obs_default("2023-12-08 18-45-03_CAM2.mp4")
        assert result is not None
        assert result["camera"] == "CAM2"

    def test_obs_groups_same_timestamp(self):
        r1 = parse_obs_default("2023-12-08 18-45-03.mp4")
        r2 = parse_obs_default("2023-12-08 18-45-03_CAM2.mp4")
        assert r1["session_key"] == r2["session_key"]

    def test_non_obs_returns_none(self):
        assert parse_obs_default("workshop_take01.mp4") is None


class TestParseCameraPrefix:
    def test_basic_camera_prefix(self):
        result = parse_camera_prefix("CAM1_2023-12-08_session1.mp4")
        assert result is not None
        assert result["pattern"] == "camera_prefix"
        assert result["camera"] == "CAM1"
        assert result["session_key"] == "session1_2023-12-08"

    def test_case_insensitive(self):
        result = parse_camera_prefix("cam2_2023-12-08_keynote.mp4")
        assert result is not None
        assert result["camera"] == "CAM2"

    def test_non_camera_returns_none(self):
        assert parse_camera_prefix("2023-12-08 18-45-03.mp4") is None


class TestParseTakeNumbering:
    def test_basic_take(self):
        result = parse_take_numbering("workshop_take01.mp4")
        assert result is not None
        assert result["pattern"] == "take_numbering"
        assert result["session_key"] == "workshop_takes"
        assert result["camera"] == "take01"

    def test_takes_group_together(self):
        r1 = parse_take_numbering("workshop_take01.mp4")
        r2 = parse_take_numbering("workshop_take02.mp4")
        assert r1["session_key"] == r2["session_key"]

    def test_different_labels_separate(self):
        r1 = parse_take_numbering("workshop_take01.mp4")
        r2 = parse_take_numbering("lecture_take01.mp4")
        assert r1["session_key"] != r2["session_key"]

    def test_non_take_returns_none(self):
        assert parse_take_numbering("2023-12-08 18-45-03.mp4") is None


class TestParseCustomLabel:
    def test_underscore_label(self):
        result = parse_custom_label("siggraph_talk_full.mp4")
        assert result is not None
        assert result["pattern"] == "custom_label"
        assert result["session_key"] == "siggraph_talk_full"

    def test_no_underscore_returns_none(self):
        assert parse_custom_label("singlevideo.mp4") is None

    def test_date_prefix_returns_none(self):
        # OBS-style should be caught by obs parser, not custom label
        assert parse_custom_label("2023-12-08 18-45-03.mp4") is None


class TestParseFilename:
    def test_obs_priority(self):
        result = parse_filename("2023-12-08 18-45-03.mp4")
        assert result["pattern"] == "obs_default"

    def test_camera_prefix(self):
        result = parse_filename("CAM1_2023-12-08_session1.mp4")
        assert result["pattern"] == "camera_prefix"

    def test_take_numbering(self):
        result = parse_filename("workshop_take01.mp4")
        assert result["pattern"] == "take_numbering"

    def test_custom_label(self):
        result = parse_filename("siggraph_talk_full.mp4")
        assert result["pattern"] == "custom_label"

    def test_unrecognized_returns_none(self):
        assert parse_filename("singlevideo.mp4") is None


# ---------------------------------------------------------------------------
# Grouping logic
# ---------------------------------------------------------------------------


class TestGroupByPattern:
    def test_groups_obs_files(self):
        files = [
            {"filename": "2023-12-08 18-45-03.mp4", "path": "/a", "creation_time": datetime.now()},
            {"filename": "2023-12-08 18-45-03_CAM2.mp4", "path": "/b", "creation_time": datetime.now()},
        ]
        groups, unmatched = group_by_pattern(files)
        assert len(groups) == 1
        assert len(unmatched) == 0
        key = list(groups.keys())[0]
        assert len(groups[key]) == 2

    def test_groups_takes_together(self):
        files = [
            {"filename": "workshop_take01.mp4", "path": "/a", "creation_time": datetime.now()},
            {"filename": "workshop_take02.mp4", "path": "/b", "creation_time": datetime.now()},
        ]
        groups, unmatched = group_by_pattern(files)
        assert len(groups) == 1
        assert len(unmatched) == 0

    def test_separates_different_sessions(self):
        files = [
            {"filename": "2023-12-08 18-45-03.mp4", "path": "/a", "creation_time": datetime.now()},
            {"filename": "workshop_take01.mp4", "path": "/b", "creation_time": datetime.now()},
        ]
        groups, unmatched = group_by_pattern(files)
        assert len(groups) == 2
        assert len(unmatched) == 0

    def test_unmatched_files(self):
        files = [
            {"filename": "randomfile.mp4", "path": "/a", "creation_time": datetime.now()},
        ]
        groups, unmatched = group_by_pattern(files)
        assert len(groups) == 0
        assert len(unmatched) == 1


class TestGroupByProximity:
    def test_groups_close_files(self):
        now = datetime.now()
        files = [
            {"filename": "a.mp4", "path": "/a", "creation_time": now},
            {"filename": "b.mp4", "path": "/b", "creation_time": now + timedelta(minutes=2)},
        ]
        groups = group_by_proximity(files, threshold_minutes=5)
        assert len(groups) == 1

    def test_separates_distant_files(self):
        now = datetime.now()
        files = [
            {"filename": "a.mp4", "path": "/a", "creation_time": now},
            {"filename": "b.mp4", "path": "/b", "creation_time": now + timedelta(minutes=30)},
        ]
        groups = group_by_proximity(files, threshold_minutes=5)
        assert len(groups) == 2

    def test_empty_input(self):
        groups = group_by_proximity([], threshold_minutes=5)
        assert len(groups) == 0

    def test_single_file(self):
        files = [{"filename": "a.mp4", "path": "/a", "creation_time": datetime.now()}]
        groups = group_by_proximity(files, threshold_minutes=5)
        assert len(groups) == 1


# ---------------------------------------------------------------------------
# Integration: match_footage
# ---------------------------------------------------------------------------


class TestMatchFootage:
    def test_with_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create empty video files with recognizable names
            for name in [
                "2023-12-08 18-45-03.mp4",
                "2023-12-08 18-45-03_CAM2.mp4",
                "workshop_take01.mp4",
                "workshop_take02.mp4",
                "siggraph_talk_full.mp4",
            ]:
                Path(tmpdir, name).touch()

            result = match_footage(tmpdir)
            assert result["total_files"] == 5
            assert result["group_count"] >= 3  # OBS group, takes group, custom label

    def test_nonexistent_dir(self):
        result = match_footage("/nonexistent/path/12345")
        assert result["total_files"] == 0
        assert result["groups"] == {}

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = match_footage(tmpdir)
            assert result["total_files"] == 0

    def test_non_video_files_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "readme.txt").touch()
            Path(tmpdir, "photo.jpg").touch()
            Path(tmpdir, "actual_video.mp4").touch()
            result = match_footage(tmpdir)
            assert result["total_files"] == 1
