"""EdBot retention pacer -- PySceneDetect + silence -> cut pacing analysis.

Short-form best practice: visual change every 2-4 seconds.
Analyzes existing cuts and suggests additional cut/zoom points.
"""

import json
import logging
from pathlib import Path
from typing import Any

from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector

logger = logging.getLogger(__name__)


def analyze_pacing(
    video_path: str,
    output_dir: str = "temp",
    target_cut_interval: tuple = (2.0, 4.0),
    silence_map: dict | None = None,
) -> dict[str, Any]:
    """Analyze video cut pacing and suggest improvements.

    Parameters
    ----------
    video_path : str
        Path to source video.
    output_dir : str
        Directory for output JSON.
    target_cut_interval : tuple
        Target range (min, max) seconds between cuts.
    silence_map : dict | None
        Optional silence map from silence_detect tool.

    Returns
    -------
    dict
        Pacing analysis with cut suggestions and retention score.
    """
    vpath = Path(video_path)
    if not vpath.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    # Run scene detection
    video = open_video(str(vpath))
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=27.0))
    scene_manager.detect_scenes(video)
    scene_list = scene_manager.get_scene_list()

    # Get video duration from scene detection metadata
    video_fps = video.frame_rate
    video_frames = video.duration.get_frames()
    duration = video_frames / video_fps if video_fps > 0 else 0

    # Handle very short videos
    if duration < 5.0:
        return {
            "source": vpath.name,
            "duration": round(duration, 2),
            "existing_cuts": 0,
            "avg_cut_interval": round(duration, 2),
            "target_cut_interval": list(target_cut_interval),
            "suggested_cuts": [],
            "retention_score": 1.0,
            "pacing_verdict": "good",
        }

    # Extract cut timestamps
    cut_timestamps: list[float] = [0.0]
    for scene in scene_list:
        start_time = scene[0].get_seconds()
        cut_timestamps.append(round(start_time, 2))
    cut_timestamps.append(round(duration, 2))

    # Remove duplicates and sort
    cut_timestamps = sorted(set(cut_timestamps))

    # Compute intervals
    intervals: list[float] = []
    for i in range(1, len(cut_timestamps)):
        interval = cut_timestamps[i] - cut_timestamps[i - 1]
        intervals.append(round(interval, 2))

    avg_interval = sum(intervals) / len(intervals) if intervals else duration
    existing_cuts = len(scene_list)

    # Get silence gaps for cut suggestions
    silence_gaps: list[dict] = []
    if silence_map and "segments" in silence_map:
        for seg in silence_map["segments"]:
            if seg.get("is_silence"):
                silence_gaps.append({
                    "start": seg["start"],
                    "end": seg["end"],
                })

    # Generate suggestions for long stretches
    min_target, max_target = target_cut_interval
    suggested_cuts: list[dict[str, Any]] = []

    for i in range(len(intervals)):
        if intervals[i] > max_target:
            seg_start = cut_timestamps[i]
            seg_end = cut_timestamps[i + 1]

            # Find best cut point within this stretch
            cut_point = _find_best_cut(
                seg_start, seg_end, silence_gaps, max_target,
            )

            reason = f"{intervals[i]:.1f}s without visual change"

            # Decide cut type
            if silence_gaps:
                # Check if cut_point is near a silence gap
                near_silence = any(
                    abs(cut_point - g["start"]) < 0.5 or abs(cut_point - g["end"]) < 0.5
                    for g in silence_gaps
                )
                if near_silence:
                    suggested_cuts.append({
                        "timestamp": round(cut_point, 2),
                        "type": "cut_at_silence",
                        "reason": reason,
                    })
                else:
                    suggested_cuts.append({
                        "timestamp": round(cut_point, 2),
                        "type": "zoom_change",
                        "reason": reason,
                    })
            else:
                # No silence map -- suggest zoom change at midpoint
                suggested_cuts.append({
                    "timestamp": round(cut_point, 2),
                    "type": "zoom_change",
                    "reason": reason,
                })

            # If stretch is very long, suggest B-roll insertion too
            if intervals[i] > max_target * 2:
                broll_point = seg_start + intervals[i] * 0.75
                suggested_cuts.append({
                    "timestamp": round(broll_point, 2),
                    "type": "broll_insert",
                    "reason": "long talking head segment",
                })

    # Compute retention score (0-1)
    retention_score = _compute_retention_score(
        intervals, min_target, max_target, duration,
    )

    # Pacing verdict
    if retention_score >= 0.8:
        verdict = "good"
    elif avg_interval < min_target:
        verdict = "too_choppy"
    else:
        verdict = "needs_more_cuts"

    result: dict[str, Any] = {
        "source": vpath.name,
        "duration": round(duration, 2),
        "existing_cuts": existing_cuts,
        "avg_cut_interval": round(avg_interval, 2),
        "target_cut_interval": list(target_cut_interval),
        "suggested_cuts": suggested_cuts,
        "retention_score": round(retention_score, 2),
        "pacing_verdict": verdict,
    }

    # Write output
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{vpath.stem}_pacing_analysis.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result


def _find_best_cut(
    seg_start: float,
    seg_end: float,
    silence_gaps: list[dict],
    max_interval: float,
) -> float:
    """Find the best cut point within a long segment."""
    midpoint = (seg_start + seg_end) / 2

    # Look for silence gap nearest to midpoint
    best_gap = None
    best_dist = float("inf")
    for gap in silence_gaps:
        gap_mid = (gap["start"] + gap["end"]) / 2
        if seg_start < gap_mid < seg_end:
            dist = abs(gap_mid - midpoint)
            if dist < best_dist:
                best_dist = dist
                best_gap = gap_mid

    return best_gap if best_gap is not None else midpoint


def _compute_retention_score(
    intervals: list[float],
    min_target: float,
    max_target: float,
    duration: float,
) -> float:
    """Compute retention score from cut intervals.

    Score 1.0 = all intervals within target range.
    Penalty for intervals too long (viewer boredom).
    Smaller penalty for intervals too short (jumpcut fatigue).
    """
    if not intervals:
        return 0.5

    score = 1.0
    for interval in intervals:
        if interval > max_target:
            # Long stretch penalty
            excess = (interval - max_target) / max_target
            score -= min(0.15, excess * 0.1)
        elif interval < min_target:
            # Too choppy penalty (lighter)
            deficit = (min_target - interval) / min_target
            score -= min(0.05, deficit * 0.03)

    return max(0.0, min(1.0, score))
