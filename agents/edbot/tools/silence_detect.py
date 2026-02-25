"""Detect silence gaps in video using ffmpeg's silencedetect filter.

Runs ffmpeg silencedetect, parses stderr for silence_start/silence_end lines,
builds a silence map with gaps, speech segments (inverse of gaps), and stats,
then writes silence_map.json.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


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


def _parse_silence_stderr(stderr: str) -> tuple[list[dict[str, float]], list[float]]:
    """Parse ffmpeg silencedetect stderr output into a list of gap dicts.

    Returns:
        Tuple of (gaps, unmatched_starts). Each gap has keys: start, end, duration.
        unmatched_starts contains any silence_start values without a matching
        silence_end (e.g., silence running to end-of-file).
    """
    starts: list[float] = []
    gaps: list[dict[str, float]] = []

    re_start = re.compile(r"silence_start:\s*([\d.]+)")
    re_end = re.compile(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)")

    for line in stderr.splitlines():
        m_start = re_start.search(line)
        if m_start:
            starts.append(float(m_start.group(1)))
            continue

        m_end = re_end.search(line)
        if m_end:
            end_time = float(m_end.group(1))
            dur = float(m_end.group(2))
            if starts:
                start_time = starts.pop(0)
            else:
                # Fallback: compute start from end - duration
                start_time = end_time - dur
            gaps.append({
                "start": start_time,
                "end": end_time,
                "duration": dur,
            })

    # Remaining unmatched starts are returned for caller to handle
    # (e.g., silence running to end-of-file).
    return gaps, starts


def _build_speech_segments(gaps: list[dict[str, float]], duration: float) -> list[dict[str, float]]:
    """Compute speech segments as the inverse of silence gaps.

    Given gaps sorted by start time and total duration, returns the
    intervals not covered by any gap.
    """
    speech_segments: list[dict[str, float]] = []
    cursor = 0.0

    for gap in gaps:
        if gap["start"] > cursor:
            seg_dur = gap["start"] - cursor
            speech_segments.append({
                "start": cursor,
                "end": gap["start"],
                "duration": seg_dur,
            })
        cursor = gap["end"]

    if cursor < duration:
        seg_dur = duration - cursor
        speech_segments.append({
            "start": cursor,
            "end": duration,
            "duration": seg_dur,
        })

    return speech_segments


def _compute_stats(gaps: list[dict[str, float]], duration: float) -> dict[str, Any]:
    """Compute summary statistics from gaps and total duration."""
    total_silence = sum(g["duration"] for g in gaps)
    total_speech = duration - total_silence
    if duration > 0:
        silence_percentage = round(total_silence / duration * 100, 1)
    else:
        silence_percentage = 0.0

    return {
        "total_silence": total_silence,
        "total_speech": total_speech,
        "silence_percentage": silence_percentage,
        "gap_count": len(gaps),
    }


def detect_silence(
    video_path: str,
    threshold_db: float = -30.0,
    min_duration: float = 0.5,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Detect silence in a video file using ffmpeg's silencedetect filter.

    Runs ffmpeg silencedetect, parses the output, computes speech segments
    (inverse of silence gaps), and writes a silence_map.json file.

    Args:
        video_path: Path to input video file.
        threshold_db: Silence threshold in dB (default -30.0).
        min_duration: Minimum silence duration in seconds (default 0.5).
        output_dir: Directory for silence_map.json. Defaults to video's parent dir.

    Returns:
        Dict with source, duration, threshold_db, gaps, speech, and stats.
        On failure, returns {"error": "silence detection failed", "source": video_path}.
    """
    vpath = Path(video_path)
    odir = Path(output_dir) if output_dir else vpath.parent
    odir.mkdir(parents=True, exist_ok=True)

    # Step 1: Run ffmpeg silencedetect.
    cmd = [
        "ffmpeg", "-i", str(vpath),
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            return {"error": "silence detection failed", "source": vpath.name}
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {"error": "silence detection failed", "source": vpath.name}

    # Step 2: Parse stderr for silence gaps.
    gaps, trailing_starts = _parse_silence_stderr(result.stderr)

    # Step 3: Get total duration via ffprobe, with fallback.
    duration = _get_duration(vpath)
    if duration is None:
        # Fallback: use max gap end time, or 0.0.
        if gaps:
            duration = max(g["end"] for g in gaps)
        else:
            duration = 0.0

    # Handle trailing silence (silence_start without silence_end = silence to EOF).
    for ts in trailing_starts:
        if duration > ts:
            gaps.append({
                "start": ts,
                "end": duration,
                "duration": duration - ts,
            })

    # Step 4: Build speech segments (inverse of gaps).
    speech = _build_speech_segments(gaps, duration)

    # Step 5: Compute stats.
    stats = _compute_stats(gaps, duration)

    # Step 6: Assemble silence map.
    silence_map: dict[str, Any] = {
        "source": vpath.name,
        "duration": duration,
        "threshold_db": threshold_db,
        "gaps": gaps,
        "speech": speech,
        "stats": stats,
    }

    # Step 7: Write silence_map.json.
    map_path = odir / "silence_map.json"
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(silence_map, f, indent=2)

    return silence_map


def main() -> None:
    """CLI entry point for silence detection."""
    parser = argparse.ArgumentParser(description="Detect silence in video")
    parser.add_argument("--input", required=True, help="Path to video file")
    parser.add_argument("--threshold", type=float, default=-30.0,
                        help="Silence threshold in dB")
    parser.add_argument("--min-duration", type=float, default=0.5,
                        help="Minimum silence duration")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--json", action="store_true", help="Print map as JSON")
    args = parser.parse_args()

    result = detect_silence(args.input, args.threshold, args.min_duration,
                            args.output_dir)
    if args.json:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
