"""Transcribe video to word-level chunks for EdBot pipeline.

Extracts audio via ffmpeg, runs faster-whisper via subtitle_gen.transcribe_clip(),
buckets word timestamps into 10-second chunks, and writes chunks.json + transcript.json.
"""

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

# Import transcribe_clip from sibling module.
# sys.path manipulation mirrors the pattern used by other edbot tools/tests.
_tools_dir = str(Path(__file__).resolve().parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from subtitle_gen import transcribe_clip


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


def transcribe_video(video_path: str, output_dir: str | None = None) -> dict[str, Any]:
    """Transcribe a video file into 10-second chunks with word timestamps.

    Pipeline:
        1. Extract audio to WAV via ffmpeg (16kHz mono)
        2. Transcribe via faster-whisper (transcribe_clip)
        3. Bucket words into 10-second chunks
        4. Write chunks.json and transcript.json
        5. Return chunks dict

    Args:
        video_path: Path to input video file.
        output_dir: Directory for output JSON files and temp audio.

    Returns:
        Dict with source, duration, and chunks list.
        On ffmpeg failure, returns {"error": ..., "source": ...}.
    """
    vpath = Path(video_path)
    odir = Path(output_dir) if output_dir else vpath.parent
    odir.mkdir(parents=True, exist_ok=True)

    wav_path = odir / f"{vpath.stem}_audio.wav"

    # Step 1: Extract audio.
    if not _extract_audio(vpath, wav_path):
        return {"error": "audio extraction failed", "source": vpath.name}

    try:
        # Step 2: Transcribe.
        words: list[dict] = transcribe_clip(wav_path)

        # Step 3: Get duration (fallback to max word end + 1.0).
        duration = _get_duration(vpath)
        if duration is None:
            if words:
                duration = max(w["end"] for w in words) + 1.0
            else:
                duration = 0.0

        # Step 4: Bucket into chunks.
        chunks = _bucket_words(words, duration)

        # Step 5: Build output dicts.
        source_name = vpath.name

        chunks_data: dict[str, Any] = {
            "source": source_name,
            "duration": duration,
            "chunks": chunks,
        }

        transcript_data: dict[str, Any] = {
            "source": source_name,
            "words": words,
        }

        # Step 6: Write JSON files.
        chunks_path = odir / "chunks.json"
        transcript_path = odir / "transcript.json"

        with open(chunks_path, "w", encoding="utf-8") as f:
            json.dump(chunks_data, f, indent=2)

        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(transcript_data, f, indent=2)

        return chunks_data

    finally:
        # Clean up WAV file.
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
    parser.add_argument("--json", action="store_true", help="Print chunks as JSON")
    args = parser.parse_args()

    result = transcribe_video(args.input, args.output_dir)
    if args.json:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
