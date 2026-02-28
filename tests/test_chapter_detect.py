"""Tests for chapter_detect.py — all offline, pure Python, no external deps."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools"))
from chapter_detect import (
    detect_chapters,
    _find_boundaries_from_silence_map,
    _find_boundaries_from_chunks,
    _chunk_title,
    _resolve_duration,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def _make_chunk(
    cid: int,
    start: float | None = None,
    end: float | None = None,
    text: str = "",
    silence_ratio: float = 0.2,
    has_speech: bool = True,
) -> dict:
    """Build a minimal chunk dict for testing."""
    if start is None:
        start = cid * 10.0
    if end is None:
        end = start + 10.0
    return {
        "id": cid,
        "start": start,
        "end": end,
        "text": text,
        "word_count": len(text.split()) if text.strip() else 0,
        "silence_ratio": silence_ratio,
        "has_speech": has_speech,
    }


def _make_chunks(n: int, **overrides) -> list[dict]:
    """Create *n* sequential 10-second chunks with speech."""
    chunks = []
    for i in range(n):
        kw = {"cid": i, "text": f"chunk {i} words here for testing purposes"}
        kw.update(overrides)
        kw["cid"] = i  # Always override to keep sequential
        chunks.append(_make_chunk(**kw))
    return chunks


def _make_silence_map(
    gaps: list[dict] | None = None,
    duration: float = 100.0,
) -> dict:
    """Build a minimal silence_map dict for testing."""
    if gaps is None:
        gaps = []
    return {
        "source": "test.mp4",
        "duration": duration,
        "threshold_db": -30.0,
        "gaps": gaps,
        "speech": [],
        "stats": {"total_silence": 0, "total_speech": duration, "silence_percentage": 0.0, "gap_count": len(gaps)},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBasicChapterDetectionWithSilenceMap:
    """Test chapter detection using silence_map gaps as boundary markers."""

    def test_two_chapters_from_single_gap(self):
        """A single long silence gap in the middle splits into 2 chapters."""
        chunks = _make_chunks(10)  # 0-100s
        silence_map = _make_silence_map(
            gaps=[{"start": 50.0, "end": 55.0, "duration": 5.0}],
            duration=100.0,
        )

        chapters = detect_chapters(
            chunks, silence_map=silence_map,
            min_chapter_duration=10.0, silence_gap_threshold=2.0,
        )

        assert len(chapters) == 2
        assert chapters[0]["chapter_id"] == 0
        assert chapters[0]["start"] == 0.0
        assert chapters[0]["chunk_ids"] == [0, 1, 2, 3, 4]
        assert chapters[1]["chapter_id"] == 1
        assert chapters[1]["start"] == 50.0
        assert chapters[1]["chunk_ids"] == [5, 6, 7, 8, 9]

    def test_three_chapters_from_two_gaps(self):
        """Two gaps produce 3 chapters."""
        chunks = _make_chunks(9)  # 0-90s
        silence_map = _make_silence_map(
            gaps=[
                {"start": 30.0, "end": 33.0, "duration": 3.0},
                {"start": 60.0, "end": 63.0, "duration": 3.0},
            ],
            duration=90.0,
        )

        chapters = detect_chapters(
            chunks, silence_map=silence_map,
            min_chapter_duration=10.0, silence_gap_threshold=2.0,
        )

        assert len(chapters) == 3
        assert chapters[0]["chunk_ids"] == [0, 1, 2]
        assert chapters[1]["chunk_ids"] == [3, 4, 5]
        assert chapters[2]["chunk_ids"] == [6, 7, 8]

    def test_gap_below_threshold_ignored(self):
        """Gaps shorter than silence_gap_threshold do not create boundaries."""
        chunks = _make_chunks(6)  # 0-60s
        silence_map = _make_silence_map(
            gaps=[{"start": 30.0, "end": 31.0, "duration": 1.0}],  # < 2.0s threshold
            duration=60.0,
        )

        chapters = detect_chapters(
            chunks, silence_map=silence_map,
            min_chapter_duration=10.0, silence_gap_threshold=2.0,
        )

        assert len(chapters) == 1
        assert chapters[0]["chunk_ids"] == [0, 1, 2, 3, 4, 5]


class TestFallbackWithoutSilenceMap:
    """Test chapter detection using chunk silence_ratio when no silence_map."""

    def test_high_silence_ratio_creates_boundary(self):
        """Chunks with silence_ratio > 0.8 mark chapter boundaries."""
        chunks = _make_chunks(6)
        # Make chunk 3 a high-silence chunk (boundary marker).
        chunks[3]["silence_ratio"] = 0.9

        chapters = detect_chapters(
            chunks, silence_map=None,
            min_chapter_duration=10.0,
        )

        assert len(chapters) == 2
        assert chapters[0]["chunk_ids"] == [0, 1, 2]
        # Chunk 3 starts the second chapter since its start is the boundary.
        assert chapters[1]["chunk_ids"] == [3, 4, 5]

    def test_all_low_silence_ratio_single_chapter(self):
        """No chunk exceeds threshold -> entire video is one chapter."""
        chunks = _make_chunks(5)
        # All default silence_ratio=0.2 -> well below 0.8.

        chapters = detect_chapters(chunks, silence_map=None, min_chapter_duration=10.0)

        assert len(chapters) == 1
        assert chapters[0]["chunk_ids"] == [0, 1, 2, 3, 4]


class TestMinChapterDurationMerging:
    """Test that short chapters are merged into the previous chapter."""

    def test_short_chapter_merged_into_previous(self):
        """A 10-second chapter (below 30s min) gets merged."""
        chunks = _make_chunks(10)  # 0-100s
        silence_map = _make_silence_map(
            gaps=[
                {"start": 30.0, "end": 33.0, "duration": 3.0},  # boundary at 30s
                {"start": 40.0, "end": 43.0, "duration": 3.0},  # boundary at 40s -> only 10s chapter
            ],
            duration=100.0,
        )

        chapters = detect_chapters(
            chunks, silence_map=silence_map,
            min_chapter_duration=30.0, silence_gap_threshold=2.0,
        )

        # Chunks 0-2 = chapter 0 (30s).
        # Chunks 3 = 10s, too short, merged into chapter 0.
        # Chunks 4-9 = chapter 1 (60s).
        assert len(chapters) == 2
        assert 3 in chapters[0]["chunk_ids"]
        assert chapters[0]["chunk_ids"] == [0, 1, 2, 3]
        assert chapters[1]["chunk_ids"] == [4, 5, 6, 7, 8, 9]

    def test_multiple_short_chapters_cascade_merge(self):
        """Multiple consecutive short chapters all merge into one."""
        # 7 chunks, boundaries every 10s -> all would be 10s chapters.
        chunks = _make_chunks(7)  # 0-70s
        silence_map = _make_silence_map(
            gaps=[
                {"start": 10.0, "end": 12.5, "duration": 2.5},
                {"start": 20.0, "end": 22.5, "duration": 2.5},
                {"start": 30.0, "end": 32.5, "duration": 2.5},
                {"start": 40.0, "end": 42.5, "duration": 2.5},
                {"start": 50.0, "end": 52.5, "duration": 2.5},
                {"start": 60.0, "end": 62.5, "duration": 2.5},
            ],
            duration=70.0,
        )

        chapters = detect_chapters(
            chunks, silence_map=silence_map,
            min_chapter_duration=30.0, silence_gap_threshold=2.0,
        )

        # Each raw chapter would be 10s. Merging:
        # Ch 0: [0] 10s < 30s -> start
        # Ch 1: [1] 10s < 30s -> merge into ch 0 -> [0,1] 20s
        # Ch 2: [2] 10s < 30s -> merge into ch 0 -> [0,1,2] 30s
        # Ch 3: [3] 10s < 30s -> merge into ch 0 -> [0,1,2,3] 40s
        # Ch 4: [4] 10s < 30s -> merge into ch 0 -> [0,1,2,3,4] 50s
        # Wait, re-read the logic: first chapter always starts, then short
        # ones merge. Let me check: ch0=[0] (10s), ch1=[1] merge -> [0,1] (20s),
        # ch2=[2] merge -> [0,1,2] (30s), ch3=[3] 10s < 30 merge -> [0,1,2,3] 40s ...
        # Actually the first raw chapter is always kept. Then short ones merge.
        # The min_chapter_duration check looks at the NEW chapter's duration.
        # So: raw=[0],[1],[2],[3],[4],[5],[6]. Each is 10s.
        # merged starts: [0] kept. [1] is 10s < 30 -> merge into prev: [0,1].
        # [2] is 10s < 30 -> merge: [0,1,2]. [3] is 10s < 30 -> merge: [0,1,2,3].
        # [4] is 10s < 30 -> merge: [0,1,2,3,4]. [5] is 10s < 30 -> merge: [0,1,2,3,4,5].
        # [6] is 10s < 30 -> merge: [0,1,2,3,4,5,6].
        # Result: 1 chapter.
        assert len(chapters) == 1
        assert chapters[0]["chunk_ids"] == [0, 1, 2, 3, 4, 5, 6]


class TestSingleChunkInput:
    """Test with a single chunk."""

    def test_single_chunk_produces_one_chapter(self):
        """A single chunk always produces exactly one chapter."""
        chunks = [_make_chunk(0, text="Hello world welcome to the show")]

        chapters = detect_chapters(chunks)

        assert len(chapters) == 1
        assert chapters[0]["chapter_id"] == 0
        assert chapters[0]["start"] == 0.0
        assert chapters[0]["end"] == 10.0
        assert chapters[0]["chunk_ids"] == [0]
        assert chapters[0]["title"] == "Hello world welcome to the show."

    def test_single_chunk_with_silence_map(self):
        """Single chunk with silence_map still produces one chapter."""
        chunks = [_make_chunk(0, text="Only chunk")]
        silence_map = _make_silence_map(duration=10.0)

        chapters = detect_chapters(chunks, silence_map=silence_map)

        assert len(chapters) == 1


class TestEmptyChunksList:
    """Test with empty chunks input."""

    def test_empty_chunks_returns_empty(self):
        """Empty input produces empty output."""
        chapters = detect_chapters([])
        assert chapters == []

    def test_empty_chunks_with_silence_map_returns_empty(self):
        """Empty chunks with silence_map still returns empty."""
        silence_map = _make_silence_map(
            gaps=[{"start": 5.0, "end": 8.0, "duration": 3.0}],
            duration=100.0,
        )
        chapters = detect_chapters([], silence_map=silence_map)
        assert chapters == []


class TestChapterTitleGeneration:
    """Test that chapter titles use first 8 words of first speech chunk."""

    def test_title_from_first_speech_chunk(self):
        """Title comes from the first chunk with has_speech=True."""
        chunks = [
            _make_chunk(0, text="", has_speech=False, silence_ratio=1.0),
            _make_chunk(1, text="Hello everyone welcome to the big grand opening ceremony today"),
        ]

        chapters = detect_chapters(chunks, min_chapter_duration=5.0)

        assert len(chapters) == 1
        assert chapters[0]["title"] == "Hello everyone welcome to the big grand opening ceremony today."

    def test_title_truncated_to_25_words(self):
        """Title is capped at 25 words even if text is longer."""
        text = " ".join(f"word{i}" for i in range(30))
        chunks = [_make_chunk(0, text=text)]

        chapters = detect_chapters(chunks)

        title = chapters[0]["title"]
        # 25 words + trailing period
        assert len(title.rstrip(".").split()) == 25

    def test_title_empty_when_no_speech(self):
        """Title is empty string when no chunks have speech."""
        chunks = [
            _make_chunk(0, text="", has_speech=False, silence_ratio=1.0),
            _make_chunk(1, text="", has_speech=False, silence_ratio=1.0),
        ]

        chapters = detect_chapters(chunks, min_chapter_duration=5.0)

        assert chapters[0]["title"] == ""

    def test_title_short_text_not_padded(self):
        """A chunk with fewer than 8 words uses all of them."""
        chunks = [_make_chunk(0, text="Hi there")]

        chapters = detect_chapters(chunks)

        assert chapters[0]["title"] == "Hi there."

    def test_title_strips_leading_filler(self):
        """Leading filler words (um, so, basically) are removed."""
        chunks = [_make_chunk(0, text="um so basically the project is amazing")]

        chapters = detect_chapters(chunks)

        assert chapters[0]["title"] == "The project is amazing."

    def test_title_has_trailing_period(self):
        """All non-empty titles end with a period (or punctuation)."""
        chunks = [_make_chunk(0, text="Welcome to the show")]

        chapters = detect_chapters(chunks)

        assert chapters[0]["title"].endswith(".")

    def test_title_sentence_case(self):
        """First character is uppercased."""
        chunks = [_make_chunk(0, text="hello world")]

        chapters = detect_chapters(chunks)

        assert chapters[0]["title"][0].isupper()
        assert chapters[0]["title"] == "Hello world."

    def test_title_multi_chunk_concatenation(self):
        """Title gathers words from multiple chunks when first is short."""
        chunks = [
            _make_chunk(0, text="Start here"),
            _make_chunk(1, text="continue there"),
        ]

        title = _chunk_title(chunks, [0, 1])

        assert "Start" in title
        assert "continue" in title

    def test_title_capped_at_25_words(self):
        """Long text across chunks is capped at 25 words."""
        text = " ".join(f"word{i}" for i in range(40))
        chunks = [_make_chunk(0, text=text)]

        title = _chunk_title(chunks, [0])

        assert len(title.rstrip(".").split()) == 25

    def test_title_all_filler_returns_empty(self):
        """Chunks with only filler words produce an empty title."""
        chunks = [_make_chunk(0, text="um uh like")]

        chapters = detect_chapters(chunks)

        assert chapters[0]["title"] == ""


class TestNoSilenceGaps:
    """Test when silence_map has zero gaps -> entire video = 1 chapter."""

    def test_no_gaps_single_chapter(self):
        """Empty gaps list means the entire video is one chapter."""
        chunks = _make_chunks(10)
        silence_map = _make_silence_map(gaps=[], duration=100.0)

        chapters = detect_chapters(
            chunks, silence_map=silence_map,
            min_chapter_duration=30.0, silence_gap_threshold=2.0,
        )

        assert len(chapters) == 1
        assert chapters[0]["chapter_id"] == 0
        assert chapters[0]["start"] == 0.0
        assert chapters[0]["end"] == 100.0
        assert chapters[0]["chunk_ids"] == list(range(10))


class TestDurationParameterInference:
    """Test the duration parameter and inference logic."""

    def test_explicit_duration_overrides_all(self):
        """Explicit duration param takes priority over silence_map and chunks."""
        chunks = _make_chunks(3)  # ends at 30.0
        silence_map = _make_silence_map(duration=30.0)

        chapters = detect_chapters(
            chunks, silence_map=silence_map,
            duration=500.0, min_chapter_duration=10.0,
        )

        # Last chapter's end should extend to 500.0.
        assert chapters[-1]["end"] == 500.0

    def test_duration_from_silence_map(self):
        """When no explicit duration, silence_map duration is used."""
        chunks = _make_chunks(3)  # chunk ends at 30.0
        silence_map = _make_silence_map(duration=200.0)

        chapters = detect_chapters(
            chunks, silence_map=silence_map,
            min_chapter_duration=10.0,
        )

        assert chapters[-1]["end"] == 200.0

    def test_duration_from_last_chunk(self):
        """When no silence_map and no explicit duration, last chunk end is used."""
        chunks = _make_chunks(5)  # ends at 50.0

        chapters = detect_chapters(chunks, min_chapter_duration=10.0)

        assert chapters[-1]["end"] == 50.0

    def test_resolve_duration_priority(self):
        """_resolve_duration follows priority: explicit > silence_map > chunks."""
        chunks = [_make_chunk(0, start=0, end=10)]
        sm = _make_silence_map(duration=99.0)

        # Explicit wins.
        assert _resolve_duration(chunks, sm, 42.0) == 42.0
        # silence_map next.
        assert _resolve_duration(chunks, sm, None) == 99.0
        # Chunks last.
        assert _resolve_duration(chunks, None, None) == 10.0
        # Nothing: 0.0.
        assert _resolve_duration([], None, None) == 0.0


class TestChapterSchema:
    """Test that output chapter dicts have all required keys and correct types."""

    def test_chapter_keys(self):
        chunks = _make_chunks(4)

        chapters = detect_chapters(chunks, min_chapter_duration=10.0)

        for ch in chapters:
            assert "chapter_id" in ch
            assert "start" in ch
            assert "end" in ch
            assert "duration" in ch
            assert "chunk_ids" in ch
            assert "title" in ch
            assert isinstance(ch["chapter_id"], int)
            assert isinstance(ch["start"], float)
            assert isinstance(ch["end"], float)
            assert isinstance(ch["duration"], (int, float))
            assert isinstance(ch["chunk_ids"], list)
            assert isinstance(ch["title"], str)

    def test_chapter_ids_sequential(self):
        """Chapter IDs start at 0 and are sequential."""
        chunks = _make_chunks(10)
        silence_map = _make_silence_map(
            gaps=[
                {"start": 30.0, "end": 33.0, "duration": 3.0},
                {"start": 60.0, "end": 63.0, "duration": 3.0},
            ],
            duration=100.0,
        )

        chapters = detect_chapters(
            chunks, silence_map=silence_map,
            min_chapter_duration=10.0, silence_gap_threshold=2.0,
        )

        ids = [ch["chapter_id"] for ch in chapters]
        assert ids == list(range(len(ids)))

    def test_duration_matches_start_end(self):
        """Each chapter's duration equals end - start."""
        chunks = _make_chunks(6)
        silence_map = _make_silence_map(
            gaps=[{"start": 30.0, "end": 33.0, "duration": 3.0}],
            duration=60.0,
        )

        chapters = detect_chapters(
            chunks, silence_map=silence_map,
            min_chapter_duration=10.0, silence_gap_threshold=2.0,
        )

        for ch in chapters:
            expected_dur = ch["end"] - ch["start"]
            assert abs(ch["duration"] - expected_dur) < 1e-5


class TestRealDataShape:
    """Integration-style test using real chunks.json + silence_map.json data."""

    @pytest.fixture
    def real_chunks(self):
        """Load real SIGGRAPH chunks if available, else skip."""
        p = Path("C:/AT01/temp/chunks.json")
        if not p.exists():
            pytest.skip("Real chunks.json not available")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("chunks", data)

    @pytest.fixture
    def real_silence_map(self):
        """Load real silence_map if available, else skip."""
        p = Path("C:/AT01/temp/silence_map.json")
        if not p.exists():
            pytest.skip("Real silence_map.json not available")
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def test_real_data_produces_chapters(self, real_chunks, real_silence_map):
        """Real data produces at least one chapter with valid schema."""
        chapters = detect_chapters(
            real_chunks,
            silence_map=real_silence_map,
            min_chapter_duration=30.0,
            silence_gap_threshold=2.0,
        )

        assert len(chapters) >= 1

        # All chunk IDs from input should appear in exactly one chapter.
        all_chunk_ids = set()
        for ch in chapters:
            for cid in ch["chunk_ids"]:
                assert cid not in all_chunk_ids, f"Chunk {cid} in multiple chapters"
                all_chunk_ids.add(cid)

        input_ids = {c["id"] for c in real_chunks}
        assert all_chunk_ids == input_ids, "Not all chunks assigned to chapters"

    def test_real_data_fallback_mode(self, real_chunks):
        """Real data without silence_map uses fallback detection."""
        chapters = detect_chapters(
            real_chunks,
            silence_map=None,
            min_chapter_duration=30.0,
        )

        assert len(chapters) >= 1
        # First chapter always starts at 0.
        assert chapters[0]["start"] == 0.0
