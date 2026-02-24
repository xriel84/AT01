"""Stage 8 — Subtitle burn-in via FFmpeg h264_nvenc.

Burns .ass subtitles onto rendered clips using GPU-accelerated encoding,
then validates output with ffprobe.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


PLATFORM_RESOLUTION = {
    "tiktok":   {"w": 1080, "h": 1920},
    "reels":    {"w": 1080, "h": 1920},
    "shorts":   {"w": 1080, "h": 1920},
    "youtube":  {"w": 1920, "h": 1080},
    "linkedin": {"w": 1080, "h": 1080},
}


def ass_path_for_ffmpeg(path: Path) -> str:
    """Convert path to forward-slash string for FFmpeg -vf ass= filter on Windows."""
    return str(path).replace("\\", "/")


def build_ffmpeg_cmd(
    input_path: Path,
    ass_path: Path,
    output_path: Path,
) -> list[str]:
    """Build the FFmpeg burn-in command."""
    ass_escaped = ass_path_for_ffmpeg(ass_path)
    return [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", f"ass={ass_escaped}",
        "-c:v", "h264_nvenc",
        "-preset", "p4",
        "-rc", "vbr",
        "-cq", "18",
        "-r", "30",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-movflags", "+faststart",
        str(output_path),
    ]


def probe_output(path: Path) -> dict | None:
    """Validate output file with ffprobe. Returns metadata dict or None on failure."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]
        fmt = data.get("format", {})

        # Parse frame rate fraction (e.g. "30/1")
        fps_str = stream.get("r_frame_rate", "0/1")
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) > 0 else 0.0

        return {
            "width": stream.get("width"),
            "height": stream.get("height"),
            "codec": stream.get("codec_name"),
            "fps": round(fps, 2),
            "duration": float(fmt.get("duration", 0)),
        }
    except Exception as exc:
        print(f"  ffprobe failed: {exc}", file=sys.stderr)
        return None


def burn_subtitle(
    input_path: Path,
    ass_path: Path,
    output_path: Path,
) -> dict:
    """Burn a single .ass subtitle onto a clip.

    Returns dict with keys: filename, status, probe (ffprobe results or None).
    """
    cmd = build_ffmpeg_cmd(input_path, ass_path, output_path)

    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {
            "filename": input_path.name,
            "status": "failed",
            "error": str(exc),
            "probe": None,
        }

    probe = probe_output(output_path)
    return {
        "filename": input_path.name,
        "status": "ok",
        "probe": probe,
    }


def burn_batch(
    clip_dir: Path,
    ass_dir: Path,
    output_dir: Path,
    platforms: list[str] | None = None,
) -> dict:
    """Burn subtitles for all clips across all platforms.

    Expects .ass files named {clip_stem}_{platform}.ass in ass_dir.

    Returns summary dict: {processed, failed, results}.
    """
    clip_dir = Path(clip_dir)
    ass_dir = Path(ass_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if platforms is None:
        platforms = list(PLATFORM_RESOLUTION.keys())

    clips = sorted(
        p for p in clip_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".mp4"
    )

    summary = {"processed": 0, "failed": 0, "results": []}

    for clip in clips:
        stem = clip.stem
        for platform in platforms:
            ass_file = ass_dir / f"{stem}_{platform}.ass"
            if not ass_file.exists():
                continue

            out_name = f"{stem}_{platform}_subtitled.mp4"
            out_path = output_dir / out_name

            print(f"  Burning: {clip.name} + {ass_file.name} -> {out_name}")
            result = burn_subtitle(clip, ass_file, out_path)
            result["platform"] = platform

            if result["status"] == "ok":
                summary["processed"] += 1
                probe = result["probe"]
                if probe:
                    print(f"    -> OK  {probe['width']}x{probe['height']} "
                          f"{probe['codec']} {probe['fps']}fps {probe['duration']:.1f}s")
            else:
                summary["failed"] += 1
                print(f"    -> FAILED: {result.get('error', 'unknown')}")

            summary["results"].append(result)

    return summary


def build_output_path(clip_path: Path, platform: str, output_dir: Path) -> Path:
    """Construct the output path for a subtitled clip."""
    return output_dir / f"{clip_path.stem}_{platform}_subtitled.mp4"


def main():
    parser = argparse.ArgumentParser(description="Burn .ass subtitles onto clips via FFmpeg")
    parser.add_argument("--clip-dir", required=True, help="Directory of rendered .mp4 clips")
    parser.add_argument("--ass-dir", required=True, help="Directory of .ass subtitle files")
    parser.add_argument("--output-dir", required=True, help="Output directory for subtitled clips")
    parser.add_argument("--platform", nargs="+", choices=list(PLATFORM_RESOLUTION.keys()),
                        help="Target platforms (default: all)")
    parser.add_argument("--json", action="store_true", help="Print summary as JSON")
    args = parser.parse_args()

    summary = burn_batch(
        clip_dir=Path(args.clip_dir),
        ass_dir=Path(args.ass_dir),
        output_dir=Path(args.output_dir),
        platforms=args.platform,
    )

    print(f"\nSummary: {summary['processed']} burned, {summary['failed']} failed")
    if args.json:
        print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
