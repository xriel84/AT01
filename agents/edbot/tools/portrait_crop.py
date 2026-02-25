"""Portrait (9:16) cropping with center-crop default and optional mediapipe face detection.

Crops landscape video to portrait aspect ratio using ffmpeg. Center crop is the
default method (always works, no external dependencies). Face detection via
mediapipe is an upgrade path with lazy import and graceful fallback.
"""

import argparse
import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _safe_output_path(output_dir: Path, stem: str, suffix: str, ext: str) -> Path:
    """Build an output path that never overwrites an existing file.

    Pattern: {stem}_{suffix}{ext}. If that exists, try {stem}_{suffix}_1{ext},
    {stem}_{suffix}_2{ext}, etc.
    """
    candidate = output_dir / f"{stem}_{suffix}{ext}"
    if not candidate.exists():
        return candidate

    counter = 1
    while True:
        candidate = output_dir / f"{stem}_{suffix}_{counter}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


# ---------------------------------------------------------------------------
# Face detection (upgrade path — lazy import, graceful fallback)
# ---------------------------------------------------------------------------


def _crop_with_face_detect(
    input_path: Path,
    output_path: Path,
    start: float | None = None,
    end: float | None = None,
) -> dict | None:
    """Attempt portrait crop centered on detected face position.

    Uses mediapipe for face detection on the first frame. Returns a result
    dict on success, or None if mediapipe is unavailable (caller falls back
    to center crop).
    """
    try:
        import mediapipe as mp  # type: ignore[import-not-found]
    except ImportError:
        return None

    # If mediapipe is available, detect face in first frame and compute
    # horizontal offset for the crop. This is the upgrade path — not
    # expected to work today.
    try:
        import cv2  # type: ignore[import-not-found]

        cap = cv2.VideoCapture(str(input_path))
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return None

        h, w = frame.shape[:2]
        crop_w = int(h * 9 / 16)

        # Detect face using mediapipe.
        face_detection = mp.solutions.face_detection.FaceDetection(
            min_detection_confidence=0.5,
        )
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_detection.process(rgb_frame)
        face_detection.close()

        if not results.detections:
            return None

        # Use the first detection's bounding box center.
        bbox = results.detections[0].location_data.relative_bounding_box
        face_center_x = bbox.xmin + bbox.width / 2
        # Convert to pixel position.
        center_px = int(face_center_x * w)

        # Compute crop x offset, clamped to valid range.
        x_offset = max(0, min(center_px - crop_w // 2, w - crop_w))

        crop_filter = f"crop={crop_w}:{h}:{x_offset}:0"

        cmd = ["ffmpeg"]
        if start is not None:
            cmd.extend(["-ss", str(start)])
        cmd.extend(["-i", str(input_path)])
        if start is not None and end is not None:
            duration = end - start
            cmd.extend(["-t", str(duration)])
        elif end is not None:
            cmd.extend(["-t", str(end)])
        cmd.extend(["-vf", crop_filter, "-c:a", "copy", "-y", str(output_path)])

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            return None

        return {
            "method": "face",
            "crop_filter": crop_filter,
            "ffmpeg_cmd": shlex.join(cmd),
        }

    except Exception:
        return None


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def portrait_crop(
    input_path: str,
    output_dir: str = "output",
    method: str = "center",
    start: float | None = None,
    end: float | None = None,
) -> dict:
    """Crop landscape video to portrait (9:16) aspect ratio.

    Args:
        input_path: Path to input video file.
        output_dir: Output directory for cropped file.
        method: Crop method — "center" (default) or "face" (mediapipe upgrade).
        start: Optional start time in seconds for trimming.
        end: Optional end time in seconds for trimming.

    Returns:
        Result dict with keys: status, action, input, output, method,
        duration_in, duration_out, crop_filter, ffmpeg_cmd, elapsed_seconds, error.
    """
    t0 = time.perf_counter()

    in_path = Path(input_path)
    out_dir = Path(output_dir)

    # Validate input exists.
    if not in_path.exists():
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            input_path=str(in_path),
            output_path=None,
            method=method,
            duration_in=None,
            duration_out=None,
            crop_filter=None,
            ffmpeg_cmd=None,
            elapsed_seconds=elapsed,
            error=f"input file not found: {in_path}",
        )

    # Create output directory.
    out_dir.mkdir(parents=True, exist_ok=True)

    # Get input duration.
    duration_in = _get_duration(in_path)

    # Build output path: {stem}_portrait{ext}
    out_path = _safe_output_path(out_dir, in_path.stem, "portrait", in_path.suffix)

    # Try face detection method if requested.
    if method == "face":
        face_result = _crop_with_face_detect(in_path, out_path, start, end)
        if face_result is not None:
            duration_out = _get_duration(out_path)
            elapsed = time.perf_counter() - t0
            return _result_dict(
                status="success",
                input_path=str(in_path),
                output_path=str(out_path),
                method="face",
                duration_in=duration_in,
                duration_out=duration_out,
                crop_filter=face_result["crop_filter"],
                ffmpeg_cmd=face_result["ffmpeg_cmd"],
                elapsed_seconds=elapsed,
                error=None,
            )
        # Face detection unavailable — fall through to center crop.

    # Center crop: crop=ih*9/16:ih (uses input height to compute width).
    crop_filter = "crop=ih*9/16:ih"

    cmd = ["ffmpeg"]

    # Place -ss before -i for fast input seeking.
    if start is not None:
        cmd.extend(["-ss", str(start)])

    cmd.extend(["-i", str(in_path)])

    # Compute duration for -t flag.
    if start is not None and end is not None:
        duration = end - start
        cmd.extend(["-t", str(duration)])
    elif end is not None:
        cmd.extend(["-t", str(end)])

    cmd.extend(["-vf", crop_filter, "-c:a", "copy", "-y", str(out_path)])

    cmd_str = shlex.join(cmd)

    # Run ffmpeg.
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            input_path=str(in_path),
            output_path=str(out_path),
            method="center",
            duration_in=duration_in,
            duration_out=None,
            crop_filter=crop_filter,
            ffmpeg_cmd=cmd_str,
            elapsed_seconds=elapsed,
            error=str(exc),
        )

    if proc.returncode != 0:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            input_path=str(in_path),
            output_path=str(out_path),
            method="center",
            duration_in=duration_in,
            duration_out=None,
            crop_filter=crop_filter,
            ffmpeg_cmd=cmd_str,
            elapsed_seconds=elapsed,
            error=f"ffmpeg exited {proc.returncode}: {proc.stderr[:500]}",
        )

    # Get output duration.
    duration_out = _get_duration(out_path)

    elapsed = time.perf_counter() - t0
    return _result_dict(
        status="success",
        input_path=str(in_path),
        output_path=str(out_path),
        method="center",
        duration_in=duration_in,
        duration_out=duration_out,
        crop_filter=crop_filter,
        ffmpeg_cmd=cmd_str,
        elapsed_seconds=elapsed,
        error=None,
    )


def _result_dict(
    *,
    status: str,
    input_path: str,
    output_path: str | None,
    method: str,
    duration_in: float | None,
    duration_out: float | None,
    crop_filter: str | None,
    ffmpeg_cmd: str | None,
    elapsed_seconds: float,
    error: str | None,
) -> dict[str, Any]:
    """Build the standard result dict for portrait_crop."""
    return {
        "status": status,
        "action": "portrait_crop",
        "input": input_path,
        "output": output_path,
        "method": method,
        "duration_in": duration_in,
        "duration_out": duration_out,
        "crop_filter": crop_filter,
        "ffmpeg_cmd": ffmpeg_cmd,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "error": error,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for portrait cropping."""
    parser = argparse.ArgumentParser(description="Portrait (9:16) crop for video")
    parser.add_argument("--input", required=True, help="Path to video file")
    parser.add_argument("--output-dir", default="output",
                        help="Output directory (default: output)")
    parser.add_argument("--method", default="center", choices=["center", "face"],
                        help="Crop method (default: center)")
    parser.add_argument("--start", type=float, default=None,
                        help="Start time in seconds")
    parser.add_argument("--end", type=float, default=None,
                        help="End time in seconds")
    parser.add_argument("--json", action="store_true",
                        help="Print result as JSON to stdout")
    args = parser.parse_args()

    result = portrait_crop(
        input_path=args.input,
        output_dir=args.output_dir,
        method=args.method,
        start=args.start,
        end=args.end,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["status"] == "success":
            print(f"Portrait crop: {result['input']} -> {result['output']}")
            print(f"  Method: {result['method']}")
            print(f"  Filter: {result['crop_filter']}")
            print(f"  Duration: {result['duration_in']}s -> {result['duration_out']}s")
            print(f"  Elapsed: {result['elapsed_seconds']}s")
        else:
            print(f"Error: {result['error']}")


if __name__ == "__main__":
    main()
