"""Stage 5 — Silence removal via auto-editor.

Batch wrapper that runs auto-editor on each clip in an input directory,
filters by platform minimum duration, and produces a summary.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


MIN_CLIP_DURATION = {
    "tiktok": 6,
    "reels": 6,
    "shorts": 6,
    "youtube": 15,
    "linkedin": 10,
}

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


def get_duration(path: Path) -> float:
    """Get video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return 0.0


def build_auto_editor_cmd(input_path: Path, output_path: Path) -> list[str]:
    """Build the auto-editor command list."""
    return [
        "auto-editor", str(input_path),
        "--margin", "0.15s",
        "--no-open",
        "--output", str(output_path),
    ]


def process_clip(input_path: Path, output_path: Path) -> dict:
    """Run auto-editor on a single clip.

    Returns a dict with keys: filename, original_duration, cleaned_duration,
    pct_removed, status ('processed' | 'failed').
    """
    filename = input_path.name
    original_duration = get_duration(input_path)

    cmd = build_auto_editor_cmd(input_path, output_path)
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        # Fallback: copy original to output dir
        print(f"  FAIL  {filename}: {exc}", file=sys.stderr)
        shutil.copy2(input_path, output_path)
        return {
            "filename": filename,
            "original_duration": original_duration,
            "cleaned_duration": original_duration,
            "pct_removed": 0.0,
            "status": "failed",
        }

    cleaned_duration = get_duration(output_path)
    saved = original_duration - cleaned_duration
    pct = (saved / original_duration * 100) if original_duration > 0 else 0.0

    return {
        "filename": filename,
        "original_duration": original_duration,
        "cleaned_duration": cleaned_duration,
        "pct_removed": round(pct, 1),
        "status": "processed",
    }


def remove_silence(
    input_dir: Path,
    output_dir: Path,
    platform: str = "tiktok",
) -> dict:
    """Process all clips in input_dir, write cleaned clips to output_dir.

    Returns summary dict: {processed, skipped, failed, total_saved_seconds, clips}.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    min_dur = MIN_CLIP_DURATION.get(platform, 6)

    clips = sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )

    summary = {
        "processed": 0,
        "skipped": 0,
        "failed": 0,
        "total_saved_seconds": 0.0,
        "clips": [],
    }

    for clip in clips:
        out_path = output_dir / clip.name
        print(f"  Processing: {clip.name}")

        result = process_clip(clip, out_path)

        if result["status"] == "failed":
            summary["failed"] += 1
            summary["clips"].append(result)
            print(f"    -> FAILED (original copied)")
            continue

        # Check minimum duration
        if result["cleaned_duration"] < min_dur:
            # Remove the too-short output
            if out_path.exists():
                out_path.unlink()
            result["status"] = "skipped"
            summary["skipped"] += 1
            summary["clips"].append(result)
            print(f"    -> SKIPPED ({result['cleaned_duration']:.1f}s < {min_dur}s min for {platform})")
            continue

        saved = result["original_duration"] - result["cleaned_duration"]
        summary["total_saved_seconds"] += saved
        summary["processed"] += 1
        summary["clips"].append(result)
        print(
            f"    -> OK  {result['original_duration']:.1f}s -> {result['cleaned_duration']:.1f}s "
            f"({result['pct_removed']}% removed)"
        )

    summary["total_saved_seconds"] = round(summary["total_saved_seconds"], 2)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Batch silence removal via auto-editor")
    parser.add_argument("--input-dir", required=True, help="Directory of .mp4 clips")
    parser.add_argument("--output-dir", required=True, help="Directory for cleaned clips")
    parser.add_argument(
        "--platform", default="tiktok",
        choices=list(MIN_CLIP_DURATION.keys()),
        help="Target platform (sets minimum clip duration)",
    )
    parser.add_argument("--json", action="store_true", help="Print summary as JSON")
    args = parser.parse_args()

    print(f"Silence removal — platform={args.platform}, min_duration={MIN_CLIP_DURATION[args.platform]}s")
    summary = remove_silence(Path(args.input_dir), Path(args.output_dir), args.platform)

    print(f"\nSummary: {summary['processed']} processed, {summary['skipped']} skipped, "
          f"{summary['failed']} failed, {summary['total_saved_seconds']}s saved")

    if args.json:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
