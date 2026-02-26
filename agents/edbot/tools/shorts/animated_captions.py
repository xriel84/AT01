"""EdBot animated captions -- word-level timestamps -> animated ASS subtitles.

Generates word-by-word highlight captions (CapCut/Submagic style).
Current word highlighted (bold/accent color), surrounding words visible.
Output: ASS file for FFmpeg burn-in via -vf "ass=captions.ass"
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ASS colors in BGR format: &HBBGGRR&
_COLOR_WHITE = "&HFFFFFF&"
_COLOR_YELLOW = "&H00FFFF&"   # yellow in BGR
_COLOR_BLACK = "&H000000&"

# Style presets
CAPTION_STYLES: dict[str, dict[str, Any]] = {
    "default": {
        "fontsize": 48,
        "primary_color": _COLOR_WHITE,
        "highlight_color": _COLOR_YELLOW,
        "outline_color": _COLOR_BLACK,
        "outline_width": 2,
        "bold_highlight": True,
        "scale_highlight": 110,
    },
    "bold_center": {
        "fontsize": 56,
        "primary_color": _COLOR_WHITE,
        "highlight_color": _COLOR_WHITE,
        "outline_color": _COLOR_BLACK,
        "outline_width": 3,
        "bold_highlight": True,
        "scale_highlight": 120,
    },
    "highlight_word": {
        "fontsize": 52,
        "primary_color": _COLOR_WHITE,
        "highlight_color": _COLOR_YELLOW,
        "outline_color": _COLOR_BLACK,
        "outline_width": 2,
        "bold_highlight": True,
        "scale_highlight": 110,
    },
    "karaoke": {
        "fontsize": 52,
        "primary_color": _COLOR_WHITE,
        "highlight_color": _COLOR_YELLOW,
        "outline_color": _COLOR_BLACK,
        "outline_width": 2,
        "bold_highlight": False,
        "scale_highlight": 100,
    },
}


def _format_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format: H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _load_transcript(transcript: dict | str) -> dict:
    """Load transcript from dict or JSON path."""
    if isinstance(transcript, str):
        p = Path(transcript)
        if not p.exists():
            raise FileNotFoundError(f"Transcript not found: {transcript}")
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return transcript


def _extract_words(transcript: dict) -> list[dict[str, Any]]:
    """Extract flat word list with timestamps from transcript.

    Handles multiple transcript formats:
    - {"words": [{"word": ..., "start": ..., "end": ...}]}
    - {"segments": [{"words": [...]}]}
    - {"chunks": [{"text": ..., "start": ..., "end": ...}]}  (segment-level fallback)
    """
    words: list[dict[str, Any]] = []

    # Direct word list
    if "words" in transcript and isinstance(transcript["words"], list):
        for w in transcript["words"]:
            if "word" in w and "start" in w and "end" in w:
                words.append({
                    "word": w["word"].strip(),
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                })
        return words

    # Segments with word-level timestamps
    if "segments" in transcript:
        for seg in transcript["segments"]:
            if "words" in seg:
                for w in seg["words"]:
                    if "word" in w and "start" in w and "end" in w:
                        words.append({
                            "word": w["word"].strip(),
                            "start": float(w["start"]),
                            "end": float(w["end"]),
                        })
        if words:
            return words

    # Chunk-level fallback (no individual word timestamps)
    if "chunks" in transcript:
        for chunk in transcript["chunks"]:
            text = chunk.get("text", "").strip()
            if text and "start" in chunk and "end" in chunk:
                words.append({
                    "word": text,
                    "start": float(chunk["start"]),
                    "end": float(chunk["end"]),
                    "_is_segment": True,
                })
        return words

    return words


def generate_animated_captions(
    transcript: dict | str,
    output_path: str = "temp/captions.ass",
    style: str = "default",
    words_per_group: int = 4,
    position: str = "bottom_center",
    target_resolution: tuple = (1080, 1920),
) -> dict[str, Any]:
    """Generate animated ASS captions from word-level transcript.

    Parameters
    ----------
    transcript : dict | str
        Transcript dict or path to JSON with word timestamps.
    output_path : str
        Output ASS file path.
    style : str
        Caption style preset name.
    words_per_group : int
        Number of words shown simultaneously.
    position : str
        Caption position: "bottom_center", "center", "top_center".
    target_resolution : tuple
        Target video resolution (width, height).

    Returns
    -------
    dict
        Caption manifest with word count, group count, duration, and file path.
    """
    data = _load_transcript(transcript)
    words = _extract_words(data)

    style_config = CAPTION_STYLES.get(style, CAPTION_STYLES["default"])
    res_w, res_h = target_resolution

    # Position mapping
    pos_y_map = {
        "bottom_center": int(res_h * 0.88),
        "center": res_h // 2,
        "top_center": int(res_h * 0.12),
    }
    pos_x = res_w // 2
    pos_y = pos_y_map.get(position, pos_y_map["bottom_center"])

    # Write ASS file
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []

    # ASS header
    lines.append("[Script Info]")
    lines.append("Title: EdBot Animated Captions")
    lines.append("ScriptType: v4.00+")
    lines.append(f"PlayResX: {res_w}")
    lines.append(f"PlayResY: {res_h}")
    lines.append("WrapStyle: 0")
    lines.append("")

    # Styles
    fontsize = style_config["fontsize"]
    primary = style_config["primary_color"]
    outline = style_config["outline_color"]
    outline_w = style_config["outline_width"]

    lines.append("[V4+ Styles]")
    lines.append("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
    lines.append(
        f"Style: Default,Arial,{fontsize},{primary},&H000000FF&,{outline},&H80000000&,"
        f"0,0,0,0,100,100,0,0,1,{outline_w},1,2,10,10,10,1"
    )
    lines.append("")

    # Events
    lines.append("[Events]")
    lines.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")

    highlight_color = style_config["highlight_color"]
    bold_hl = style_config["bold_highlight"]
    scale_hl = style_config["scale_highlight"]

    if not words:
        # Empty transcript
        pass
    elif words and words[0].get("_is_segment"):
        # Segment-level fallback (no word timestamps)
        for w in words:
            start_ts = _format_time(w["start"])
            end_ts = _format_time(w["end"])
            text = w["word"]
            line = f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{{\\pos({pos_x},{pos_y})}}{text}"
            lines.append(line)
    else:
        # Word-level animated captions
        groups = _group_words(words, words_per_group)
        for group in groups:
            for word_idx, word in enumerate(group):
                start_ts = _format_time(word["start"])
                end_ts = _format_time(word["end"])

                # Build text with current word highlighted
                parts: list[str] = []
                for gi, gw in enumerate(group):
                    if gi == word_idx:
                        # Highlighted word
                        hl_tags = f"{{\\c{highlight_color}"
                        if bold_hl:
                            hl_tags += "\\b1"
                        if scale_hl != 100:
                            hl_tags += f"\\fscx{scale_hl}\\fscy{scale_hl}"
                        hl_tags += "}"
                        reset_tags = f"{{\\c{primary}\\b0\\fscx100\\fscy100}}"
                        parts.append(f"{hl_tags}{gw['word']}{reset_tags}")
                    else:
                        parts.append(gw["word"])

                text = " ".join(parts)
                line = f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{{\\pos({pos_x},{pos_y})}}{text}"
                lines.append(line)

    # Write file
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # Build manifest
    total_words = len([w for w in words if not w.get("_is_segment")])
    if not total_words:
        total_words = len(words)

    duration = 0.0
    if words:
        duration = words[-1]["end"] - words[0]["start"]

    manifest: dict[str, Any] = {
        "output_path": str(out_path),
        "style": style,
        "word_count": total_words,
        "group_count": len(_group_words(words, words_per_group)) if words else 0,
        "duration": round(duration, 2),
        "target_resolution": list(target_resolution),
        "position": position,
    }

    return manifest


def _group_words(
    words: list[dict], words_per_group: int
) -> list[list[dict]]:
    """Split words into display groups."""
    groups: list[list[dict]] = []
    for i in range(0, len(words), words_per_group):
        group = words[i:i + words_per_group]
        if group:
            groups.append(group)
    return groups
