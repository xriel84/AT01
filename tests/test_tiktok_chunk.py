"""Tests for tiktok_chunk.py -- all offline, portrait_crop is mocked."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from tiktok_chunk import (
    generate_tiktok_chunks,
    _build_chunk_lookup,
    _split_chapter_at_chunk_boundaries,
    _split_chapter_by_time,
    _output_filename,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def _make_chunk(cid: int, start: float | None = None, end: float | None = None) -> dict:
    """Build a minimal chunk dict for testing."""
    if start is None:
        start = cid * 10.0
    if end is None:
        end = start + 10.0
    return {
        "id": cid,
        "start": start,
        "end": end,
        "text": f"chunk {cid}",
        "word_count": 2,
        "silence_ratio": 0.1,
        "has_speech": True,
    }


def _make_chunks(n: int) -> list[dict]:
    """Create n sequential 10-second chunks."""
    return [_make_chunk(i) for i in range(n)]


def _make_chapter(
    chapter_id: int,
    start: float,
    end: float,
    chunk_ids: list[int] | None = None,
    title: str = "Test chapter",
) -> dict:
    """Build a chapter dict matching chapter_detect output."""
    return {
        "chapter_id": chapter_id,
        "start": start,
        "end": end,
        "duration": round(end - start, 6),
        "chunk_ids": chunk_ids or [],
        "title": title,
    }


def _mock_portrait_crop_success(
    input_path: str,
    output_dir: str = "output",
    method: str = "center",
    start: float | None = None,
    end: float | None = None,
) -> dict:
    """Mock portrait_crop that always succeeds.

    Creates a fake output file and returns a success dict.
    """
    in_path = Path(input_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{in_path.stem}_portrait{in_path.suffix}"
    out_path.write_text("fake portrait output")

    return {
        "status": "success",
        "action": "portrait_crop",
        "input": str(in_path),
        "output": str(out_path),
        "method": method,
        "duration_in": 120.0,
        "duration_out": (end - start) if start is not None and end is not None else 120.0,
        "crop_filter": "crop=ih*9/16:ih",
        "ffmpeg_cmd": "ffmpeg ...",
        "elapsed_seconds": 0.5,
        "error": None,
    }


def _mock_portrait_crop_error(
    input_path: str,
    output_dir: str = "output",
    method: str = "center",
    start: float | None = None,
    end: float | None = None,
) -> dict:
    """Mock portrait_crop that always fails."""
    return {
        "status": "error",
        "action": "portrait_crop",
        "input": input_path,
        "output": None,
        "method": method,
        "duration_in": None,
        "duration_out": None,
        "crop_filter": None,
        "ffmpeg_cmd": None,
        "elapsed_seconds": 0.1,
        "error": "ffmpeg not found",
    }


# Track calls for selective failure mock.
_call_counter = 0


def _mock_portrait_crop_selective_fail(
    input_path: str,
    output_dir: str = "output",
    method: str = "center",
    start: float | None = None,
    end: float | None = None,
) -> dict:
    """Mock portrait_crop that fails on the second call only."""
    global _call_counter
    _call_counter += 1
    if _call_counter == 2:
        return _mock_portrait_crop_error(input_path, output_dir, method, start, end)
    return _mock_portrait_crop_success(input_path, output_dir, method, start, end)


# ---------------------------------------------------------------------------
# Tests: Single chapter that fits in max_duration
# ---------------------------------------------------------------------------


class TestSingleChapterFits:
    """Test a single chapter whose duration is within max_duration."""

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_single_chapter_one_clip(self, mock_crop, tmp_path):
        """A 45s chapter with max_duration=60 produces exactly 1 clip."""
        video = tmp_path / "IMG_5769.MOV"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 45.0, [0, 1, 2, 3], "Hello world")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
            max_duration=60.0,
        )

        assert result["total_clips"] == 1
        assert result["clips"][0]["start"] == 0.0
        assert result["clips"][0]["end"] == 45.0
        assert result["clips"][0]["duration"] == 45.0
        assert result["clips"][0]["chapter_id"] == 0

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_single_chapter_preserves_title(self, mock_crop, tmp_path):
        """Clip inherits the chapter title."""
        video = tmp_path / "clip.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 30.0, [0, 1, 2], "Hello how's everyone doing")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        assert result["clips"][0]["title"] == "Hello how's everyone doing"


# ---------------------------------------------------------------------------
# Tests: Chapter exceeds max_duration -- split at chunk boundaries
# ---------------------------------------------------------------------------


class TestChapterExceedsMaxDuration:
    """Test splitting a long chapter at chunk boundaries."""

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_90s_chapter_splits_into_two(self, mock_crop, tmp_path):
        """A 90s chapter (9 chunks of 10s) with max_duration=60 splits into 2 clips."""
        video = tmp_path / "IMG_5769.MOV"
        video.write_text("fake")
        out = tmp_path / "out"

        chunks = _make_chunks(9)  # 0-90s, 10s each
        chapters = [_make_chapter(0, 0.0, 90.0, list(range(9)), "Long chapter")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            chunks=chunks,
            output_dir=str(out),
            max_duration=60.0,
        )

        assert result["total_clips"] == 2
        # First clip: chunks 0-5 (0-60s).
        assert result["clips"][0]["start"] == 0.0
        assert result["clips"][0]["end"] == 60.0
        assert result["clips"][0]["clip_id"] == 0
        # Second clip: chunks 6-8 (60-90s).
        assert result["clips"][1]["start"] == 60.0
        assert result["clips"][1]["end"] == 90.0
        assert result["clips"][1]["clip_id"] == 1

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_split_never_exceeds_max_duration(self, mock_crop, tmp_path):
        """No clip produced by splitting should exceed max_duration."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chunks = _make_chunks(15)  # 0-150s
        chapters = [_make_chapter(0, 0.0, 150.0, list(range(15)), "Very long")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            chunks=chunks,
            output_dir=str(out),
            max_duration=60.0,
        )

        for clip in result["clips"]:
            assert clip["duration"] <= 60.0, (
                f"Clip {clip['clip_id']} duration {clip['duration']} exceeds max_duration"
            )

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_chunk_boundary_respected(self, mock_crop, tmp_path):
        """Splits happen at chunk boundaries, not mid-chunk."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        # Uneven chunks: 0-25s, 25-50s, 50-80s (30s), 80-110s (30s)
        chunks = [
            _make_chunk(0, 0.0, 25.0),
            _make_chunk(1, 25.0, 50.0),
            _make_chunk(2, 50.0, 80.0),
            _make_chunk(3, 80.0, 110.0),
        ]
        chapters = [_make_chapter(0, 0.0, 110.0, [0, 1, 2, 3], "Uneven")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            chunks=chunks,
            output_dir=str(out),
            max_duration=60.0,
        )

        # Chunks 0+1 = 50s (fits), adding chunk 2 would make 80s (>60).
        # So segment 1: [0,1] 0-50s, segment 2: [2,3] 50-110s.
        # Segment 2 is >60s but chunk 2 alone is 30s and chunk 3 would push to 60s.
        # Actually segment 2: chunk 2 starts at 50 and ends 80, that's 30s.
        # Adding chunk 3: 50-110=60s. That's exactly 60, not >60. So it stays.
        # Wait: the check is "proposed_duration > max_duration". 60 is NOT > 60.
        assert result["total_clips"] == 2
        assert result["clips"][0]["end"] == 50.0
        assert result["clips"][1]["start"] == 50.0


# ---------------------------------------------------------------------------
# Tests: Multiple chapters
# ---------------------------------------------------------------------------


class TestMultipleChapters:
    """Test processing multiple chapters."""

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_two_short_chapters(self, mock_crop, tmp_path):
        """Two chapters each within max_duration produce two clips."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [
            _make_chapter(0, 0.0, 45.0, [0, 1, 2, 3], "Chapter one"),
            _make_chapter(1, 45.0, 90.0, [4, 5, 6, 7], "Chapter two"),
        ]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
            max_duration=60.0,
        )

        assert result["total_clips"] == 2
        assert result["clips"][0]["chapter_id"] == 0
        assert result["clips"][1]["chapter_id"] == 1

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_mixed_short_and_long_chapters(self, mock_crop, tmp_path):
        """One short chapter + one long chapter produces 3+ clips."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chunks = _make_chunks(12)  # 0-120s
        chapters = [
            _make_chapter(0, 0.0, 30.0, [0, 1, 2], "Short intro"),
            _make_chapter(1, 30.0, 120.0, list(range(3, 12)), "Long main"),
        ]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            chunks=chunks,
            output_dir=str(out),
            max_duration=60.0,
        )

        # Chapter 0 = 30s (1 clip). Chapter 1 = 90s (2 clips).
        assert result["total_clips"] == 3
        assert result["clips"][0]["chapter_id"] == 0
        assert result["clips"][1]["chapter_id"] == 1
        assert result["clips"][2]["chapter_id"] == 1

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_clip_ids_are_sequential_across_chapters(self, mock_crop, tmp_path):
        """Clip IDs are sequential across all chapters, not reset per chapter."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [
            _make_chapter(0, 0.0, 30.0, [0, 1, 2], "Ch 1"),
            _make_chapter(1, 30.0, 60.0, [3, 4, 5], "Ch 2"),
            _make_chapter(2, 60.0, 90.0, [6, 7, 8], "Ch 3"),
        ]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        ids = [c["clip_id"] for c in result["clips"]]
        assert ids == [0, 1, 2]


# ---------------------------------------------------------------------------
# Tests: Output filename pattern
# ---------------------------------------------------------------------------


class TestOutputFilenamePattern:
    """Test that output files follow {stem}_tiktok_{clip_id}{ext} pattern."""

    def test_output_filename_helper(self):
        """_output_filename produces correct pattern."""
        assert _output_filename("IMG_5769", 0, ".MOV") == "IMG_5769_tiktok_0.MOV"
        assert _output_filename("clip", 3, ".mp4") == "clip_tiktok_3.mp4"
        assert _output_filename("video", 12, ".avi") == "video_tiktok_12.avi"

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_clip_output_path_follows_pattern(self, mock_crop, tmp_path):
        """Clip output_path uses {stem}_tiktok_{clip_id}{ext} naming."""
        video = tmp_path / "IMG_5769.MOV"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 30.0, [0, 1, 2], "Test")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        clip_path = Path(result["clips"][0]["output_path"])
        assert clip_path.name == "IMG_5769_tiktok_0.MOV"

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_multiple_clips_named_sequentially(self, mock_crop, tmp_path):
        """Multiple clips get sequential names."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [
            _make_chapter(0, 0.0, 30.0, [], "Ch 1"),
            _make_chapter(1, 30.0, 60.0, [], "Ch 2"),
        ]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        names = [Path(c["output_path"]).name for c in result["clips"]]
        assert names == ["vid_tiktok_0.mp4", "vid_tiktok_1.mp4"]


# ---------------------------------------------------------------------------
# Tests: Clips manifest written to disk
# ---------------------------------------------------------------------------


class TestClipsManifest:
    """Test that clips_manifest.json is written to output directory."""

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_manifest_file_exists(self, mock_crop, tmp_path):
        """clips_manifest.json is written to output_dir."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 30.0, [], "Test")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        manifest_path = Path(result["clips_manifest_path"])
        assert manifest_path.exists()
        assert manifest_path.name == "clips_manifest.json"

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_manifest_content_matches_result(self, mock_crop, tmp_path):
        """Written manifest JSON matches the returned result dict."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 30.0, [], "Test")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        manifest_path = Path(result["clips_manifest_path"])
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        assert manifest["source"] == result["source"]
        assert manifest["total_clips"] == result["total_clips"]
        assert len(manifest["clips"]) == len(result["clips"])

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_manifest_path_in_output_dir(self, mock_crop, tmp_path):
        """Manifest is placed inside the specified output directory."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "custom_output"

        chapters = [_make_chapter(0, 0.0, 30.0, [], "Test")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        manifest_path = Path(result["clips_manifest_path"])
        assert manifest_path.parent == out


# ---------------------------------------------------------------------------
# Tests: Portrait crop error handling
# ---------------------------------------------------------------------------


class TestPortraitCropErrorHandling:
    """Test that portrait_crop errors are recorded but don't stop processing."""

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_error)
    def test_error_recorded_in_clip_status(self, mock_crop, tmp_path):
        """When portrait_crop fails, clip status is 'error'."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 30.0, [], "Test")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        assert result["clips"][0]["status"] == "error"
        assert "error" in result["clips"][0]

    @patch("tiktok_chunk.portrait_crop")
    def test_one_failure_doesnt_stop_others(self, mock_crop, tmp_path):
        """If one clip fails, remaining clips still process."""
        global _call_counter
        _call_counter = 0

        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        # Set up selective failure: call 2 fails, rest succeed.
        mock_crop.side_effect = _mock_portrait_crop_selective_fail

        chapters = [
            _make_chapter(0, 0.0, 30.0, [], "Ch 1"),
            _make_chapter(1, 30.0, 60.0, [], "Ch 2"),  # This one will fail
            _make_chapter(2, 60.0, 90.0, [], "Ch 3"),
        ]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        assert result["total_clips"] == 3
        assert result["clips"][0]["status"] == "success"
        assert result["clips"][1]["status"] == "error"
        assert result["clips"][2]["status"] == "success"

    @patch("tiktok_chunk.portrait_crop", side_effect=Exception("unexpected crash"))
    def test_exception_caught_and_recorded(self, mock_crop, tmp_path):
        """Exceptions from portrait_crop are caught and recorded as errors."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 30.0, [], "Test")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        assert result["clips"][0]["status"] == "error"
        assert "unexpected crash" in result["clips"][0]["error"]


# ---------------------------------------------------------------------------
# Tests: Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema:
    """Test that the result dict has all required keys with correct types."""

    REQUIRED_TOP_KEYS = {"source", "total_clips", "max_duration", "crop_method", "clips", "clips_manifest_path"}
    REQUIRED_CLIP_KEYS = {"clip_id", "chapter_id", "start", "end", "duration", "title", "output_path", "status"}

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_top_level_keys_present(self, mock_crop, tmp_path):
        """Result dict has all required top-level keys."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 30.0, [], "Test")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        for key in self.REQUIRED_TOP_KEYS:
            assert key in result, f"Missing top-level key: {key}"

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_clip_keys_present(self, mock_crop, tmp_path):
        """Each clip dict has all required keys."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 30.0, [], "Test")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        for clip in result["clips"]:
            for key in self.REQUIRED_CLIP_KEYS:
                assert key in clip, f"Missing clip key: {key}"

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_source_is_filename_only(self, mock_crop, tmp_path):
        """source field is just the filename, not the full path."""
        video = tmp_path / "IMG_5769.MOV"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 30.0, [], "Test")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        assert result["source"] == "IMG_5769.MOV"

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_max_duration_in_result(self, mock_crop, tmp_path):
        """max_duration in result matches the parameter."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 30.0, [], "Test")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
            max_duration=45.0,
        )

        assert result["max_duration"] == 45.0

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_crop_method_in_result(self, mock_crop, tmp_path):
        """crop_method in result matches the parameter."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 30.0, [], "Test")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
            crop_method="face",
        )

        assert result["crop_method"] == "face"

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_total_clips_matches_clips_length(self, mock_crop, tmp_path):
        """total_clips equals len(clips)."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [
            _make_chapter(0, 0.0, 30.0, [], "Ch 1"),
            _make_chapter(1, 30.0, 60.0, [], "Ch 2"),
        ]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        assert result["total_clips"] == len(result["clips"])


# ---------------------------------------------------------------------------
# Tests: No chunks provided (time-based splitting fallback)
# ---------------------------------------------------------------------------


class TestNoChunksProvided:
    """Test fallback behavior when chunks parameter is None."""

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_short_chapter_no_split(self, mock_crop, tmp_path):
        """A chapter within max_duration is not split even without chunks."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 45.0, [], "Short")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            chunks=None,
            output_dir=str(out),
            max_duration=60.0,
        )

        assert result["total_clips"] == 1
        assert result["clips"][0]["start"] == 0.0
        assert result["clips"][0]["end"] == 45.0

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_long_chapter_time_split(self, mock_crop, tmp_path):
        """Without chunks, a long chapter is split at time intervals."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 150.0, [], "Long")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            chunks=None,
            output_dir=str(out),
            max_duration=60.0,
        )

        # 150s / 60s = 3 clips (60+60+30).
        assert result["total_clips"] == 3
        assert result["clips"][0]["duration"] == 60.0
        assert result["clips"][1]["duration"] == 60.0
        assert result["clips"][2]["duration"] == 30.0

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_time_split_covers_full_duration(self, mock_crop, tmp_path):
        """Time-based split covers the full chapter from start to end."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 10.0, 130.0, [], "Long")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            chunks=None,
            output_dir=str(out),
            max_duration=60.0,
        )

        # Should start at 10.0 and end at 130.0.
        assert result["clips"][0]["start"] == 10.0
        assert result["clips"][-1]["end"] == 130.0


# ---------------------------------------------------------------------------
# Tests: max_duration exactly matches chapter duration
# ---------------------------------------------------------------------------


class TestExactDurationMatch:
    """Test edge case where chapter duration exactly equals max_duration."""

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_exact_match_no_split(self, mock_crop, tmp_path):
        """Chapter of exactly max_duration produces a single clip (no split)."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 60.0, [0, 1, 2, 3, 4, 5], "Exact")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
            max_duration=60.0,
        )

        assert result["total_clips"] == 1
        assert result["clips"][0]["duration"] == 60.0

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_slightly_over_splits(self, mock_crop, tmp_path):
        """Chapter just barely over max_duration gets split."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        # 7 chunks of 10s = 70s, just over 60.
        chunks = _make_chunks(7)
        chapters = [_make_chapter(0, 0.0, 70.0, list(range(7)), "Over")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            chunks=chunks,
            output_dir=str(out),
            max_duration=60.0,
        )

        assert result["total_clips"] == 2

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_exact_with_chunks_no_split(self, mock_crop, tmp_path):
        """Exactly max_duration with chunk data still produces one clip."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chunks = _make_chunks(6)  # 0-60s exactly
        chapters = [_make_chapter(0, 0.0, 60.0, list(range(6)), "Exact")]

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            chunks=chunks,
            output_dir=str(out),
            max_duration=60.0,
        )

        assert result["total_clips"] == 1


# ---------------------------------------------------------------------------
# Tests: Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    """Test internal helper functions."""

    def test_build_chunk_lookup(self):
        """_build_chunk_lookup maps id -> chunk."""
        chunks = _make_chunks(3)
        lookup = _build_chunk_lookup(chunks)

        assert len(lookup) == 3
        assert lookup[0]["start"] == 0.0
        assert lookup[2]["end"] == 30.0

    def test_split_chapter_by_time_short(self):
        """_split_chapter_by_time with short chapter returns one segment."""
        chapter = _make_chapter(0, 0.0, 30.0)
        segments = _split_chapter_by_time(chapter, 60.0)

        assert len(segments) == 1
        assert segments[0]["start"] == 0.0
        assert segments[0]["end"] == 30.0

    def test_split_chapter_by_time_long(self):
        """_split_chapter_by_time with 130s chapter at 60s max produces 3 segments."""
        chapter = _make_chapter(0, 0.0, 130.0)
        segments = _split_chapter_by_time(chapter, 60.0)

        assert len(segments) == 3
        assert segments[0] == {"start": 0.0, "end": 60.0, "duration": 60.0}
        assert segments[1] == {"start": 60.0, "end": 120.0, "duration": 60.0}
        assert segments[2]["start"] == 120.0
        assert segments[2]["end"] == 130.0

    def test_split_at_chunk_boundaries(self):
        """_split_chapter_at_chunk_boundaries respects chunk edges."""
        chunks = _make_chunks(9)  # 0-90s
        lookup = _build_chunk_lookup(chunks)
        chapter = _make_chapter(0, 0.0, 90.0, list(range(9)))

        segments = _split_chapter_at_chunk_boundaries(chapter, lookup, 60.0)

        assert len(segments) == 2
        # First segment should end at a chunk boundary <= 60s.
        assert segments[0]["end"] <= 60.0
        assert segments[1]["start"] >= segments[0]["end"]

    def test_split_empty_chapter(self):
        """Empty chapter (no chunk_ids) returns no segments."""
        chapter = _make_chapter(0, 0.0, 30.0, [])
        segments = _split_chapter_at_chunk_boundaries(chapter, {}, 60.0)
        assert segments == []


# ---------------------------------------------------------------------------
# Tests: Empty chapters list
# ---------------------------------------------------------------------------


class TestEmptyChapters:
    """Test edge case with no chapters."""

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_no_chapters_no_clips(self, mock_crop, tmp_path):
        """Empty chapters list produces zero clips."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=[],
            output_dir=str(out),
        )

        assert result["total_clips"] == 0
        assert result["clips"] == []

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_empty_chapters_still_writes_manifest(self, mock_crop, tmp_path):
        """Even with no chapters, manifest is written."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        result = generate_tiktok_chunks(
            input_path=str(video),
            chapters=[],
            output_dir=str(out),
        )

        manifest_path = Path(result["clips_manifest_path"])
        assert manifest_path.exists()


# ---------------------------------------------------------------------------
# Tests: portrait_crop is called with correct arguments
# ---------------------------------------------------------------------------


class TestPortraitCropCallArgs:
    """Test that portrait_crop is called with the correct arguments."""

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_crop_called_with_start_end(self, mock_crop, tmp_path):
        """portrait_crop receives correct start and end times."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 10.5, 45.2, [], "Test")]

        generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        mock_crop.assert_called_once()
        call_kwargs = mock_crop.call_args
        assert call_kwargs[1]["start"] == 10.5
        assert call_kwargs[1]["end"] == 45.2

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_crop_called_with_method(self, mock_crop, tmp_path):
        """portrait_crop receives the specified crop method."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [_make_chapter(0, 0.0, 30.0, [], "Test")]

        generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
            crop_method="face",
        )

        call_kwargs = mock_crop.call_args
        assert call_kwargs[1]["method"] == "face"

    @patch("tiktok_chunk.portrait_crop", side_effect=_mock_portrait_crop_success)
    def test_crop_called_once_per_segment(self, mock_crop, tmp_path):
        """portrait_crop is called exactly once per output clip."""
        video = tmp_path / "vid.mp4"
        video.write_text("fake")
        out = tmp_path / "out"

        chapters = [
            _make_chapter(0, 0.0, 30.0, [], "Ch 1"),
            _make_chapter(1, 30.0, 60.0, [], "Ch 2"),
        ]

        generate_tiktok_chunks(
            input_path=str(video),
            chapters=chapters,
            output_dir=str(out),
        )

        assert mock_crop.call_count == 2
