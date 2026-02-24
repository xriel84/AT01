"""Tests for promote.py — all offline."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from promote import advance, log_promotion


class TestAdvance:
    def test_advance_tier1_to_tier2(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            src = base / "tier1" / "logo_001.png"
            src.parent.mkdir(parents=True)
            src.write_bytes(b"fake-png")

            result = advance(src, current_tier=1, base_dir=base)

            assert result == base / "tier2" / "logo_001.png"
            assert result.exists()
            assert not src.exists()

    def test_advance_tier2_to_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            src = base / "tier2" / "banner_002.png"
            src.parent.mkdir(parents=True)
            src.write_bytes(b"fake-png")

            result = advance(src, current_tier=2, base_dir=base)

            assert result == base / "workspace" / "banner_002.png"
            assert result.exists()
            assert not src.exists()

    def test_advance_workspace_to_marketing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            src = base / "workspace" / "hero_003.png"
            src.parent.mkdir(parents=True)
            src.write_bytes(b"fake-png")

            result = advance(src, current_tier=3, base_dir=base)

            assert result == base / "marketing" / "hero_003.png"
            assert result.exists()
            assert not src.exists()

    def test_rejects_invalid_tier(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            src = base / "marketing" / "done.png"
            src.parent.mkdir(parents=True)
            src.write_bytes(b"fake-png")

            with pytest.raises(ValueError):
                advance(src, current_tier=4, base_dir=base)

    def test_creates_target_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            src = base / "tier1" / "new_asset.png"
            src.parent.mkdir(parents=True)
            src.write_bytes(b"fake-png")

            # tier2/ does not exist yet
            assert not (base / "tier2").exists()

            result = advance(src, current_tier=1, base_dir=base)

            assert (base / "tier2").is_dir()
            assert result.exists()


class TestLogPromotion:
    def test_logs_promotion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "promo.json"

            log_promotion(log_path, "logo_001.png", from_tier=1, to_tier=2)

            entries = json.loads(log_path.read_text(encoding="utf-8"))
            assert len(entries) == 1
            assert entries[0]["file_name"] == "logo_001.png"

    def test_creates_log_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "subdir" / "promo.json"

            assert not log_path.exists()

            log_promotion(log_path, "a.png", from_tier=1, to_tier=2)

            assert log_path.exists()
            entries = json.loads(log_path.read_text(encoding="utf-8"))
            assert len(entries) == 1

    def test_appends_to_existing_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "promo.json"

            log_promotion(log_path, "a.png", from_tier=1, to_tier=2)
            log_promotion(log_path, "b.png", from_tier=2, to_tier=3)

            entries = json.loads(log_path.read_text(encoding="utf-8"))
            assert len(entries) == 2
            assert entries[0]["file_name"] == "a.png"
            assert entries[1]["file_name"] == "b.png"

    def test_log_entry_has_required_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "promo.json"

            log_promotion(log_path, "x.png", from_tier=2, to_tier=3)

            entries = json.loads(log_path.read_text(encoding="utf-8"))
            entry = entries[0]
            assert "file_name" in entry
            assert "from_tier" in entry
            assert "to_tier" in entry
            assert "timestamp" in entry
            assert entry["from_tier"] == 2
            assert entry["to_tier"] == 3
