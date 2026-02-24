"""shot_align.py -- Align multi-camera recordings by transcript or audio.

Mode 1 (transcript): Uses faster-whisper to transcribe both files, then
finds the longest common word subsequence to calculate time offset.

Mode 2 (audio fingerprint): Extracts audio features with librosa and
cross-correlates to find peak alignment. Fallback when transcription
quality is poor.

Dependencies:
  - faster-whisper (GPU, ~10GB VRAM)
  - librosa (pip install librosa)
  - numpy
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class WordTiming:
    """A single word with start/end timestamps."""
    word: str
    start: float
    end: float


@dataclass
class AlignmentResult:
    """Result of aligning two recordings."""
    file_a: str
    file_b: str
    offset_seconds: float
    confidence: float
    method: str
    matched_words: int = 0
    total_words_a: int = 0
    total_words_b: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Transcript alignment (Mode 1)
# ---------------------------------------------------------------------------

def transcribe_file(filepath: str, model_size: str = "base") -> list[WordTiming]:
    """Transcribe a file using faster-whisper. Returns word-level timings.

    Raises ImportError if faster-whisper is not installed.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ImportError(
            "faster-whisper not installed. Run: pip install faster-whisper"
        )

    model = WhisperModel(model_size, device="cuda", compute_type="float16")
    segments, _ = model.transcribe(filepath, word_timestamps=True)

    words: list[WordTiming] = []
    for segment in segments:
        if segment.words:
            for w in segment.words:
                words.append(WordTiming(
                    word=w.word.strip().lower(),
                    start=w.start,
                    end=w.end,
                ))
    return words


def find_longest_common_subsequence(
    words_a: list[WordTiming],
    words_b: list[WordTiming],
    min_window: int = 5,
) -> tuple[list[tuple[int, int]], float]:
    """Find matching word sequences between two transcripts.

    Uses a sliding window approach: for each position in words_a, try to
    find a matching run of min_window+ consecutive words in words_b.

    Returns (list of (idx_a, idx_b) pairs, confidence score).
    """
    if not words_a or not words_b:
        return [], 0.0

    text_a = [w.word for w in words_a]
    text_b = [w.word for w in words_b]

    best_matches: list[tuple[int, int]] = []
    best_length = 0

    for i in range(len(text_a) - min_window + 1):
        window = text_a[i : i + min_window]
        window_str = " ".join(window)

        for j in range(len(text_b) - min_window + 1):
            candidate = " ".join(text_b[j : j + min_window])
            if window_str == candidate:
                # Extend the match as far as possible
                match_pairs = []
                ia, ib = i, j
                while ia < len(text_a) and ib < len(text_b) and text_a[ia] == text_b[ib]:
                    match_pairs.append((ia, ib))
                    ia += 1
                    ib += 1

                if len(match_pairs) > best_length:
                    best_matches = match_pairs
                    best_length = len(match_pairs)

    total = max(len(text_a), len(text_b))
    confidence = best_length / total if total > 0 else 0.0
    return best_matches, confidence


def calculate_offset_from_matches(
    words_a: list[WordTiming],
    words_b: list[WordTiming],
    matches: list[tuple[int, int]],
) -> float:
    """Calculate the average time offset from matched word pairs.

    Offset = time_in_b - time_in_a. Positive means B starts later.
    """
    if not matches:
        return 0.0

    offsets = []
    for idx_a, idx_b in matches:
        offset = words_b[idx_b].start - words_a[idx_a].start
        offsets.append(offset)

    return sum(offsets) / len(offsets)


def align_by_transcript(
    file_a: str,
    file_b: str,
    model_size: str = "base",
) -> AlignmentResult:
    """Align two files using transcript matching."""
    print(f"[ALIGN] Transcribing: {os.path.basename(file_a)}")
    words_a = transcribe_file(file_a, model_size)
    print(f"  Words: {len(words_a)}")

    print(f"[ALIGN] Transcribing: {os.path.basename(file_b)}")
    words_b = transcribe_file(file_b, model_size)
    print(f"  Words: {len(words_b)}")

    print("[ALIGN] Finding matching sequences...")
    matches, confidence = find_longest_common_subsequence(words_a, words_b)

    offset = calculate_offset_from_matches(words_a, words_b, matches)

    print(f"  Matched words: {len(matches)}")
    print(f"  Confidence: {confidence:.3f}")
    print(f"  Offset: {offset:.3f}s")

    return AlignmentResult(
        file_a=file_a,
        file_b=file_b,
        offset_seconds=round(offset, 3),
        confidence=round(confidence, 3),
        method="transcript",
        matched_words=len(matches),
        total_words_a=len(words_a),
        total_words_b=len(words_b),
    )


# ---------------------------------------------------------------------------
# Audio fingerprint alignment (Mode 2 — fallback)
# ---------------------------------------------------------------------------

def align_by_audio(file_a: str, file_b: str) -> AlignmentResult:
    """Align two files using audio cross-correlation.

    Uses librosa to extract chromagram features and numpy to
    cross-correlate them. Fallback when transcript quality is poor.
    """
    try:
        import librosa
        import numpy as np
    except ImportError:
        return AlignmentResult(
            file_a=file_a,
            file_b=file_b,
            offset_seconds=0.0,
            confidence=0.0,
            method="audio_fingerprint",
            error="librosa/numpy not installed. Run: pip install librosa numpy",
        )

    print(f"[ALIGN] Loading audio: {os.path.basename(file_a)}")
    y_a, sr_a = librosa.load(file_a, sr=22050, mono=True)

    print(f"[ALIGN] Loading audio: {os.path.basename(file_b)}")
    y_b, sr_b = librosa.load(file_b, sr=22050, mono=True)

    print("[ALIGN] Computing chromagrams...")
    chroma_a = librosa.feature.chroma_stft(y=y_a, sr=sr_a)
    chroma_b = librosa.feature.chroma_stft(y=y_b, sr=sr_b)

    # Flatten to 1D for cross-correlation
    flat_a = chroma_a.mean(axis=0)
    flat_b = chroma_b.mean(axis=0)

    print("[ALIGN] Cross-correlating...")
    correlation = np.correlate(flat_a, flat_b, mode="full")
    peak_idx = np.argmax(correlation)
    peak_value = correlation[peak_idx]

    # Convert frame offset to seconds
    hop_length = 512  # librosa default
    frame_offset = peak_idx - len(flat_b) + 1
    offset_seconds = frame_offset * hop_length / 22050

    # Confidence from normalized peak
    max_possible = np.sqrt(np.sum(flat_a ** 2) * np.sum(flat_b ** 2))
    confidence = float(peak_value / max_possible) if max_possible > 0 else 0.0

    print(f"  Offset: {offset_seconds:.3f}s")
    print(f"  Confidence: {confidence:.3f}")

    return AlignmentResult(
        file_a=file_a,
        file_b=file_b,
        offset_seconds=round(offset_seconds, 3),
        confidence=round(confidence, 3),
        method="audio_fingerprint",
    )


# ---------------------------------------------------------------------------
# Main alignment dispatcher
# ---------------------------------------------------------------------------

TRANSCRIPT_CONFIDENCE_THRESHOLD = 0.1


def align_files(
    file_a: str,
    file_b: str,
    method: str = "auto",
    model_size: str = "base",
) -> AlignmentResult:
    """Align two recordings.

    method='auto': try transcript first, fall back to audio if confidence
    is below threshold.
    method='transcript': transcript only.
    method='audio': audio fingerprint only.
    """
    if method == "audio":
        return align_by_audio(file_a, file_b)

    if method == "transcript":
        return align_by_transcript(file_a, file_b, model_size)

    # Auto mode: try transcript, fall back to audio
    try:
        result = align_by_transcript(file_a, file_b, model_size)
        if result.confidence >= TRANSCRIPT_CONFIDENCE_THRESHOLD:
            return result
        print(f"[ALIGN] Transcript confidence too low ({result.confidence:.3f}), trying audio...")
    except ImportError as e:
        print(f"[ALIGN] Transcript failed ({e}), trying audio...")
    except Exception as e:
        print(f"[ALIGN] Transcript error ({e}), trying audio...")

    return align_by_audio(file_a, file_b)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="shot_align -- Align multi-camera recordings by transcript or audio.",
    )
    parser.add_argument("--file-a", type=str, required=True, help="First recording")
    parser.add_argument("--file-b", type=str, required=True, help="Second recording")
    parser.add_argument(
        "--method",
        choices=["auto", "transcript", "audio"],
        default="auto",
        help="Alignment method (default: auto)",
    )
    parser.add_argument(
        "--model-size",
        type=str,
        default="base",
        help="Whisper model size for transcription (default: base)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="alignment.json",
        help="Output JSON path (default: alignment.json)",
    )

    args = parser.parse_args()

    for f in [args.file_a, args.file_b]:
        if not os.path.isfile(f):
            print(f"[ERROR] File not found: {f}")
            sys.exit(1)

    result = align_files(args.file_a, args.file_b, args.method, args.model_size)

    output = asdict(result)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"  ALIGNMENT RESULT")
    print(f"{'='*60}")
    print(f"  File A:    {os.path.basename(result.file_a)}")
    print(f"  File B:    {os.path.basename(result.file_b)}")
    print(f"  Method:    {result.method}")
    print(f"  Offset:    {result.offset_seconds}s")
    print(f"  Confidence:{result.confidence}")
    if result.matched_words:
        print(f"  Matched:   {result.matched_words} words")
    if result.error:
        print(f"  Error:     {result.error}")
    print(f"  Output:    {args.output}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
