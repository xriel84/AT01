"""Stage 7 — Subtitle generation via faster-whisper + pysubs2.

Transcribes a clip (or uses existing transcript JSON) and generates
platform-specific .ass subtitle files with word-level timing.
"""

import argparse
import json
import sys
from pathlib import Path

import pysubs2


PLATFORM_PLAYRES = {
    "tiktok":   {"x": 1080, "y": 1920},
    "reels":    {"x": 1080, "y": 1920},
    "shorts":   {"x": 1080, "y": 1920},
    "youtube":  {"x": 1920, "y": 1080},
    "linkedin": {"x": 1080, "y": 1080},
}

# Vertical = 9:16 (tiktok, reels, shorts), Horizontal = 16:9 (youtube), Square = 1:1 (linkedin)
VERTICAL_PLATFORMS = {"tiktok", "reels", "shorts"}
MAX_CHARS_VERTICAL = 42
MAX_CHARS_HORIZONTAL = 84

# ASS color format: &HAABBGGRR
PLATFORM_STYLES = {
    "tiktok": {
        "fontname": "Arial",
        "fontsize": 48,
        "primarycolor": "&H00FFFFFF",   # white
        "outlinecolor": "&H00000000",   # black outline
        "backcolor": "&H80000000",      # semi-transparent black
        "bold": True,
        "outline": 2.0,
        "shadow": 0,
        "alignment": 2,    # bottom-center
        "marginv": 120,
        "marginl": 40,
        "marginr": 40,
    },
    "reels": {
        "fontname": "Arial",
        "fontsize": 48,
        "primarycolor": "&H00FFFFFF",
        "outlinecolor": "&H00000000",
        "backcolor": "&H80000000",
        "bold": True,
        "outline": 2.0,
        "shadow": 0,
        "alignment": 2,
        "marginv": 120,
        "marginl": 40,
        "marginr": 40,
    },
    "shorts": {
        "fontname": "Arial",
        "fontsize": 48,
        "primarycolor": "&H00FFFFFF",
        "outlinecolor": "&H00000000",
        "backcolor": "&H80000000",
        "bold": True,
        "outline": 2.0,
        "shadow": 0,
        "alignment": 2,
        "marginv": 120,
        "marginl": 40,
        "marginr": 40,
    },
    "youtube": {
        "fontname": "Arial",
        "fontsize": 36,
        "primarycolor": "&H00FFFFFF",
        "outlinecolor": "&H00000000",
        "backcolor": "&H80000000",
        "bold": True,
        "outline": 2.0,
        "shadow": 0,
        "alignment": 2,
        "marginv": 50,
        "marginl": 60,
        "marginr": 60,
    },
    "linkedin": {
        "fontname": "Arial",
        "fontsize": 40,
        "primarycolor": "&H00FFFFFF",
        "outlinecolor": "&H00000000",
        "backcolor": "&H80000000",
        "bold": True,
        "outline": 2.0,
        "shadow": 0,
        "alignment": 2,
        "marginv": 80,
        "marginl": 50,
        "marginr": 50,
    },
}


def transcribe_clip(
    clip_path: Path,
    model_size: str = "large-v3",
    device: str = "cuda",
    compute_type: str = "float16",
) -> list[dict]:
    """Transcribe a clip using faster-whisper with word timestamps.

    Args:
        clip_path: Path to audio/video file.
        model_size: Whisper model size (e.g. "large-v3", "medium", "small").
        device: "cuda" or "cpu".
        compute_type: "float16", "int8_float16", "int8", etc.

    Returns list of dicts: [{"word": str, "start": float, "end": float}, ...]
    """
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, _ = model.transcribe(
        str(clip_path),
        word_timestamps=True,
        vad_filter=True,
    )

    words = []
    for segment in segments:
        if segment.words:
            for w in segment.words:
                words.append({
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                })
    return words


def load_transcript_json(path: Path) -> list[dict]:
    """Load a transcript JSON file with word timestamps.

    Expected format: [{"word": str, "start": float, "end": float}, ...]
    """
    with open(path) as f:
        data = json.load(f)
    return data


def parse_ass_color(color_str: str) -> pysubs2.Color:
    """Parse ASS color string (&HAABBGGRR) to pysubs2.Color(r, g, b, a)."""
    s = color_str.lstrip("&H")
    a = int(s[0:2], 16)
    b = int(s[2:4], 16)
    g = int(s[4:6], 16)
    r = int(s[6:8], 16)
    return pysubs2.Color(r, g, b, a)


def re_zero_timestamps(words: list[dict], clip_start: float) -> list[dict]:
    """Shift all timestamps so clip_start becomes 0:00."""
    return [
        {
            "word": w["word"],
            "start": max(0.0, w["start"] - clip_start),
            "end": max(0.0, w["end"] - clip_start),
        }
        for w in words
    ]


def break_into_lines(words: list[dict], max_chars: int) -> list[list[dict]]:
    """Group words into lines respecting max_chars per line."""
    lines = []
    current_line = []
    current_len = 0

    for w in words:
        word_len = len(w["word"])
        # +1 for the space before the word (unless first word in line)
        needed = word_len if current_len == 0 else word_len + 1

        if current_len + needed > max_chars and current_line:
            lines.append(current_line)
            current_line = [w]
            current_len = word_len
        else:
            current_line.append(w)
            current_len += needed

    if current_line:
        lines.append(current_line)

    return lines


def seconds_to_ass_time(seconds: float) -> int:
    """Convert seconds to pysubs2 milliseconds."""
    return int(round(seconds * 1000))


def generate_ass(
    words: list[dict],
    platform: str,
    clip_start: float = 0.0,
) -> pysubs2.SSAFile:
    """Generate an ASS subtitle file for a given platform.

    Args:
        words: List of {word, start, end} dicts with absolute timestamps.
        platform: Target platform name.
        clip_start: Original clip start time in seconds (for re-zeroing).

    Returns:
        pysubs2.SSAFile ready to save.
    """
    playres = PLATFORM_PLAYRES[platform]
    style_spec = PLATFORM_STYLES[platform]
    is_vertical = platform in VERTICAL_PLATFORMS
    max_chars = MAX_CHARS_VERTICAL if is_vertical else MAX_CHARS_HORIZONTAL

    # Re-zero timestamps
    zeroed = re_zero_timestamps(words, clip_start)

    # Break into lines
    lines = break_into_lines(zeroed, max_chars)

    # Create ASS file
    subs = pysubs2.SSAFile()
    subs.info["PlayResX"] = str(playres["x"])
    subs.info["PlayResY"] = str(playres["y"])

    # Define style
    style = pysubs2.SSAStyle(
        fontname=style_spec["fontname"],
        fontsize=style_spec["fontsize"],
        primarycolor=parse_ass_color(style_spec["primarycolor"]),
        outlinecolor=parse_ass_color(style_spec["outlinecolor"]),
        backcolor=parse_ass_color(style_spec["backcolor"]),
        bold=style_spec["bold"],
        outline=style_spec["outline"],
        shadow=style_spec["shadow"],
        alignment=style_spec["alignment"],
        marginv=style_spec["marginv"],
        marginl=style_spec["marginl"],
        marginr=style_spec["marginr"],
    )
    subs.styles["Default"] = style

    # Create events from lines
    for line_words in lines:
        if not line_words:
            continue
        text = " ".join(w["word"] for w in line_words)
        start_ms = seconds_to_ass_time(line_words[0]["start"])
        end_ms = seconds_to_ass_time(line_words[-1]["end"])
        event = pysubs2.SSAEvent(
            start=start_ms,
            end=end_ms,
            text=text,
        )
        subs.events.append(event)

    return subs


def generate_all_platforms(
    clip_path: Path,
    output_dir: Path,
    transcript_path: Path | None = None,
    clip_start: float = 0.0,
    platforms: list[str] | None = None,
    model_size: str = "large-v3",
) -> dict[str, Path]:
    """Generate .ass files for all (or specified) platforms.

    Returns dict mapping platform name to output .ass path.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if platforms is None:
        platforms = list(PLATFORM_PLAYRES.keys())

    # Get word timestamps
    if transcript_path and Path(transcript_path).exists():
        words = load_transcript_json(Path(transcript_path))
    else:
        words = transcribe_clip(clip_path, model_size=model_size)

    stem = Path(clip_path).stem
    results = {}

    for platform in platforms:
        subs = generate_ass(words, platform, clip_start=clip_start)
        out_path = output_dir / f"{stem}_{platform}.ass"
        subs.save(str(out_path))
        results[platform] = out_path
        print(f"  {platform}: {out_path.name} ({len(subs.events)} events)")

    return results


def run_demo():
    """Generate sample .ass files from a mock transcript for all platforms."""
    import tempfile

    mock_words = [
        {"word": "Welcome", "start": 0.0, "end": 0.4},
        {"word": "to", "start": 0.4, "end": 0.5},
        {"word": "the", "start": 0.5, "end": 0.6},
        {"word": "Agile", "start": 0.6, "end": 0.9},
        {"word": "Lens", "start": 0.9, "end": 1.2},
        {"word": "content", "start": 1.3, "end": 1.7},
        {"word": "pipeline", "start": 1.7, "end": 2.1},
        {"word": "demo.", "start": 2.1, "end": 2.5},
        {"word": "Today", "start": 2.8, "end": 3.1},
        {"word": "we", "start": 3.1, "end": 3.2},
        {"word": "are", "start": 3.2, "end": 3.3},
        {"word": "building", "start": 3.3, "end": 3.7},
        {"word": "automated", "start": 3.7, "end": 4.2},
        {"word": "subtitles", "start": 4.2, "end": 4.7},
        {"word": "for", "start": 4.7, "end": 4.8},
        {"word": "every", "start": 4.8, "end": 5.1},
        {"word": "platform.", "start": 5.1, "end": 5.6},
    ]

    output_dir = Path("tests/demos/subtitle_samples")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Generating demo .ass files for all platforms...\n")
    for platform in PLATFORM_PLAYRES:
        subs = generate_ass(mock_words, platform, clip_start=0.0)
        out_path = output_dir / f"demo_{platform}.ass"
        subs.save(str(out_path))
        print(f"  {platform}: {out_path}")

    print(f"\nDemo files written to: {output_dir.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="Generate platform-specific .ass subtitles")
    parser.add_argument("--clip", help="Path to clip .mp4 file")
    parser.add_argument("--transcript", help="Path to transcript JSON (optional)")
    parser.add_argument("--output-dir", help="Output directory for .ass files")
    parser.add_argument("--clip-start", type=float, default=0.0,
                        help="Original clip start time for timestamp re-zeroing")
    parser.add_argument("--platform", nargs="+", choices=list(PLATFORM_PLAYRES.keys()),
                        help="Target platforms (default: all)")
    parser.add_argument("--model-size", default="large-v3",
                        help="Whisper model size (default: large-v3)")
    parser.add_argument("--demo", action="store_true",
                        help="Generate demo .ass files from mock transcript")
    args = parser.parse_args()

    if args.demo:
        run_demo()
        return

    if not args.clip:
        parser.error("--clip is required (unless using --demo)")

    output_dir = Path(args.output_dir) if args.output_dir else Path(args.clip).parent
    transcript = Path(args.transcript) if args.transcript else None

    results = generate_all_platforms(
        clip_path=Path(args.clip),
        output_dir=output_dir,
        transcript_path=transcript,
        clip_start=args.clip_start,
        platforms=args.platform,
        model_size=args.model_size,
    )
    print(f"\nGenerated {len(results)} .ass files.")


if __name__ == "__main__":
    main()
