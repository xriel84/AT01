"""Tests for manifest_writer — AT pipeline → JP viewer schema bridge."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from manifest_writer import (
    to_raptor_entry,
    to_assembly_clip,
    write_raptor_library,
    write_assembly_manifest,
    sync_all,
    _words_to_segments,
    _two_word_name,
    _load_json_safe,
    ASPECT_RESOLUTION_MAP,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PROBE = {
    "path": "C:/AT01/input/Adlab/video_final.mp4",
    "filename": "video_final.mp4",
    "duration_sec": 142.5,
    "width": 1920,
    "height": 1080,
    "fps": 29.97,
    "video_codec": "h264",
    "audio_codec": "aac",
    "bitrate_kbps": 8500,
    "audio_channels": 2,
    "file_size_mb": 145.3,
    "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
}

SAMPLE_CHUNKS = [
    {"id": 0, "start": 0.0, "end": 10.0, "text": "Hello world this is a test", "word_count": 6, "silence_ratio": 0.1, "has_speech": True},
    {"id": 1, "start": 10.0, "end": 20.0, "text": "Second chunk with more words", "word_count": 5, "silence_ratio": 0.2, "has_speech": True},
    {"id": 2, "start": 20.0, "end": 30.0, "text": "", "word_count": 0, "silence_ratio": 1.0, "has_speech": False},
]

SAMPLE_WORDS = [
    {"word": "Hello", "start": 0.0, "end": 0.3},
    {"word": "world", "start": 0.4, "end": 0.7},
    {"word": "this", "start": 0.8, "end": 1.0},
    {"word": "is", "start": 1.1, "end": 1.2},
    {"word": "a", "start": 1.3, "end": 1.4},
    {"word": "test", "start": 1.5, "end": 1.8},
]


# ---------------------------------------------------------------------------
# TestToRaptorEntry
# ---------------------------------------------------------------------------

class TestToRaptorEntry:
    """Tests for to_raptor_entry — AT pipeline → raptor-library entry."""

    def test_basic_entry(self):
        """Probe + chunks + words → valid raptor entry."""
        entry = to_raptor_entry(SAMPLE_PROBE, SAMPLE_CHUNKS, SAMPLE_WORDS)
        assert entry["filename"] == "video_final.mp4"
        assert entry["duration_sec"] == 142.5
        assert entry["resolution"] == "1920x1080"
        assert entry["has_audio"] is True
        assert entry["has_video"] is True
        assert entry["codec_video"] == "h264"
        assert entry["codec_audio"] == "aac"
        assert entry["filesize_mb"] == 145.3
        assert entry["status"] == "transcribed"
        assert entry["error"] is None

    def test_transcript_assembled(self):
        """Full transcript is assembled from chunks."""
        entry = to_raptor_entry(SAMPLE_PROBE, SAMPLE_CHUNKS)
        assert "Hello world this is a test" in entry["transcript_full"]
        assert "Second chunk" in entry["transcript_full"]
        assert entry["transcript_snippet"] == entry["transcript_full"][:120]

    def test_whisper_segments_from_words(self):
        """Word-level timestamps are grouped into segments."""
        entry = to_raptor_entry(SAMPLE_PROBE, SAMPLE_CHUNKS, SAMPLE_WORDS)
        assert len(entry["whisper_segments"]) >= 1
        seg = entry["whisper_segments"][0]
        assert "start" in seg
        assert "end" in seg
        assert "text" in seg

    def test_context_block(self):
        """Context block has required fields."""
        entry = to_raptor_entry(SAMPLE_PROBE, SAMPLE_CHUNKS)
        ctx = entry["context"]
        assert ctx["language"] == "en"
        assert ctx["has_narration"] is True  # has speech chunks
        assert ctx["content_type"] == "narration"
        assert "speaker_count" in ctx

    def test_relative_path_with_source_root(self):
        """relative_path calculated from source_root."""
        entry = to_raptor_entry(SAMPLE_PROBE, source_root="C:/AT01/input")
        assert entry["relative_path"] == "Adlab/video_final.mp4"
        assert entry["subdir"] == "Adlab"

    def test_relative_path_without_source_root(self):
        """Without source_root, relative_path is just filename."""
        entry = to_raptor_entry(SAMPLE_PROBE)
        assert entry["relative_path"] == "video_final.mp4"

    def test_auto_id(self):
        """Auto-generated ID starts with RH_."""
        entry = to_raptor_entry(SAMPLE_PROBE)
        assert entry["id"].startswith("RH_")

    def test_custom_id(self):
        """Custom ID overrides auto-generation."""
        entry = to_raptor_entry(SAMPLE_PROBE, entry_id="MY_001")
        assert entry["id"] == "MY_001"

    def test_no_chunks(self):
        """No chunks → probed status, no transcript."""
        entry = to_raptor_entry(SAMPLE_PROBE)
        assert entry["status"] == "probed"
        assert entry["transcript_full"] == ""
        assert entry["summary"] == "[NO TRANSCRIPT]"

    def test_silent_video(self):
        """All silent chunks → content_type silent."""
        silent_chunks = [{"id": 0, "start": 0.0, "end": 10.0, "text": "", "word_count": 0, "silence_ratio": 1.0, "has_speech": False}]
        entry = to_raptor_entry(SAMPLE_PROBE, silent_chunks)
        assert entry["context"]["content_type"] == "silent"
        assert entry["context"]["has_narration"] is False

    def test_no_audio_codec(self):
        """Probe with no audio → has_audio False."""
        probe = {**SAMPLE_PROBE, "audio_codec": None}
        entry = to_raptor_entry(probe)
        assert entry["has_audio"] is False

    def test_forward_slashes(self):
        """Paths use forward slashes."""
        entry = to_raptor_entry(SAMPLE_PROBE)
        assert "\\" not in entry["absolute_path"]
        assert "\\" not in entry["relative_path"]


# ---------------------------------------------------------------------------
# TestToAssemblyClip
# ---------------------------------------------------------------------------

class TestToAssemblyClip:
    """Tests for to_assembly_clip — AT chunk → assembly_manifest clip."""

    def test_basic_clip(self):
        """Chunk → valid assembly clip."""
        clip = to_assembly_clip(SAMPLE_CHUNKS[0])
        assert clip["platform"] == "tiktok"
        assert clip["aspect"] == "9:16"
        assert clip["resolution"] == "1080x1920"
        assert clip["duration_sec"] == 10.0
        assert "Hello" in clip["transcript_snippet"]
        assert clip["silence_pct"] == 10

    def test_custom_platform(self):
        """Custom platform assignment."""
        clip = to_assembly_clip(SAMPLE_CHUNKS[0], platform="youtube_shorts")
        assert clip["platform"] == "youtube_shorts"

    def test_custom_aspect(self):
        """Custom aspect → correct resolution."""
        clip = to_assembly_clip(SAMPLE_CHUNKS[0], aspect="16:9")
        assert clip["aspect"] == "16:9"
        assert clip["resolution"] == "1920x1080"

    def test_square_aspect(self):
        """Square aspect → 1080x1080."""
        clip = to_assembly_clip(SAMPLE_CHUNKS[0], aspect="1:1")
        assert clip["resolution"] == "1080x1080"

    def test_source_id(self):
        """source_id links clip to raptor-library entry."""
        clip = to_assembly_clip(SAMPLE_CHUNKS[0], source_id="RH_abc123")
        assert clip["source_id"] == "RH_abc123"

    def test_auto_id_format(self):
        """Auto-generated ID includes platform."""
        clip = to_assembly_clip(SAMPLE_CHUNKS[0], platform="ig_reels")
        assert "igreels" in clip["id"]

    def test_custom_id(self):
        """Custom ID overrides auto-generation."""
        clip = to_assembly_clip(SAMPLE_CHUNKS[0], clip_id="CUSTOM_01")
        assert clip["id"] == "CUSTOM_01"

    def test_name_from_text(self):
        """Name derived from first words of text."""
        clip = to_assembly_clip(SAMPLE_CHUNKS[0])
        assert clip["name"] == "Hello world this is"

    def test_empty_text(self):
        """Empty text → 'Clip N' name."""
        clip = to_assembly_clip(SAMPLE_CHUNKS[2])
        assert "Clip" in clip["name"]

    def test_output_path(self):
        """Custom output path."""
        clip = to_assembly_clip(SAMPLE_CHUNKS[0], output_path="output/custom.mp4")
        assert clip["path"] == "output/custom.mp4"

    def test_default_path(self):
        """Default path uses output/ prefix."""
        clip = to_assembly_clip(SAMPLE_CHUNKS[0])
        assert clip["path"].startswith("output/")
        assert clip["path"].endswith(".mp4")

    def test_status_ready(self):
        """Clips have ready status."""
        clip = to_assembly_clip(SAMPLE_CHUNKS[0])
        assert clip["status"] == "ready"


# ---------------------------------------------------------------------------
# TestWriteRaptorLibrary
# ---------------------------------------------------------------------------

class TestWriteRaptorLibrary:
    """Tests for write_raptor_library — batch output."""

    def test_write_file(self, tmp_path):
        """Writes valid JSON file."""
        entry = to_raptor_entry(SAMPLE_PROBE, SAMPLE_CHUNKS)
        out = tmp_path / "raptor-library.json"
        result = write_raptor_library([entry], out, source_root="C:/input")

        assert out.exists()
        data = json.loads(out.read_text())
        assert data["total_files"] == 1
        assert data["processed"] == 1
        assert data["skipped"] == 0
        assert len(data["entries"]) == 1
        assert data["source_root"] == "C:/input"
        assert "generated" in data

    def test_multiple_entries(self, tmp_path):
        """Multiple entries in one library."""
        e1 = to_raptor_entry(SAMPLE_PROBE, SAMPLE_CHUNKS)
        e2 = to_raptor_entry({**SAMPLE_PROBE, "filename": "other.mp4"})
        out = tmp_path / "raptor-library.json"
        result = write_raptor_library([e1, e2], out)
        assert result["total_files"] == 2

    def test_empty_entries(self, tmp_path):
        """Empty entries list → valid JSON."""
        out = tmp_path / "raptor-library.json"
        result = write_raptor_library([], out)
        assert result["total_files"] == 0
        assert result["entries"] == []

    def test_creates_parent_dirs(self, tmp_path):
        """Creates parent directories if needed."""
        out = tmp_path / "sub" / "dir" / "raptor-library.json"
        write_raptor_library([], out)
        assert out.exists()


# ---------------------------------------------------------------------------
# TestWriteAssemblyManifest
# ---------------------------------------------------------------------------

class TestWriteAssemblyManifest:
    """Tests for write_assembly_manifest — batch output."""

    def test_write_file(self, tmp_path):
        """Writes valid JSON file."""
        clip = to_assembly_clip(SAMPLE_CHUNKS[0])
        out = tmp_path / "assembly_manifest.json"
        result = write_assembly_manifest([clip], out, source_clip="video.mov")

        assert out.exists()
        data = json.loads(out.read_text())
        assert data["source_clip"] == "video.mov"
        assert len(data["clips"]) == 1
        assert "generated" in data

    def test_multiple_clips(self, tmp_path):
        """Multiple clips in one manifest."""
        clips = [to_assembly_clip(c) for c in SAMPLE_CHUNKS[:2]]
        out = tmp_path / "assembly_manifest.json"
        result = write_assembly_manifest(clips, out)
        assert len(result["clips"]) == 2

    def test_empty_clips(self, tmp_path):
        """Empty clips list → valid JSON."""
        out = tmp_path / "assembly_manifest.json"
        result = write_assembly_manifest([], out)
        assert result["clips"] == []


# ---------------------------------------------------------------------------
# TestSyncAll
# ---------------------------------------------------------------------------

class TestSyncAll:
    """Tests for sync_all — full orchestration."""

    @patch("manifest_writer.scan_local_dir")
    def test_basic_sync(self, mock_scan, tmp_path):
        """Scan + convert → both output files created."""
        mock_scan.return_value = {
            "directory": str(tmp_path),
            "videos": [SAMPLE_PROBE],
            "total_count": 1,
            "total_size_mb": 145.3,
        }
        result = sync_all(str(tmp_path), str(tmp_path))
        assert result["entry_count"] == 1
        assert result["clip_count"] == 0  # no chunks data available
        assert (tmp_path / "raptor-library.json").exists()
        assert (tmp_path / "assembly_manifest.json").exists()

    @patch("manifest_writer.scan_local_dir")
    def test_sync_with_chunks(self, mock_scan, tmp_path):
        """With chunks.json present → clips generated."""
        mock_scan.return_value = {
            "directory": str(tmp_path),
            "videos": [SAMPLE_PROBE],
            "total_count": 1,
            "total_size_mb": 145.3,
        }
        # Write matching chunks.json
        chunks_data = {"source": "video_final.mp4", "chunks": SAMPLE_CHUNKS}
        (tmp_path / "chunks.json").write_text(json.dumps(chunks_data))

        result = sync_all(str(tmp_path), str(tmp_path))
        assert result["entry_count"] == 1
        assert result["clip_count"] == 2  # 2 speech chunks

    @patch("manifest_writer.scan_local_dir")
    def test_sync_error(self, mock_scan, tmp_path):
        """scan_local_dir error → error returned."""
        mock_scan.return_value = {"error": "directory not found"}
        result = sync_all(str(tmp_path), str(tmp_path))
        assert "error" in result

    @patch("manifest_writer.scan_local_dir")
    def test_sync_no_videos(self, mock_scan, tmp_path):
        """No videos → empty manifests."""
        mock_scan.return_value = {
            "directory": str(tmp_path),
            "videos": [],
            "total_count": 0,
            "total_size_mb": 0,
        }
        result = sync_all(str(tmp_path), str(tmp_path))
        assert result["entry_count"] == 0
        assert result["clip_count"] == 0


# ---------------------------------------------------------------------------
# TestHelpers
# ---------------------------------------------------------------------------

class TestHelpers:
    """Tests for helper functions."""

    def test_words_to_segments_basic(self):
        """Words grouped into segments."""
        segments = _words_to_segments(SAMPLE_WORDS)
        assert len(segments) == 1
        assert segments[0]["start"] == 0.0
        assert segments[0]["end"] == 1.8
        assert "Hello" in segments[0]["text"]

    def test_words_to_segments_empty(self):
        """Empty words → empty segments."""
        assert _words_to_segments([]) == []

    def test_words_to_segments_many(self):
        """Many words → multiple segments (10 words each)."""
        words = [{"word": f"w{i}", "start": float(i), "end": float(i) + 0.5} for i in range(25)]
        segments = _words_to_segments(words)
        assert len(segments) == 3  # 10, 10, 5

    def test_two_word_name_underscores(self):
        """Filename with underscores → title case."""
        assert _two_word_name("interview_take_3.mov") == "Interview Take"

    def test_two_word_name_dashes(self):
        """Filename with dashes → title case."""
        assert _two_word_name("final-cut.mp4") == "Final Cut"

    def test_two_word_name_single_word(self):
        """Single word → title case."""
        assert _two_word_name("overview.mp4") == "Overview"

    def test_two_word_name_img(self):
        """IMG-style filename."""
        assert _two_word_name("IMG_5769.MOV") == "Img 5769"

    def test_load_json_safe_missing(self, tmp_path):
        """Missing file → None."""
        assert _load_json_safe(tmp_path / "nope.json") is None

    def test_load_json_safe_valid(self, tmp_path):
        """Valid JSON → dict."""
        p = tmp_path / "test.json"
        p.write_text('{"source": "test.mp4", "chunks": []}')
        result = _load_json_safe(p)
        assert result["source"] == "test.mp4"

    def test_load_json_safe_source_mismatch(self, tmp_path):
        """Source mismatch → None."""
        p = tmp_path / "test.json"
        p.write_text('{"source": "other.mp4", "chunks": []}')
        result = _load_json_safe(p, source_filename="test.mp4")
        assert result is None

    def test_load_json_safe_invalid(self, tmp_path):
        """Invalid JSON → None."""
        p = tmp_path / "test.json"
        p.write_text("not json {{{")
        assert _load_json_safe(p) is None

    def test_aspect_resolution_map(self):
        """All expected aspect ratios mapped."""
        assert ASPECT_RESOLUTION_MAP["9:16"] == "1080x1920"
        assert ASPECT_RESOLUTION_MAP["16:9"] == "1920x1080"
        assert ASPECT_RESOLUTION_MAP["1:1"] == "1080x1080"
