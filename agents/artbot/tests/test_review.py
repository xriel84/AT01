"""Tests for review.py — all offline."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from review import build_review_manifest, mark_selection, save_manifest


class TestBuildReviewManifest:
    def test_creates_json_from_images(self):
        images = [Path("/fake/img_0.png"), Path("/fake/img_1.png"), Path("/fake/img_2.png")]
        brief = {"raw_text": "noir logo", "asset_type": "logo"}
        result = build_review_manifest(images, brief)
        assert "images" in result
        assert len(result["images"]) == 3
        for i, entry in enumerate(result["images"]):
            assert "path" in entry
            assert entry["index"] == i
            assert "tier" in entry

    def test_includes_brief_metadata(self):
        images = [Path("/fake/img_0.png")]
        brief = {"raw_text": "gold banner animated", "asset_type": "banner"}
        result = build_review_manifest(images, brief)
        assert result["brief"] == brief

    def test_tier_defaults_to_1(self):
        images = [Path("/fake/a.png"), Path("/fake/b.png")]
        brief = {"raw_text": "test"}
        result = build_review_manifest(images, brief)
        for entry in result["images"]:
            assert entry["tier"] == 1

    def test_custom_tier(self):
        images = [Path("/fake/a.png"), Path("/fake/b.png")]
        brief = {"raw_text": "test"}
        result = build_review_manifest(images, brief, tier=2)
        for entry in result["images"]:
            assert entry["tier"] == 2


class TestMarkSelection:
    def test_marks_selected_images(self):
        images = [Path("/fake/a.png"), Path("/fake/b.png"), Path("/fake/c.png")]
        brief = {"raw_text": "test"}
        manifest = build_review_manifest(images, brief)
        result = mark_selection(manifest, selected=[0, 2])
        assert result["images"][0]["selected"] is True
        assert result["images"][1]["selected"] is False
        assert result["images"][2]["selected"] is True

    def test_designates_animate_flag(self):
        images = [Path("/fake/a.png"), Path("/fake/b.png"), Path("/fake/c.png")]
        brief = {"raw_text": "test"}
        manifest = build_review_manifest(images, brief)
        result = mark_selection(manifest, selected=[0, 2], animate=[0])
        assert result["images"][0]["animate"] is True
        assert result["images"][2]["animate"] is False

    def test_unselected_not_animated(self):
        images = [Path("/fake/a.png"), Path("/fake/b.png"), Path("/fake/c.png")]
        brief = {"raw_text": "test"}
        manifest = build_review_manifest(images, brief)
        # Mark image 1 in animate list but NOT in selected list
        result = mark_selection(manifest, selected=[0], animate=[1])
        assert result["images"][1]["selected"] is False
        assert result["images"][1]["animate"] is False


class TestSaveManifest:
    def test_saves_to_disk(self):
        images = [Path("/fake/a.png")]
        brief = {"raw_text": "test"}
        manifest = build_review_manifest(images, brief)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "manifest.json"
            save_manifest(manifest, out_path)
            loaded = json.loads(out_path.read_text(encoding="utf-8"))
            assert loaded == manifest

    def test_returns_path(self):
        images = [Path("/fake/a.png")]
        brief = {"raw_text": "test"}
        manifest = build_review_manifest(images, brief)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "manifest.json"
            result = save_manifest(manifest, out_path)
            assert isinstance(result, Path)
            assert result == out_path
