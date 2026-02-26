"""Tests for frame_scanner — scene detection + CLIP frame labeling."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from frame_scanner import detect_scenes, extract_keyframes, label_frames, scan_frames, DEFAULT_LABELS


# ---------------------------------------------------------------------------
# detect_scenes
# ---------------------------------------------------------------------------

class TestDetectScenes:
    """Tests for detect_scenes function."""

    def test_file_not_found(self, tmp_path):
        result = detect_scenes(str(tmp_path / "nope.mp4"))
        assert result["code"] == "FILE_NOT_FOUND"

    @patch("frame_scanner.detect")
    @patch("frame_scanner.ContentDetector")
    def test_successful_detection(self, mock_cd, mock_detect, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00")

        start1 = MagicMock()
        start1.get_seconds.return_value = 0.0
        end1 = MagicMock()
        end1.get_seconds.return_value = 5.5
        (end1 - start1).get_seconds.return_value = 5.5

        start2 = MagicMock()
        start2.get_seconds.return_value = 5.5
        end2 = MagicMock()
        end2.get_seconds.return_value = 12.0
        (end2 - start2).get_seconds.return_value = 6.5

        mock_detect.return_value = [(start1, end1), (start2, end2)]

        result = detect_scenes(str(video))
        assert result["scene_count"] == 2
        assert result["scenes"][0]["start_sec"] == 0.0
        assert result["scenes"][0]["end_sec"] == 5.5
        assert result["scenes"][1]["start_sec"] == 5.5

    @patch("frame_scanner.detect", side_effect=Exception("codec error"))
    @patch("frame_scanner.ContentDetector")
    def test_detection_error(self, mock_cd, mock_detect, tmp_path):
        video = tmp_path / "bad.mp4"
        video.write_bytes(b"\x00")
        result = detect_scenes(str(video))
        assert result["code"] == "SCENE_ERROR"

    @patch("frame_scanner.detect", return_value=[])
    @patch("frame_scanner.ContentDetector")
    def test_no_scenes(self, mock_cd, mock_detect, tmp_path):
        video = tmp_path / "static.mp4"
        video.write_bytes(b"\x00")
        result = detect_scenes(str(video))
        assert result["scene_count"] == 0
        assert result["scenes"] == []


# ---------------------------------------------------------------------------
# extract_keyframes
# ---------------------------------------------------------------------------

class TestExtractKeyframes:
    """Tests for extract_keyframes function."""

    @patch("frame_scanner.subprocess.run")
    def test_extracts_frames(self, mock_run, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00")
        out_dir = tmp_path / "frames"
        out_dir.mkdir()

        def side_effect(*args, **kwargs):
            # Create the output file to simulate ffmpeg success
            cmd = args[0]
            out_path = Path(cmd[-1])
            out_path.write_bytes(b"\xff\xd8\xff")
            return MagicMock()

        mock_run.side_effect = side_effect

        paths = extract_keyframes(str(video), [0.0, 5.0, 10.0], str(out_dir))
        assert len(paths) == 3
        assert all(Path(p).exists() for p in paths)

    @patch("frame_scanner.subprocess.run", side_effect=FileNotFoundError)
    def test_ffmpeg_missing(self, mock_run, tmp_path):
        paths = extract_keyframes(str(tmp_path / "test.mp4"), [0.0], str(tmp_path))
        assert paths == []


# ---------------------------------------------------------------------------
# label_frames
# ---------------------------------------------------------------------------

class TestLabelFrames:
    """Tests for label_frames function."""

    def test_empty_input(self):
        result = label_frames([])
        assert result == []

    @patch("frame_scanner.CLIPModel")
    @patch("frame_scanner.CLIPProcessor")
    @patch("frame_scanner.Image")
    @patch("frame_scanner.torch")
    def test_labels_frames(self, mock_torch, mock_image, mock_processor, mock_model):
        import torch as real_torch

        mock_torch.cuda.is_available.return_value = False
        mock_torch.no_grad.return_value.__enter__ = MagicMock()
        mock_torch.no_grad.return_value.__exit__ = MagicMock()

        # Mock model
        model_inst = MagicMock()
        mock_model.from_pretrained.return_value = model_inst
        model_inst.to.return_value = model_inst

        # Mock processor — return dict with real tensors
        proc_inst = MagicMock()
        mock_processor.from_pretrained.return_value = proc_inst
        proc_inst.return_value = {
            "input_ids": real_torch.zeros(1, 1),
            "pixel_values": real_torch.zeros(1, 3, 224, 224),
        }

        # Mock model output with real tensor for softmax
        logits = real_torch.tensor([[0.9, 0.1, 0.05, 0.02, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01]])
        outputs = MagicMock()
        outputs.logits_per_image = [logits[0]]
        model_inst.return_value = outputs

        # Mock image
        mock_image.open.return_value.convert.return_value = MagicMock()

        result = label_frames(["fake_frame.jpg"], top_k=3)
        assert len(result) == 1
        assert "labels" in result[0]
        assert len(result[0]["labels"]) == 3

    def test_default_labels(self):
        assert len(DEFAULT_LABELS) >= 10
        assert "person talking to camera" in DEFAULT_LABELS
        assert "b-roll footage" in DEFAULT_LABELS


# ---------------------------------------------------------------------------
# scan_frames (integration)
# ---------------------------------------------------------------------------

class TestScanFrames:
    """Tests for scan_frames orchestrator."""

    def test_file_not_found(self, tmp_path):
        result = scan_frames(str(tmp_path / "nope.mp4"))
        assert result["code"] == "FILE_NOT_FOUND"

    @patch("frame_scanner.label_frames", return_value=[])
    @patch("frame_scanner.extract_keyframes", return_value=[])
    @patch("frame_scanner.detect_scenes")
    def test_pipeline_runs(self, mock_scenes, mock_frames, mock_labels, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00")

        mock_scenes.return_value = {
            "video_path": str(video),
            "scenes": [{"start_sec": 0.0, "end_sec": 5.0, "duration_sec": 5.0}],
            "scene_count": 1,
        }

        result = scan_frames(str(video))
        assert result["scene_count"] == 1
        assert "scenes" in result
        assert "frames" in result

    @patch("frame_scanner.detect_scenes")
    def test_pipeline_error_propagation(self, mock_scenes, tmp_path):
        video = tmp_path / "bad.mp4"
        video.write_bytes(b"\x00")
        mock_scenes.return_value = {"error": "codec error", "code": "SCENE_ERROR"}
        result = scan_frames(str(video))
        assert result["code"] == "SCENE_ERROR"
