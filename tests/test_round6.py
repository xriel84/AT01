"""Round 6 tests: transcript intelligence layer — 40 tests, all mocked.

No GPU, no ffmpeg, no spaCy model loading, no disk I/O in CI.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Tools path
_tools_dir = str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)


# ---------------------------------------------------------------------------
# Mock spaCy helpers
# ---------------------------------------------------------------------------

class _MockEntity:
    def __init__(self, text, label_):
        self.text = text
        self.label_ = label_


class _MockToken:
    def __init__(self, text, is_stop=False, is_punct=False, pos_="NOUN"):
        self.text = text
        self.is_stop = is_stop
        self.is_punct = is_punct
        self.pos_ = pos_


class _MockDoc:
    def __init__(self, text, entities=None):
        self.text = text
        self.ents = entities or []
        _stop = {"the", "a", "is", "at", "in", "and", "to", "of", "for", "on", "with"}
        self._tokens = []
        for w in text.split():
            clean = w.strip(".,!?;:")
            if not clean:
                continue
            is_stop = clean.lower() in _stop
            is_punct = all(c in ".,!?;:" for c in clean)
            pos_ = "PROPN" if clean[0:1].isupper() and not is_stop else "NOUN"
            self._tokens.append(
                _MockToken(clean, is_stop=is_stop, is_punct=is_punct, pos_=pos_)
            )

    def __iter__(self):
        return iter(self._tokens)


class _MockNLP:
    def __init__(self, entities=None):
        self._entities = entities or []

    def __call__(self, text):
        return _MockDoc(text, entities=self._entities)


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

def _make_chunks(texts, duration_per_chunk=10.0):
    """Create a list of chunk dicts from text strings."""
    chunks = []
    for i, text in enumerate(texts):
        chunks.append({
            "id": i,
            "start": i * duration_per_chunk,
            "end": (i + 1) * duration_per_chunk,
            "text": text,
            "word_count": len(text.split()),
            "silence_ratio": 0.1,
            "has_speech": bool(text.strip()),
        })
    return chunks


def _make_transcript(texts, duration_per_chunk=10.0):
    """Create a transcript dict from text strings."""
    chunks = _make_chunks(texts, duration_per_chunk)
    return {
        "source": "test.mp4",
        "duration": len(texts) * duration_per_chunk,
        "chunks": chunks,
    }


# ===========================================================================
# batch_transcribe tests (8)
# ===========================================================================

class TestBatchTranscribe:

    @patch("batch_transcribe.transcribe_video")
    def test_batch_scan_extensions(self, mock_tv, tmp_path):
        """Finds .mov, .mp4, .mkv, skips .txt, .json."""
        from batch_transcribe import batch_transcribe

        (tmp_path / "a.mov").write_text("fake")
        (tmp_path / "b.mp4").write_text("fake")
        (tmp_path / "c.mkv").write_text("fake")
        (tmp_path / "d.txt").write_text("skip me")
        (tmp_path / "e.json").write_text("{}")

        mock_tv.return_value = {"duration": 10.0, "chunks": [], "source": "test"}
        out = tmp_path / "out"
        result = batch_transcribe(str(tmp_path), str(out))

        assert result["file_count"] == 3
        assert len(result["errors"]) == 0

    @patch("batch_transcribe.transcribe_video")
    def test_batch_empty_dir(self, mock_tv, tmp_path):
        """Empty directory -> file_count: 0, empty files list."""
        from batch_transcribe import batch_transcribe

        out = tmp_path / "out"
        result = batch_transcribe(str(tmp_path), str(out))

        assert result["file_count"] == 0
        assert result["files"] == []
        mock_tv.assert_not_called()

    @patch("batch_transcribe.transcribe_video")
    def test_batch_one_file(self, mock_tv, tmp_path):
        """Single video -> manifest with 1 entry."""
        from batch_transcribe import batch_transcribe

        (tmp_path / "video.mp4").write_text("fake")
        mock_tv.return_value = {
            "duration": 30.0,
            "chunks": [{"id": 0}],
            "source": "video.mp4",
        }
        out = tmp_path / "out"
        result = batch_transcribe(str(tmp_path), str(out))

        assert result["file_count"] == 1
        assert result["files"][0]["filename"] == "video.mp4"
        assert result["files"][0]["duration"] == 30.0

    @patch("batch_transcribe.transcribe_video")
    def test_batch_multiple(self, mock_tv, tmp_path):
        """3 videos -> manifest with 3 entries, correct total_duration."""
        from batch_transcribe import batch_transcribe

        for name in ["a.mp4", "b.mov", "c.mkv"]:
            (tmp_path / name).write_text("fake")

        mock_tv.side_effect = [
            {"duration": 100.0, "chunks": [{"id": 0}], "source": "a.mp4"},
            {"duration": 200.0, "chunks": [{"id": 0}, {"id": 1}], "source": "b.mov"},
            {"duration": 300.0, "chunks": [{"id": 0}], "source": "c.mkv"},
        ]
        out = tmp_path / "out"
        result = batch_transcribe(str(tmp_path), str(out))

        assert result["file_count"] == 3
        assert result["total_duration"] == 600.0

    @patch("batch_transcribe.transcribe_video")
    def test_batch_error_handling(self, mock_tv, tmp_path):
        """One file fails transcription -> in errors list, others succeed."""
        from batch_transcribe import batch_transcribe

        (tmp_path / "bad.mp4").write_text("fake")
        (tmp_path / "good.mp4").write_text("fake")

        mock_tv.side_effect = [
            Exception("whisper crashed"),
            {"duration": 10.0, "chunks": [], "source": "good.mp4"},
        ]
        out = tmp_path / "out"
        result = batch_transcribe(str(tmp_path), str(out))

        assert result["file_count"] == 1
        assert len(result["errors"]) == 1
        assert "whisper crashed" in result["errors"][0]["error"]

    @patch("batch_transcribe.transcribe_video")
    def test_batch_case_insensitive(self, mock_tv, tmp_path):
        """.MOV and .mov both matched."""
        from batch_transcribe import batch_transcribe

        (tmp_path / "upper.MOV").write_text("fake")
        (tmp_path / "lower.mov").write_text("fake")

        mock_tv.return_value = {"duration": 5.0, "chunks": [], "source": "test"}
        out = tmp_path / "out"
        result = batch_transcribe(str(tmp_path), str(out))

        assert result["file_count"] == 2

    @patch("batch_transcribe.transcribe_video")
    def test_batch_no_recursion(self, mock_tv, tmp_path):
        """Files in subdirectories are NOT included."""
        from batch_transcribe import batch_transcribe

        (tmp_path / "top.mp4").write_text("fake")
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "nested.mp4").write_text("fake")

        mock_tv.return_value = {"duration": 5.0, "chunks": [], "source": "top.mp4"}
        out = tmp_path / "out"
        result = batch_transcribe(str(tmp_path), str(out))

        assert result["file_count"] == 1

    @patch("batch_transcribe.transcribe_video")
    def test_batch_manifest_schema(self, mock_tv, tmp_path):
        """Manifest has all required fields."""
        from batch_transcribe import batch_transcribe

        (tmp_path / "v.mp4").write_text("fake")
        mock_tv.return_value = {"duration": 10.0, "chunks": [], "source": "v.mp4"}
        out = tmp_path / "out"
        result = batch_transcribe(str(tmp_path), str(out))

        for key in ("input_dir", "file_count", "total_duration", "files", "errors"):
            assert key in result


# ===========================================================================
# auto_name tests (7)
# ===========================================================================

class TestAutoName:

    @patch("auto_name._load_nlp")
    def test_auto_name_with_entities(self, mock_load):
        """Transcript with 'Jensen Huang at SIGGRAPH' -> contains jensen-huang."""
        from auto_name import auto_name

        mock_load.return_value = _MockNLP(entities=[
            _MockEntity("Jensen Huang", "PERSON"),
            _MockEntity("SIGGRAPH", "EVENT"),
        ])

        transcript = _make_transcript(
            ["Jensen Huang keynote at SIGGRAPH about graphics"]
        )
        result = auto_name(transcript)

        assert "jensen" in result
        assert "huang" in result

    @patch("auto_name._load_nlp")
    def test_auto_name_no_entities(self, mock_load):
        """Plain transcript -> first significant words."""
        from auto_name import auto_name

        mock_load.return_value = _MockNLP(entities=[])

        transcript = _make_transcript(
            ["video editing software review tutorial"]
        )
        result = auto_name(transcript)

        assert len(result) > 0
        assert result != "untitled"

    def test_auto_name_empty(self):
        """Empty transcript -> 'untitled'."""
        from auto_name import auto_name

        assert auto_name({}) == "untitled"
        assert auto_name({"chunks": []}) == "untitled"

    @patch("auto_name._load_nlp")
    def test_auto_name_sanitize(self, mock_load):
        """Special chars removed, lowercase, hyphens."""
        from auto_name import auto_name

        mock_load.return_value = _MockNLP(entities=[
            _MockEntity("O'Brien & Co.", "ORG"),
        ])

        transcript = _make_transcript(["O'Brien & Co. discusses the future"])
        result = auto_name(transcript)

        assert "'" not in result
        assert "&" not in result
        assert result == result.lower()

    @patch("auto_name._load_nlp")
    def test_auto_name_max_words(self, mock_load):
        """Name respects max_words limit."""
        from auto_name import auto_name

        mock_load.return_value = _MockNLP(entities=[])

        transcript = _make_transcript(
            ["one two three four five six seven eight nine ten"]
        )
        result = auto_name(transcript, max_words=3)

        assert len(result.split("-")) <= 3

    @patch("auto_name._load_nlp")
    def test_batch_auto_name_dedup(self, mock_load, tmp_path):
        """Duplicate names get -2, -3 suffix."""
        from auto_name import batch_auto_name

        mock_load.return_value = _MockNLP(entities=[
            _MockEntity("Jensen Huang", "PERSON"),
        ])

        for stem in ["video1", "video2"]:
            transcript = _make_transcript(["Jensen Huang keynote at NVIDIA"])
            with open(tmp_path / f"{stem}_chunks.json", "w") as f:
                json.dump(transcript, f)

        manifest = {
            "files": [
                {"filename": "video1.mp4", "path": "video1.mp4"},
                {"filename": "video2.mp4", "path": "video2.mp4"},
            ]
        }

        result = batch_auto_name(manifest, str(tmp_path))
        names = [f["suggested_name"] for f in result["files"]]

        assert names[0] != names[1]
        assert "-2" in names[1]

    def test_auto_name_spacy_fallback(self):
        """spaCy load error -> fallback to word extraction."""
        from auto_name import auto_name

        with patch("auto_name._load_nlp", return_value=None):
            transcript = _make_transcript(
                ["interesting technology demonstration review"]
            )
            result = auto_name(transcript)

            assert result != "untitled"
            assert len(result) > 0


# ===========================================================================
# auto_chapter tests (7)
# ===========================================================================

class TestAutoChapter:

    def test_auto_chapter_basic(self, tmp_path):
        """Produces enhanced chapters with titles and entities."""
        from auto_chapter import auto_chapter

        transcript = _make_transcript([
            "Welcome to the SIGGRAPH keynote by Jensen Huang.",
            "Today we discuss real-time rendering technology.",
            "The new GPU architecture enables faster processing.",
            "NVIDIA announces breakthrough in ray tracing.",
        ], duration_per_chunk=30.0)

        with open(tmp_path / "test_chunks.json", "w") as f:
            json.dump(transcript, f)

        with patch("auto_chapter._load_nlp") as mock_nlp:
            mock_nlp.return_value = _MockNLP(entities=[
                _MockEntity("Jensen Huang", "PERSON"),
                _MockEntity("SIGGRAPH", "EVENT"),
                _MockEntity("NVIDIA", "ORG"),
            ])
            result = auto_chapter(str(tmp_path / "test.mp4"), str(tmp_path))

        assert "chapters" in result
        assert len(result["chapters"]) > 0

    def test_auto_chapter_no_silence(self, tmp_path):
        """Works without silence_map."""
        from auto_chapter import auto_chapter

        transcript = _make_transcript(
            ["Text chunk one.", "Text chunk two."], duration_per_chunk=40.0
        )
        with open(tmp_path / "vid_chunks.json", "w") as f:
            json.dump(transcript, f)

        with patch("auto_chapter._load_nlp", return_value=_MockNLP()):
            result = auto_chapter(str(tmp_path / "vid.mp4"), str(tmp_path))

        assert "chapters" in result
        assert not (tmp_path / "vid_silence.json").exists()

    def test_auto_chapter_spacy_titles(self, tmp_path):
        """Chapter titles include entity names when present."""
        from auto_chapter import auto_chapter

        transcript = _make_transcript([
            "Jensen Huang presents the keynote at GTC conference.",
        ], duration_per_chunk=60.0)

        with open(tmp_path / "talk_chunks.json", "w") as f:
            json.dump(transcript, f)

        mock_entities = [
            _MockEntity("Jensen Huang", "PERSON"),
            _MockEntity("GTC", "EVENT"),
        ]
        with patch("auto_chapter._load_nlp", return_value=_MockNLP(entities=mock_entities)):
            result = auto_chapter(str(tmp_path / "talk.mp4"), str(tmp_path))

        chapters = result["chapters"]
        assert len(chapters) >= 1
        assert len(chapters[0]["title"]) > 0

    def test_auto_chapter_summary(self, tmp_path):
        """Each chapter has summary field."""
        from auto_chapter import auto_chapter

        transcript = _make_transcript([
            "This is the first sentence. Then more content follows.",
        ], duration_per_chunk=60.0)
        with open(tmp_path / "s_chunks.json", "w") as f:
            json.dump(transcript, f)

        with patch("auto_chapter._load_nlp", return_value=_MockNLP()):
            result = auto_chapter(str(tmp_path / "s.mp4"), str(tmp_path))

        for ch in result["chapters"]:
            assert "summary" in ch
            assert isinstance(ch["summary"], str)

    def test_auto_chapter_entities(self, tmp_path):
        """key_entities list populated from NER."""
        from auto_chapter import auto_chapter

        transcript = _make_transcript([
            "NVIDIA CEO Jensen Huang at SIGGRAPH in Los Angeles."
        ], duration_per_chunk=60.0)
        with open(tmp_path / "ent_chunks.json", "w") as f:
            json.dump(transcript, f)

        mock_entities = [
            _MockEntity("Jensen Huang", "PERSON"),
            _MockEntity("NVIDIA", "ORG"),
            _MockEntity("Los Angeles", "GPE"),
        ]
        with patch("auto_chapter._load_nlp", return_value=_MockNLP(entities=mock_entities)):
            result = auto_chapter(str(tmp_path / "ent.mp4"), str(tmp_path))

        chapters = result["chapters"]
        assert len(chapters) >= 1
        entities = chapters[0]["key_entities"]
        assert isinstance(entities, list)
        assert len(entities) > 0

    def test_auto_chapter_single(self, tmp_path):
        """Short video -> single chapter still valid."""
        from auto_chapter import auto_chapter

        transcript = _make_transcript(
            ["Short clip content."], duration_per_chunk=15.0
        )
        with open(tmp_path / "short_chunks.json", "w") as f:
            json.dump(transcript, f)

        with patch("auto_chapter._load_nlp", return_value=_MockNLP()):
            result = auto_chapter(str(tmp_path / "short.mp4"), str(tmp_path))

        assert len(result["chapters"]) >= 1

    def test_auto_chapter_spacy_fallback(self, tmp_path):
        """spaCy fails -> original detect_chapters titles preserved."""
        from auto_chapter import auto_chapter

        transcript = _make_transcript([
            "Some content about video editing and production.",
        ], duration_per_chunk=60.0)
        with open(tmp_path / "fb_chunks.json", "w") as f:
            json.dump(transcript, f)

        with patch("auto_chapter._load_nlp", return_value=None):
            result = auto_chapter(str(tmp_path / "fb.mp4"), str(tmp_path))

        assert "chapters" in result
        assert len(result["chapters"]) >= 1
        assert isinstance(result["chapters"][0]["title"], str)


# ===========================================================================
# transcript_index tests (10)
# ===========================================================================

class TestTranscriptIndex:

    def _write_chunks(self, tmp_path, stem, texts):
        """Helper to write chunk files."""
        transcript = _make_transcript(texts)
        with open(tmp_path / f"{stem}_chunks.json", "w") as f:
            json.dump(transcript, f)

    @patch("transcript_index._load_nlp", return_value=None)
    def test_build_index_basic(self, mock_nlp, tmp_path):
        """Index built from manifest, word_count > 0."""
        from transcript_index import build_index

        self._write_chunks(tmp_path, "video1", ["Hello world this is a test video"])
        manifest = {"files": [{"filename": "video1.mp4"}]}
        index = build_index(manifest, str(tmp_path))

        assert index["word_count"] > 0
        assert index["files_indexed"] == 1

    def test_build_index_entities(self, tmp_path):
        """NER entities appear in entities index."""
        from transcript_index import build_index

        self._write_chunks(
            tmp_path, "video1",
            ["Jensen Huang speaks at NVIDIA conference"]
        )

        mock_entities = [
            _MockEntity("Jensen Huang", "PERSON"),
            _MockEntity("NVIDIA", "ORG"),
        ]
        manifest = {"files": [{"filename": "video1.mp4"}]}

        with patch("transcript_index._load_nlp",
                    return_value=_MockNLP(entities=mock_entities)):
            index = build_index(manifest, str(tmp_path))

        assert index["entity_count"] > 0
        assert "Jensen Huang" in index["entities"]

    @patch("transcript_index._load_nlp", return_value=None)
    def test_search_single_word(self, mock_nlp, tmp_path):
        """Search 'siggraph' -> results with file/chunk/start."""
        from transcript_index import build_index, search_index

        self._write_chunks(
            tmp_path, "v1",
            ["SIGGRAPH conference keynote presentation"]
        )
        manifest = {"files": [{"filename": "v1.mp4"}]}
        index = build_index(manifest, str(tmp_path))
        results = search_index(index, "siggraph")

        assert len(results) > 0
        assert "file" in results[0]
        assert "chunk" in results[0]
        assert "start" in results[0]

    @patch("transcript_index._load_nlp", return_value=None)
    def test_search_multi_word(self, mock_nlp, tmp_path):
        """Multi-word query intersects results."""
        from transcript_index import build_index, search_index

        self._write_chunks(tmp_path, "v1", [
            "SIGGRAPH conference keynote presentation",
            "another topic without those words",
            "SIGGRAPH presentation review session",
        ])
        manifest = {"files": [{"filename": "v1.mp4"}]}
        index = build_index(manifest, str(tmp_path))

        results = search_index(index, "siggraph presentation")
        assert len(results) >= 1

    @patch("transcript_index._load_nlp", return_value=None)
    def test_search_case_insensitive(self, mock_nlp, tmp_path):
        """'siggraph' matches 'SIGGRAPH'."""
        from transcript_index import build_index, search_index

        self._write_chunks(tmp_path, "v1", ["SIGGRAPH conference event"])
        manifest = {"files": [{"filename": "v1.mp4"}]}
        index = build_index(manifest, str(tmp_path))

        results = search_index(index, "siggraph")
        assert len(results) > 0

    @patch("transcript_index._load_nlp", return_value=None)
    def test_search_partial_match(self, mock_nlp, tmp_path):
        """'render' matches 'rendering' via startswith."""
        from transcript_index import build_index, search_index

        self._write_chunks(
            tmp_path, "v1",
            ["real-time rendering technology advances"]
        )
        manifest = {"files": [{"filename": "v1.mp4"}]}
        index = build_index(manifest, str(tmp_path))

        results = search_index(index, "render")
        assert len(results) > 0

    @patch("transcript_index._load_nlp", return_value=None)
    def test_search_no_results(self, mock_nlp, tmp_path):
        """Unknown word -> empty list."""
        from transcript_index import build_index, search_index

        self._write_chunks(tmp_path, "v1", ["hello world test"])
        manifest = {"files": [{"filename": "v1.mp4"}]}
        index = build_index(manifest, str(tmp_path))

        results = search_index(index, "xyznonexistent")
        assert results == []

    @patch("transcript_index._load_nlp", return_value=None)
    def test_search_max_results(self, mock_nlp, tmp_path):
        """Results capped at max_results."""
        from transcript_index import build_index, search_index

        texts = [f"technology advance number {i}" for i in range(30)]
        self._write_chunks(tmp_path, "v1", texts)
        manifest = {"files": [{"filename": "v1.mp4"}]}
        index = build_index(manifest, str(tmp_path))

        results = search_index(index, "technology", max_results=5)
        assert len(results) <= 5

    @patch("transcript_index._load_nlp", return_value=None)
    def test_index_empty_manifest(self, mock_nlp, tmp_path):
        """Empty manifest -> index with 0 counts."""
        from transcript_index import build_index

        manifest = {"files": []}
        index = build_index(manifest, str(tmp_path))

        assert index["word_count"] == 0
        assert index["files_indexed"] == 0

    @patch("transcript_index._load_nlp", return_value=None)
    def test_index_schema(self, mock_nlp, tmp_path):
        """Index has all required top-level fields."""
        from transcript_index import build_index

        manifest = {"files": []}
        index = build_index(manifest, str(tmp_path))

        for key in ("word_count", "entity_count", "files_indexed", "words", "entities"):
            assert key in index


# ===========================================================================
# shot_matcher tests (8)
# ===========================================================================

class TestShotMatcher:

    def _write_chunks(self, tmp_path, stem, texts):
        """Helper to write chunk files."""
        transcript = _make_transcript(texts)
        with open(tmp_path / f"{stem}_chunks.json", "w") as f:
            json.dump(transcript, f)

    def test_match_basic(self, tmp_path):
        """Two similar chunks across files -> match found."""
        from shot_matcher import find_matching_shots

        shared = ("this is a repeated segment about real-time "
                  "rendering technology and graphics processing")
        self._write_chunks(tmp_path, "video1", [shared])
        self._write_chunks(tmp_path, "video2", [shared])

        manifest = {"files": [
            {"filename": "video1.mp4"},
            {"filename": "video2.mp4"},
        ]}

        matches = find_matching_shots(manifest, str(tmp_path), similarity_threshold=0.5)
        assert len(matches) > 0
        assert matches[0]["similarity"] >= 0.5

    def test_match_threshold(self, tmp_path):
        """Below threshold -> not returned."""
        from shot_matcher import find_matching_shots

        self._write_chunks(
            tmp_path, "v1",
            ["completely different content about cooking and food preparation recipes"]
        )
        self._write_chunks(
            tmp_path, "v2",
            ["video editing software tutorial for beginners starting from scratch today"]
        )

        manifest = {"files": [
            {"filename": "v1.mp4"},
            {"filename": "v2.mp4"},
        ]}
        matches = find_matching_shots(
            manifest, str(tmp_path), similarity_threshold=0.9
        )
        assert len(matches) == 0

    def test_match_skip_same_file(self, tmp_path):
        """Same-file comparisons excluded."""
        from shot_matcher import find_matching_shots

        text = ("this is some repeated text about technology "
                "and rendering in modern systems")
        self._write_chunks(tmp_path, "v1", [text, text])

        manifest = {"files": [{"filename": "v1.mp4"}]}
        matches = find_matching_shots(
            manifest, str(tmp_path), similarity_threshold=0.5
        )
        assert len(matches) == 0

    def test_match_skip_short_chunks(self, tmp_path):
        """Chunks < 10 words skipped."""
        from shot_matcher import find_matching_shots

        self._write_chunks(tmp_path, "v1", ["short text"])
        self._write_chunks(tmp_path, "v2", ["short text"])

        manifest = {"files": [
            {"filename": "v1.mp4"},
            {"filename": "v2.mp4"},
        ]}
        matches = find_matching_shots(
            manifest, str(tmp_path), similarity_threshold=0.1
        )
        assert len(matches) == 0

    def test_match_similarity_range(self, tmp_path):
        """All similarities between 0.0 and 1.0."""
        from shot_matcher import find_matching_shots

        text = ("this is a test segment about real-time "
                "rendering technology and modern graphics")
        self._write_chunks(tmp_path, "v1", [text])
        self._write_chunks(
            tmp_path, "v2",
            [text + " with some extra words added at the end"]
        )

        manifest = {"files": [
            {"filename": "v1.mp4"},
            {"filename": "v2.mp4"},
        ]}
        matches = find_matching_shots(
            manifest, str(tmp_path), similarity_threshold=0.3
        )
        for m in matches:
            assert 0.0 <= m["similarity"] <= 1.0

    def test_match_empty_manifest(self, tmp_path):
        """Empty manifest -> empty matches list."""
        from shot_matcher import find_matching_shots

        manifest = {"files": []}
        matches = find_matching_shots(manifest, str(tmp_path))
        assert matches == []

    def test_match_preview_text(self, tmp_path):
        """Match includes shared_text_preview."""
        from shot_matcher import find_matching_shots

        text = ("this is a repeated segment about real-time "
                "rendering technology and graphics processing")
        self._write_chunks(tmp_path, "v1", [text])
        self._write_chunks(tmp_path, "v2", [text])

        manifest = {"files": [
            {"filename": "v1.mp4"},
            {"filename": "v2.mp4"},
        ]}
        matches = find_matching_shots(
            manifest, str(tmp_path), similarity_threshold=0.5
        )
        assert len(matches) > 0
        assert "shared_text_preview" in matches[0]
        assert len(matches[0]["shared_text_preview"]) > 0

    def test_match_schema(self, tmp_path):
        """Each match has all required fields."""
        from shot_matcher import find_matching_shots

        text = ("this is a repeated segment about real-time "
                "rendering technology and graphics processing")
        self._write_chunks(tmp_path, "v1", [text])
        self._write_chunks(tmp_path, "v2", [text])

        manifest = {"files": [
            {"filename": "v1.mp4"},
            {"filename": "v2.mp4"},
        ]}
        matches = find_matching_shots(
            manifest, str(tmp_path), similarity_threshold=0.5
        )
        assert len(matches) > 0

        required = {
            "file_a", "chunk_a", "start_a",
            "file_b", "chunk_b", "start_b",
            "similarity", "shared_text_preview",
        }
        assert required.issubset(set(matches[0].keys()))
