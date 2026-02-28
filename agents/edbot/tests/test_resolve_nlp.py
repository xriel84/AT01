"""Tests for resolve_nlp — template matching, Ollama translation, JSON extraction.

All Ollama calls are mocked (no live Ollama dependency in pytest).
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_tools_dir = str(Path(__file__).resolve().parent.parent / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

_shared_dir = str(Path(__file__).resolve().parent.parent.parent / "shared")
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)

from resolve_nlp import (
    translate_command,
    parse_timecode_to_seconds,
    timecode_to_frame,
    _match_template,
    _extract_json_from_response,
    _extract_color_from_command,
    _template_chapters_to_markers,
    _template_speakers_to_clip_colors,
    _template_chapters_to_subclips,
    SYSTEM_PROMPT,
)
from resolve_decisions import validate_decisions


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _chapter_context() -> dict:
    """Context with chapters for template tests."""
    return {
        "chapters": [
            {"title": "Intro", "start": 0, "end": 60, "summary": "Opening segment"},
            {"title": "Main", "start": 60, "end": 180, "summary": "Core content"},
            {"title": "Outro", "start": 180, "end": 240, "summary": "Closing"},
        ],
        "fps": 24.0,
    }


def _speaker_context() -> dict:
    """Context with speakers for template tests."""
    return {
        "speakers": [
            {"name": "Alice", "clips": ["alice_cam.mp4", "alice_mic.wav"]},
            {"name": "Bob", "clips": ["bob_cam.mp4"]},
        ],
        "fps": 24.0,
    }


def _mock_ollama_success(decisions_json: dict) -> dict:
    """Build a mock delegate_to_ollama return for successful inference."""
    return {
        "status": "pass",
        "response": json.dumps(decisions_json),
        "model": "qwen2.5-coder:14b",
        "duration_s": 2.5,
        "task_type": "coding",
        "timestamp": "2026-02-27T00:00:00Z",
    }


def _mock_ollama_error() -> dict:
    """Build a mock delegate_to_ollama return for failed inference."""
    return {
        "status": "error",
        "response": "connection refused",
        "model": "qwen2.5-coder:14b",
        "duration_s": 0.1,
        "task_type": "coding",
        "timestamp": "2026-02-27T00:00:00Z",
    }


# ===========================================================================
# Template matching (3)
# ===========================================================================

class TestTemplateMatching:
    def test_chapters_to_markers(self):
        """'mark chapters as blue markers' matches chapters_to_markers template."""
        result = _match_template("mark chapters as blue markers")
        assert result is not None
        assert result[0] == "chapters_to_markers"

    def test_speakers_to_colors(self):
        """'color-code clips by speaker' matches speakers_to_clip_colors template."""
        result = _match_template("color-code clips by speaker")
        assert result is not None
        assert result[0] == "speakers_to_clip_colors"

    def test_chapters_to_subclips(self):
        """'create subclips from chapters' matches chapters_to_subclips template."""
        result = _match_template("create subclips from chapters")
        assert result is not None
        assert result[0] == "chapters_to_subclips"

    def test_no_match_freeform(self):
        """Free-form command does not match any template."""
        result = _match_template("add a marker at 1 minute 30 seconds")
        assert result is None

    def test_case_insensitive(self):
        """Template matching is case-insensitive."""
        result = _match_template("MARK CHAPTERS AS GREEN MARKERS")
        assert result is not None
        assert result[0] == "chapters_to_markers"


# ===========================================================================
# Template output validation (3)
# ===========================================================================

class TestTemplateOutput:
    def test_chapters_to_markers_schema_valid(self):
        """chapters_to_markers template produces valid schema."""
        ctx = _chapter_context()
        result = _template_chapters_to_markers(ctx)
        valid, errors = validate_decisions(result)
        assert valid, f"Validation errors: {errors}"
        assert len(result["decisions"]) == 3
        assert result["decisions"][0]["name"] == "Intro"
        assert result["decisions"][0]["frame_in"] == 0
        assert result["decisions"][1]["frame_in"] == 60 * 24  # 1440

    def test_speakers_to_colors_schema_valid(self):
        """speakers_to_clip_colors template produces valid schema."""
        ctx = _speaker_context()
        result = _template_speakers_to_clip_colors(ctx)
        valid, errors = validate_decisions(result)
        assert valid, f"Validation errors: {errors}"
        assert len(result["decisions"]) == 3  # 2 Alice clips + 1 Bob clip

    def test_chapters_to_subclips_schema_valid(self):
        """chapters_to_subclips template produces valid schema."""
        ctx = _chapter_context()
        ctx["entry_filename"] = "video.mp4"
        result = _template_chapters_to_subclips(ctx)
        valid, errors = validate_decisions(result)
        assert valid, f"Validation errors: {errors}"
        assert len(result["decisions"]) == 3
        assert result["decisions"][0]["subclip_name"] == "Intro"

    def test_chapters_to_markers_color_override(self):
        """Template extracts color from command string."""
        ctx = _chapter_context()
        result = translate_command("mark chapters as green markers", ctx)
        assert result["decisions"][0]["color"] == "Green"


# ===========================================================================
# Timecode parsing (4)
# ===========================================================================

class TestTimecodeParsing:
    def test_mmss(self):
        """Parse MM:SS timecode."""
        assert parse_timecode_to_seconds("1:23") == 83.0

    def test_hhmmss(self):
        """Parse H:MM:SS timecode."""
        assert parse_timecode_to_seconds("1:02:30") == 3750.0

    def test_plain_seconds(self):
        """Parse plain seconds."""
        assert parse_timecode_to_seconds("90.5") == 90.5

    def test_frame_conversion(self):
        """timecode_to_frame converts correctly at 24fps."""
        assert timecode_to_frame("1:23", 24.0) == 1992  # 83 * 24

    def test_invalid_timecode(self):
        """Invalid timecode returns None."""
        assert parse_timecode_to_seconds("not-a-time") is None
        assert timecode_to_frame("bad", 24.0) is None


# ===========================================================================
# JSON extraction from Ollama response (3)
# ===========================================================================

class TestJsonExtraction:
    def test_clean_json(self):
        """Extracts clean JSON directly."""
        text = '{"generated_by": "test", "fps": 24.0}'
        result = _extract_json_from_response(text)
        assert result is not None
        assert result["generated_by"] == "test"

    def test_json_in_code_fence(self):
        """Extracts JSON from markdown code fence."""
        text = 'Here is the result:\n```json\n{"generated_by": "test", "fps": 24.0}\n```\n'
        result = _extract_json_from_response(text)
        assert result is not None
        assert result["fps"] == 24.0

    def test_json_with_surrounding_text(self):
        """Extracts JSON from response with surrounding explanation."""
        text = 'I will create the following:\n{"generated_by": "test", "fps": 24.0}\nDone!'
        result = _extract_json_from_response(text)
        assert result is not None

    def test_no_json_returns_none(self):
        """Returns None when no JSON found."""
        result = _extract_json_from_response("This is just text with no JSON")
        assert result is None


# ===========================================================================
# Ollama translation — mocked (4)
# ===========================================================================

class TestOllamaTranslation:
    def test_successful_translation(self):
        """Ollama returns valid decisions JSON on first try."""
        valid_decisions = {
            "generated_by": "ollama_nlp",
            "generated_at": "2026-02-27T00:00:00Z",
            "fps": 24.0,
            "decisions": [
                {"type": "add_marker", "frame_in": 1992, "color": "Blue", "name": "Highlight"}
            ],
        }

        with patch("ollama_delegate.delegate_to_ollama", return_value=_mock_ollama_success(valid_decisions)):
            result = translate_command(
                "add a blue marker at 1:23",
                {"fps": 24.0},
            )

        assert "error" not in result
        assert result["_translation_method"] == "ollama"
        assert len(result["decisions"]) == 1

    def test_retry_on_bad_json(self):
        """Ollama retries when first response is invalid JSON."""
        valid_decisions = {
            "generated_by": "ollama_nlp",
            "generated_at": "2026-02-27T00:00:00Z",
            "fps": 24.0,
            "decisions": [
                {"type": "add_marker", "frame_in": 0, "color": "Blue", "name": "Test"}
            ],
        }

        bad_response = {
            "status": "pass",
            "response": "I'll create a marker...",  # not JSON
            "model": "qwen2.5-coder:14b",
            "duration_s": 2.0,
            "task_type": "coding",
            "timestamp": "2026-02-27T00:00:00Z",
        }

        with patch("ollama_delegate.delegate_to_ollama", side_effect=[
            bad_response,
            _mock_ollama_success(valid_decisions),
        ]):
            result = translate_command(
                "add a marker at the start",
                {"fps": 24.0},
            )

        assert "error" not in result
        assert len(result["decisions"]) == 1

    def test_persistent_failure_returns_error(self):
        """Ollama returns error dict after both attempts fail."""
        bad_response = {
            "status": "pass",
            "response": "Sorry, I cannot do that.",
            "model": "qwen2.5-coder:14b",
            "duration_s": 1.0,
            "task_type": "coding",
            "timestamp": "2026-02-27T00:00:00Z",
        }

        with patch("ollama_delegate.delegate_to_ollama", return_value=bad_response):
            result = translate_command(
                "do something complex",
                {"fps": 24.0},
            )

        assert "error" in result

    def test_ollama_connection_error(self):
        """Ollama connection failure returns error dict (no crash)."""
        with patch("ollama_delegate.delegate_to_ollama", return_value=_mock_ollama_error()):
            result = translate_command(
                "add a marker",
                {"fps": 24.0},
            )

        assert "error" in result
        assert "connection" in result["error"].lower() or "failed" in result["error"].lower()


# ===========================================================================
# translate_command integration (3)
# ===========================================================================

class TestTranslateCommand:
    def test_template_path_no_ollama(self):
        """Template commands do not call Ollama."""
        ctx = _chapter_context()
        with patch("ollama_delegate.delegate_to_ollama") as mock_ollama:
            result = translate_command("mark chapters as blue markers", ctx)

        mock_ollama.assert_not_called()
        assert result["_translation_method"] == "template"
        assert len(result["decisions"]) == 3

    def test_empty_command_returns_error(self):
        """Empty command returns error dict."""
        result = translate_command("", {"fps": 24.0})
        assert "error" in result

    def test_freeform_uses_ollama(self):
        """Free-form command falls through to Ollama."""
        valid_decisions = {
            "generated_by": "ollama_nlp",
            "generated_at": "2026-02-27T00:00:00Z",
            "fps": 24.0,
            "decisions": [
                {"type": "add_marker", "frame_in": 0, "color": "Red", "name": "Alert"}
            ],
        }

        with patch("ollama_delegate.delegate_to_ollama", return_value=_mock_ollama_success(valid_decisions)):
            result = translate_command(
                "put a red alert marker at the very beginning",
                {"fps": 24.0},
            )

        assert result["_translation_method"] == "ollama"
        assert "error" not in result


# ===========================================================================
# Color extraction (1)
# ===========================================================================

class TestColorExtraction:
    def test_extracts_all_colors(self):
        """_extract_color_from_command finds each valid color."""
        from resolve_decisions import VALID_COLORS
        for color in VALID_COLORS:
            result = _extract_color_from_command(f"mark as {color.lower()} markers")
            assert result == color, f"Failed to extract {color}"


# ===========================================================================
# System prompt (1)
# ===========================================================================

class TestSystemPrompt:
    def test_system_prompt_has_all_types(self):
        """System prompt documents all 4 decision types."""
        assert "add_marker" in SYSTEM_PROMPT
        assert "set_clip_color" in SYSTEM_PROMPT
        assert "create_subclip" in SYSTEM_PROMPT
        assert "add_to_timeline" in SYSTEM_PROMPT

    def test_system_prompt_has_valid_colors(self):
        """System prompt lists all valid colors."""
        for color in ["Blue", "Green", "Yellow", "Red", "Purple", "Cyan", "Pink", "Orange"]:
            assert color in SYSTEM_PROMPT
