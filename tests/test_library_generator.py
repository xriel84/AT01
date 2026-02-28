"""Tests for library_generator.py — offline, no ffprobe/ffmpeg required."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from library_generator import (
    scan_video_files,
    probe_video,
    load_transcript_segments,
    build_library_entry,
    generate_library,
    VIDEO_EXTENSIONS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def video_dir(tmp_path):
    """Create a temp directory with mixed video and non-video files."""
    (tmp_path / "clip1.mp4").write_bytes(b"")
    (tmp_path / "clip2.mov").write_bytes(b"")
    (tmp_path / "notes.txt").write_bytes(b"")
    (tmp_path / "image.png").write_bytes(b"")
    (tmp_path / "sub" / "deep.mkv").mkdir(parents=True, exist_ok=True)
    # Actually create the file, not a dir
    (tmp_path / "sub").rmdir()  # remove the dir we accidentally made
    return tmp_path


@pytest.fixture()
def video_dir_clean(tmp_path):
    """Create a temp directory with video files (no accidental dirs)."""
    (tmp_path / "clip1.mp4").write_bytes(b"")
    (tmp_path / "clip2.mov").write_bytes(b"")
    (tmp_path / "notes.txt").write_bytes(b"")
    (tmp_path / "image.png").write_bytes(b"")
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "deep.mkv").write_bytes(b"")
    return tmp_path


@pytest.fixture()
def video_with_chunks(tmp_path):
    """Video file with a matching chunks JSON alongside it."""
    (tmp_path / "interview.mp4").write_bytes(b"")
    chunks = {
        "chunks": [
            {"id": 0, "start": 0.0, "end": 5.0, "text": "Hello world",
             "word_count": 2, "silence_ratio": 0.1, "has_speech": True},
            {"id": 1, "start": 5.0, "end": 10.0, "text": "Second chunk",
             "word_count": 2, "silence_ratio": 0.2, "has_speech": True},
        ]
    }
    with open(tmp_path / "interview_chunks.json", "w", encoding="utf-8") as f:
        json.dump(chunks, f)
    return tmp_path


# ---------------------------------------------------------------------------
# Tests: scan_video_files
# ---------------------------------------------------------------------------

class TestScanVideoFiles:

    def test_scan_finds_video_files(self, video_dir_clean):
        """Only video extensions are returned, non-video files excluded."""
        videos = scan_video_files(video_dir_clean)
        names = {v.name for v in videos}
        assert "clip1.mp4" in names
        assert "clip2.mov" in names
        assert "deep.mkv" in names
        assert "notes.txt" not in names
        assert "image.png" not in names

    def test_scan_returns_paths(self, video_dir_clean):
        """All returned items are Path objects."""
        videos = scan_video_files(video_dir_clean)
        for v in videos:
            assert isinstance(v, Path)

    def test_scan_empty_directory(self, tmp_path):
        """Empty directory returns empty list."""
        assert scan_video_files(tmp_path) == []

    def test_scan_nonexistent_directory(self):
        """Non-existent path returns empty list, no exception."""
        assert scan_video_files("/nonexistent/path/xyz") == []

    def test_skips_non_video_files(self, video_dir_clean):
        """Text and image files are not included in scan results."""
        videos = scan_video_files(video_dir_clean)
        exts = {v.suffix.lower() for v in videos}
        assert ".txt" not in exts
        assert ".png" not in exts
        assert all(ext in VIDEO_EXTENSIONS for ext in exts)


# ---------------------------------------------------------------------------
# Tests: probe_video
# ---------------------------------------------------------------------------

class TestProbeVideo:

    def test_probe_returns_dict(self, tmp_path):
        """Probe always returns a dict, even for non-existent files."""
        result = probe_video(tmp_path / "nonexistent.mp4")
        assert isinstance(result, dict)
        assert "duration" in result
        assert "resolution" in result
        assert "codec" in result

    def test_probe_with_mock_ffprobe(self, tmp_path):
        """Probe parses ffprobe JSON output correctly."""
        fake_output = json.dumps({
            "format": {"duration": "120.500"},
            "streams": [{
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
            }],
        })
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = fake_output

        with patch("library_generator.subprocess.run", return_value=mock_proc):
            result = probe_video(tmp_path / "test.mp4")

        assert result["duration"] == 120.5
        assert result["resolution"] == "1920x1080"
        assert result["codec"] == "h264"
        assert result["width"] == 1920
        assert result["height"] == 1080


# ---------------------------------------------------------------------------
# Tests: load_transcript_segments
# ---------------------------------------------------------------------------

class TestLoadTranscriptSegments:

    def test_loads_from_stem_chunks(self, video_with_chunks):
        """Loads segments from <stem>_chunks.json file."""
        video = video_with_chunks / "interview.mp4"
        segments = load_transcript_segments(video)
        assert len(segments) == 2
        assert segments[0]["text"] == "Hello world"
        assert segments[0]["start"] == 0.0
        assert segments[1]["end"] == 10.0

    def test_no_transcript_returns_empty(self, tmp_path):
        """Returns empty list when no chunks file exists."""
        (tmp_path / "video.mp4").write_bytes(b"")
        segments = load_transcript_segments(tmp_path / "video.mp4")
        assert segments == []

    def test_loads_bare_list_chunks(self, tmp_path):
        """Handles chunks file that is a bare list (no wrapper dict)."""
        (tmp_path / "clip.mp4").write_bytes(b"")
        chunks = [
            {"start": 0, "end": 3, "text": "bare list chunk"},
        ]
        with open(tmp_path / "clip_chunks.json", "w", encoding="utf-8") as f:
            json.dump(chunks, f)

        segments = load_transcript_segments(tmp_path / "clip.mp4")
        assert len(segments) == 1
        assert segments[0]["text"] == "bare list chunk"


# ---------------------------------------------------------------------------
# Tests: generate_library
# ---------------------------------------------------------------------------

class TestGenerateLibrary:

    def test_single_video_output(self, tmp_path):
        """Single video produces a 1-entry library."""
        (tmp_path / "test.mp4").write_bytes(b"")
        out = tmp_path / "library.json"

        with patch("library_generator.probe_video") as mock_probe:
            mock_probe.return_value = {
                "duration": 60.0, "resolution": "1280x720",
                "codec": "h264", "width": 1280, "height": 720,
            }
            result = generate_library(tmp_path, out)

        assert result["video_count"] == 1
        assert out.exists()

        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["filename"] == "test.mp4"
        assert data[0]["duration"] == 60.0

    def test_empty_directory_output(self, tmp_path):
        """Empty directory produces an empty library JSON array."""
        out = tmp_path / "empty.json"
        result = generate_library(tmp_path, out)

        assert result["video_count"] == 0
        assert out.exists()

        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        assert data == []

    def test_output_schema_matches_viewer(self, tmp_path):
        """Generated entries have all fields the viewer expects."""
        (tmp_path / "clip.mp4").write_bytes(b"")
        out = tmp_path / "lib.json"

        with patch("library_generator.probe_video") as mock_probe:
            mock_probe.return_value = {
                "duration": 30.0, "resolution": "1920x1080",
                "codec": "h264", "width": 1920, "height": 1080,
            }
            generate_library(tmp_path, out)

        with open(out, encoding="utf-8") as f:
            data = json.load(f)

        entry = data[0]
        # Viewer requires these fields.
        assert "filename" in entry
        assert "duration" in entry
        assert "whisper_segments" in entry
        assert isinstance(entry["whisper_segments"], list)
        assert isinstance(entry["duration"], (int, float))

    def test_output_json_is_utf8(self, tmp_path):
        """Output file is valid UTF-8 JSON."""
        (tmp_path / "vid.mp4").write_bytes(b"")
        out = tmp_path / "out.json"

        with patch("library_generator.probe_video") as mock_probe:
            mock_probe.return_value = {
                "duration": 10.0, "resolution": "640x480",
                "codec": "h264", "width": 640, "height": 480,
            }
            generate_library(tmp_path, out)

        # Read as UTF-8 bytes and verify.
        raw = out.read_bytes()
        text = raw.decode("utf-8")  # Should not raise
        json.loads(text)  # Should be valid JSON

    def test_multiple_videos(self, tmp_path):
        """Multiple videos in directory each get an entry."""
        for name in ["a.mp4", "b.mov", "c.mkv"]:
            (tmp_path / name).write_bytes(b"")
        out = tmp_path / "multi.json"

        with patch("library_generator.probe_video") as mock_probe:
            mock_probe.return_value = {
                "duration": 5.0, "resolution": "320x240",
                "codec": "h264", "width": 320, "height": 240,
            }
            result = generate_library(tmp_path, out)

        assert result["video_count"] == 3
        assert result["total_duration"] == 15.0
