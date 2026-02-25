"""Detect speakers in audio/video using energy-based heuristic or optional pyannote.

Default method is energy-based: extracts 16kHz mono WAV via ffmpeg, reads raw
PCM samples with struct.unpack, computes per-chunk RMS energy, and flags speaker
changes where energy shifts >30% between adjacent chunks. Optional pyannote.audio
diarization available as upgrade path (lazy import, graceful fallback).
"""

import argparse
import json
import math
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENERGY_CHANGE_THRESHOLD = 0.30  # 30% relative shift marks speaker change
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # 16-bit PCM
NUM_CHANNELS = 1
DEFAULT_CHUNK_DURATION = 10.0


# ---------------------------------------------------------------------------
# Audio extraction
# ---------------------------------------------------------------------------


def _extract_wav(input_path: Path, wav_path: Path) -> bool:
    """Extract 16kHz mono WAV from input file using ffmpeg.

    Returns True on success, False on failure.
    """
    cmd = [
        "ffmpeg", "-i", str(input_path),
        "-ar", str(SAMPLE_RATE), "-ac", str(NUM_CHANNELS), "-f", "wav",
        str(wav_path), "-y",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _read_pcm_samples(wav_path: Path) -> tuple[list[int], int]:
    """Read all PCM samples from a 16-bit mono WAV file.

    Returns:
        Tuple of (samples as list of int16, sample_rate).
    """
    with wave.open(str(wav_path), "rb") as wf:
        n_frames = wf.getnframes()
        sr = wf.getframerate()
        raw = wf.readframes(n_frames)
    # Unpack as signed 16-bit little-endian.
    count = len(raw) // SAMPLE_WIDTH
    samples = list(struct.unpack(f"<{count}h", raw[:count * SAMPLE_WIDTH]))
    return samples, sr


# ---------------------------------------------------------------------------
# Energy computation
# ---------------------------------------------------------------------------


def _rms_energy(samples: list[int]) -> float:
    """Compute RMS energy of a list of 16-bit PCM samples.

    Returns 0.0 for empty input.
    """
    if not samples:
        return 0.0
    sum_sq = sum(s * s for s in samples)
    return math.sqrt(sum_sq / len(samples))


def _compute_chunk_energies(
    samples: list[int],
    sample_rate: int,
    chunks: list[dict] | None,
) -> list[dict]:
    """Compute RMS energy for each chunk time range.

    If chunks is None, creates synthetic 10-second chunks covering the audio.

    Returns list of dicts: [{"id": int, "start": float, "end": float, "energy": float}, ...]
    """
    total_duration = len(samples) / sample_rate if sample_rate > 0 else 0.0

    if chunks is None:
        # Synthesise chunks every DEFAULT_CHUNK_DURATION seconds.
        num = max(1, math.ceil(total_duration / DEFAULT_CHUNK_DURATION))
        chunks = []
        for i in range(num):
            start = i * DEFAULT_CHUNK_DURATION
            end = min((i + 1) * DEFAULT_CHUNK_DURATION, total_duration)
            chunks.append({"id": i, "start": start, "end": end})

    results = []
    for chunk in chunks:
        cid = chunk.get("id", 0)
        start = float(chunk.get("start", 0.0))
        end = float(chunk.get("end", start + DEFAULT_CHUNK_DURATION))

        # Convert times to sample indices.
        s_start = max(0, int(start * sample_rate))
        s_end = min(len(samples), int(end * sample_rate))

        chunk_samples = samples[s_start:s_end]
        energy = _rms_energy(chunk_samples)
        results.append({
            "id": cid,
            "start": start,
            "end": end,
            "energy": energy,
        })

    return results


def _normalize_energies(chunk_energies: list[dict]) -> list[dict]:
    """Normalize energy values to 0.0-1.0 range across all chunks.

    Modifies chunk dicts in place by adding 'energy_norm' key.
    """
    if not chunk_energies:
        return chunk_energies

    max_energy = max(ce["energy"] for ce in chunk_energies)
    for ce in chunk_energies:
        if max_energy > 0:
            ce["energy_norm"] = ce["energy"] / max_energy
        else:
            ce["energy_norm"] = 0.0

    return chunk_energies


# ---------------------------------------------------------------------------
# Speaker assignment
# ---------------------------------------------------------------------------


def _assign_speakers_by_energy(
    chunk_energies: list[dict],
    num_speakers: int | None = None,
) -> tuple[dict[str, str], list[dict]]:
    """Assign speaker labels by detecting energy-level changes between chunks.

    A speaker change is flagged when the normalized energy shifts by more than
    ENERGY_CHANGE_THRESHOLD (30%) between adjacent chunks.

    Returns:
        Tuple of (chunk_speakers mapping, segments list).
        chunk_speakers: {"0": "SPEAKER_0", "1": "SPEAKER_0", ...}
        segments: [{"start": 0.0, "end": 90.0, "speaker": "SPEAKER_0"}, ...]
    """
    if not chunk_energies:
        return {}, []

    # Walk chunks and detect change points.
    speaker_idx = 0
    labels: list[str] = [f"SPEAKER_{speaker_idx}"]

    for i in range(1, len(chunk_energies)):
        prev_norm = chunk_energies[i - 1]["energy_norm"]
        curr_norm = chunk_energies[i]["energy_norm"]

        # Compute relative shift — use max of the two as denominator to avoid
        # division by near-zero. If both are zero, no change.
        denom = max(prev_norm, curr_norm)
        if denom > 0:
            shift = abs(curr_norm - prev_norm) / denom
        else:
            shift = 0.0

        if shift > ENERGY_CHANGE_THRESHOLD:
            speaker_idx += 1
            labels.append(f"SPEAKER_{speaker_idx}")
        else:
            labels.append(labels[-1])

    # If num_speakers is provided and we found more, merge smallest segments.
    if num_speakers is not None and num_speakers > 0:
        unique = sorted(set(labels), key=lambda l: labels.count(l))
        while len(unique) > num_speakers:
            # Merge the least-frequent label into the one it most often borders.
            rarest = unique[0]
            # Find the label that most often neighbours the rarest.
            neighbour_counts: dict[str, int] = {}
            for i, lbl in enumerate(labels):
                if lbl == rarest:
                    if i > 0 and labels[i - 1] != rarest:
                        neighbour_counts[labels[i - 1]] = neighbour_counts.get(labels[i - 1], 0) + 1
                    if i < len(labels) - 1 and labels[i + 1] != rarest:
                        neighbour_counts[labels[i + 1]] = neighbour_counts.get(labels[i + 1], 0) + 1
            if neighbour_counts:
                merge_into = max(neighbour_counts, key=neighbour_counts.get)
            else:
                # No neighbours found (edge case), merge into the most common.
                merge_into = unique[-1] if unique[-1] != rarest else unique[0]
            labels = [merge_into if l == rarest else l for l in labels]
            unique = sorted(set(labels), key=lambda l: labels.count(l))

        # Relabel sequentially (SPEAKER_0, SPEAKER_1, ...).
        seen: dict[str, str] = {}
        counter = 0
        relabeled = []
        for lbl in labels:
            if lbl not in seen:
                seen[lbl] = f"SPEAKER_{counter}"
                counter += 1
            relabeled.append(seen[lbl])
        labels = relabeled

    # Build chunk_speakers mapping.
    chunk_speakers: dict[str, str] = {}
    for ce, lbl in zip(chunk_energies, labels):
        chunk_speakers[str(ce["id"])] = lbl

    # Build contiguous segments.
    segments: list[dict] = []
    seg_start = chunk_energies[0]["start"]
    seg_speaker = labels[0]

    for i in range(1, len(chunk_energies)):
        if labels[i] != seg_speaker:
            segments.append({
                "start": seg_start,
                "end": chunk_energies[i]["start"],
                "speaker": seg_speaker,
            })
            seg_start = chunk_energies[i]["start"]
            seg_speaker = labels[i]

    # Final segment ends at last chunk's end.
    segments.append({
        "start": seg_start,
        "end": chunk_energies[-1]["end"],
        "speaker": seg_speaker,
    })

    return chunk_speakers, segments


# ---------------------------------------------------------------------------
# Pyannote path (lazy import, upgrade only)
# ---------------------------------------------------------------------------


def _diarize_with_pyannote(
    wav_path: Path,
    chunks: list[dict] | None,
    num_speakers: int | None,
) -> dict | None:
    """Attempt speaker diarization using pyannote.audio.

    Returns a result dict on success, or None if pyannote is unavailable.
    The caller falls back to the energy method when None is returned.
    """
    try:
        from pyannote.audio import Pipeline  # type: ignore[import-not-found]
    except ImportError:
        return None

    try:
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization")
        diarization = pipeline(str(wav_path), num_speakers=num_speakers)
    except Exception:
        return None

    # Map diarization output to our format.
    segments: list[dict] = []
    all_speakers: set[str] = set()

    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append({
            "start": turn.start,
            "end": turn.end,
            "speaker": speaker,
        })
        all_speakers.add(speaker)

    # Assign speakers to chunks if provided.
    chunk_speakers: dict[str, str] = {}
    if chunks:
        for chunk in chunks:
            cid = str(chunk.get("id", 0))
            chunk_mid = (chunk["start"] + chunk["end"]) / 2
            # Find the segment that covers the chunk midpoint.
            assigned = "SPEAKER_0"
            for seg in segments:
                if seg["start"] <= chunk_mid <= seg["end"]:
                    assigned = seg["speaker"]
                    break
            chunk_speakers[cid] = assigned

    return {
        "method": "pyannote",
        "speakers": sorted(all_speakers),
        "segments": segments,
        "chunk_speakers": chunk_speakers,
    }


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def detect_speakers(
    audio_path: str,
    chunks: list[dict] | None = None,
    method: str = "energy",
    num_speakers: int | None = None,
    output_dir: str | None = None,
) -> dict:
    """Detect speakers in an audio or video file.

    Uses energy-based heuristic by default (always works, stdlib only).
    Optionally tries pyannote.audio for real diarization (lazy import).

    Args:
        audio_path: Path to input audio/video file.
        chunks: Optional list of chunk dicts (each with id, start, end).
            When provided, speakers are assigned to chunks. Otherwise
            synthetic 10-second chunks are generated.
        method: Detection method — "energy" (default) or "pyannote".
        num_speakers: Optional hint for expected number of speakers.
            When set and more speakers are found, smallest segments merge.
        output_dir: Optional directory for speaker_map.json output.

    Returns:
        Dict with source, method, speakers, segments, chunk_speakers.
        On failure, returns {"error": str, "source": str}.
    """
    apath = Path(audio_path)
    source_name = apath.name

    # Determine output directory.
    odir = Path(output_dir) if output_dir else apath.parent
    odir.mkdir(parents=True, exist_ok=True)

    wav_path = odir / f"{apath.stem}_speaker_audio.wav"

    # Step 1: Extract audio to WAV.
    if not _extract_wav(apath, wav_path):
        return {"error": "audio extraction failed", "source": source_name}

    try:
        # Step 2: Try pyannote if requested.
        if method == "pyannote":
            pyannote_result = _diarize_with_pyannote(wav_path, chunks, num_speakers)
            if pyannote_result is not None:
                result = {"source": source_name, **pyannote_result}
                # Write speaker_map.json.
                map_path = odir / "speaker_map.json"
                with open(map_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2)
                return result
            # pyannote unavailable — fall through to energy method.

        # Step 3: Energy-based detection.
        samples, sr = _read_pcm_samples(wav_path)

        # Step 4: Compute per-chunk energy.
        chunk_energies = _compute_chunk_energies(samples, sr, chunks)
        chunk_energies = _normalize_energies(chunk_energies)

        # Step 5: Assign speakers based on energy shifts.
        chunk_speakers, segments = _assign_speakers_by_energy(chunk_energies, num_speakers)

        # Step 6: Deduplicate speaker labels.
        speakers = sorted(set(chunk_speakers.values()))

        # Step 7: Build result.
        result: dict[str, Any] = {
            "source": source_name,
            "method": "energy",
            "speakers": speakers,
            "segments": segments,
            "chunk_speakers": chunk_speakers,
        }

        # Step 8: Write speaker_map.json.
        map_path = odir / "speaker_map.json"
        with open(map_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        return result

    finally:
        # Clean up temporary WAV file.
        if wav_path.exists():
            try:
                wav_path.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for speaker detection."""
    parser = argparse.ArgumentParser(description="Detect speakers in audio/video")
    parser.add_argument("--input", required=True, help="Path to audio/video file")
    parser.add_argument("--chunks-path", default=None,
                        help="Path to chunks.json (from transcribe_video)")
    parser.add_argument("--method", default="energy", choices=["energy", "pyannote"],
                        help="Detection method (default: energy)")
    parser.add_argument("--num-speakers", type=int, default=None,
                        help="Expected number of speakers")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory (default: same as input)")
    parser.add_argument("--json", action="store_true",
                        help="Print speaker map as JSON to stdout")
    args = parser.parse_args()

    # Load chunks if provided.
    chunks = None
    if args.chunks_path:
        chunks_path = Path(args.chunks_path)
        with open(chunks_path, "r", encoding="utf-8") as f:
            chunks_data = json.load(f)
        # chunks.json may be a bare list or a dict with "chunks" key.
        if isinstance(chunks_data, list):
            chunks = chunks_data
        else:
            chunks = chunks_data.get("chunks", [])

    result = detect_speakers(
        audio_path=args.input,
        chunks=chunks,
        method=args.method,
        num_speakers=args.num_speakers,
        output_dir=args.output_dir,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(f"Source: {result['source']}")
            print(f"Method: {result['method']}")
            print(f"Speakers: {', '.join(result['speakers'])}")
            print(f"Segments: {len(result['segments'])}")
            for seg in result["segments"]:
                print(
                    f"  {seg['start']:.1f}s - {seg['end']:.1f}s  {seg['speaker']}"
                )


if __name__ == "__main__":
    main()
