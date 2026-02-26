"""EdBot shorts assembler -- orchestrate full landscape-to-shorts pipeline.

Chains: person_tracker -> smart_crop -> face_zoom -> animated_captions ->
emphasis_zoom -> retention_pacer -> FFmpeg render.

Each step is optional and produces intermediate JSON.
Human can review/edit intermediates before final render.
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from . import person_tracker, smart_crop, face_zoom
from . import animated_captions, emphasis_zoom, retention_pacer

logger = logging.getLogger(__name__)

# Supported video extensions
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".mxf"}


def assemble_short(
    video_path: str,
    output_dir: str = "output",
    target_aspect: str = "9:16",
    max_duration: float = 60.0,
    caption_style: str = "highlight_word",
    enable_face_zoom: bool = True,
    enable_emphasis_zoom: bool = True,
    zoom_alternation_interval: float = 4.0,
    output_resolution: tuple | None = None,
) -> dict[str, Any]:
    """Assemble a short-form video from landscape source.

    Parameters
    ----------
    video_path : str
        Path to source landscape video.
    output_dir : str
        Output directory for final render.
    target_aspect : str
        Target aspect ratio: "9:16" or "1:1".
    max_duration : float
        Maximum output duration in seconds.
    caption_style : str
        Caption style preset name.
    enable_face_zoom : bool
        Whether to detect and apply face zoom segments.
    enable_emphasis_zoom : bool
        Whether to detect audio emphasis for zoom.
    zoom_alternation_interval : float
        Seconds between zoom alternations.
    output_resolution : tuple | None
        Override output resolution. Auto-computed if None.

    Returns
    -------
    dict
        Assembly manifest with all intermediate paths and settings.
    """
    vpath = Path(video_path)
    if not vpath.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    # Resolve output resolution
    if output_resolution is None:
        if target_aspect == "9:16":
            output_resolution = (1080, 1920)
        elif target_aspect == "1:1":
            output_resolution = (1080, 1080)
        else:
            output_resolution = (1080, 1920)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = out_dir.parent / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    stem = vpath.stem

    pipeline_steps: dict[str, str | None] = {}

    # Step 1: Transcribe (reuse existing)
    transcript_path = temp_dir / f"{stem}_transcript.json"
    transcript_data = None
    if transcript_path.exists():
        with open(transcript_path, encoding="utf-8") as f:
            transcript_data = json.load(f)
        pipeline_steps["transcribe"] = str(transcript_path)
    else:
        try:
            import sys
            _tools_dir = str(Path(__file__).resolve().parent.parent)
            if _tools_dir not in sys.path:
                sys.path.insert(0, _tools_dir)
            from transcribe import transcribe_video
            transcript_data = transcribe_video(video_path, str(temp_dir))
            pipeline_steps["transcribe"] = str(transcript_path)
        except Exception as exc:
            logger.warning("Transcription failed: %s", exc)
            pipeline_steps["transcribe"] = None

    # Step 2: Silence detect (reuse existing)
    silence_path = temp_dir / f"{stem}_silence_map.json"
    silence_data = None
    if silence_path.exists():
        with open(silence_path, encoding="utf-8") as f:
            silence_data = json.load(f)
        pipeline_steps["silence"] = str(silence_path)
    else:
        pipeline_steps["silence"] = None

    # Step 3: Track persons
    try:
        tracking_data = person_tracker.track_persons(
            video_path, output_dir=str(temp_dir),
        )
        pipeline_steps["tracking"] = str(temp_dir / f"{stem}_tracking_data.json")
    except Exception as exc:
        logger.warning("Person tracking failed: %s", exc)
        tracking_data = None
        pipeline_steps["tracking"] = None

    # Step 4: Smart crop
    if tracking_data:
        try:
            crop_data = smart_crop.generate_crop_keyframes(
                tracking_data, target_aspect=target_aspect,
            )
            crop_path = temp_dir / f"{stem}_crop_keyframes.json"
            with open(crop_path, "w", encoding="utf-8") as f:
                json.dump(crop_data, f, indent=2)
            pipeline_steps["crop"] = str(crop_path)
        except Exception as exc:
            logger.warning("Smart crop failed: %s", exc)
            crop_data = None
            pipeline_steps["crop"] = None
    else:
        crop_data = None
        pipeline_steps["crop"] = None

    # Step 5: Face zoom (optional)
    zoom_data = None
    if enable_face_zoom:
        try:
            zoom_data = face_zoom.detect_face_zoom_points(
                video_path, output_dir=str(temp_dir),
            )
            pipeline_steps["face_zoom"] = str(temp_dir / f"{stem}_zoom_keyframes.json")
        except Exception as exc:
            logger.warning("Face zoom detection failed: %s", exc)
            pipeline_steps["face_zoom"] = None
    else:
        pipeline_steps["face_zoom"] = None

    # Step 6: Emphasis zoom (optional)
    emphasis_data = None
    if enable_emphasis_zoom:
        try:
            emphasis_data = emphasis_zoom.detect_emphasis_points(
                video_path, output_dir=str(temp_dir),
            )
            pipeline_steps["emphasis"] = str(temp_dir / f"{stem}_emphasis_keyframes.json")
        except Exception as exc:
            logger.warning("Emphasis zoom detection failed: %s", exc)
            pipeline_steps["emphasis"] = None
    else:
        pipeline_steps["emphasis"] = None

    # Step 7: Retention pacing
    try:
        pacing_data = retention_pacer.analyze_pacing(
            video_path, output_dir=str(temp_dir), silence_map=silence_data,
        )
        pipeline_steps["pacing"] = str(temp_dir / f"{stem}_pacing_analysis.json")
    except Exception as exc:
        logger.warning("Retention pacing failed: %s", exc)
        pacing_data = None
        pipeline_steps["pacing"] = None

    # Step 8: Animated captions
    caption_path = None
    if transcript_data:
        try:
            ass_path = str(temp_dir / f"{stem}_captions.ass")
            caption_manifest = animated_captions.generate_animated_captions(
                transcript_data,
                output_path=ass_path,
                style=caption_style,
                target_resolution=output_resolution,
            )
            caption_path = ass_path
            pipeline_steps["captions"] = ass_path
        except Exception as exc:
            logger.warning("Caption generation failed: %s", exc)
            pipeline_steps["captions"] = None
    else:
        pipeline_steps["captions"] = None

    # Step 9: Render via FFmpeg
    output_name = f"{stem}_short_{target_aspect.replace(':', 'x')}.mp4"
    output_path = out_dir / output_name

    try:
        _render_short(
            video_path=str(vpath),
            output_path=str(output_path),
            crop_data=crop_data,
            caption_path=caption_path,
            max_duration=max_duration,
            output_resolution=output_resolution,
        )
    except Exception as exc:
        logger.warning("Render failed: %s", exc)
        output_path = None

    manifest: dict[str, Any] = {
        "source": str(vpath),
        "output": str(output_path) if output_path else None,
        "target_aspect": target_aspect,
        "output_resolution": list(output_resolution),
        "duration": max_duration,
        "pipeline_steps": pipeline_steps,
        "settings": {
            "caption_style": caption_style,
            "face_zoom_enabled": enable_face_zoom,
            "emphasis_zoom_enabled": enable_emphasis_zoom,
            "max_duration": max_duration,
        },
    }

    # Write manifest
    manifest_path = out_dir / f"{stem}_assembly_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def _render_short(
    video_path: str,
    output_path: str,
    crop_data: dict | None,
    caption_path: str | None,
    max_duration: float,
    output_resolution: tuple,
) -> None:
    """Render the final short via FFmpeg."""
    vf_filters: list[str] = []

    # Crop filter
    if crop_data:
        crop_w = crop_data["crop_width"]
        crop_h = crop_data["crop_height"]
        keyframes = crop_data.get("keyframes", [])
        if keyframes:
            avg_x = sum(kf["crop_x"] for kf in keyframes) // len(keyframes)
        else:
            src_w = crop_data["source_resolution"][0]
            avg_x = (src_w - crop_w) // 2
        vf_filters.append(f"crop={crop_w}:{crop_h}:{avg_x}:0")

    # Scale to output resolution
    sw, sh = output_resolution
    vf_filters.append(f"scale={sw}:{sh}")

    # Caption overlay
    if caption_path and Path(caption_path).exists():
        # Escape path for FFmpeg filter (backslashes and colons)
        esc_path = caption_path.replace("\\", "/").replace(":", "\\:")
        vf_filters.append(f"ass={esc_path}")

    vf_str = ",".join(vf_filters) if vf_filters else f"scale={sw}:{sh}"

    cmd = ["ffmpeg", "-i", video_path]

    if max_duration and max_duration > 0:
        cmd.extend(["-t", str(max_duration)])

    cmd.extend([
        "-vf", vf_str,
        "-c:v", "libx264", "-crf", "23",
        "-c:a", "aac",
        "-y", output_path,
    ])

    subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=True)


def batch_assemble_shorts(
    input_dir: str,
    output_dir: str = "output/shorts",
    **kwargs: Any,
) -> dict[str, Any]:
    """Process all videos in input_dir through assemble_short.

    Parameters
    ----------
    input_dir : str
        Directory containing source video files.
    output_dir : str
        Output directory for rendered shorts.
    **kwargs
        Passed through to assemble_short().

    Returns
    -------
    dict
        Batch manifest with results per video.
    """
    in_dir = Path(input_dir)
    if not in_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    videos = [
        f for f in in_dir.iterdir()
        if f.is_file() and f.suffix.lower() in _VIDEO_EXTS
    ]

    results: list[dict[str, Any]] = []
    for video in sorted(videos):
        try:
            manifest = assemble_short(str(video), output_dir=output_dir, **kwargs)
            results.append({"source": str(video), "status": "success", "manifest": manifest})
        except Exception as exc:
            results.append({"source": str(video), "status": "error", "error": str(exc)})

    batch_manifest: dict[str, Any] = {
        "input_dir": str(in_dir),
        "output_dir": output_dir,
        "total": len(videos),
        "success": sum(1 for r in results if r["status"] == "success"),
        "failed": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "batch_shorts_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(batch_manifest, f, indent=2)

    return batch_manifest
