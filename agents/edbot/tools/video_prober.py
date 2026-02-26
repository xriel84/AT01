"""Probe video files for metadata using ffprobe.

Returns structured metadata: duration, resolution, codec, bitrate, fps,
audio channels, file size, etc. Works on local files and network paths.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpg", ".mpeg", ".ts", ".mts"}


def probe_video(video_path: str) -> dict[str, Any]:
    """Extract metadata from a video file via ffprobe.

    Returns dict with keys: path, filename, duration_sec, width, height,
    fps, video_codec, audio_codec, bitrate_kbps, audio_channels,
    file_size_mb, format_name.
    """
    p = Path(video_path)
    if not p.exists():
        return {"error": f"file not found: {video_path}", "code": "FILE_NOT_FOUND"}
    if p.suffix.lower() not in VIDEO_EXTENSIONS:
        return {"error": f"not a video file: {p.suffix}", "code": "INVALID_INPUT"}

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(p),
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"error": f"ffprobe failed: {result.stderr.strip()}", "code": "PROBE_ERROR"}

        data = json.loads(result.stdout)
    except FileNotFoundError:
        return {"error": "ffprobe not found — install FFmpeg", "code": "FFPROBE_MISSING"}
    except subprocess.TimeoutExpired:
        return {"error": "ffprobe timed out", "code": "TIMEOUT"}
    except json.JSONDecodeError:
        return {"error": "ffprobe returned invalid JSON", "code": "PROBE_ERROR"}

    fmt = data.get("format", {})
    streams = data.get("streams", [])

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    # Parse FPS from r_frame_rate (e.g. "24000/1001")
    fps = None
    r_frame_rate = video_stream.get("r_frame_rate", "")
    if "/" in r_frame_rate:
        parts = r_frame_rate.split("/")
        try:
            fps = round(int(parts[0]) / int(parts[1]), 3)
        except (ValueError, ZeroDivisionError):
            pass
    elif r_frame_rate:
        try:
            fps = round(float(r_frame_rate), 3)
        except ValueError:
            pass

    duration = None
    dur_str = fmt.get("duration") or video_stream.get("duration")
    if dur_str:
        try:
            duration = round(float(dur_str), 2)
        except ValueError:
            pass

    bitrate = None
    br_str = fmt.get("bit_rate")
    if br_str:
        try:
            bitrate = round(int(br_str) / 1000)
        except ValueError:
            pass

    file_size_mb = round(p.stat().st_size / (1024 * 1024), 2)

    return {
        "path": str(p.resolve()),
        "filename": p.name,
        "duration_sec": duration,
        "width": _int_or_none(video_stream.get("width")),
        "height": _int_or_none(video_stream.get("height")),
        "fps": fps,
        "video_codec": video_stream.get("codec_name"),
        "audio_codec": audio_stream.get("codec_name"),
        "bitrate_kbps": bitrate,
        "audio_channels": _int_or_none(audio_stream.get("channels")),
        "file_size_mb": file_size_mb,
        "format_name": fmt.get("format_name"),
    }


def scan_local_dir(directory: str, recursive: bool = True) -> dict[str, Any]:
    """Scan a local directory for video files and probe each one.

    Returns dict with keys: directory, videos (list of probe results),
    total_count, total_size_mb, total_duration_sec.
    """
    d = Path(directory)
    if not d.exists():
        return {"error": f"directory not found: {directory}", "code": "DIR_NOT_FOUND"}
    if not d.is_dir():
        return {"error": f"not a directory: {directory}", "code": "INVALID_INPUT"}

    pattern = "**/*" if recursive else "*"
    video_files = sorted(
        f for f in d.glob(pattern)
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    )

    videos = []
    for vf in video_files:
        probe = probe_video(str(vf))
        if not probe.get("error"):
            videos.append(probe)

    total_size = sum(v.get("file_size_mb", 0) for v in videos)
    total_dur = sum(v.get("duration_sec", 0) or 0 for v in videos)

    return {
        "directory": str(d.resolve()),
        "videos": videos,
        "total_count": len(videos),
        "total_size_mb": round(total_size, 2),
        "total_duration_sec": round(total_dur, 2),
    }


def _int_or_none(val):
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
