"""Tests for generate.py -- all offline, no ComfyUI, mock HTTP."""

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate import build_workflow, submit_batch, collect_results


# ---------------------------------------------------------------------------
# TestBuildWorkflow
# ---------------------------------------------------------------------------

class TestBuildWorkflow:
    def test_builds_valid_comfyui_payload(self):
        """Given prompt + settings -> returns dict with 'prompt' key."""
        settings = {"cfg_scale": 7.0, "seed": 42, "sampler": "euler_ancestral"}
        result = build_workflow("noir robot character", settings)
        assert isinstance(result, dict)
        assert "prompt" in result

    def test_resolution_512(self):
        """All workflows force 512x512 resolution (VACE constraint)."""
        settings = {"cfg_scale": 7.0, "seed": 42, "sampler": "euler_ancestral"}
        result = build_workflow("noir robot character", settings)
        payload_str = json.dumps(result)
        # Width and height must both be 512
        assert '"width": 512' in payload_str or '"width":512' in payload_str
        assert '"height": 512' in payload_str or '"height":512' in payload_str

    def test_includes_prompt_text(self):
        """The prompt string appears somewhere in the workflow dict."""
        prompt_text = "1930s art deco robot, noir lighting"
        settings = {"cfg_scale": 7.0, "seed": 42, "sampler": "euler_ancestral"}
        result = build_workflow(prompt_text, settings)
        payload_str = json.dumps(result)
        assert prompt_text in payload_str

    def test_includes_cfg_scale(self):
        """Settings cfg_scale value is present in workflow."""
        settings = {"cfg_scale": 8.5, "seed": 42, "sampler": "euler_ancestral"}
        result = build_workflow("test prompt", settings)
        payload_str = json.dumps(result)
        assert "8.5" in payload_str


# ---------------------------------------------------------------------------
# TestSubmitBatch
# ---------------------------------------------------------------------------

class TestSubmitBatch:
    def test_submits_n_workflows(self):
        """Mock urlopen, submit 3 workflows -> 3 calls, returns 3 results."""
        workflows = [
            build_workflow("prompt A", {"cfg_scale": 7.0, "seed": 1, "sampler": "euler"}),
            build_workflow("prompt B", {"cfg_scale": 7.5, "seed": 2, "sampler": "euler"}),
            build_workflow("prompt C", {"cfg_scale": 8.0, "seed": 3, "sampler": "euler"}),
        ]

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"prompt_id": "abc-123"}
        ).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("generate.urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            results = submit_batch(workflows)
            assert mock_urlopen.call_count == 3
            assert len(results) == 3

    def test_returns_prompt_ids(self):
        """Each result dict has a 'prompt_id' key."""
        workflows = [
            build_workflow("test", {"cfg_scale": 7.0, "seed": 1, "sampler": "euler"}),
        ]

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"prompt_id": "test-id-001"}
        ).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("generate.urllib.request.urlopen", return_value=mock_response):
            results = submit_batch(workflows)
            assert len(results) == 1
            assert results[0]["prompt_id"] == "test-id-001"
            assert results[0]["status"] == "submitted"

    def test_handles_comfyui_offline(self):
        """ConnectionRefusedError -> returns error list, no crash."""
        workflows = [
            build_workflow("test", {"cfg_scale": 7.0, "seed": 1, "sampler": "euler"}),
        ]

        with patch(
            "generate.urllib.request.urlopen",
            side_effect=ConnectionRefusedError("Connection refused"),
        ):
            results = submit_batch(workflows)
            assert len(results) >= 1
            assert results[0]["status"] == "error"
            assert "error" in results[0]


# ---------------------------------------------------------------------------
# TestCollectResults
# ---------------------------------------------------------------------------

class TestCollectResults:
    def test_polls_for_images(self):
        """Mock /history endpoint returning completed -> returns list of Paths."""
        history_data = {
            "prompt-001": {
                "status": {"completed": True},
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "al_aribot_M-C_idle_00001.png", "subfolder": "al", "type": "output"}
                        ]
                    }
                },
            }
        }

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(history_data).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("generate.urllib.request.urlopen", return_value=mock_response):
            results = collect_results(["prompt-001"], timeout=5)
            assert len(results) >= 1
            assert all(isinstance(p, Path) for p in results)

    def test_handles_timeout(self):
        """Mock never returns completed -> returns after timeout with empty/partial."""
        # Return empty history (no completed jobs)
        empty_history = {}

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(empty_history).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("generate.urllib.request.urlopen", return_value=mock_response):
            start = time.time()
            results = collect_results(["prompt-001"], timeout=2)
            elapsed = time.time() - start
            # Should return within reasonable time (timeout + some slack)
            assert elapsed < 10
            assert isinstance(results, list)

    def test_returns_paths(self):
        """All returned items are Path objects."""
        history_data = {
            "prompt-001": {
                "status": {"completed": True},
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "output_00001.png", "subfolder": "al", "type": "output"},
                            {"filename": "output_00002.png", "subfolder": "al", "type": "output"},
                        ]
                    }
                },
            }
        }

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(history_data).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("generate.urllib.request.urlopen", return_value=mock_response):
            results = collect_results(["prompt-001"], timeout=5)
            for item in results:
                assert isinstance(item, Path)
