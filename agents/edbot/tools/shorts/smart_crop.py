"""EdBot smart crop -- generate crop keyframes from person tracking data.

Takes per-frame bounding boxes from person_tracker, generates smooth crop window
that follows primary subject. X-AXIS PAN ONLY for 9:16 from 16:9 source
(eliminates the Y-axis black bar problem that plagues Resolve Smart Reframe).
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _load_tracking_data(tracking_data: dict | str) -> dict:
    """Load tracking data from dict or JSON file path."""
    if isinstance(tracking_data, str):
        p = Path(tracking_data)
        if not p.exists():
            raise FileNotFoundError(f"Tracking data not found: {tracking_data}")
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return tracking_data


def generate_crop_keyframes(
    tracking_data: dict | str,
    target_aspect: str = "9:16",
    smoothing_window: float = 1.0,
    max_pan_speed: float = 0.15,
    follow_track_id: int | None = None,
    dead_zone: float = 0.15,
) -> dict[str, Any]:
    """Generate crop keyframes from person tracking data.

    Parameters
    ----------
    tracking_data : dict | str
        Tracking data dict or path to JSON file.
    target_aspect : str
        Target aspect ratio: "9:16" or "1:1".
    smoothing_window : float
        Temporal smoothing window in seconds.
    max_pan_speed : float
        Maximum pan speed as fraction of frame width per second.
    follow_track_id : int | None
        Specific track to follow. None = use primary_track_id.
    dead_zone : float
        Fraction of crop width. If subject is within this zone of center, don't move.

    Returns
    -------
    dict
        Crop keyframes with per-timestamp crop coordinates.
    """
    data = _load_tracking_data(tracking_data)
    src_w, src_h = data["resolution"]
    fps = data["fps"]

    # Parse target aspect
    parts = target_aspect.split(":")
    aspect_w, aspect_h = int(parts[0]), int(parts[1])

    # Compute crop dimensions (always use full source height, X-axis pan only)
    if aspect_h >= aspect_w:
        # Portrait or square from landscape
        crop_h = src_h
        crop_w = int(src_h * aspect_w / aspect_h)
        # Ensure even
        crop_w = crop_w - (crop_w % 2)
    else:
        # Target is landscape -- identity crop
        crop_w = src_w
        crop_h = src_h

    # Output resolution
    if target_aspect == "9:16":
        output_resolution = [1080, 1920]
    elif target_aspect == "1:1":
        output_resolution = [1080, 1080]
    else:
        output_resolution = [crop_w, crop_h]

    # Select track to follow
    target_tid = follow_track_id
    if target_tid is None:
        target_tid = data.get("primary_track_id")

    # Build raw crop_x values from tracking frames
    raw_keyframes: list[dict[str, Any]] = []
    default_crop_x = (src_w - crop_w) // 2  # center

    prev_crop_x = default_crop_x

    for frame_data in data.get("frames", []):
        timestamp = frame_data["timestamp"]
        persons = frame_data.get("persons", [])

        # Find target person
        target_person = None
        if target_tid is not None:
            for p in persons:
                if p.get("track_id") == target_tid:
                    target_person = p
                    break

        # If target not found, use highest-confidence person
        if target_person is None and persons:
            target_person = persons[0]

        if target_person is not None:
            bbox = target_person["bbox"]
            # bbox is [cx, cy, w, h] in xywh format
            person_center_x = bbox[0]
            ideal_crop_x = int(person_center_x - crop_w / 2)

            # Dead zone check
            current_center = prev_crop_x + crop_w / 2
            if abs(person_center_x - current_center) < dead_zone * crop_w:
                ideal_crop_x = prev_crop_x
        else:
            # No detection -- hold previous position
            ideal_crop_x = prev_crop_x

        # Clamp to frame bounds
        ideal_crop_x = max(0, min(ideal_crop_x, src_w - crop_w))

        raw_keyframes.append({
            "timestamp": timestamp,
            "crop_x": ideal_crop_x,
            "crop_y": 0,
        })
        prev_crop_x = ideal_crop_x

    # Apply temporal smoothing
    if raw_keyframes:
        smooth_frames = max(1, int(smoothing_window * fps / max(1, int(fps / data.get("sample_fps", fps)))))
        smoothed = _smooth_keyframes(raw_keyframes, smooth_frames)

        # Apply speed clamping
        max_delta_per_frame = max_pan_speed * src_w / fps
        sample_interval = max(1, int(fps / data.get("sample_fps", fps)))
        max_delta = max_delta_per_frame * sample_interval
        smoothed = _clamp_speed(smoothed, max_delta, src_w - crop_w)
    else:
        smoothed = raw_keyframes

    # Detect static vs pan regions
    static_regions = _detect_regions(smoothed, crop_w, threshold=5.0)

    result: dict[str, Any] = {
        "source": data.get("source", ""),
        "source_resolution": [src_w, src_h],
        "target_aspect": target_aspect,
        "crop_width": crop_w,
        "crop_height": crop_h,
        "output_resolution": output_resolution,
        "follow_track_id": target_tid,
        "smoothing_window": smoothing_window,
        "keyframe_count": len(smoothed),
        "keyframes": smoothed,
        "static_regions": static_regions,
    }

    return result


def _smooth_keyframes(
    keyframes: list[dict], window: int
) -> list[dict]:
    """Apply rolling average smoothing to crop_x values."""
    if window <= 1 or len(keyframes) <= 1:
        return keyframes

    values = [kf["crop_x"] for kf in keyframes]
    smoothed_values: list[int] = []

    half = window // 2
    for i in range(len(values)):
        start = max(0, i - half)
        end = min(len(values), i + half + 1)
        avg = sum(values[start:end]) / (end - start)
        smoothed_values.append(int(round(avg)))

    return [
        {"timestamp": kf["timestamp"], "crop_x": sv, "crop_y": 0}
        for kf, sv in zip(keyframes, smoothed_values)
    ]


def _clamp_speed(
    keyframes: list[dict], max_delta: float, max_x: int
) -> list[dict]:
    """Clamp consecutive crop_x changes to max_delta."""
    if len(keyframes) <= 1:
        return keyframes

    result = [keyframes[0].copy()]
    for i in range(1, len(keyframes)):
        prev_x = result[-1]["crop_x"]
        target_x = keyframes[i]["crop_x"]
        delta = target_x - prev_x

        if abs(delta) > max_delta:
            clamped_x = prev_x + int(max_delta * (1 if delta > 0 else -1))
        else:
            clamped_x = target_x

        clamped_x = max(0, min(clamped_x, max_x))
        result.append({
            "timestamp": keyframes[i]["timestamp"],
            "crop_x": clamped_x,
            "crop_y": 0,
        })

    return result


def _detect_regions(
    keyframes: list[dict], crop_w: int, threshold: float = 5.0
) -> list[dict[str, Any]]:
    """Detect static vs pan regions based on crop_x movement."""
    if not keyframes:
        return []

    regions: list[dict[str, Any]] = []
    region_start = keyframes[0]["timestamp"]
    region_xs: list[int] = [keyframes[0]["crop_x"]]

    for i in range(1, len(keyframes)):
        prev_x = keyframes[i - 1]["crop_x"]
        curr_x = keyframes[i]["crop_x"]

        if abs(curr_x - prev_x) > threshold:
            # Movement detected -- close current region if it was static
            if region_xs:
                avg_x = sum(region_xs) // len(region_xs)
                x_range = max(region_xs) - min(region_xs)
                movement = "minimal" if x_range < threshold * 3 else "pan_right" if region_xs[-1] > region_xs[0] else "pan_left"
                regions.append({
                    "start": round(region_start, 3),
                    "end": round(keyframes[i - 1]["timestamp"], 3),
                    "avg_crop_x": avg_x,
                    "movement": movement,
                })
            region_start = keyframes[i]["timestamp"]
            region_xs = [curr_x]
        else:
            region_xs.append(curr_x)

    # Close final region
    if region_xs:
        avg_x = sum(region_xs) // len(region_xs)
        x_range = max(region_xs) - min(region_xs)
        movement = "minimal" if x_range < threshold * 3 else "pan_right" if region_xs[-1] > region_xs[0] else "pan_left"
        regions.append({
            "start": round(region_start, 3),
            "end": round(keyframes[-1]["timestamp"], 3),
            "avg_crop_x": avg_x,
            "movement": movement,
        })

    return regions


def render_cropped_video(
    video_path: str,
    crop_keyframes: dict | str,
    output_path: str | None = None,
    scale_output: tuple = (1080, 1920),
) -> str:
    """Apply crop keyframes via FFmpeg.

    For mostly-static crops, uses a single crop+scale filter.
    For dynamic panning, uses the average crop per static region.

    Returns output file path.
    """
    if isinstance(crop_keyframes, str):
        with open(crop_keyframes, encoding="utf-8") as f:
            crop_keyframes = json.load(f)

    vpath = Path(video_path)
    if output_path is None:
        output_path = str(vpath.parent / f"{vpath.stem}_cropped.mp4")

    crop_w = crop_keyframes["crop_width"]
    crop_h = crop_keyframes["crop_height"]

    # Use average crop_x from all keyframes for single-pass render
    keyframes = crop_keyframes.get("keyframes", [])
    if keyframes:
        avg_x = sum(kf["crop_x"] for kf in keyframes) // len(keyframes)
    else:
        src_w = crop_keyframes["source_resolution"][0]
        avg_x = (src_w - crop_w) // 2

    sw, sh = scale_output
    vf = f"crop={crop_w}:{crop_h}:{avg_x}:0,scale={sw}:{sh}"

    cmd = [
        "ffmpeg", "-i", str(vpath),
        "-vf", vf,
        "-c:v", "libx264", "-crf", "23",
        "-c:a", "aac",
        "-y", output_path,
    ]

    subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=True)
    return output_path
