"""NLP action parser — keyword regex engine.

Converts natural-language text commands into structured action JSON
for the EdBot pipeline.  Pure regex, no external dependencies.
"""

import argparse
import json
import re
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SILENCE_THRESHOLD_DB: int = -30
CAPTION_STYLE: str = "default"

RESOLVE_ACTIONS: set[str] = {"color_grade", "fusion_comp"}

PLATFORM_ASPECT: dict[str, str] = {
    "tiktok":          "9:16",
    "youtube_shorts":  "9:16",
    "ig_reels":        "9:16",
    "youtube_long":    "16:9",
    "x_video":         "16:9",
    "linkedin":        "1:1",
}

PLATFORM_MAX_DURATION: dict[str, int] = {
    "tiktok":         60,
    "youtube_shorts": 60,
    "ig_reels":       90,
}

# ---------------------------------------------------------------------------
# Platform name normalization
# ---------------------------------------------------------------------------

_PLATFORM_ALIASES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"tik\s*tok"),             "tiktok"),
    (re.compile(r"instagram|(?<!\w)ig(?!\w)"), "ig_reels"),
    (re.compile(r"linkedin"),              "linkedin"),
    (re.compile(r"youtube|(?<!\w)yt(?!\w)"), "_youtube"),  # resolved below
    (re.compile(r"(?<!\w)x(?!\w)|twitter"), "x_video"),
]


def _normalize_platform(text: str) -> str | None:
    """Return a canonical platform name from *text*, or None."""
    for pat, name in _PLATFORM_ALIASES:
        if pat.search(text):
            if name == "_youtube":
                # "youtube shorts" → youtube_shorts, else youtube_long
                if re.search(r"short", text):
                    return "youtube_shorts"
                return "youtube_long"
            return name
    return None


# ---------------------------------------------------------------------------
# Action patterns — ordered by specificity (first match wins)
# ---------------------------------------------------------------------------

_ACTION_PATTERNS: list[tuple[re.Pattern[str], str, dict[str, Any]]] = [
    # silence removal
    (re.compile(r"(remove|cut|delete)\s*(the\s+)?silence"),
     "silence_remove", {}),

    # platform shortcuts — tiktok / shorts / reels
    (re.compile(r"make\s+.*?(tiktok|tik\s*tok)"),
     "platform_export",
     {"platform": "tiktok", "aspect": "9:16", "max_duration": 60}),

    (re.compile(r"make\s+.*?(short|shorts)"),
     "platform_export",
     {"platform": "youtube_shorts", "aspect": "9:16", "max_duration": 60}),

    (re.compile(r"make\s+.*?(reel|reels)"),
     "platform_export",
     {"platform": "ig_reels", "aspect": "9:16", "max_duration": 90}),

    # trim
    (re.compile(r"trim\s+to\s+(\d+)\s*s"),
     "trim", {}),

    # captions / subtitles
    (re.compile(r"(add|burn)\s*(in\s+)?(caption|subtitle)"),
     "caption_burn", {}),

    # crop
    (re.compile(r"crop\s+(vertical|portrait)"),
     "crop", {"aspect": "9:16"}),

    (re.compile(r"crop\s+square"),
     "crop", {"aspect": "1:1"}),

    # export for <platform>
    (re.compile(r"export\s+for\s+(\w+)"),
     "platform_export", {}),

    # transcribe
    (re.compile(r"transcribe"),
     "transcribe", {}),
]

# Duration extraction patterns (applied after action match)
_DURATION_SECONDS = re.compile(r"(\d+)\s*s(?:ec)?(?:ond)?")
_DURATION_MINUTES = re.compile(r"(\d+)\s*min")


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

def parse_command(
    text: str,
    input_path: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Parse a natural-language command into a structured action dict.

    Parameters
    ----------
    text : str
        Free-form command, e.g. "make a 60 second tiktok".
    input_path : str | None
        Optional path to the input media file.
    output_dir : str | None
        Optional output directory.

    Returns
    -------
    dict
        Action JSON with keys: action, params, executor, confidence.
    """
    text_lower = text.strip().lower()

    action: str = "unknown"
    extras: dict[str, Any] = {}
    confidence: float = 0.3

    # --- pattern matching (first match wins) ---
    for pattern, act, defaults in _ACTION_PATTERNS:
        m = pattern.search(text_lower)
        if m:
            action = act
            extras = dict(defaults)
            confidence = 0.95

            # trim: capture duration from the pattern itself
            if act == "trim" and m.lastindex and m.lastindex >= 1:
                extras["max_duration"] = int(m.group(1))

            # "export for <platform>": resolve platform from captured word
            if act == "platform_export" and not extras.get("platform"):
                platform = _normalize_platform(text_lower)
                if platform:
                    extras["platform"] = platform
                    extras.setdefault("aspect", PLATFORM_ASPECT.get(platform))
                    extras.setdefault(
                        "max_duration",
                        PLATFORM_MAX_DURATION.get(platform),
                    )
                else:
                    # captured word from "export for (\w+)"
                    if m.lastindex and m.lastindex >= 1:
                        raw = m.group(1)
                        platform = _normalize_platform(raw)
                        if platform:
                            extras["platform"] = platform
                            extras.setdefault(
                                "aspect", PLATFORM_ASPECT.get(platform)
                            )
                            extras.setdefault(
                                "max_duration",
                                PLATFORM_MAX_DURATION.get(platform),
                            )
                        else:
                            extras["platform"] = raw
                            confidence = 0.6
            break
    else:
        # No pattern matched — check for partial signals
        platform = _normalize_platform(text_lower)
        if platform:
            action = "platform_export"
            extras["platform"] = platform
            extras["aspect"] = PLATFORM_ASPECT.get(platform)
            extras["max_duration"] = PLATFORM_MAX_DURATION.get(platform)
            confidence = 0.6

    # --- duration override (post-match) ---
    dur_m = _DURATION_MINUTES.search(text_lower)
    if dur_m:
        extras["max_duration"] = int(dur_m.group(1)) * 60
    else:
        dur_s = _DURATION_SECONDS.search(text_lower)
        if dur_s:
            extras["max_duration"] = int(dur_s.group(1))

    # --- executor ---
    executor = "resolve" if action in RESOLVE_ACTIONS else "ffmpeg"

    # --- build result ---
    result: dict[str, Any] = {
        "action": action,
        "params": {
            "input": input_path,
            "output": output_dir,
            "platform": extras.get("platform"),
            "max_duration": extras.get("max_duration"),
            "aspect": extras.get("aspect"),
            "silence_threshold_db": SILENCE_THRESHOLD_DB,
            "caption_style": CAPTION_STYLE,
        },
        "executor": executor,
        "confidence": confidence,
    }
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI wrapper: parse text from argv, print action JSON."""
    parser = argparse.ArgumentParser(
        description="Parse NLP command to action JSON",
    )
    parser.add_argument("text", nargs="+", help="Natural language command")
    parser.add_argument("--input", default=None)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    text = " ".join(args.text)
    result = parse_command(text, args.input, args.output_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
