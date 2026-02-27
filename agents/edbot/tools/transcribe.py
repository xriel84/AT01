"""Transcribe video to word-level chunks for EdBot pipeline.

Extracts audio via ffmpeg, runs faster-whisper via subtitle_gen.transcribe_clip(),
buckets word timestamps into 10-second chunks, and writes chunks.json + transcript.json.

GPU-aware: auto-detects available VRAM and selects optimal model/compute type.
Chunked: splits files >3 min into 90s chunks for faster parallel processing.
Fallback chain: float16 → int8_float16 → medium/int8_float16 → small/cpu.
"""

import argparse
import json
import logging
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Import transcribe_clip from sibling module.
# sys.path manipulation mirrors the pattern used by other edbot tools/tests.
_tools_dir = str(Path(__file__).resolve().parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from subtitle_gen import transcribe_clip
from gpu_check import recommend_whisper_config

# Chunking thresholds
_CHUNK_THRESHOLD_SEC = 180  # Only chunk files longer than 3 minutes
_CHUNK_SIZE_SEC = 90        # Each chunk is 90 seconds
_CHUNK_OVERLAP_SEC = 5      # 5-second overlap between chunks

# Fallback chain: ordered list of (model_size, compute_type, device)
_FALLBACK_CHAIN = [
    ("large-v3", "float16", "cuda"),
    ("large-v3", "int8_float16", "cuda"),
    ("medium", "int8_float16", "cuda"),
    ("small", "int8", "cpu"),
]


def _extract_audio(video_path: Path, wav_path: Path) -> bool:
    """Extract 16kHz mono WAV from video using ffmpeg.

    Returns True on success, False on failure.
    """
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-ar", "16000", "-ac", "1", "-f", "wav",
        str(wav_path), "-y",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _extract_audio_chunk(video_path: Path, wav_path: Path, start_sec: float, duration_sec: float) -> bool:
    """Extract a specific time range of audio to 16kHz mono WAV.

    Returns True on success, False on failure.
    """
    cmd = [
        "ffmpeg", "-ss", str(start_sec),
        "-t", str(duration_sec),
        "-i", str(video_path),
        "-vn", "-ar", "16000", "-ac", "1", "-f", "wav",
        str(wav_path), "-y",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _get_duration(video_path: Path) -> float | None:
    """Get video duration in seconds via ffprobe.

    Returns duration as float, or None on failure.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError,
            json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def _bucket_words(words: list[dict], duration: float) -> list[dict]:
    """Bucket word-level timestamps into 10-second chunks.

    Args:
        words: List of {"word": str, "start": float, "end": float}.
        duration: Total video duration in seconds.

    Returns:
        List of chunk dicts with id, start, end, text, word_count,
        silence_ratio, and has_speech.
    """
    chunk_size = 10.0
    num_chunks = max(1, math.ceil(duration / chunk_size))

    # Group words into buckets by start time.
    buckets: dict[int, list[dict]] = {}
    for w in words:
        cid = math.floor(w["start"] / chunk_size)
        buckets.setdefault(cid, []).append(w)

    # Expand to include any words beyond declared duration (ffprobe/whisper mismatch).
    if buckets:
        num_chunks = max(num_chunks, max(buckets.keys()) + 1)

    chunks = []
    for i in range(num_chunks):
        start = i * chunk_size
        end = min((i + 1) * chunk_size, duration)
        bucket_words = buckets.get(i, [])

        text = " ".join(w["word"] for w in bucket_words)
        word_count = len(bucket_words)
        has_speech = word_count > 0

        # Silence ratio: fraction of chunk NOT covered by speech.
        chunk_dur = end - start
        if chunk_dur > 0 and has_speech:
            speech_dur = sum(w["end"] - w["start"] for w in bucket_words)
            silence_ratio = 1.0 - (speech_dur / chunk_dur)
            silence_ratio = max(0.0, min(1.0, silence_ratio))
        else:
            silence_ratio = 1.0

        chunks.append({
            "id": i,
            "start": start,
            "end": end,
            "text": text,
            "word_count": word_count,
            "silence_ratio": round(silence_ratio, 6),
            "has_speech": has_speech,
        })

    return chunks


def _resolve_config(model_size: str | None, compute_type: str | None, device: str | None) -> dict[str, str]:
    """Resolve transcription config — use overrides or auto-detect from GPU status.

    Returns dict with model_size, compute_type, device keys.
    """
    if model_size and compute_type and device:
        return {"model_size": model_size, "compute_type": compute_type, "device": device}

    rec = recommend_whisper_config()

    return {
        "model_size": model_size or rec["model_size"],
        "compute_type": compute_type or rec["compute_type"],
        "device": device or rec["device"],
    }


def _transcribe_with_fallback(wav_path: Path, config: dict[str, str]) -> tuple[list[dict], dict[str, str]]:
    """Transcribe audio with fallback chain on CUDA errors.

    Returns (words, config_actually_used).
    """
    # Find where the requested config sits in the fallback chain
    requested = (config["model_size"], config["compute_type"], config["device"])
    start_idx = 0
    for i, entry in enumerate(_FALLBACK_CHAIN):
        if entry == requested:
            start_idx = i
            break

    # Try from the requested config through the fallback chain
    chain = _FALLBACK_CHAIN[start_idx:]
    # If the requested config wasn't in the chain, prepend it
    if requested not in _FALLBACK_CHAIN:
        chain = [requested] + list(_FALLBACK_CHAIN)

    last_error = None
    for model_size, compute_type, device in chain:
        try:
            words = transcribe_clip(
                wav_path,
                model_size=model_size,
                device=device,
                compute_type=compute_type,
            )
            return words, {"model_size": model_size, "compute_type": compute_type, "device": device}
        except Exception as exc:
            last_error = exc
            error_str = str(exc).lower()
            is_cuda_error = any(
                term in error_str
                for term in ("cuda", "gpu", "cublas", "cudnn", "out of memory", "oom", "exit 127", "nccl")
            )
            if is_cuda_error:
                logger.warning("CUDA error with %s/%s/%s: %s — trying next fallback", model_size, compute_type, device, exc)
                continue
            # Non-CUDA error — don't retry
            raise

    raise RuntimeError(f"all fallback configs failed, last error: {last_error}")


def _deduplicate_overlap(words: list[dict], overlap_start: float, overlap_end: float) -> list[dict]:
    """Remove duplicate words that fall within an overlap window.

    Keeps words from the first chunk (already in the list) and removes
    words from the second chunk that have matching text within the overlap zone.
    """
    if not words:
        return words

    # Find existing words in the overlap zone
    existing_in_overlap = set()
    for w in words:
        if overlap_start <= w["start"] <= overlap_end:
            existing_in_overlap.add(w["word"].lower())

    return words, existing_in_overlap


def _merge_chunked_words(
    chunk_results: list[tuple[list[dict], float]],
    overlap_sec: float,
) -> list[dict]:
    """Merge words from multiple audio chunks, deduplicating overlaps.

    Args:
        chunk_results: List of (words, chunk_offset_sec) tuples.
        overlap_sec: Overlap duration in seconds between chunks.

    Returns:
        Merged list of word dicts with corrected timestamps.
    """
    if not chunk_results:
        return []

    all_words: list[dict] = []

    for i, (words, offset) in enumerate(chunk_results):
        # Shift timestamps by chunk offset
        shifted = [
            {"word": w["word"], "start": round(w["start"] + offset, 3), "end": round(w["end"] + offset, 3)}
            for w in words
        ]

        if i == 0:
            all_words.extend(shifted)
            continue

        # For subsequent chunks, skip words in the overlap zone
        overlap_start = offset
        overlap_end = offset + overlap_sec

        # Collect recent words near the overlap boundary for dedup
        # Look at words in [overlap_start - overlap_sec, overlap_end]
        existing_texts = set()
        for w in all_words:
            if w["start"] >= (overlap_start - overlap_sec) and w["start"] <= overlap_end:
                existing_texts.add(w["word"].lower())

        for w in shifted:
            # Skip words in overlap zone that match existing words
            if w["start"] < overlap_end and w["word"].lower() in existing_texts:
                continue
            # Skip words that start before the overlap zone ends if we already have words there
            if w["start"] < overlap_end and existing_texts:
                continue
            all_words.append(w)

    # Sort by start time
    all_words.sort(key=lambda w: w["start"])
    return all_words


def transcribe_video(
    video_path: str,
    output_dir: str | None = None,
    model_size: str | None = None,
    compute_type: str | None = None,
    device: str | None = None,
) -> dict[str, Any]:
    """Transcribe a video file into 10-second chunks with word timestamps.

    Pipeline:
        1. Get duration, decide if chunking needed (>3 min)
        2. Extract audio to WAV via ffmpeg (16kHz mono)
        3. Transcribe via faster-whisper with GPU-aware config + fallback
        4. Bucket words into 10-second chunks
        5. Write chunks.json and transcript.json
        6. Return chunks dict

    Args:
        video_path: Path to input video file.
        output_dir: Directory for output JSON files and temp audio.
        model_size: Override whisper model (default: auto-detect).
        compute_type: Override compute type (default: auto-detect).
        device: Override device (default: auto-detect).

    Returns:
        Dict with source, duration, chunks, config_used, and optionally
        chunked/chunk_count fields.
        On failure, returns {"error": ..., "source": ...}.
    """
    vpath = Path(video_path)
    odir = Path(output_dir) if output_dir else vpath.parent
    odir.mkdir(parents=True, exist_ok=True)

    # Resolve GPU-aware config
    config = _resolve_config(model_size, compute_type, device)

    # Get duration for chunking decision
    duration = _get_duration(vpath)
    use_chunking = duration is not None and duration > _CHUNK_THRESHOLD_SEC

    if use_chunking:
        return _transcribe_chunked(vpath, odir, config, duration)
    else:
        return _transcribe_single(vpath, odir, config)


def _transcribe_single(vpath: Path, odir: Path, config: dict[str, str]) -> dict[str, Any]:
    """Transcribe a video as a single audio file (for files <=3 min)."""
    wav_path = odir / f"{vpath.stem}_audio.wav"

    if not _extract_audio(vpath, wav_path):
        return {"error": "audio extraction failed", "source": vpath.name}

    try:
        words, config_used = _transcribe_with_fallback(wav_path, config)

        duration = _get_duration(vpath)
        if duration is None:
            if words:
                duration = max(w["end"] for w in words) + 1.0
            else:
                duration = 0.0

        chunks = _bucket_words(words, duration)
        source_name = vpath.name

        chunks_data: dict[str, Any] = {
            "source": source_name,
            "duration": duration,
            "chunks": chunks,
            "word_count": sum(c["word_count"] for c in chunks),
            "config_used": config_used,
            "chunked": False,
        }

        transcript_data: dict[str, Any] = {
            "source": source_name,
            "words": words,
        }

        _write_outputs(odir, chunks_data, transcript_data)
        return chunks_data

    finally:
        _cleanup(wav_path)


def _transcribe_chunked(vpath: Path, odir: Path, config: dict[str, str], duration: float) -> dict[str, Any]:
    """Transcribe a long video in chunks for speed."""
    chunk_dir = odir / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    chunk_wavs: list[Path] = []
    chunk_results: list[tuple[list[dict], float]] = []
    config_used = None

    # Calculate chunk boundaries
    chunk_starts = []
    t = 0.0
    while t < duration:
        chunk_starts.append(t)
        t += _CHUNK_SIZE_SEC

    try:
        for i, start in enumerate(chunk_starts):
            chunk_duration = _CHUNK_SIZE_SEC + _CHUNK_OVERLAP_SEC
            # Don't exceed file duration
            if start + chunk_duration > duration:
                chunk_duration = duration - start

            wav_path = chunk_dir / f"{vpath.stem}_chunk_{i:03d}.wav"
            chunk_wavs.append(wav_path)

            if not _extract_audio_chunk(vpath, wav_path, start, chunk_duration):
                logger.warning("Failed to extract chunk %d (%.1f-%.1f)", i, start, start + chunk_duration)
                continue

            words, used = _transcribe_with_fallback(wav_path, config)
            if config_used is None:
                config_used = used
            chunk_results.append((words, start))

        if not chunk_results:
            return {"error": "all chunks failed to transcribe", "source": vpath.name}

        # Merge words from all chunks
        all_words = _merge_chunked_words(chunk_results, _CHUNK_OVERLAP_SEC)

        chunks = _bucket_words(all_words, duration)
        source_name = vpath.name

        chunks_data: dict[str, Any] = {
            "source": source_name,
            "duration": duration,
            "chunks": chunks,
            "word_count": sum(c["word_count"] for c in chunks),
            "config_used": config_used or config,
            "chunked": True,
            "chunk_count": len(chunk_results),
        }

        transcript_data: dict[str, Any] = {
            "source": source_name,
            "words": all_words,
        }

        _write_outputs(odir, chunks_data, transcript_data)
        return chunks_data

    finally:
        # Clean up chunk WAVs
        for wav in chunk_wavs:
            _cleanup(wav)
        # Remove chunk dir if empty
        try:
            if chunk_dir.exists() and not list(chunk_dir.iterdir()):
                chunk_dir.rmdir()
        except OSError:
            pass


def _write_outputs(odir: Path, chunks_data: dict, transcript_data: dict) -> None:
    """Write chunks.json and transcript.json to output dir."""
    chunks_path = odir / "chunks.json"
    transcript_path = odir / "transcript.json"

    with open(chunks_path, "w", encoding="utf-8") as f:
        json.dump(chunks_data, f, indent=2)

    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript_data, f, indent=2)


def _cleanup(wav_path: Path) -> None:
    """Remove a temp WAV file if it exists."""
    if wav_path.exists():
        try:
            wav_path.unlink()
        except OSError:
            pass


def main() -> None:
    """CLI entry point for video transcription."""
    parser = argparse.ArgumentParser(description="Transcribe video to chunks.json")
    parser.add_argument("--input", required=True, help="Path to video file")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: same as input)")
    parser.add_argument("--model-size", default=None, help="Whisper model size (default: auto-detect)")
    parser.add_argument("--compute-type", default=None, help="Compute type (default: auto-detect)")
    parser.add_argument("--device", default=None, help="Device: cuda or cpu (default: auto-detect)")
    parser.add_argument("--json", action="store_true", help="Print chunks as JSON")
    args = parser.parse_args()

    result = transcribe_video(
        args.input, args.output_dir,
        model_size=args.model_size,
        compute_type=args.compute_type,
        device=args.device,
    )
    if args.json:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
