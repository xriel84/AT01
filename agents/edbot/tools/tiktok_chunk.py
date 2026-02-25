"""TikTok chunk generator -- produces <=60s portrait clips at chapter/speaker boundaries.

Combines chapter_detect output with portrait_crop to create TikTok-ready
vertical video segments. Chapters longer than max_duration are split at
chunk boundaries (never mid-chunk). Each segment is portrait-cropped and
logged in a clips manifest.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Import portrait_crop from sibling module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from portrait_crop import portrait_crop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_chunk_lookup(chunks: list[dict]) -> dict[int, dict]:
    """Build a dict mapping chunk id -> chunk dict for fast lookup."""
    return {c["id"]: c for c in chunks}


def _split_chapter_at_chunk_boundaries(
    chapter: dict,
    chunk_lookup: dict[int, dict],
    max_duration: float,
) -> list[dict]:
    """Split a chapter into segments that each fit within max_duration.

    Walks through the chapter's chunk_ids, accumulating chunks until adding
    the next chunk would push the segment over max_duration. Starts a new
    segment at that point. Each segment gets the chapter's start/end adjusted
    to its actual chunk range.

    Returns a list of segment dicts with keys: start, end, duration, chunk_ids.
    """
    chunk_ids = chapter.get("chunk_ids", [])
    if not chunk_ids:
        return []

    segments: list[dict] = []
    current_ids: list[int] = []
    seg_start: float | None = None

    for cid in chunk_ids:
        chunk = chunk_lookup.get(cid)
        if chunk is None:
            continue

        chunk_start = chunk["start"]
        chunk_end = chunk["end"]

        if seg_start is None:
            # First chunk in a new segment.
            seg_start = chunk_start
            current_ids = [cid]
            continue

        # Would adding this chunk exceed max_duration?
        proposed_end = chunk_end
        proposed_duration = proposed_end - seg_start

        if proposed_duration > max_duration and current_ids:
            # Flush the current segment before this chunk.
            last_chunk = chunk_lookup[current_ids[-1]]
            segments.append({
                "start": seg_start,
                "end": last_chunk["end"],
                "duration": round(last_chunk["end"] - seg_start, 6),
                "chunk_ids": list(current_ids),
            })
            # Start a new segment with this chunk.
            seg_start = chunk_start
            current_ids = [cid]
        else:
            current_ids.append(cid)

    # Flush the final segment.
    if current_ids and seg_start is not None:
        last_chunk = chunk_lookup[current_ids[-1]]
        segments.append({
            "start": seg_start,
            "end": last_chunk["end"],
            "duration": round(last_chunk["end"] - seg_start, 6),
            "chunk_ids": list(current_ids),
        })

    return segments


def _split_chapter_by_time(
    chapter: dict,
    max_duration: float,
) -> list[dict]:
    """Split a chapter into time-based segments when no chunk data is available.

    Divides the chapter into segments of at most max_duration seconds each.
    Returns a list of segment dicts with keys: start, end, duration.
    """
    ch_start = chapter["start"]
    ch_end = chapter["end"]
    ch_duration = ch_end - ch_start

    if ch_duration <= max_duration:
        return [{
            "start": ch_start,
            "end": ch_end,
            "duration": round(ch_duration, 6),
        }]

    segments: list[dict] = []
    seg_start = ch_start
    while seg_start < ch_end:
        seg_end = min(seg_start + max_duration, ch_end)
        segments.append({
            "start": round(seg_start, 6),
            "end": round(seg_end, 6),
            "duration": round(seg_end - seg_start, 6),
        })
        seg_start = seg_end

    return segments


def _output_filename(stem: str, clip_id: int, ext: str) -> str:
    """Build output filename: {stem}_tiktok_{clip_id}{ext}."""
    return f"{stem}_tiktok_{clip_id}{ext}"


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def generate_tiktok_chunks(
    input_path: str,
    chapters: list[dict],
    chunks: list[dict] | None = None,
    output_dir: str = "output",
    max_duration: float = 60.0,
    crop_method: str = "center",
) -> dict:
    """Generate TikTok-ready portrait clips from chapters.

    For each chapter, if duration <= max_duration, produce one clip.
    If duration > max_duration, split into segments at chunk boundaries
    (or by time if no chunk data). Each segment is portrait-cropped.

    Args:
        input_path: Path to source video file.
        chapters: List of chapter dicts from chapter_detect.detect_chapters.
        chunks: Optional list of chunk dicts (from transcribe_video) for
            splitting at chunk boundaries. If None, falls back to time splits.
        output_dir: Output directory for clips and manifest.
        max_duration: Maximum clip duration in seconds (default 60.0).
        crop_method: Portrait crop method -- "center" or "face".

    Returns:
        Result dict with keys: source, total_clips, max_duration, crop_method,
        clips (list), clips_manifest_path.
    """
    in_path = Path(input_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = in_path.stem
    ext = in_path.suffix

    # Build chunk lookup if chunks provided.
    chunk_lookup: dict[int, dict] | None = None
    if chunks is not None:
        chunk_lookup = _build_chunk_lookup(chunks)

    # Process each chapter into segments.
    clips: list[dict[str, Any]] = []
    clip_id = 0

    for chapter in chapters:
        ch_duration = chapter.get("duration", chapter["end"] - chapter["start"])
        ch_title = chapter.get("title", "")
        ch_id = chapter.get("chapter_id", 0)

        # Decide how to split this chapter.
        if ch_duration <= max_duration:
            # Whole chapter fits in one clip.
            segments = [{
                "start": chapter["start"],
                "end": chapter["end"],
                "duration": round(ch_duration, 6),
            }]
        elif chunk_lookup is not None and chapter.get("chunk_ids"):
            # Split at chunk boundaries.
            segments = _split_chapter_at_chunk_boundaries(
                chapter, chunk_lookup, max_duration,
            )
        else:
            # No chunk data -- split by time.
            segments = _split_chapter_by_time(chapter, max_duration)

        # Process each segment.
        for seg in segments:
            out_filename = _output_filename(stem, clip_id, ext)
            out_path = out_dir / out_filename

            clip_entry: dict[str, Any] = {
                "clip_id": clip_id,
                "chapter_id": ch_id,
                "start": seg["start"],
                "end": seg["end"],
                "duration": seg["duration"],
                "title": ch_title,
                "output_path": str(out_path),
                "status": "pending",
            }

            # Call portrait_crop for this segment.
            try:
                crop_result = portrait_crop(
                    input_path=input_path,
                    output_dir=output_dir,
                    method=crop_method,
                    start=seg["start"],
                    end=seg["end"],
                )

                if crop_result.get("status") == "success":
                    # Rename the output file to our naming convention.
                    crop_output = Path(crop_result["output"])
                    if crop_output.exists() and crop_output != out_path:
                        # Move the portrait_crop output to our expected path.
                        crop_output.rename(out_path)
                    clip_entry["output_path"] = str(out_path)
                    clip_entry["status"] = "success"
                else:
                    clip_entry["status"] = "error"
                    clip_entry["error"] = crop_result.get("error", "portrait_crop failed")
            except Exception as exc:
                clip_entry["status"] = "error"
                clip_entry["error"] = str(exc)

            clips.append(clip_entry)
            clip_id += 1

    # Build the result manifest.
    result: dict[str, Any] = {
        "source": in_path.name,
        "total_clips": len(clips),
        "max_duration": max_duration,
        "crop_method": crop_method,
        "clips": clips,
        "clips_manifest_path": str(out_dir / "clips_manifest.json"),
    }

    # Write clips manifest to disk.
    manifest_path = out_dir / "clips_manifest.json"
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    except OSError:
        # If we can't write the manifest, record it but don't fail.
        result["clips_manifest_path"] = None

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for TikTok chunk generation."""
    parser = argparse.ArgumentParser(
        description="Generate TikTok-ready portrait clips from chapter data",
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to source video file",
    )
    parser.add_argument(
        "--chapters-path", required=True,
        help="Path to chapters JSON file (from chapter_detect)",
    )
    parser.add_argument(
        "--chunks-path", default=None,
        help="Path to chunks JSON file (for chunk-boundary splitting)",
    )
    parser.add_argument(
        "--output-dir", default="output",
        help="Output directory for clips (default: output)",
    )
    parser.add_argument(
        "--max-duration", type=float, default=60.0,
        help="Maximum clip duration in seconds (default: 60.0)",
    )
    parser.add_argument(
        "--crop-method", default="center", choices=["center", "face"],
        help="Portrait crop method (default: center)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Print result as JSON to stdout",
    )
    args = parser.parse_args()

    # Load chapters.
    chapters_path = Path(args.chapters_path)
    with open(chapters_path, "r", encoding="utf-8") as f:
        chapters = json.load(f)

    # Load chunks if provided.
    chunks = None
    if args.chunks_path:
        chunks_path = Path(args.chunks_path)
        with open(chunks_path, "r", encoding="utf-8") as f:
            chunks_data = json.load(f)
        # Handle both bare list and dict with "chunks" key.
        if isinstance(chunks_data, list):
            chunks = chunks_data
        else:
            chunks = chunks_data.get("chunks", [])

    result = generate_tiktok_chunks(
        input_path=args.input,
        chapters=chapters,
        chunks=chunks,
        output_dir=args.output_dir,
        max_duration=args.max_duration,
        crop_method=args.crop_method,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"TikTok chunks: {result['source']}")
        print(f"  Total clips: {result['total_clips']}")
        print(f"  Max duration: {result['max_duration']}s")
        print(f"  Crop method: {result['crop_method']}")
        for clip in result["clips"]:
            status_mark = "OK" if clip["status"] == "success" else "FAIL"
            print(
                f"  [{status_mark}] Clip {clip['clip_id']}: "
                f"{clip['start']:.1f}s - {clip['end']:.1f}s "
                f"({clip['duration']:.1f}s) "
                f"  {clip['title']}"
            )
        print(f"  Manifest: {result['clips_manifest_path']}")


if __name__ == "__main__":
    main()
