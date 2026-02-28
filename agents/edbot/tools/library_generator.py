"""Generate a video library JSON file for the chapter navigation viewer.

Scans a directory of video files, probes each for metadata via ffprobe,
optionally loads existing transcript data (chunks.json files), and outputs
a library JSON file compatible with yd-chapter-nav.html.

Output schema (array of entries):
    [
        {
            "filename": "video.mp4",
            "path": "D:/Videos/video.mp4",
            "duration": 120.5,
            "resolution": "1920x1080",
            "codec": "h264",
            "whisper_segments": [
                {"start": 0.0, "end": 3.5, "text": "Hello world"},
                ...
            ]
        },
        ...
    ]

Usage:
    py -3.12 -m agents.edbot.tools.library_generator \\
        --input "D:/Videos/UnrealInterviewMix" \\
        --output "output/yd-library.json"
"""

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def scan_video_files(directory: str | Path) -> list[Path]:
    """Recursively scan *directory* for video files, sorted by name.

    Returns a list of Path objects for files whose extension (lowercased)
    matches VIDEO_EXTENSIONS.
    """
    root = Path(directory)
    if not root.is_dir():
        return []
    videos: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            videos.append(p)
    return videos


def probe_video(path: str | Path) -> dict[str, Any]:
    """Run ffprobe on a video file and return metadata dict.

    Returns a dict with keys: duration, resolution, codec, width, height.
    Returns partial results on probe failure (missing fields set to None).
    """
    fpath = str(path)
    result: dict[str, Any] = {
        "duration": None,
        "resolution": None,
        "codec": None,
        "width": None,
        "height": None,
    }

    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            fpath,
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            return result

        data = json.loads(proc.stdout)

        # Duration from format.
        fmt = data.get("format", {})
        if "duration" in fmt:
            result["duration"] = round(float(fmt["duration"]), 3)

        # Video stream metadata.
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                result["codec"] = stream.get("codec_name")
                w = stream.get("width")
                h = stream.get("height")
                if w and h:
                    result["width"] = int(w)
                    result["height"] = int(h)
                    result["resolution"] = f"{w}x{h}"
                # Duration fallback from stream.
                if result["duration"] is None and "duration" in stream:
                    result["duration"] = round(float(stream["duration"]), 3)
                break

    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError,
            ValueError, OSError):
        pass

    return result


def load_transcript_segments(video_path: Path) -> list[dict]:
    """Attempt to load transcript segments for a video from nearby chunks file.

    Looks for ``<stem>_chunks.json`` or ``chunks.json`` in the same directory
    as the video file. Extracts whisper-compatible segments (start, end, text)
    from the chunks data.

    Returns an empty list if no transcript file is found.
    """
    stem = video_path.stem
    parent = video_path.parent
    candidates = [
        parent / f"{stem}_chunks.json",
        parent / "chunks.json",
    ]

    for cpath in candidates:
        if cpath.exists():
            try:
                with open(cpath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Accept bare list or {"chunks": [...]} wrapper.
                chunks = data if isinstance(data, list) else data.get("chunks", [])
                segments: list[dict] = []
                for chunk in chunks:
                    segments.append({
                        "start": float(chunk.get("start", 0)),
                        "end": float(chunk.get("end", 0)),
                        "text": chunk.get("text", ""),
                    })
                return segments
            except (json.JSONDecodeError, OSError, TypeError, KeyError):
                continue

    return []


def build_library_entry(video_path: Path) -> dict[str, Any]:
    """Build a single library entry for a video file.

    Probes the video for metadata and loads any available transcript data.
    """
    meta = probe_video(video_path)
    segments = load_transcript_segments(video_path)

    entry: dict[str, Any] = {
        "filename": video_path.name,
        "path": str(video_path),
        "duration": meta["duration"] or 0.0,
        "resolution": meta["resolution"] or "unknown",
        "codec": meta["codec"] or "unknown",
        "whisper_segments": segments,
    }
    return entry


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def generate_library(
    video_dir: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Scan *video_dir* for videos, probe each, and write library JSON.

    Args:
        video_dir: Directory to scan for video files (recursive).
        output_path: Path to write the output JSON library file.

    Returns:
        Summary dict with keys: video_count, total_duration, output_path,
        entries (the list of entry dicts).
    """
    videos = scan_video_files(video_dir)
    entries: list[dict[str, Any]] = []

    for vpath in videos:
        entry = build_library_entry(vpath)
        entries.append(entry)

    # Write output.
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

    total_duration = sum(e["duration"] for e in entries)

    return {
        "video_count": len(entries),
        "total_duration": round(total_duration, 1),
        "output_path": str(out),
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for video library generation."""
    parser = argparse.ArgumentParser(
        description="Generate a video library JSON for the chapter navigation viewer",
    )
    parser.add_argument(
        "--input", required=True,
        help="Directory containing video files to scan (recursive)",
    )
    parser.add_argument(
        "--output", required=True,
        help="Output path for the library JSON file",
    )
    args = parser.parse_args()

    result = generate_library(args.input, args.output)

    print(f"Scanned: {result['video_count']} videos")
    print(f"Total duration: {result['total_duration']:.1f}s")
    print(f"Output: {result['output_path']}")

    # Per-video summary.
    for entry in result["entries"]:
        seg_count = len(entry["whisper_segments"])
        dur = entry["duration"]
        print(f"  {entry['filename']}: {dur:.1f}s, {seg_count} segments")


if __name__ == "__main__":
    main()
