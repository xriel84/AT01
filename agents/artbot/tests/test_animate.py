"""Tests for animate.py -- all offline, no ComfyUI."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from animate import build_animate_workflow, animate_batch


# ---------------------------------------------------------------------------
# TestBuildAnimateWorkflow
# ---------------------------------------------------------------------------

class TestBuildAnimateWorkflow:
    def test_uses_vace_512(self):
        """Workflow dict forces 512x512 resolution (VACE OOM constraint)."""
        wf = build_animate_workflow(Path("C:/NB11/ComfyUI/output/at/test.png"))
        payload_str = json.dumps(wf)
        assert '"width": 512' in payload_str or '"width":512' in payload_str
        assert '"height": 512' in payload_str or '"height":512' in payload_str

    def test_accepts_input_image(self):
        """Source image path string appears in workflow."""
        image_path = Path("C:/NB11/ComfyUI/output/at/at_aribot_M-C_idle_00001.png")
        wf = build_animate_workflow(image_path)
        payload_str = json.dumps(wf)
        assert str(image_path) in payload_str or image_path.name in payload_str

    def test_returns_dict(self):
        """Return type is dict."""
        wf = build_animate_workflow(Path("test.png"))
        assert isinstance(wf, dict)

    def test_default_settings(self):
        """No settings arg -> uses sensible defaults (cfg_scale, steps)."""
        wf = build_animate_workflow(Path("test.png"))
        payload_str = json.dumps(wf)
        # Default cfg_scale=7.0 and steps=20
        assert "7.0" in payload_str or "7" in payload_str
        assert "20" in payload_str


# ---------------------------------------------------------------------------
# TestAnimateBatch
# ---------------------------------------------------------------------------

class TestAnimateBatch:
    def _make_manifest(self):
        """Helper: manifest with 3 images, 2 animate=True, 1 animate=False."""
        return {
            "images": [
                {"path": "C:/NB11/ComfyUI/output/at/img_a.png", "animate": True},
                {"path": "C:/NB11/ComfyUI/output/at/img_b.png", "animate": True},
                {"path": "C:/NB11/ComfyUI/output/at/img_c.png", "animate": False},
            ]
        }

    def test_submits_only_animated(self):
        """Manifest with 3 images (2 animate=True, 1 animate=False) -> only 2 submissions."""
        manifest = self._make_manifest()

        mock_results = [
            {"prompt_id": "p1", "status": "submitted"},
            {"prompt_id": "p2", "status": "submitted"},
        ]

        with patch("animate.submit_batch", return_value=mock_results) as mock_submit:
            results = animate_batch(manifest)
            # submit_batch should have been called with exactly 2 workflows
            assert mock_submit.call_count == 1
            workflows_arg = mock_submit.call_args[0][0]
            assert len(workflows_arg) == 2

    def test_skips_static_images(self):
        """Images with animate=False not submitted."""
        manifest = {
            "images": [
                {"path": "C:/NB11/ComfyUI/output/at/static.png", "animate": False},
                {"path": "C:/NB11/ComfyUI/output/at/static2.png", "animate": False},
            ]
        }

        with patch("animate.submit_batch", return_value=[]) as mock_submit:
            results = animate_batch(manifest)
            # Nothing to submit -- submit_batch called with empty list or not called
            if mock_submit.call_count == 1:
                workflows_arg = mock_submit.call_args[0][0]
                assert len(workflows_arg) == 0
            else:
                assert mock_submit.call_count == 0
            assert isinstance(results, list)
            assert len(results) == 0

    def test_handles_offline(self):
        """Mock ConnectionRefusedError -> returns error list, no crash."""
        manifest = self._make_manifest()

        error_results = [
            {"status": "error", "error": "Connection refused"},
            {"status": "error", "error": "Connection refused"},
        ]

        with patch("animate.submit_batch", return_value=error_results):
            results = animate_batch(manifest)
            assert isinstance(results, list)
            # Should have entries for the 2 animate=True images
            assert len(results) == 2
            assert all(r["status"] == "error" for r in results)

    def test_returns_results_list(self):
        """Return is a list of dicts with status info."""
        manifest = self._make_manifest()

        mock_results = [
            {"prompt_id": "p1", "status": "submitted"},
            {"prompt_id": "p2", "status": "submitted"},
        ]

        with patch("animate.submit_batch", return_value=mock_results):
            results = animate_batch(manifest)
            assert isinstance(results, list)
            for r in results:
                assert isinstance(r, dict)
                assert "status" in r
