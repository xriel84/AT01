"""NLP command translator for Resolve edit decisions.

Converts natural language editing commands into structured edit-decision JSON
using either deterministic templates (fast, free) or Ollama inference (flexible).

Template fast-path handles common patterns without Ollama:
    "mark chapters as blue markers"  → chapters_to_markers template
    "color clips by speaker"         → speakers_to_clip_colors template
    "create subclips from chapters"  → chapters_to_subclips template

All other commands are sent to Ollama for free-form translation.
"""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Ensure imports work from tools dir and project root
_tools_dir = str(Path(__file__).resolve().parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

_shared_dir = str(Path(__file__).resolve().parent.parent.parent / "shared")
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)

from resolve_decisions import VALID_COLORS, validate_decisions

# ---------------------------------------------------------------------------
# System prompt for Ollama
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a Resolve editing assistant. Your job is to translate natural language editing commands into structured JSON that controls DaVinci Resolve.

OUTPUT FORMAT: You must output ONLY a valid JSON object matching this schema. No markdown, no explanation, no code fences — just the raw JSON.

SCHEMA:
{
  "generated_by": "ollama_nlp",
  "generated_at": "<ISO-8601 timestamp>",
  "fps": <float from context>,
  "decisions": [
    { "type": "<decision_type>", ...fields }
  ]
}

DECISION TYPES:

1. add_marker — Add a marker to the timeline
   Required: type, frame_in (int >= 0), color (str), name (str)
   Optional: note (str, default ""), duration (int >= 1, default 1), marker_target ("timeline"|"clip", default "timeline"), entry_filename (str, required if marker_target="clip")

2. set_clip_color — Set color tag on a media pool clip
   Required: type, entry_filename (str), color (str)

3. create_subclip — Create subclip from a source clip
   Required: type, entry_filename (str), frame_in (int >= 0), frame_out (int >= frame_in), subclip_name (str)
   Optional: target_bin (str)

4. add_to_timeline — Append clip segment to timeline
   Required: type, entry_filename (str), frame_in (int >= 0), frame_out (int >= frame_in)
   Optional: track_index (int >= 1, default 1), target_timeline (str)

VALID COLORS: Blue, Green, Yellow, Red, Purple, Cyan, Pink, Orange

FRAME NUMBERS: Convert timecodes to frames using fps from context.
  seconds = (hours * 3600) + (minutes * 60) + seconds
  frame_in = int(seconds * fps)

CONSTRAINTS:
- ADDITIVE ONLY — never delete markers, clips, bins, or timelines
- All names/labels come from user input or context — never invent them
- Use only the decision types listed above
- Colors must be from the VALID COLORS list

EXAMPLES:

User: "mark all chapters as blue markers"
Context: {"chapters": [{"title": "Intro", "start": 0}, {"title": "Main", "start": 90}], "fps": 24}
Output:
{"generated_by": "ollama_nlp", "generated_at": "2026-01-01T00:00:00Z", "fps": 24.0, "decisions": [{"type": "add_marker", "frame_in": 0, "color": "Blue", "name": "Intro"}, {"type": "add_marker", "frame_in": 2160, "color": "Blue", "name": "Main"}]}

User: "create a subclip from 1:23 to 2:45 called Interview Highlight"
Context: {"fps": 24}
Output:
{"generated_by": "ollama_nlp", "generated_at": "2026-01-01T00:00:00Z", "fps": 24.0, "decisions": [{"type": "create_subclip", "entry_filename": "", "frame_in": 1992, "frame_out": 3960, "subclip_name": "Interview Highlight"}]}

User: "color-code clips by speaker: Alice=Blue, Bob=Green"
Context: {"speakers": [{"name": "Alice", "clips": ["clip1.mp4"]}, {"name": "Bob", "clips": ["clip2.mp4"]}], "fps": 24}
Output:
{"generated_by": "ollama_nlp", "generated_at": "2026-01-01T00:00:00Z", "fps": 24.0, "decisions": [{"type": "set_clip_color", "entry_filename": "clip1.mp4", "color": "Blue"}, {"type": "set_clip_color", "entry_filename": "clip2.mp4", "color": "Green"}]}

User: "add chapter markers at 0:00, 1:30, 3:00, 5:00"
Context: {"fps": 24}
Output:
{"generated_by": "ollama_nlp", "generated_at": "2026-01-01T00:00:00Z", "fps": 24.0, "decisions": [{"type": "add_marker", "frame_in": 0, "color": "Blue", "name": "Chapter 1"}, {"type": "add_marker", "frame_in": 2160, "color": "Blue", "name": "Chapter 2"}, {"type": "add_marker", "frame_in": 4320, "color": "Blue", "name": "Chapter 3"}, {"type": "add_marker", "frame_in": 7200, "color": "Blue", "name": "Chapter 4"}]}
"""


# ---------------------------------------------------------------------------
# Timecode parsing
# ---------------------------------------------------------------------------

def parse_timecode_to_seconds(tc: str) -> Optional[float]:
    """Parse a timecode string to seconds.

    Supports formats: H:MM:SS, MM:SS, M:SS, SS, and decimal seconds.
    Returns None if parsing fails.
    """
    tc = tc.strip()

    # Try H:MM:SS or HH:MM:SS
    m = re.match(r"^(\d+):(\d{1,2}):(\d{1,2})(?:\.(\d+))?$", tc)
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        frac = float(f"0.{m.group(4)}") if m.group(4) else 0.0
        return h * 3600 + mn * 60 + s + frac

    # Try MM:SS or M:SS
    m = re.match(r"^(\d{1,2}):(\d{1,2})(?:\.(\d+))?$", tc)
    if m:
        mn, s = int(m.group(1)), int(m.group(2))
        frac = float(f"0.{m.group(3)}") if m.group(3) else 0.0
        return mn * 60 + s + frac

    # Try plain seconds
    try:
        return float(tc)
    except ValueError:
        return None


def timecode_to_frame(tc: str, fps: float) -> Optional[int]:
    """Convert a timecode string to a frame number at given fps."""
    secs = parse_timecode_to_seconds(tc)
    if secs is None:
        return None
    return int(secs * fps)


# ---------------------------------------------------------------------------
# Template fast-path
# ---------------------------------------------------------------------------

def _template_chapters_to_markers(
    context: dict[str, Any],
    color: str = "Blue",
) -> dict[str, Any]:
    """Convert chapters from context into add_marker decisions."""
    chapters = context.get("chapters", [])
    fps = context.get("fps", 24.0)
    now = datetime.now(timezone.utc).isoformat()

    decisions = []
    for ch in chapters:
        start = ch.get("start", 0)
        frame = int(float(start) * fps)
        decisions.append({
            "type": "add_marker",
            "frame_in": frame,
            "color": color,
            "name": ch.get("title", f"Chapter {len(decisions) + 1}"),
            "note": ch.get("summary", ""),
        })

    return {
        "generated_by": "template:chapters_to_markers",
        "generated_at": now,
        "fps": fps,
        "decisions": decisions,
    }


def _template_speakers_to_clip_colors(
    context: dict[str, Any],
    color_map: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Convert speaker-clip mapping into set_clip_color decisions."""
    speakers = context.get("speakers", [])
    fps = context.get("fps", 24.0)
    now = datetime.now(timezone.utc).isoformat()

    # Default color rotation if no explicit map
    default_colors = ["Blue", "Green", "Yellow", "Red", "Purple", "Cyan", "Pink", "Orange"]

    decisions = []
    for idx, spk in enumerate(speakers):
        name = spk.get("name", f"Speaker {idx + 1}")
        clips = spk.get("clips", [])
        if color_map and name in color_map:
            color = color_map[name]
        else:
            color = default_colors[idx % len(default_colors)]

        for clip_file in clips:
            decisions.append({
                "type": "set_clip_color",
                "entry_filename": clip_file,
                "color": color,
            })

    return {
        "generated_by": "template:speakers_to_clip_colors",
        "generated_at": now,
        "fps": fps,
        "decisions": decisions,
    }


def _template_chapters_to_subclips(
    context: dict[str, Any],
    bin_name: Optional[str] = None,
) -> dict[str, Any]:
    """Convert chapters into create_subclip decisions."""
    chapters = context.get("chapters", [])
    fps = context.get("fps", 24.0)
    entry_filename = context.get("entry_filename", "")
    now = datetime.now(timezone.utc).isoformat()

    decisions = []
    for ch in chapters:
        start = ch.get("start", 0)
        end = ch.get("end", start)
        if end <= start:
            continue
        frame_in = int(float(start) * fps)
        frame_out = int(float(end) * fps)
        title = ch.get("title", f"Chapter {len(decisions) + 1}")

        decision: dict[str, Any] = {
            "type": "create_subclip",
            "entry_filename": entry_filename,
            "frame_in": frame_in,
            "frame_out": frame_out,
            "subclip_name": title,
        }
        if bin_name:
            decision["target_bin"] = bin_name
        decisions.append(decision)

    return {
        "generated_by": "template:chapters_to_subclips",
        "generated_at": now,
        "fps": fps,
        "decisions": decisions,
    }


# Template registry: (keywords_any, keywords_all) -> handler
# Match: ALL keywords in keywords_all must be present AND at least one from keywords_any
_TEMPLATES: list[tuple[str, list[str], list[str], Any]] = [
    # name, must_have_all, must_have_any, handler
    ("chapters_to_markers", ["chapter"], ["marker", "mark"], _template_chapters_to_markers),
    ("speakers_to_clip_colors", ["speaker"], ["color", "colour"], _template_speakers_to_clip_colors),
    ("chapters_to_subclips", ["chapter"], ["subclip", "sub-clip", "sub clip"], _template_chapters_to_subclips),
]


def _match_template(command: str) -> Optional[tuple[str, Any]]:
    """Check if command matches a known template pattern.

    Returns (template_name, handler_fn) or None.
    """
    cmd_lower = command.lower()
    for name, must_all, must_any, handler in _TEMPLATES:
        all_present = all(kw in cmd_lower for kw in must_all)
        any_present = any(kw in cmd_lower for kw in must_any)
        if all_present and any_present:
            return name, handler
    return None


def _extract_color_from_command(command: str) -> Optional[str]:
    """Extract a color name from the command string if present."""
    cmd_lower = command.lower()
    for color in VALID_COLORS:
        if color.lower() in cmd_lower:
            return color
    return None


# ---------------------------------------------------------------------------
# Ollama translation
# ---------------------------------------------------------------------------

def _extract_json_from_response(text: str) -> Optional[dict[str, Any]]:
    """Extract JSON object from Ollama response text.

    Handles responses that may include markdown code fences or surrounding text.
    """
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from code fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } block
    brace_start = text.find("{")
    if brace_start >= 0:
        # Find matching closing brace
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start:i + 1])
                    except json.JSONDecodeError:
                        break

    return None


def _build_user_message(command: str, context: dict[str, Any]) -> str:
    """Build the user message combining command and serialized context."""
    context_str = json.dumps(context, default=str)
    return f"Command: {command}\nContext: {context_str}"


def _translate_via_ollama(
    command: str,
    context: dict[str, Any],
    model: str,
    ollama_host: str,
) -> dict[str, Any]:
    """Send command to Ollama and parse the response as edit decisions.

    Retries once if the first response is not valid JSON.

    Returns:
        Valid decisions envelope dict on success, or error dict on failure.
    """
    from ollama_delegate import delegate_to_ollama

    user_msg = _build_user_message(command, context)
    full_prompt = f"{SYSTEM_PROMPT}\n\n{user_msg}"

    # First attempt
    result = delegate_to_ollama(
        prompt=full_prompt,
        model=model,
        task_type="coding",
        timeout=120,
        temperature=0.2,
    )

    if result.get("status") != "pass":
        return {
            "error": f"Ollama request failed: {result.get('response', 'unknown error')}",
            "model": result.get("model"),
            "duration_s": result.get("duration_s", 0),
        }

    response_text = result.get("response", "")
    parsed = _extract_json_from_response(response_text)

    if parsed is not None:
        valid, errors = validate_decisions(parsed)
        if valid:
            return parsed
        # JSON parsed but failed schema validation — retry with error feedback
        logger.info("Ollama response failed validation: %s. Retrying.", errors)

    # Retry with correction prompt
    retry_prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Your previous output was not valid. "
        f"Please output ONLY a valid JSON object matching the schema above. "
        f"No markdown, no explanation.\n\n{user_msg}"
    )

    result2 = delegate_to_ollama(
        prompt=retry_prompt,
        model=model,
        task_type="coding",
        timeout=120,
        temperature=0.1,
    )

    if result2.get("status") != "pass":
        return {
            "error": f"Ollama retry failed: {result2.get('response', 'unknown error')}",
            "model": result2.get("model"),
            "duration_s": result.get("duration_s", 0) + result2.get("duration_s", 0),
        }

    response_text2 = result2.get("response", "")
    parsed2 = _extract_json_from_response(response_text2)

    if parsed2 is not None:
        valid2, errors2 = validate_decisions(parsed2)
        if valid2:
            return parsed2
        return {
            "error": f"Ollama output failed schema validation after retry: {errors2}",
            "raw_response": response_text2[:500],
            "model": result2.get("model"),
        }

    return {
        "error": "Could not extract valid JSON from Ollama response after retry",
        "raw_response": response_text2[:500] if response_text2 else response_text[:500],
        "model": result2.get("model"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def translate_command(
    command: str,
    context: dict[str, Any],
    model: str | None = None,
    ollama_host: str = "http://localhost:11434",
) -> dict[str, Any]:
    """Translate a natural language editing command into edit-decisions JSON.

    Checks template fast-path first, falls back to Ollama inference.

    Args:
        command: Natural language command (e.g. "mark chapters as blue markers").
        context: Dict with chapters, speakers, clips, fps, etc.
        model: Ollama model to use for free-form translation.
        ollama_host: Ollama server URL.

    Returns:
        Dict with either a valid decisions envelope or an error key.
        On success: {"generated_by": ..., "decisions": [...], ...}
        Also includes "_translation_method": "template" or "ollama".
        On failure: {"error": "...", ...}
    """
    if not command or not command.strip():
        return {"error": "Empty command"}

    # Ensure fps is present in context
    if "fps" not in context:
        context["fps"] = 24.0

    # Try template fast-path
    match = _match_template(command)
    if match is not None:
        template_name, handler = match

        # Extract color override from command if present
        kwargs: dict[str, Any] = {}
        color = _extract_color_from_command(command)

        if template_name == "chapters_to_markers" and color:
            kwargs["color"] = color
        elif template_name == "chapters_to_subclips":
            # Check for bin name in command
            bin_match = re.search(r"(?:into|in|to)\s+(?:bin|folder)\s+['\"]?(\w[\w\s]*\w)['\"]?", command, re.IGNORECASE)
            if bin_match:
                kwargs["bin_name"] = bin_match.group(1).strip()

        result = handler(context, **kwargs)

        # Validate template output
        if result.get("decisions"):
            result["_translation_method"] = "template"
            return result
        return {"error": f"Template '{template_name}' produced no decisions", "_translation_method": "template"}

    # Fall back to Ollama
    result = _translate_via_ollama(command, context, model, ollama_host)
    if "error" not in result:
        result["_translation_method"] = "ollama"
    else:
        result["_translation_method"] = "ollama"
    return result
