"""EdBot executor — runs FFmpeg actions from NLP action JSON.

Takes an action dict (from nlp_action.parse_command), builds the
corresponding FFmpeg command, executes it via subprocess.run, and
returns a result dict with output path, timing, and metadata.
"""

import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Sibling imports — mirrors pattern used by other edbot tools.
_tools_dir = str(Path(__file__).resolve().parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

try:
    from subtitle_burn import burn_subtitle as _burn_subtitle
except ImportError:
    _burn_subtitle = None  # type: ignore[assignment]

try:
    from transcribe import transcribe_video as _transcribe_video
except ImportError:
    _transcribe_video = None  # type: ignore[assignment]

try:
    from resolve_bridge import resolve_export as _resolve_export
except ImportError:
    _resolve_export = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Platform export presets
# ---------------------------------------------------------------------------

PLATFORM_PRESETS: dict[str, dict[str, Any]] = {
    "tiktok":         {"max_duration": 60,   "aspect": "9:16", "codec": "libx264", "crf": 23},
    "youtube_shorts": {"max_duration": 60,   "aspect": "9:16", "codec": "libx264", "crf": 23},
    "ig_reels":       {"max_duration": 90,   "aspect": "9:16", "codec": "libx264", "crf": 23},
    "x_video":        {"max_duration": 140,  "aspect": "16:9", "codec": "libx264", "crf": 23},
    "youtube_long":   {"max_duration": None, "aspect": "16:9", "codec": "libx264", "crf": 18},
}

# Supported action types that this executor handles.
SUPPORTED_ACTIONS: set[str] = {
    "silence_remove", "trim", "crop", "caption_burn",
    "platform_export", "transcribe", "resolve_export",
    "assemble_short", "smart_crop", "person_track",
    "animated_captions", "batch_shorts",
}


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


def _safe_output_path(output_dir: Path, stem: str, action: str, ext: str) -> Path:
    """Build an output path that never overwrites an existing file.

    Pattern: {stem}_{action}{ext}. If that exists, try {stem}_{action}_1{ext},
    {stem}_{action}_2{ext}, etc.
    """
    candidate = output_dir / f"{stem}_{action}{ext}"
    if not candidate.exists():
        return candidate

    counter = 1
    while True:
        candidate = output_dir / f"{stem}_{action}_{counter}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


def _result_dict(
    *,
    status: str,
    action: str,
    input_path: str,
    output_path: str | None,
    duration_in: float | None,
    duration_out: float | None,
    ffmpeg_cmd: str | None,
    elapsed_seconds: float,
    error: str | None,
) -> dict[str, Any]:
    """Build the standard result dict."""
    return {
        "status": status,
        "action": action,
        "input": input_path,
        "output": output_path,
        "duration_in": duration_in,
        "duration_out": duration_out,
        "ffmpeg_cmd": ffmpeg_cmd,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "error": error,
    }


def _aspect_to_scale_crop(aspect: str, src_width: int = 1920, src_height: int = 1080) -> str:
    """Convert aspect ratio string to FFmpeg scale+crop filter chain.

    Returns a -vf filter string like 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920'.
    """
    parts = aspect.split(":")
    aw, ah = int(parts[0]), int(parts[1])

    # Calculate target dimensions maintaining source size order-of-magnitude.
    if aw > ah:
        # landscape
        target_w = src_width
        target_h = int(src_width * ah / aw)
    elif ah > aw:
        # portrait
        target_h = src_height
        target_w = int(src_height * aw / ah)
    else:
        # square
        dim = min(src_width, src_height)
        target_w = dim
        target_h = dim

    return (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h}"
    )


# ---------------------------------------------------------------------------
# Action handlers — each returns (cmd_list, output_path) or raises ValueError
# ---------------------------------------------------------------------------

def _handle_silence_remove(
    input_path: Path, output_path: Path, params: dict[str, Any],
) -> list[str]:
    """Build ffmpeg command for silence removal using silencedetect + segment filter."""
    threshold = params.get("silence_threshold_db", -30)
    return [
        "ffmpeg", "-i", str(input_path),
        "-af", f"silenceremove=start_periods=1:start_silence=0.5:start_threshold={threshold}dB:"
               f"stop_periods=-1:stop_silence=0.5:stop_threshold={threshold}dB",
        "-c:v", "copy",
        "-y", str(output_path),
    ]


def _handle_trim(
    input_path: Path, output_path: Path, params: dict[str, Any],
) -> list[str]:
    """Build ffmpeg command for trimming video."""
    cmd = ["ffmpeg"]

    # Place -ss before -i for fast input seeking.
    start = params.get("start")
    if start is not None:
        cmd.extend(["-ss", str(start)])

    cmd.extend(["-i", str(input_path)])

    max_duration = params.get("max_duration")
    if max_duration is not None:
        cmd.extend(["-t", str(max_duration)])

    cmd.extend(["-c", "copy", "-y", str(output_path)])
    return cmd


def _handle_crop(
    input_path: Path, output_path: Path, params: dict[str, Any],
) -> list[str]:
    """Build ffmpeg command for cropping to target aspect ratio."""
    aspect = params.get("aspect", "9:16")
    vf = _aspect_to_scale_crop(aspect)
    return [
        "ffmpeg", "-i", str(input_path),
        "-vf", vf,
        "-c:a", "copy",
        "-y", str(output_path),
    ]


def _handle_platform_export(
    input_path: Path, output_path: Path, params: dict[str, Any],
) -> list[str]:
    """Build ffmpeg command for platform-specific export."""
    platform = params.get("platform", "tiktok")
    preset = PLATFORM_PRESETS.get(platform, PLATFORM_PRESETS["tiktok"])

    codec = preset["codec"]
    crf = preset["crf"]
    aspect = preset["aspect"]
    max_duration = preset["max_duration"]

    vf = _aspect_to_scale_crop(aspect)

    cmd = ["ffmpeg", "-i", str(input_path)]

    if max_duration is not None:
        cmd.extend(["-t", str(max_duration)])

    cmd.extend([
        "-vf", vf,
        "-c:v", codec,
        "-crf", str(crf),
        "-c:a", "aac",
        "-y", str(output_path),
    ])
    return cmd


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def execute_action(
    action: dict[str, Any],
    input_path: str | None = None,
    output_dir: str = "output",
) -> dict[str, Any]:
    """Execute an NLP action dict and return a result dict.

    Parameters
    ----------
    action : dict
        Action JSON from nlp_action.parse_command(). Required keys:
        action, params, executor.
    input_path : str | None
        Override for action["params"]["input"]. Takes precedence when provided.
    output_dir : str
        Output directory for rendered files.

    Returns
    -------
    dict
        Result dict with keys: status, action, input, output, duration_in,
        duration_out, ffmpeg_cmd, elapsed_seconds, error.
    """
    t0 = time.perf_counter()

    # --- Validate action dict ---
    required_keys = {"action", "params", "executor"}
    missing = required_keys - set(action.keys())
    if missing:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            action=action.get("action", "unknown"),
            input_path=input_path,
            output_path=None,
            duration_in=None,
            duration_out=None,
            ffmpeg_cmd=None,
            elapsed_seconds=elapsed,
            error=f"missing required keys: {sorted(missing)}",
        )

    action_type: str = action["action"]
    params: dict[str, Any] = action.get("params", {})

    # --- Resolve input path (arg overrides params) ---
    resolved_input = input_path or params.get("input")
    if not resolved_input:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            action=action_type,
            input_path=None,
            output_path=None,
            duration_in=None,
            duration_out=None,
            ffmpeg_cmd=None,
            elapsed_seconds=elapsed,
            error="no input path provided",
        )

    in_path = Path(resolved_input)

    # --- Validate action type ---
    if action_type not in SUPPORTED_ACTIONS:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            action=action_type,
            input_path=str(in_path),
            output_path=None,
            duration_in=None,
            duration_out=None,
            ffmpeg_cmd=None,
            elapsed_seconds=elapsed,
            error=f"unsupported action: {action_type}",
        )

    # --- Resolve output dir ---
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Delegate to wrapper functions for non-ffmpeg actions ---
    if action_type == "caption_burn":
        return _execute_caption_burn(in_path, out_dir, params, t0)

    if action_type == "transcribe":
        return _execute_transcribe(in_path, out_dir, params, t0)

    if action_type == "resolve_export":
        return _execute_resolve_export(in_path, out_dir, params, t0)

    if action_type == "assemble_short":
        return _execute_assemble_short(in_path, out_dir, params, t0)

    if action_type == "smart_crop":
        return _execute_smart_crop(in_path, out_dir, params, t0)

    if action_type == "person_track":
        return _execute_person_track(in_path, out_dir, params, t0)

    if action_type == "animated_captions":
        return _execute_animated_captions(in_path, out_dir, params, t0)

    if action_type == "batch_shorts":
        return _execute_batch_shorts(in_path, out_dir, params, t0)

    # --- Get input duration ---
    duration_in = _get_duration(in_path)

    # --- Build output path ---
    out_path = _safe_output_path(out_dir, in_path.stem, action_type, in_path.suffix)

    # --- Build ffmpeg command ---
    try:
        if action_type == "silence_remove":
            cmd = _handle_silence_remove(in_path, out_path, params)
        elif action_type == "trim":
            cmd = _handle_trim(in_path, out_path, params)
        elif action_type == "crop":
            cmd = _handle_crop(in_path, out_path, params)
        elif action_type == "platform_export":
            cmd = _handle_platform_export(in_path, out_path, params)
        else:
            # Should not reach here due to SUPPORTED_ACTIONS check above.
            elapsed = time.perf_counter() - t0
            return _result_dict(
                status="error",
                action=action_type,
                input_path=str(in_path),
                output_path=None,
                duration_in=duration_in,
                duration_out=None,
                ffmpeg_cmd=None,
                elapsed_seconds=elapsed,
                error=f"no handler for action: {action_type}",
            )
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            action=action_type,
            input_path=str(in_path),
            output_path=None,
            duration_in=duration_in,
            duration_out=None,
            ffmpeg_cmd=None,
            elapsed_seconds=elapsed,
            error=str(exc),
        )

    cmd_str = shlex.join(cmd)

    # --- Run ffmpeg ---
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            action=action_type,
            input_path=str(in_path),
            output_path=str(out_path),
            duration_in=duration_in,
            duration_out=None,
            ffmpeg_cmd=cmd_str,
            elapsed_seconds=elapsed,
            error=str(exc),
        )

    if proc.returncode != 0:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            action=action_type,
            input_path=str(in_path),
            output_path=str(out_path),
            duration_in=duration_in,
            duration_out=None,
            ffmpeg_cmd=cmd_str,
            elapsed_seconds=elapsed,
            error=f"ffmpeg exited {proc.returncode}: {proc.stderr[:500]}",
        )

    # --- Get output duration ---
    duration_out = _get_duration(out_path)

    elapsed = time.perf_counter() - t0
    return _result_dict(
        status="success",
        action=action_type,
        input_path=str(in_path),
        output_path=str(out_path),
        duration_in=duration_in,
        duration_out=duration_out,
        ffmpeg_cmd=cmd_str,
        elapsed_seconds=elapsed,
        error=None,
    )


# ---------------------------------------------------------------------------
# Wrapper handlers for non-pure-ffmpeg actions
# ---------------------------------------------------------------------------

def _execute_caption_burn(
    in_path: Path, out_dir: Path, params: dict[str, Any], t0: float,
) -> dict[str, Any]:
    """Wrap subtitle_burn.burn_subtitle for caption_burn action."""
    if _burn_subtitle is None:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            action="caption_burn",
            input_path=str(in_path),
            output_path=None,
            duration_in=None,
            duration_out=None,
            ffmpeg_cmd=None,
            elapsed_seconds=elapsed,
            error="subtitle_burn module not available",
        )

    # Determine ASS subtitle path — look for {stem}.ass next to input.
    ass_path = params.get("ass_path")
    if ass_path:
        ass_file = Path(ass_path)
    else:
        ass_file = in_path.with_suffix(".ass")

    out_path = _safe_output_path(out_dir, in_path.stem, "caption_burn", in_path.suffix)

    duration_in = _get_duration(in_path)

    result = _burn_subtitle(in_path, ass_file, out_path)

    duration_out = _get_duration(out_path) if result.get("status") == "ok" else None

    elapsed = time.perf_counter() - t0
    status = "success" if result.get("status") == "ok" else "error"
    error = result.get("error") if status == "error" else None

    return _result_dict(
        status=status,
        action="caption_burn",
        input_path=str(in_path),
        output_path=str(out_path),
        duration_in=duration_in,
        duration_out=duration_out,
        ffmpeg_cmd=None,
        elapsed_seconds=elapsed,
        error=error,
    )


def _execute_transcribe(
    in_path: Path, out_dir: Path, params: dict[str, Any], t0: float,
) -> dict[str, Any]:
    """Wrap transcribe.transcribe_video for transcribe action."""
    if _transcribe_video is None:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            action="transcribe",
            input_path=str(in_path),
            output_path=None,
            duration_in=None,
            duration_out=None,
            ffmpeg_cmd=None,
            elapsed_seconds=elapsed,
            error="transcribe module not available",
        )

    result = _transcribe_video(str(in_path), str(out_dir))

    elapsed = time.perf_counter() - t0
    if "error" in result:
        return _result_dict(
            status="error",
            action="transcribe",
            input_path=str(in_path),
            output_path=str(out_dir),
            duration_in=None,
            duration_out=None,
            ffmpeg_cmd=None,
            elapsed_seconds=elapsed,
            error=result["error"],
        )

    return _result_dict(
        status="success",
        action="transcribe",
        input_path=str(in_path),
        output_path=str(out_dir),
        duration_in=result.get("duration"),
        duration_out=None,
        ffmpeg_cmd=None,
        elapsed_seconds=elapsed,
        error=None,
    )


def _execute_resolve_export(
    in_path: Path, out_dir: Path, params: dict[str, Any], t0: float,
) -> dict[str, Any]:
    """Render a timeline from DaVinci Resolve via resolve_bridge.

    Requires Resolve running. Never silently falls back to FFmpeg.
    """
    if _resolve_export is None:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            action="resolve_export",
            input_path=str(in_path),
            output_path=None,
            duration_in=None,
            duration_out=None,
            ffmpeg_cmd=None,
            elapsed_seconds=elapsed,
            error="resolve_bridge module not available",
        )

    timeline_name = params.get("timeline_name")
    if not timeline_name:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            action="resolve_export",
            input_path=str(in_path),
            output_path=None,
            duration_in=None,
            duration_out=None,
            ffmpeg_cmd=None,
            elapsed_seconds=elapsed,
            error="resolve_export requires 'timeline_name' in params",
        )

    preset = params.get("preset", "h264_mp4")
    out_path = _safe_output_path(out_dir, in_path.stem, "resolve_export", ".mp4")

    try:
        result = _resolve_export(timeline_name, str(out_path), preset=preset)
    except RuntimeError as exc:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error",
            action="resolve_export",
            input_path=str(in_path),
            output_path=str(out_path),
            duration_in=None,
            duration_out=None,
            ffmpeg_cmd=None,
            elapsed_seconds=elapsed,
            error=str(exc),
        )

    elapsed = result.get("elapsed_seconds", time.perf_counter() - t0)
    if result.get("success"):
        duration_out = _get_duration(out_path)
        return _result_dict(
            status="success",
            action="resolve_export",
            input_path=str(in_path),
            output_path=result.get("output_path", str(out_path)),
            duration_in=None,
            duration_out=duration_out,
            ffmpeg_cmd=None,
            elapsed_seconds=elapsed,
            error=None,
        )

    return _result_dict(
        status="error",
        action="resolve_export",
        input_path=str(in_path),
        output_path=str(out_path),
        duration_in=None,
        duration_out=None,
        ffmpeg_cmd=None,
        elapsed_seconds=elapsed,
        error=result.get("error", "resolve render failed"),
    )


# ---------------------------------------------------------------------------
# Shorts pipeline handlers
# ---------------------------------------------------------------------------

def _execute_assemble_short(
    in_path: Path, out_dir: Path, params: dict[str, Any], t0: float,
) -> dict[str, Any]:
    """Run shorts assembler pipeline."""
    try:
        from shorts.shorts_assembler import assemble_short
    except ImportError:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error", action="assemble_short", input_path=str(in_path),
            output_path=None, duration_in=None, duration_out=None,
            ffmpeg_cmd=None, elapsed_seconds=elapsed,
            error="shorts.shorts_assembler not available",
        )

    target_aspect = params.get("target_aspect", "9:16")
    max_duration = params.get("max_duration", 60.0)
    caption_style = params.get("caption_style", "highlight_word")

    try:
        result = assemble_short(
            str(in_path), output_dir=str(out_dir),
            target_aspect=target_aspect, max_duration=max_duration,
            caption_style=caption_style,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error", action="assemble_short", input_path=str(in_path),
            output_path=None, duration_in=None, duration_out=None,
            ffmpeg_cmd=None, elapsed_seconds=elapsed, error=str(exc),
        )

    elapsed = time.perf_counter() - t0
    output = result.get("output")
    return _result_dict(
        status="success", action="assemble_short", input_path=str(in_path),
        output_path=output, duration_in=None, duration_out=None,
        ffmpeg_cmd=None, elapsed_seconds=elapsed, error=None,
    )


def _execute_smart_crop(
    in_path: Path, out_dir: Path, params: dict[str, Any], t0: float,
) -> dict[str, Any]:
    """Run person tracking + smart crop keyframe generation."""
    try:
        from shorts.person_tracker import track_persons
        from shorts.smart_crop import generate_crop_keyframes
    except ImportError:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error", action="smart_crop", input_path=str(in_path),
            output_path=None, duration_in=None, duration_out=None,
            ffmpeg_cmd=None, elapsed_seconds=elapsed,
            error="shorts tools not available",
        )

    try:
        tracking = track_persons(str(in_path), output_dir=str(out_dir))
        crop_kf = generate_crop_keyframes(
            tracking, target_aspect=params.get("target_aspect", "9:16"),
        )
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error", action="smart_crop", input_path=str(in_path),
            output_path=None, duration_in=None, duration_out=None,
            ffmpeg_cmd=None, elapsed_seconds=elapsed, error=str(exc),
        )

    elapsed = time.perf_counter() - t0
    return _result_dict(
        status="success", action="smart_crop", input_path=str(in_path),
        output_path=None, duration_in=None, duration_out=None,
        ffmpeg_cmd=None, elapsed_seconds=elapsed, error=None,
    )


def _execute_person_track(
    in_path: Path, out_dir: Path, params: dict[str, Any], t0: float,
) -> dict[str, Any]:
    """Run person tracking only."""
    try:
        from shorts.person_tracker import track_persons
    except ImportError:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error", action="person_track", input_path=str(in_path),
            output_path=None, duration_in=None, duration_out=None,
            ffmpeg_cmd=None, elapsed_seconds=elapsed,
            error="shorts.person_tracker not available",
        )

    try:
        track_persons(str(in_path), output_dir=str(out_dir))
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error", action="person_track", input_path=str(in_path),
            output_path=None, duration_in=None, duration_out=None,
            ffmpeg_cmd=None, elapsed_seconds=elapsed, error=str(exc),
        )

    elapsed = time.perf_counter() - t0
    return _result_dict(
        status="success", action="person_track", input_path=str(in_path),
        output_path=None, duration_in=None, duration_out=None,
        ffmpeg_cmd=None, elapsed_seconds=elapsed, error=None,
    )


def _execute_animated_captions(
    in_path: Path, out_dir: Path, params: dict[str, Any], t0: float,
) -> dict[str, Any]:
    """Generate animated captions from transcript."""
    try:
        from shorts.animated_captions import generate_animated_captions
    except ImportError:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error", action="animated_captions", input_path=str(in_path),
            output_path=None, duration_in=None, duration_out=None,
            ffmpeg_cmd=None, elapsed_seconds=elapsed,
            error="shorts.animated_captions not available",
        )

    # Look for transcript JSON
    transcript_path = out_dir / f"{in_path.stem}_transcript.json"
    if not transcript_path.exists():
        transcript_path = Path("output") / "transcript.json"

    if not transcript_path.exists():
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error", action="animated_captions", input_path=str(in_path),
            output_path=None, duration_in=None, duration_out=None,
            ffmpeg_cmd=None, elapsed_seconds=elapsed,
            error="no transcript found — run transcribe first",
        )

    style = params.get("caption_style", "highlight_word")
    ass_path = str(out_dir / f"{in_path.stem}_captions.ass")

    try:
        result = generate_animated_captions(
            str(transcript_path), output_path=ass_path, style=style,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error", action="animated_captions", input_path=str(in_path),
            output_path=None, duration_in=None, duration_out=None,
            ffmpeg_cmd=None, elapsed_seconds=elapsed, error=str(exc),
        )

    elapsed = time.perf_counter() - t0
    return _result_dict(
        status="success", action="animated_captions", input_path=str(in_path),
        output_path=ass_path, duration_in=None, duration_out=None,
        ffmpeg_cmd=None, elapsed_seconds=elapsed, error=None,
    )


def _execute_batch_shorts(
    in_path: Path, out_dir: Path, params: dict[str, Any], t0: float,
) -> dict[str, Any]:
    """Run batch shorts assembly on a directory."""
    try:
        from shorts.shorts_assembler import batch_assemble_shorts
    except ImportError:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error", action="batch_shorts", input_path=str(in_path),
            output_path=None, duration_in=None, duration_out=None,
            ffmpeg_cmd=None, elapsed_seconds=elapsed,
            error="shorts.shorts_assembler not available",
        )

    input_dir = str(in_path.parent) if in_path.is_file() else str(in_path)

    try:
        result = batch_assemble_shorts(
            input_dir, output_dir=str(out_dir),
            target_aspect=params.get("target_aspect", "9:16"),
            max_duration=params.get("max_duration", 60.0),
        )
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return _result_dict(
            status="error", action="batch_shorts", input_path=input_dir,
            output_path=None, duration_in=None, duration_out=None,
            ffmpeg_cmd=None, elapsed_seconds=elapsed, error=str(exc),
        )

    elapsed = time.perf_counter() - t0
    return _result_dict(
        status="success", action="batch_shorts", input_path=input_dir,
        output_path=str(out_dir), duration_in=None, duration_out=None,
        ffmpeg_cmd=None, elapsed_seconds=elapsed, error=None,
    )
