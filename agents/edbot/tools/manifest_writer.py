"""Bridge AT pipeline outputs to JP viewer schemas.

Converts EdBot pipeline data (chunks, transcripts, video probes, shorts manifests)
into the two JSON formats consumed by the JP phone-space-viewer:

1. raptor-library.json — SOURCE tab: full video entries with transcripts + metadata
2. assembly_manifest.json — PORTRAIT tab: short clips with platform/aspect info

Both formats are documented by the normalizeRaptorEntry() and normalizeAssemblyClip()
functions in phone-space-viewer.html.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from video_prober import scan_local_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLATFORMS = ("tiktok", "youtube_shorts", "ig_reels", "x_video", "youtube_long", "ig_feed")

ASPECT_RESOLUTION_MAP = {
    "9:16": "1080x1920",
    "1:1": "1080x1080",
    "16:9": "1920x1080",
}

# ---------------------------------------------------------------------------
# Single-entry converters
# ---------------------------------------------------------------------------


def to_raptor_entry(
    video_probe: dict[str, Any],
    chunks: list[dict[str, Any]] | None = None,
    transcript_words: list[dict[str, Any]] | None = None,
    entry_id: str | None = None,
    source_root: str | None = None,
) -> dict[str, Any]:
    """Convert AT pipeline outputs for one video into a raptor-library entry.

    Args:
        video_probe: Output from video_prober.probe_video().
        chunks: List of 10-second chunk dicts from transcribe_video().
        transcript_words: Word-level timestamps from transcript.json.
        entry_id: Override entry ID (default: auto-generated from filename).
        source_root: Root directory for relative_path calculation.

    Returns:
        Dict matching the raptor-library.json entry schema.
    """
    chunks = chunks or []
    transcript_words = transcript_words or []
    filename = video_probe.get("filename", "unknown")
    abs_path = video_probe.get("path", "")

    # Build relative path
    relative_path = filename
    if source_root and abs_path:
        try:
            relative_path = str(Path(abs_path).relative_to(source_root))
        except ValueError:
            relative_path = filename

    # Derive subdir from relative path
    rel_parts = Path(relative_path).parts
    subdir = rel_parts[0] if len(rel_parts) > 1 else "[root]"

    # Build full transcript from chunks
    transcript_full = " ".join(c.get("text", "") for c in chunks if c.get("text"))

    # Build whisper segments from word-level data
    whisper_segments = _words_to_segments(transcript_words)

    # Build transcript snippet (first ~120 chars)
    transcript_snippet = transcript_full[:120].rstrip()

    # Auto-generate two-word name from filename
    two_word_name = _two_word_name(filename)

    # Summary: first ~250 chars of transcript
    summary = transcript_full[:250].rstrip() if transcript_full else "[NO TRANSCRIPT]"

    # Resolution string
    w = video_probe.get("width")
    h = video_probe.get("height")
    resolution = f"{w}x{h}" if w and h else "unknown"

    # Content type heuristic
    has_speech = any(c.get("has_speech") for c in chunks)
    word_count = sum(c.get("word_count", 0) for c in chunks)

    # File hash for dedup
    file_hash = hashlib.md5(abs_path.encode()).hexdigest()[:12]

    # Auto-ID
    if not entry_id:
        entry_id = f"RH_{file_hash}"

    return {
        "id": entry_id,
        "two_word_name": two_word_name,
        "auto_named": True,
        "filename": filename,
        "relative_path": relative_path.replace("\\", "/"),
        "absolute_path": abs_path.replace("\\", "/"),
        "subdir": subdir,
        "duration_sec": video_probe.get("duration_sec") or 0,
        "resolution": resolution,
        "has_audio": video_probe.get("audio_codec") is not None,
        "has_video": video_probe.get("video_codec") is not None,
        "is_vfr": False,
        "codec_video": video_probe.get("video_codec"),
        "codec_audio": video_probe.get("audio_codec"),
        "filesize_mb": video_probe.get("file_size_mb") or 0,
        "transcript_full": transcript_full,
        "transcript_snippet": transcript_snippet,
        "summary": summary,
        "context": {
            "subdir": subdir,
            "speaker_count": 1,
            "has_dialogue": False,
            "has_narration": has_speech,
            "language": "en",
            "content_type": "narration" if has_speech else "silent",
        },
        "whisper_segments": whisper_segments,
        "status": "transcribed" if transcript_full else "probed",
        "error": None,
        "file_hash": file_hash,
    }


def to_assembly_clip(
    chunk: dict[str, Any],
    source_id: str | None = None,
    platform: str = "tiktok",
    aspect: str = "9:16",
    output_path: str | None = None,
    clip_id: str | None = None,
) -> dict[str, Any]:
    """Convert an AT pipeline chunk/short into an assembly_manifest clip.

    Args:
        chunk: A chunk dict (from transcribe_video) or shorts assembly entry.
        source_id: ID of the source entry in raptor-library.
        platform: Target platform (tiktok, youtube_shorts, ig_reels, etc).
        aspect: Target aspect ratio (9:16, 1:1, 16:9).
        output_path: Path to the output clip file.
        clip_id: Override clip ID.

    Returns:
        Dict matching the assembly_manifest.json clip schema.
    """
    text = chunk.get("text", "")
    silence_ratio = chunk.get("silence_ratio", 0)
    duration = chunk.get("end", 0) - chunk.get("start", 0)

    if not clip_id:
        cid = chunk.get("id", 0)
        platform_suffix = platform.replace("_", "")
        clip_id = f"C{cid:02d}_{platform_suffix}" if isinstance(cid, int) else f"C_{cid}_{platform_suffix}"

    resolution = ASPECT_RESOLUTION_MAP.get(aspect, "unknown")
    filename = f"{clip_id}.mp4"

    # Name from first few words
    name = " ".join(text.split()[:4]).rstrip(".,;:") if text else f"Clip {chunk.get('id', 0)}"

    return {
        "id": clip_id,
        "platform": platform,
        "filename": filename,
        "duration_sec": round(duration, 1),
        "name": name[:30],
        "transcript_snippet": text[:120].rstrip(),
        "thumbnail": None,
        "silence_pct": round(silence_ratio * 100),
        "hashtags": [],
        "topic_branch": platform,
        "summary": text[:250].rstrip() if text else "[NO TRANSCRIPT]",
        "status": "ready",
        "source_id": source_id,
        "path": output_path or f"output/{filename}",
        "aspect": aspect,
        "resolution": resolution,
    }


# ---------------------------------------------------------------------------
# Batch writers
# ---------------------------------------------------------------------------


def write_raptor_library(
    entries: list[dict[str, Any]],
    output_path: str | Path,
    source_root: str = "",
) -> dict[str, Any]:
    """Write a raptor-library.json file from a list of entries.

    Args:
        entries: List of raptor-library entry dicts (from to_raptor_entry).
        output_path: Path for output JSON file.
        source_root: Root directory string for metadata.

    Returns:
        The written library dict (for verification).
    """
    library = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source_root": source_root.replace("\\", "/"),
        "total_files": len(entries),
        "processed": sum(1 for e in entries if e.get("status") != "error"),
        "skipped": sum(1 for e in entries if e.get("status") == "error"),
        "entries": entries,
        "errors": [e for e in entries if e.get("error")],
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(library, f, indent=2)

    logger.info("Wrote raptor-library.json: %d entries → %s", len(entries), out)
    return library


def write_assembly_manifest(
    clips: list[dict[str, Any]],
    output_path: str | Path,
    source_clip: str = "",
) -> dict[str, Any]:
    """Write an assembly_manifest.json file from a list of clips.

    Args:
        clips: List of assembly clip dicts (from to_assembly_clip).
        output_path: Path for output JSON file.
        source_clip: Source clip identifier for metadata.

    Returns:
        The written manifest dict (for verification).
    """
    manifest = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source_clip": source_clip,
        "clips": clips,
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info("Wrote assembly_manifest.json: %d clips → %s", len(clips), out)
    return manifest


# ---------------------------------------------------------------------------
# Full sync — orchestrate all conversions
# ---------------------------------------------------------------------------


def sync_all(
    video_dir: str,
    output_dir: str,
    chunks_dir: str | None = None,
) -> dict[str, Any]:
    """Scan a video directory and generate both manifest files.

    Combines video_prober scan results with any existing chunks/transcript
    data to produce raptor-library.json and assembly_manifest.json.

    Args:
        video_dir: Directory containing source videos.
        output_dir: Directory for output manifest files.
        chunks_dir: Directory containing chunks.json / transcript.json files
                    (default: output_dir).

    Returns:
        Dict with raptor_library_path, assembly_manifest_path, entry_count,
        clip_count, and any errors.
    """
    chunks_dir = chunks_dir or output_dir
    odir = Path(output_dir)
    odir.mkdir(parents=True, exist_ok=True)

    # Scan videos
    scan_result = scan_local_dir(video_dir)
    if scan_result.get("error"):
        return {"error": scan_result["error"]}

    videos = scan_result.get("videos", [])
    entries = []
    all_clips = []
    errors = []

    for probe in videos:
        filename = probe.get("filename", "")
        stem = Path(filename).stem

        # Try to load chunks and transcript for this video
        chunks = _load_json_safe(Path(chunks_dir) / "chunks.json", filename)
        transcript = _load_json_safe(Path(chunks_dir) / "transcript.json", filename)

        chunk_list = chunks.get("chunks", []) if chunks else []
        word_list = transcript.get("words", []) if transcript else []

        try:
            entry = to_raptor_entry(
                video_probe=probe,
                chunks=chunk_list,
                transcript_words=word_list,
                source_root=video_dir,
            )
            entries.append(entry)

            # Generate assembly clips for speech chunks
            speech_chunks = [c for c in chunk_list if c.get("has_speech")]
            for chunk in speech_chunks[:10]:  # Cap at 10 clips per source
                clip = to_assembly_clip(
                    chunk=chunk,
                    source_id=entry["id"],
                    platform="tiktok",
                    aspect="9:16",
                )
                all_clips.append(clip)

        except Exception as exc:
            logger.warning("Failed to process %s: %s", filename, exc)
            errors.append({"filename": filename, "error": str(exc)})

    # Write outputs
    rl_path = odir / "raptor-library.json"
    am_path = odir / "assembly_manifest.json"

    write_raptor_library(entries, rl_path, source_root=video_dir)
    write_assembly_manifest(all_clips, am_path, source_clip=video_dir)

    return {
        "raptor_library_path": str(rl_path),
        "assembly_manifest_path": str(am_path),
        "entry_count": len(entries),
        "clip_count": len(all_clips),
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _words_to_segments(words: list[dict]) -> list[dict]:
    """Convert word-level timestamps into sentence-like segments.

    Groups consecutive words into segments of ~10 words each.
    """
    if not words:
        return []

    segments = []
    group_size = 10
    for i in range(0, len(words), group_size):
        group = words[i:i + group_size]
        text = " ".join(w.get("word", "") for w in group)
        start = group[0].get("start", 0)
        end = group[-1].get("end", 0)
        segments.append({"start": round(start, 2), "end": round(end, 2), "text": text})

    return segments


def _two_word_name(filename: str) -> str:
    """Generate a two-word name from a filename.

    Examples:
        'AdLab_final cut_032920.mp4' → 'AdLab Final'
        'IMG_5769.MOV' → 'IMG 5769'
        'interview_take_3.mov' → 'Interview Take'
    """
    stem = Path(filename).stem
    # Split on common separators
    parts = stem.replace("_", " ").replace("-", " ").replace(".", " ").split()
    parts = [p for p in parts if p]  # Remove empty
    if not parts:
        return "Unknown Clip"
    if len(parts) == 1:
        return parts[0].title()
    return f"{parts[0].title()} {parts[1].title()}"


def _load_json_safe(path: Path, source_filename: str | None = None) -> dict | None:
    """Load a JSON file, returning None on any failure.

    If source_filename is provided, checks that the 'source' field matches
    before returning the data.
    """
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if source_filename and data.get("source") != source_filename:
            return None
        return data
    except (json.JSONDecodeError, OSError, KeyError):
        return None
