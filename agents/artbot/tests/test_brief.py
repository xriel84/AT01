"""Tests for brief.py — all offline, no ComfyUI, no GPU."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brief import parse_brief, build_prompt, generate_variations, load_library


class TestParseBrief:
    def test_extracts_asset_type_logo(self):
        result = parse_brief("animated logo for intro")
        assert result["asset_type"] == "logo"
        assert result["animated"] is True

    def test_extracts_static_frame(self):
        result = parse_brief("PNG frame for intro")
        assert result["asset_type"] == "frame"
        assert result["animated"] is False

    def test_extracts_style_hints(self):
        result = parse_brief("dark noir style logo")
        assert "noir" in result["style_hints"]

    def test_returns_dict_with_required_keys(self):
        result = parse_brief("anything at all")
        for key in ("asset_type", "animated", "style_hints", "raw_text"):
            assert key in result, f"Missing required key: {key}"

    def test_raw_text_preserved(self):
        text = "animated logo spinning gold"
        result = parse_brief(text)
        assert result["raw_text"] == text

    def test_multiple_style_hints(self):
        result = parse_brief("dark noir gold minimal banner")
        assert "noir" in result["style_hints"]
        assert "gold" in result["style_hints"]
        assert "dark" in result["style_hints"]
        assert "minimal" in result["style_hints"]

    def test_animation_keyword_motion(self):
        result = parse_brief("motion graphic logo")
        assert result["animated"] is True

    def test_animation_keyword_animation(self):
        result = parse_brief("logo with animation")
        assert result["animated"] is True

    def test_no_animation_keywords(self):
        result = parse_brief("static logo for print")
        assert result["animated"] is False

    def test_unknown_asset_type_defaults(self):
        result = parse_brief("something weird and unusual")
        assert result["asset_type"] == "generic"


class TestBuildPrompt:
    def test_converts_to_sdxl_language(self):
        brief = parse_brief("noir style logo")
        result = build_prompt(brief)
        assert isinstance(result, dict)
        assert "positive" in result
        assert "negative" in result
        # SDXL quality tags should be present
        assert "best quality" in result["positive"] or "masterpiece" in result["positive"]

    def test_uses_library_keywords(self):
        brief = parse_brief("noir logo")
        library = {
            "style": {"noir": "1930s art deco, bold outlines, noir lighting"},
            "quality": {"high": "masterpiece, best quality"},
            "negative": {"default": "photorealistic, blurry"},
        }
        result = build_prompt(brief, library=library)
        assert "1930s art deco" in result["positive"]

    def test_works_without_library(self):
        brief = parse_brief("gold banner for YouTube")
        result = build_prompt(brief, library=None)
        assert isinstance(result["positive"], str)
        assert len(result["positive"]) > 0

    def test_includes_negative_prompt(self):
        brief = parse_brief("logo")
        library = {
            "negative": {"default": "photorealistic, blurry, watermark"},
        }
        result = build_prompt(brief, library=library)
        assert "photorealistic" in result["negative"]

    def test_negative_prompt_without_library(self):
        brief = parse_brief("logo")
        result = build_prompt(brief, library=None)
        assert isinstance(result["negative"], str)


class TestGenerateVariations:
    def test_creates_n_variations(self):
        result = generate_variations("a cool logo, best quality", n=4)
        assert len(result) == 4

    def test_variations_differ(self):
        result = generate_variations("a cool logo, best quality", n=4)
        seeds = [v["seed"] for v in result]
        # All seeds should be unique
        assert len(set(seeds)) == 4

    def test_each_variation_has_required_keys(self):
        result = generate_variations("a cool logo, best quality", n=3)
        for variation in result:
            for key in ("prompt", "cfg_scale", "seed", "sampler"):
                assert key in variation, f"Missing required key: {key}"

    def test_cfg_scale_varies(self):
        result = generate_variations("a cool logo", n=4)
        cfg_scales = [v["cfg_scale"] for v in result]
        # At least some cfg_scale values should differ
        assert len(set(cfg_scales)) > 1

    def test_prompt_present_in_each(self):
        base = "noir logo, masterpiece"
        result = generate_variations(base, n=3)
        for v in result:
            assert base in v["prompt"]

    def test_default_n_is_4(self):
        result = generate_variations("test prompt")
        assert len(result) == 4


class TestLoadLibrary:
    def test_loads_existing_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lib_path = Path(tmpdir) / "sdxl_library.json"
            lib_data = {
                "style": {"noir": "bold outlines, noir lighting"},
                "quality": {"high": "masterpiece, best quality"},
                "negative": {"default": "blurry, watermark"},
            }
            lib_path.write_text(json.dumps(lib_data), encoding="utf-8")

            result = load_library(lib_path)
            assert result == lib_data
            assert "style" in result
            assert result["style"]["noir"] == "bold outlines, noir lighting"

    def test_returns_empty_for_missing(self):
        missing_path = Path("/nonexistent/path/sdxl_library.json")
        result = load_library(missing_path)
        assert result == {}

    def test_returns_empty_for_none(self):
        # When path is None and default file doesn't exist
        result = load_library(Path("/nonexistent/default/sdxl_library.json"))
        assert result == {}
