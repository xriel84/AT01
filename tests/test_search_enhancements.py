"""Tests for S20 search enhancements: auto-build index + chunk_text in results."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_tools_dir = str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from transcript_index import search_index, build_index, auto_build_index
from fastapi.testclient import TestClient
from agents.edbot.server import app, _cache, _session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_state():
    _cache["chunks"] = None
    _cache["silence_map"] = None
    _cache["last_input"] = None
    for key in _session:
        _session[key] = None
    yield


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def sample_chunks_dir(tmp_path):
    """Create a temp dir with chunk files mimicking transcription output."""
    chunks_data = {
        "chunks": [
            {"id": 0, "start": 0.0, "end": 10.0, "text": "Hello world OpenXR demo",
             "word_count": 4, "silence_ratio": 0.1, "has_speech": True},
            {"id": 1, "start": 10.0, "end": 20.0, "text": "Unreal Engine rendering pipeline",
             "word_count": 4, "silence_ratio": 0.2, "has_speech": True},
            {"id": 2, "start": 20.0, "end": 30.0, "text": "",
             "word_count": 0, "silence_ratio": 1.0, "has_speech": False},
        ],
    }
    with open(tmp_path / "demo_chunks.json", "w", encoding="utf-8") as f:
        json.dump(chunks_data, f)
    return tmp_path


@pytest.fixture()
def sample_index_with_text():
    """An index that includes chunk_texts and filenames."""
    return {
        "word_count": 10,
        "entity_count": 0,
        "files_indexed": 1,
        "words": {
            "hello": [{"file": 0, "chunk": 0, "start": 0.0}],
            "world": [{"file": 0, "chunk": 0, "start": 0.0}],
            "openxr": [{"file": 0, "chunk": 0, "start": 0.0}],
            "unreal": [{"file": 0, "chunk": 1, "start": 10.0}],
            "engine": [{"file": 0, "chunk": 1, "start": 10.0}],
            "rendering": [{"file": 0, "chunk": 1, "start": 10.0}],
            "pipeline": [{"file": 0, "chunk": 1, "start": 10.0}],
        },
        "entities": {},
        "chunk_texts": {
            "0:0": "Hello world OpenXR demo",
            "0:1": "Unreal Engine rendering pipeline",
        },
        "filenames": ["demo.mov"],
    }


# ---------------------------------------------------------------------------
# Enhancement #2: chunk_text in search results
# ---------------------------------------------------------------------------

class TestChunkTextInResults:

    def test_search_returns_chunk_text(self, sample_index_with_text):
        results = search_index(sample_index_with_text, "hello")
        assert len(results) >= 1
        assert results[0]["chunk_text"] == "Hello world OpenXR demo"

    def test_search_returns_filename(self, sample_index_with_text):
        results = search_index(sample_index_with_text, "unreal")
        assert len(results) >= 1
        assert results[0].get("filename") == "demo.mov"

    def test_chunk_text_empty_for_old_index(self):
        """Old indexes without chunk_texts still work, return empty string."""
        old_index = {
            "words": {"hello": [{"file": 0, "chunk": 0, "start": 0.0}]},
            "entities": {},
        }
        results = search_index(old_index, "hello")
        assert len(results) >= 1
        assert results[0]["chunk_text"] == ""

    def test_multiword_search_has_chunk_text(self, sample_index_with_text):
        results = search_index(sample_index_with_text, "hello world")
        assert len(results) >= 1
        assert "OpenXR" in results[0]["chunk_text"]

    def test_no_match_no_chunk_text(self, sample_index_with_text):
        results = search_index(sample_index_with_text, "zzzznotfound")
        assert results == []


# ---------------------------------------------------------------------------
# Enhancement #1: auto_build_index
# ---------------------------------------------------------------------------

class TestAutoBuildIndex:

    def test_auto_build_from_manifest(self, sample_chunks_dir):
        manifest = {"files": [{"filename": "demo.mov"}]}
        with open(sample_chunks_dir / "batch_manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        index = auto_build_index(str(sample_chunks_dir))
        assert index is not None
        assert index["files_indexed"] == 1
        assert "chunk_texts" in index
        assert "0:0" in index["chunk_texts"]

    def test_auto_build_fallback_no_manifest(self, sample_chunks_dir):
        """Falls back to scanning *_chunks.json when no manifest."""
        index = auto_build_index(str(sample_chunks_dir))
        assert index is not None
        assert index["files_indexed"] == 1

    def test_auto_build_no_chunks(self, tmp_path):
        """Returns None when no chunk files exist."""
        assert auto_build_index(str(tmp_path)) is None

    def test_auto_build_writes_index_file(self, sample_chunks_dir):
        auto_build_index(str(sample_chunks_dir))
        index_path = sample_chunks_dir / "transcript_index.json"
        assert index_path.exists()
        with open(index_path, encoding="utf-8") as f:
            data = json.load(f)
        assert "words" in data
        assert "chunk_texts" in data

    def test_build_index_stores_chunk_texts(self, sample_chunks_dir):
        manifest = {"files": [{"filename": "demo.mov"}]}
        index = build_index(manifest, str(sample_chunks_dir))
        assert "0:0" in index["chunk_texts"]
        assert index["chunk_texts"]["0:0"] == "Hello world OpenXR demo"
        # Chunk 2 (empty text) should NOT be in chunk_texts
        assert "0:2" not in index["chunk_texts"]

    def test_build_index_stores_filenames(self, sample_chunks_dir):
        manifest = {"files": [{"filename": "demo.mov"}]}
        index = build_index(manifest, str(sample_chunks_dir))
        assert index["filenames"] == ["demo.mov"]


# ---------------------------------------------------------------------------
# Server endpoint: auto-build + build-index
# ---------------------------------------------------------------------------

class TestBuildIndexEndpoint:

    def test_build_index_no_chunks(self, client):
        with patch("agents.edbot.server.Path") as MockPath:
            # No chunk files
            mock_instance = MagicMock()
            mock_instance.exists.return_value = False
            mock_instance.glob.return_value = []
            MockPath.return_value = mock_instance

            with patch("transcript_index.auto_build_index", return_value=None):
                resp = client.post("/api/build-index")
                assert resp.status_code in (404, 500)


class TestSearchAutoBuilds:

    def test_search_succeeds_after_auto_build(self, sample_chunks_dir):
        """Search auto-builds index when missing, then returns results."""
        index = auto_build_index(str(sample_chunks_dir))
        assert index is not None
        results = search_index(index, "openxr")
        assert len(results) >= 1
        assert results[0]["chunk_text"] == "Hello world OpenXR demo"
