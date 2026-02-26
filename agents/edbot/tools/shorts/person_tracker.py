"""EdBot person tracker -- YOLO11 + BoT-SORT for per-frame person bounding boxes.

Detects and tracks all persons in landscape video. Outputs per-frame tracking data
used by smart_crop to generate portrait/square crop windows.

Primary: YOLO11n (nano, ~5.4MB, fast) -- user can switch to YOLO11s for accuracy.
GPU: RTX A6000 -- runs ~200+ FPS on 1080p with nano model.
Tracker: BoT-SORT (ultralytics default, handles occlusion + re-ID).
"""

import json
import logging
from pathlib import Path
from typing import Any

import cv2
from ultralytics import YOLO

logger = logging.getLogger(__name__)


def track_persons(
    video_path: str,
    output_dir: str = "temp",
    model_size: str = "n",
    confidence: float = 0.5,
    sample_fps: float | None = None,
    max_persons: int = 5,
) -> dict[str, Any]:
    """Detect and track persons in a video using YOLO11 + BoT-SORT.

    Parameters
    ----------
    video_path : str
        Path to source video file.
    output_dir : str
        Directory for output JSON.
    model_size : str
        YOLO11 model variant: "n" (nano), "s" (small), "m" (medium).
    confidence : float
        Minimum detection confidence (0-1).
    sample_fps : float | None
        If set, sample frames at this rate instead of every frame.
    max_persons : int
        Maximum persons to track per frame (by confidence).

    Returns
    -------
    dict
        Tracking data with per-frame bounding boxes and track summaries.
    """
    vpath = Path(video_path)
    if not vpath.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    # Load model
    model_name = f"yolo11{model_size}.pt"
    model = YOLO(model_name)

    # Open video
    cap = cv2.VideoCapture(str(vpath))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Compute sampling interval
    if sample_fps is not None and sample_fps > 0 and sample_fps < fps:
        frame_interval = max(1, round(fps / sample_fps))
    else:
        frame_interval = 1
        sample_fps = fps

    frames_data: list[dict[str, Any]] = []
    track_frames: dict[int, list[dict]] = {}  # track_id -> list of bbox records
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval == 0:
            timestamp = round(frame_idx / fps, 3)

            # Run YOLO tracking (class 0 = person only)
            results = model.track(
                frame,
                persist=True,
                classes=[0],
                conf=confidence,
                tracker="botsort.yaml",
                verbose=False,
            )

            persons: list[dict[str, Any]] = []
            if results and len(results) > 0:
                result = results[0]
                if result.boxes is not None and len(result.boxes) > 0:
                    boxes = result.boxes
                    for i in range(len(boxes)):
                        conf_val = float(boxes.conf[i])
                        # Get track ID (may be None if tracking not yet assigned)
                        track_id = None
                        if boxes.id is not None and i < len(boxes.id):
                            track_id = int(boxes.id[i])

                        # Get bbox in xywh format
                        xywh = boxes.xywh[i].tolist()
                        bbox = [int(v) for v in xywh]

                        persons.append({
                            "track_id": track_id,
                            "bbox": bbox,
                            "confidence": round(conf_val, 3),
                        })

            # Sort by confidence descending, cap at max_persons
            persons.sort(key=lambda p: p["confidence"], reverse=True)
            persons = persons[:max_persons]

            frames_data.append({
                "frame_idx": frame_idx,
                "timestamp": timestamp,
                "persons": persons,
            })

            # Accumulate track data for summary
            for p in persons:
                tid = p["track_id"]
                if tid is not None:
                    track_frames.setdefault(tid, []).append({
                        "timestamp": timestamp,
                        "bbox": p["bbox"],
                    })

        frame_idx += 1

    cap.release()

    # Compute track summaries
    track_summary: dict[str, dict[str, Any]] = {}
    for tid, records in track_frames.items():
        bboxes = [r["bbox"] for r in records]
        avg_bbox = [
            int(sum(b[i] for b in bboxes) / len(bboxes))
            for i in range(4)
        ]
        track_summary[str(tid)] = {
            "frame_count": len(records),
            "first_seen": records[0]["timestamp"],
            "last_seen": records[-1]["timestamp"],
            "avg_bbox": avg_bbox,
        }

    # Primary track = most frames
    primary_track_id = None
    if track_summary:
        primary_track_id = int(
            max(track_summary, key=lambda k: track_summary[k]["frame_count"])
        )

    tracking_data: dict[str, Any] = {
        "source": vpath.name,
        "frame_count": total_frames,
        "fps": round(fps, 2),
        "resolution": [width, height],
        "sample_fps": round(sample_fps, 2),
        "sampled_frame_count": len(frames_data),
        "frames": frames_data,
        "track_summary": track_summary,
        "primary_track_id": primary_track_id,
    }

    # Write output
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{vpath.stem}_tracking_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(tracking_data, f, indent=2)

    logger.info(
        "Tracked %d persons across %d sampled frames in %s",
        len(track_summary), len(frames_data), vpath.name,
    )
    return tracking_data
