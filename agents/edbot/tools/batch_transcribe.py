"""Batch transcribe multiple video files in a directory.

Uses existing transcribe_video() — does NOT rewrite transcription logic.
"""

import json
import sys
from pathlib import Path
from typing import Any

_tools_dir = str(Path(__file__).resolve().parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from transcribe import transcribe_video


def batch_transcribe(
    input_dir: str,
    output_dir: str = "temp",
    extensions: tuple = (".mov", ".mp4", ".mkv", ".avi"),
) -> dict[str, Any]:
    """Batch transcribe all video files in a directory.

    Scans input_dir for video files matching extensions (case-insensitive),
    calls transcribe_video for each, and collects results into a manifest.
    Flat scan only — no recursion into subdirectories.

    Parameters
    ----------
    input_dir : str
        Directory containing video files.
    output_dir : str
        Output directory for transcription results and manifest.
    extensions : tuple
        Tuple of file extensions to match (case-insensitive).

    Returns
    -------
    dict
        Batch manifest with file_count, total_duration, files list, errors list.
    """
    in_dir = Path(input_dir)
    if not in_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ext_set = {e.lower() for e in extensions}

    # Flat scan only — no recursion
    videos = sorted([
        f for f in in_dir.iterdir()
        if f.is_file() and f.suffix.lower() in ext_set
    ])

    files: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    total_duration = 0.0

    for video in videos:
        try:
            result = transcribe_video(str(video), output_dir)

            duration = result.get("duration", 0.0)
            chunks = result.get("chunks", [])

            # Save per-file chunks under {stem}_chunks.json
            chunks_path = out_dir / f"{video.stem}_chunks.json"
            with open(chunks_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)

            files.append({
                "filename": video.name,
                "path": str(video),
                "duration": duration,
                "chunk_count": len(chunks),
                "status": "ok",
            })
            total_duration += duration

        except Exception as exc:
            errors.append({
                "filename": video.name,
                "path": str(video),
                "error": str(exc),
            })

    manifest: dict[str, Any] = {
        "input_dir": str(in_dir),
        "file_count": len(files),
        "total_duration": round(total_duration, 1),
        "files": files,
        "errors": errors,
    }

    manifest_path = out_dir / "batch_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest
