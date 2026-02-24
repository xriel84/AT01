"""Tests for label.py — all offline."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from label import build_label, rename_for_edbot


class TestBuildLabel:
    def test_follows_naming_convention(self):
        result = build_label("al", "logo", "hero", "idle", 1)
        assert result == "al_logo_hero_idle_001"

    def test_pads_sequence(self):
        result = build_label("al", "logo", "hero", "idle", 42)
        assert result.endswith("_042")

    def test_pads_single_digit(self):
        result = build_label("al", "logo", "hero", "idle", 1)
        assert result.endswith("_001")

    def test_all_lowercase(self):
        result = build_label("AL", "LOGO", "HERO", "IDLE", 1)
        assert result == "al_logo_hero_idle_001"


class TestRenameForEdbot:
    def test_renames_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source"
            src.mkdir()
            out = Path(tmpdir) / "output"

            # Create source images
            (src / "raw_photo1.png").write_bytes(b"img1")
            (src / "raw_photo2.png").write_bytes(b"img2")

            manifest = {
                "project": "al",
                "images": [
                    {
                        "path": str(src / "raw_photo1.png"),
                        "selected": True,
                        "subject": "logo",
                        "shot": "hero",
                        "action": "idle",
                        "seq": 1,
                    },
                    {
                        "path": str(src / "raw_photo2.png"),
                        "selected": True,
                        "subject": "logo",
                        "shot": "hero",
                        "action": "idle",
                        "seq": 2,
                    },
                ],
            }

            result = rename_for_edbot(manifest, out, project="al")
            assert len(result) == 2
            assert result[0].name == "al_logo_hero_idle_001.png"
            assert result[1].name == "al_logo_hero_idle_002.png"
            assert result[0].exists()
            assert result[1].exists()

    def test_preserves_extension(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source"
            src.mkdir()
            out = Path(tmpdir) / "output"

            (src / "clip.mp4").write_bytes(b"video")
            (src / "still.png").write_bytes(b"image")

            manifest = {
                "project": "al",
                "images": [
                    {
                        "path": str(src / "clip.mp4"),
                        "selected": True,
                        "subject": "logo",
                        "shot": "hero",
                        "action": "spin",
                        "seq": 1,
                    },
                    {
                        "path": str(src / "still.png"),
                        "selected": True,
                        "subject": "logo",
                        "shot": "hero",
                        "action": "idle",
                        "seq": 2,
                    },
                ],
            }

            result = rename_for_edbot(manifest, out, project="al")
            assert result[0].suffix == ".mp4"
            assert result[1].suffix == ".png"

    def test_only_renames_selected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source"
            src.mkdir()
            out = Path(tmpdir) / "output"

            (src / "a.png").write_bytes(b"a")
            (src / "b.png").write_bytes(b"b")
            (src / "c.png").write_bytes(b"c")

            manifest = {
                "project": "al",
                "images": [
                    {
                        "path": str(src / "a.png"),
                        "selected": True,
                        "subject": "logo",
                        "shot": "hero",
                        "action": "idle",
                        "seq": 1,
                    },
                    {
                        "path": str(src / "b.png"),
                        "selected": False,
                        "subject": "logo",
                        "shot": "hero",
                        "action": "idle",
                        "seq": 2,
                    },
                    {
                        "path": str(src / "c.png"),
                        "selected": True,
                        "subject": "logo",
                        "shot": "hero",
                        "action": "idle",
                        "seq": 3,
                    },
                ],
            }

            result = rename_for_edbot(manifest, out, project="al")
            assert len(result) == 2
            # Only 2 files should exist in output
            assert len(list(out.iterdir())) == 2

    def test_returns_path_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source"
            src.mkdir()
            out = Path(tmpdir) / "output"

            (src / "img.png").write_bytes(b"data")

            manifest = {
                "project": "al",
                "images": [
                    {
                        "path": str(src / "img.png"),
                        "selected": True,
                        "subject": "banner",
                        "shot": "wide",
                        "action": "idle",
                        "seq": 1,
                    },
                ],
            }

            result = rename_for_edbot(manifest, out, project="al")
            assert isinstance(result, list)
            assert all(isinstance(p, Path) for p in result)
