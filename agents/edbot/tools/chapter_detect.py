"""Rule-based chapter detection from transcription chunks and silence map.

Identifies chapter boundaries by locating silence gaps (from silence_map.json)
or high-silence chunks (from chunks.json), then merges short chapters to enforce
a minimum duration. Produces a chapter list with IDs, timestamps, chunk ranges,
and auto-generated titles from the first speech in each chapter.
"""

import argparse
import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MIN_CHAPTER_DURATION = 30.0
DEFAULT_SILENCE_GAP_THRESHOLD = 2.0
FALLBACK_SILENCE_RATIO = 0.8
TITLE_WORD_LIMIT = 8


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_boundaries_from_silence_map(
    silence_map: dict,
    silence_gap_threshold: float,
) -> list[float]:
    """Return a sorted list of chapter-boundary timestamps from silence_map gaps.

    A boundary is placed at the start of any silence gap whose duration meets
    or exceeds *silence_gap_threshold* (>=).
    """
    boundaries: list[float] = []
    for gap in silence_map.get("gaps", []):
        if gap.get("duration", 0.0) >= silence_gap_threshold:
            boundaries.append(gap["start"])
    return sorted(boundaries)


def _find_boundaries_from_chunks(
    chunks: list[dict],
    silence_ratio_threshold: float = FALLBACK_SILENCE_RATIO,
) -> list[float]:
    """Return boundary timestamps inferred from chunks with high silence ratio.

    When no silence_map is available, chunks whose silence_ratio strictly
    exceeds the threshold (>) are treated as chapter separators. The boundary
    is placed at the start of such a chunk. Strict > is used because a ratio
    of exactly 0.8 is ambiguous, while gap duration uses >= because an exact
    match clearly qualifies.
    """
    boundaries: list[float] = []
    for chunk in chunks:
        if chunk.get("silence_ratio", 0.0) > silence_ratio_threshold:
            boundaries.append(chunk["start"])
    return sorted(boundaries)


def _chunk_title(chunks: list[dict], chunk_ids: list[int]) -> str:
    """Generate a chapter title from the first speech chunk in the range.

    Returns the first *TITLE_WORD_LIMIT* words from the first chunk that
    has speech text. Returns an empty string if no speech is found.
    """
    # Build a quick lookup by chunk id.
    by_id: dict[int, dict] = {c["id"]: c for c in chunks}
    for cid in chunk_ids:
        chunk = by_id.get(cid)
        if chunk and chunk.get("has_speech") and chunk.get("text", "").strip():
            words = chunk["text"].split()
            return " ".join(words[:TITLE_WORD_LIMIT])
    return ""


def _resolve_duration(
    chunks: list[dict],
    silence_map: dict | None,
    duration: float | None,
) -> float:
    """Determine the total duration to use for the final chapter's end time.

    Priority:
        1. Explicit *duration* parameter.
        2. silence_map["duration"].
        3. Last chunk's end time.
        4. 0.0 as a last resort.
    """
    if duration is not None:
        return duration
    if silence_map is not None and "duration" in silence_map:
        return float(silence_map["duration"])
    if chunks:
        return float(chunks[-1]["end"])
    return 0.0


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def detect_chapters(
    chunks: list[dict],
    silence_map: dict | None = None,
    duration: float | None = None,
    min_chapter_duration: float = DEFAULT_MIN_CHAPTER_DURATION,
    silence_gap_threshold: float = DEFAULT_SILENCE_GAP_THRESHOLD,
) -> list[dict]:
    """Detect chapter boundaries from transcription chunks and optional silence map.

    Args:
        chunks: List of chunk dicts from transcribe_video (each has id, start,
            end, text, word_count, silence_ratio, has_speech).
        silence_map: Optional silence map dict from detect_silence (has gaps,
            speech, stats, duration). When provided, silence gaps drive chapter
            boundaries; otherwise, high-silence-ratio chunks are used.
        duration: Total video duration in seconds. If None, inferred from
            silence_map or chunks.
        min_chapter_duration: Minimum chapter length in seconds. Chapters
            shorter than this are merged into the previous chapter.
        silence_gap_threshold: Minimum silence gap duration (in seconds) to
            treat as a chapter boundary (only used when silence_map is provided).

    Returns:
        List of chapter dicts, each with: chapter_id, start, end, duration,
        chunk_ids (list of int), title (str).
    """
    if not chunks:
        return []

    # Sort chunks by id to guarantee order.
    sorted_chunks = sorted(chunks, key=lambda c: c["id"])
    total_duration = _resolve_duration(sorted_chunks, silence_map, duration)

    # Step 1: Find boundary timestamps.
    if silence_map is not None:
        boundaries = _find_boundaries_from_silence_map(
            silence_map, silence_gap_threshold,
        )
    else:
        boundaries = _find_boundaries_from_chunks(sorted_chunks)

    # Step 2: Remove boundaries that fall at or before the first chunk's start
    # (chunk 0 is always the start of chapter 1, so a boundary there is redundant).
    first_start = sorted_chunks[0]["start"]
    boundaries = [b for b in boundaries if b > first_start]

    # Step 3: Assign chunks to raw chapters based on boundaries.
    raw_chapters: list[list[dict]] = []
    current_group: list[dict] = []
    boundary_idx = 0

    for chunk in sorted_chunks:
        # Check if this chunk crosses the next boundary.
        if boundary_idx < len(boundaries) and chunk["start"] >= boundaries[boundary_idx]:
            # Start a new chapter at this boundary.
            if current_group:
                raw_chapters.append(current_group)
            current_group = [chunk]
            # Advance past any boundaries this chunk has already passed.
            while (boundary_idx < len(boundaries)
                   and boundaries[boundary_idx] <= chunk["start"]):
                boundary_idx += 1
        else:
            current_group.append(chunk)

    # Flush remaining.
    if current_group:
        raw_chapters.append(current_group)

    # Step 4: Merge short chapters into previous (or forward for the first).
    merged_chapters: list[list[dict]] = []
    for group in raw_chapters:
        group_start = group[0]["start"]
        group_end = group[-1]["end"]
        group_duration = group_end - group_start

        if (merged_chapters
                and group_duration < min_chapter_duration):
            # Merge into previous chapter.
            merged_chapters[-1].extend(group)
        else:
            merged_chapters.append(group)

    # Forward-merge: if the first chapter is too short and there is a second,
    # merge the first into the second.
    if (len(merged_chapters) > 1):
        first = merged_chapters[0]
        first_dur = first[-1]["end"] - first[0]["start"]
        if first_dur < min_chapter_duration:
            merged_chapters[1] = first + merged_chapters[1]
            merged_chapters.pop(0)

    # Step 5: Build output chapter dicts.
    chapters: list[dict[str, Any]] = []
    for idx, group in enumerate(merged_chapters):
        chunk_ids = [c["id"] for c in group]
        ch_start = group[0]["start"]
        # For the last chapter, extend to total_duration if available and greater.
        if idx == len(merged_chapters) - 1:
            ch_end = max(group[-1]["end"], total_duration)
        else:
            ch_end = group[-1]["end"]
        ch_duration = ch_end - ch_start

        chapters.append({
            "chapter_id": idx,
            "start": ch_start,
            "end": ch_end,
            "duration": round(ch_duration, 6),
            "chunk_ids": chunk_ids,
            "title": _chunk_title(sorted_chunks, chunk_ids),
        })

    return chapters


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for chapter detection."""
    parser = argparse.ArgumentParser(
        description="Detect chapters from chunks.json and optional silence_map.json",
    )
    parser.add_argument(
        "--chunks-path", required=True,
        help="Path to chunks.json (from transcribe_video)",
    )
    parser.add_argument(
        "--silence-path", default=None,
        help="Path to silence_map.json (from detect_silence)",
    )
    parser.add_argument(
        "--duration", type=float, default=None,
        help="Total video duration in seconds (overrides silence_map/chunk inference)",
    )
    parser.add_argument(
        "--min-chapter-duration", type=float, default=DEFAULT_MIN_CHAPTER_DURATION,
        help=f"Minimum chapter duration in seconds (default: {DEFAULT_MIN_CHAPTER_DURATION})",
    )
    parser.add_argument(
        "--silence-gap-threshold", type=float, default=DEFAULT_SILENCE_GAP_THRESHOLD,
        help=f"Silence gap threshold in seconds (default: {DEFAULT_SILENCE_GAP_THRESHOLD})",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Print chapters as JSON to stdout",
    )
    args = parser.parse_args()

    # Load chunks.
    chunks_path = Path(args.chunks_path)
    with open(chunks_path, "r", encoding="utf-8") as f:
        chunks_data = json.load(f)

    # chunks.json may be a bare list or a dict with "chunks" key.
    if isinstance(chunks_data, list):
        chunks = chunks_data
    else:
        chunks = chunks_data.get("chunks", [])

    # Load silence_map if provided.
    silence_map = None
    if args.silence_path:
        silence_path = Path(args.silence_path)
        with open(silence_path, "r", encoding="utf-8") as f:
            silence_map = json.load(f)

    chapters = detect_chapters(
        chunks=chunks,
        silence_map=silence_map,
        duration=args.duration,
        min_chapter_duration=args.min_chapter_duration,
        silence_gap_threshold=args.silence_gap_threshold,
    )

    if args.json:
        print(json.dumps(chapters, indent=2))
    else:
        for ch in chapters:
            mins_s = ch["start"] / 60
            mins_e = ch["end"] / 60
            print(
                f"  Chapter {ch['chapter_id']}: "
                f"{mins_s:.1f}m - {mins_e:.1f}m "
                f"({ch['duration']:.1f}s, {len(ch['chunk_ids'])} chunks) "
                f"  {ch['title']}"
            )


if __name__ == "__main__":
    main()
