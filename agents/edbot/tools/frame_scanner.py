"""Frame-level video analysis using CLIP and PySceneDetect.

All inference runs locally on GPU — zero cloud AI tokens.

- Scene detection via PySceneDetect (ContentDetector)
- Frame labeling via CLIP zero-shot classification (openai/clip-vit-base-patch32)
- Keyframe extraction at scene boundaries
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from scenedetect import detect, ContentDetector

try:
    from transformers import CLIPProcessor, CLIPModel
    from PIL import Image
    import torch
    _CLIP_AVAILABLE = True
except ImportError:
    _CLIP_AVAILABLE = False

logger = logging.getLogger(__name__)

# Default labels for zero-shot classification
DEFAULT_LABELS = [
    "person talking to camera",
    "interview",
    "b-roll footage",
    "screen recording",
    "text slide",
    "outdoor scene",
    "indoor scene",
    "close-up shot",
    "wide shot",
    "product demo",
    "whiteboard",
    "animation or graphics",
]


def detect_scenes(video_path: str, threshold: float = 27.0) -> dict[str, Any]:
    """Detect scene boundaries using PySceneDetect ContentDetector.

    Args:
        video_path: Path to video file.
        threshold: ContentDetector threshold (default 27.0).

    Returns:
        Dict with keys: scenes (list of {start_sec, end_sec, duration_sec}),
        scene_count, video_path.
    """
    p = Path(video_path)
    if not p.exists():
        return {"error": f"file not found: {video_path}", "code": "FILE_NOT_FOUND"}

    try:
        scene_list = detect(str(p), ContentDetector(threshold=threshold))
    except Exception as exc:
        return {"error": f"scene detection failed: {exc}", "code": "SCENE_ERROR"}

    scenes = []
    for start, end in scene_list:
        scenes.append({
            "start_sec": round(start.get_seconds(), 3),
            "end_sec": round(end.get_seconds(), 3),
            "duration_sec": round((end - start).get_seconds(), 3),
        })

    return {
        "video_path": str(p),
        "scenes": scenes,
        "scene_count": len(scenes),
    }


def extract_keyframes(video_path: str, timestamps: list[float], output_dir: str = "temp") -> list[str]:
    """Extract keyframes at specific timestamps using ffmpeg.

    Args:
        video_path: Path to video file.
        timestamps: List of timestamps in seconds.
        output_dir: Directory to save extracted frames.

    Returns:
        List of paths to extracted frame images.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    stem = Path(video_path).stem
    frame_paths = []

    for i, ts in enumerate(timestamps):
        frame_path = out / f"{stem}_frame_{i:04d}.jpg"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", str(ts),
                    "-i", str(video_path),
                    "-frames:v", "1",
                    "-q:v", "2",
                    str(frame_path),
                ],
                capture_output=True, timeout=10,
            )
            if frame_path.exists():
                frame_paths.append(str(frame_path))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

    return frame_paths


def label_frames(
    frame_paths: list[str],
    labels: list[str] | None = None,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Label frames using CLIP zero-shot classification.

    All inference is local GPU — zero cloud tokens.

    Args:
        frame_paths: List of paths to image files.
        labels: Custom labels for classification (defaults to DEFAULT_LABELS).
        top_k: Number of top labels to return per frame.

    Returns:
        List of dicts with keys: frame_path, labels (list of {label, score}).
    """
    if not frame_paths:
        return []

    labels = labels or DEFAULT_LABELS

    if not _CLIP_AVAILABLE:
        return [{"frame_path": fp, "error": "CLIP dependencies not installed"} for fp in frame_paths]

    device = "cuda" if torch.cuda.is_available() else "cpu"

    try:
        model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        model = model.to(device)
        model.eval()
    except Exception as exc:
        logger.error("Failed to load CLIP model: %s", exc)
        return [{"frame_path": fp, "error": f"model load failed: {exc}"} for fp in frame_paths]

    results = []
    for fp in frame_paths:
        try:
            image = Image.open(fp).convert("RGB")
            inputs = processor(text=labels, images=image, return_tensors="pt", padding=True)
            inputs = {k: v.to(device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = model(**inputs)
                logits = outputs.logits_per_image[0]
                probs = logits.softmax(dim=0)

            scored = sorted(
                zip(labels, probs.cpu().tolist()),
                key=lambda x: x[1],
                reverse=True,
            )[:top_k]

            results.append({
                "frame_path": fp,
                "labels": [{"label": lbl, "score": round(s, 4)} for lbl, s in scored],
            })
        except Exception as exc:
            results.append({"frame_path": fp, "error": str(exc)})

    return results


def scan_frames(
    video_path: str,
    labels: list[str] | None = None,
    scene_threshold: float = 27.0,
    top_k: int = 3,
    output_dir: str = "temp",
) -> dict[str, Any]:
    """Full frame scanning pipeline: detect scenes, extract keyframes, label with CLIP.

    Args:
        video_path: Path to video file.
        labels: Custom CLIP labels (defaults to DEFAULT_LABELS).
        scene_threshold: PySceneDetect threshold.
        top_k: Top-k CLIP labels per frame.
        output_dir: Where to save extracted frames.

    Returns:
        Dict with keys: video_path, scenes, frames, scene_count.
    """
    # Step 1: Detect scenes
    scene_result = detect_scenes(video_path, threshold=scene_threshold)
    if scene_result.get("error"):
        return scene_result

    scenes = scene_result["scenes"]

    # Step 2: Extract keyframes at scene start points
    timestamps = [s["start_sec"] for s in scenes]
    # Always include first frame
    if not timestamps or timestamps[0] > 0.5:
        timestamps.insert(0, 0.0)

    frame_paths = extract_keyframes(video_path, timestamps, output_dir)

    # Step 3: Label frames with CLIP
    labeled = label_frames(frame_paths, labels=labels, top_k=top_k)

    # Merge scene info with frame labels
    for i, scene in enumerate(scenes):
        if i < len(labeled):
            scene["frame_labels"] = labeled[i].get("labels", [])
            scene["frame_path"] = labeled[i].get("frame_path")

    return {
        "video_path": str(video_path),
        "scenes": scenes,
        "frames": labeled,
        "scene_count": len(scenes),
    }
