"""Shorts pipeline Round 1 tests.

All tests mock external calls (YOLO, MediaPipe, FFmpeg, librosa, scenedetect).
No GPU, no real video, no disk I/O in CI.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

# Ensure tools are importable
_tools_dir = str(Path(__file__).resolve().parent.parent / "agents" / "edbot" / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

_shorts_dir = str(Path(_tools_dir) / "shorts")
if _shorts_dir not in sys.path:
    sys.path.insert(0, _shorts_dir)


# ---------------------------------------------------------------------------
# Helpers: mock tracking data
# ---------------------------------------------------------------------------

def _make_tracking_data(
    num_frames=10, src_w=1920, src_h=1080, fps=30.0,
    person_cx=960, track_id=1,
):
    """Build a minimal tracking_data dict for testing."""
    frames = []
    for i in range(num_frames):
        frames.append({
            "frame_idx": i * 3,
            "timestamp": round(i * 0.1, 3),
            "persons": [
                {"track_id": track_id, "bbox": [person_cx, 540, 200, 400], "confidence": 0.9},
            ],
        })
    return {
        "source": "test.mp4",
        "frame_count": num_frames * 3,
        "fps": fps,
        "resolution": [src_w, src_h],
        "sample_fps": 10.0,
        "sampled_frame_count": num_frames,
        "frames": frames,
        "track_summary": {
            str(track_id): {
                "frame_count": num_frames,
                "first_seen": 0.0,
                "last_seen": round((num_frames - 1) * 0.1, 3),
                "avg_bbox": [person_cx, 540, 200, 400],
            },
        },
        "primary_track_id": track_id,
    }


def _make_tracking_no_persons(num_frames=5):
    """Tracking data with no persons detected."""
    frames = [
        {"frame_idx": i * 3, "timestamp": round(i * 0.1, 3), "persons": []}
        for i in range(num_frames)
    ]
    return {
        "source": "empty.mp4",
        "frame_count": num_frames * 3,
        "fps": 30.0,
        "resolution": [1920, 1080],
        "sample_fps": 10.0,
        "sampled_frame_count": num_frames,
        "frames": frames,
        "track_summary": {},
        "primary_track_id": None,
    }


def _make_transcript_with_words():
    """Transcript with word-level timestamps."""
    return {
        "source": "test.mp4",
        "words": [
            {"word": "Hello", "start": 0.5, "end": 0.8},
            {"word": "world", "start": 0.9, "end": 1.2},
            {"word": "this", "start": 1.3, "end": 1.5},
            {"word": "is", "start": 1.6, "end": 1.7},
            {"word": "a", "start": 1.8, "end": 1.9},
            {"word": "test", "start": 2.0, "end": 2.3},
            {"word": "of", "start": 2.4, "end": 2.5},
            {"word": "captions", "start": 2.6, "end": 3.0},
        ],
    }


def _make_transcript_segments_only():
    """Transcript with segment-level timestamps only (no word-level)."""
    return {
        "chunks": [
            {"text": "Hello world", "start": 0.0, "end": 2.0},
            {"text": "this is a test", "start": 2.0, "end": 4.0},
        ],
    }


# ===========================================================================
# person_tracker tests (6)
# ===========================================================================

class TestPersonTracker:
    """Tests for person_tracker.track_persons."""

    def _make_mock_results(self, track_id=1, conf=0.9, bbox_xywh=(960, 540, 200, 400)):
        """Create mock YOLO tracking result."""
        import torch
        mock_result = MagicMock()
        mock_boxes = MagicMock()
        mock_boxes.conf = torch.tensor([conf])
        mock_boxes.id = torch.tensor([track_id])
        mock_boxes.xywh = torch.tensor([list(bbox_xywh)])
        mock_boxes.__len__ = lambda self: 1
        mock_result.boxes = mock_boxes
        return [mock_result]

    def _make_empty_results(self):
        mock_result = MagicMock()
        mock_result.boxes = MagicMock()
        mock_result.boxes.__len__ = lambda self: 0
        mock_result.boxes.conf = []
        mock_result.boxes.id = None
        return [mock_result]

    @patch("shorts.person_tracker.cv2")
    @patch("shorts.person_tracker.YOLO")
    def test_track_single_person(self, mock_yolo_cls, mock_cv2, tmp_path):
        """One person detected across frames."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {0: 30.0, 7: 30, 3: 1920, 4: 1080}.get(prop, 0)
        mock_cap.read.side_effect = [(True, MagicMock())] * 10 + [(False, None)]
        mock_cv2.VideoCapture.return_value = mock_cap

        mock_model = MagicMock()
        mock_model.track.return_value = self._make_mock_results()
        mock_yolo_cls.return_value = mock_model

        (tmp_path / "test.mp4").touch()

        from shorts.person_tracker import track_persons
        result = track_persons(str(tmp_path / "test.mp4"), output_dir=str(tmp_path))

        assert result["primary_track_id"] == 1
        assert len(result["frames"]) == 10
        assert result["frames"][0]["persons"][0]["track_id"] == 1

    @patch("shorts.person_tracker.cv2")
    @patch("shorts.person_tracker.YOLO")
    def test_track_multiple_persons(self, mock_yolo_cls, mock_cv2, tmp_path):
        """2+ persons, primary = most frames."""
        import torch
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {0: 30.0, 7: 30, 3: 1920, 4: 1080}.get(prop, 0)
        mock_cap.read.side_effect = [(True, MagicMock())] * 10 + [(False, None)]
        mock_cv2.VideoCapture.return_value = mock_cap

        mock_result = MagicMock()
        mock_boxes = MagicMock()
        mock_boxes.conf = torch.tensor([0.9, 0.7])
        mock_boxes.id = torch.tensor([1, 2])
        mock_boxes.xywh = torch.tensor([[960, 540, 200, 400], [1400, 540, 180, 380]])
        mock_boxes.__len__ = lambda self: 2
        mock_result.boxes = mock_boxes

        mock_model = MagicMock()
        mock_model.track.return_value = [mock_result]
        mock_yolo_cls.return_value = mock_model

        (tmp_path / "test.mp4").touch()

        from shorts.person_tracker import track_persons
        result = track_persons(str(tmp_path / "test.mp4"), output_dir=str(tmp_path))

        assert "1" in result["track_summary"]
        assert "2" in result["track_summary"]
        assert result["primary_track_id"] in (1, 2)

    @patch("shorts.person_tracker.cv2")
    @patch("shorts.person_tracker.YOLO")
    def test_track_no_persons(self, mock_yolo_cls, mock_cv2, tmp_path):
        """Empty video -> null primary_track_id."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {0: 30.0, 7: 15, 3: 1920, 4: 1080}.get(prop, 0)
        mock_cap.read.side_effect = [(True, MagicMock())] * 5 + [(False, None)]
        mock_cv2.VideoCapture.return_value = mock_cap

        mock_model = MagicMock()
        mock_model.track.return_value = self._make_empty_results()
        mock_yolo_cls.return_value = mock_model

        (tmp_path / "test.mp4").touch()

        from shorts.person_tracker import track_persons
        result = track_persons(str(tmp_path / "test.mp4"), output_dir=str(tmp_path))

        assert result["primary_track_id"] is None
        assert result["track_summary"] == {}

    @patch("shorts.person_tracker.cv2")
    @patch("shorts.person_tracker.YOLO")
    def test_track_sample_fps(self, mock_yolo_cls, mock_cv2, tmp_path):
        """sample_fps reduces frame count processed."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {0: 30.0, 7: 90, 3: 1920, 4: 1080}.get(prop, 0)
        mock_cap.read.side_effect = [(True, MagicMock())] * 30 + [(False, None)]
        mock_cv2.VideoCapture.return_value = mock_cap

        mock_model = MagicMock()
        mock_model.track.return_value = self._make_mock_results()
        mock_yolo_cls.return_value = mock_model

        (tmp_path / "test.mp4").touch()

        from shorts.person_tracker import track_persons
        result = track_persons(str(tmp_path / "test.mp4"), output_dir=str(tmp_path), sample_fps=10.0)

        assert result["sampled_frame_count"] == 10

    @patch("shorts.person_tracker.cv2")
    @patch("shorts.person_tracker.YOLO")
    def test_track_summary_computed(self, mock_yolo_cls, mock_cv2, tmp_path):
        """track_summary has correct fields per track."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {0: 30.0, 7: 15, 3: 1920, 4: 1080}.get(prop, 0)
        mock_cap.read.side_effect = [(True, MagicMock())] * 5 + [(False, None)]
        mock_cv2.VideoCapture.return_value = mock_cap

        mock_model = MagicMock()
        mock_model.track.return_value = self._make_mock_results()
        mock_yolo_cls.return_value = mock_model

        (tmp_path / "test.mp4").touch()

        from shorts.person_tracker import track_persons
        result = track_persons(str(tmp_path / "test.mp4"), output_dir=str(tmp_path))

        summary = result["track_summary"]["1"]
        assert "frame_count" in summary
        assert "first_seen" in summary
        assert "last_seen" in summary
        assert "avg_bbox" in summary
        assert len(summary["avg_bbox"]) == 4

    @patch("shorts.person_tracker.cv2")
    @patch("shorts.person_tracker.YOLO")
    def test_track_output_schema(self, mock_yolo_cls, mock_cv2, tmp_path):
        """All required top-level fields present."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {0: 30.0, 7: 15, 3: 1920, 4: 1080}.get(prop, 0)
        mock_cap.read.side_effect = [(True, MagicMock())] * 5 + [(False, None)]
        mock_cv2.VideoCapture.return_value = mock_cap

        mock_model = MagicMock()
        mock_model.track.return_value = self._make_mock_results()
        mock_yolo_cls.return_value = mock_model

        (tmp_path / "test.mp4").touch()

        from shorts.person_tracker import track_persons
        result = track_persons(str(tmp_path / "test.mp4"), output_dir=str(tmp_path))

        required = {"source", "frame_count", "fps", "resolution", "sample_fps",
                     "sampled_frame_count", "frames", "track_summary", "primary_track_id"}
        assert required.issubset(set(result.keys()))


# ===========================================================================
# smart_crop tests (7)
# ===========================================================================

class TestSmartCrop:
    """Tests for smart_crop.generate_crop_keyframes."""

    def test_crop_portrait_dimensions(self):
        """1920x1080 -> crop 608x1080 for 9:16."""
        from shorts.smart_crop import generate_crop_keyframes
        data = _make_tracking_data()
        result = generate_crop_keyframes(data, target_aspect="9:16")

        assert result["crop_height"] == 1080
        # 1080 * 9 / 16 = 607.5 -> int(607.5) = 607, round to even = 606
        assert result["crop_width"] == 606

    def test_crop_square_dimensions(self):
        """1920x1080 -> crop 1080x1080 for 1:1."""
        from shorts.smart_crop import generate_crop_keyframes
        data = _make_tracking_data()
        result = generate_crop_keyframes(data, target_aspect="1:1")

        assert result["crop_width"] == 1080
        assert result["crop_height"] == 1080

    def test_crop_y_always_zero(self):
        """crop_y is 0 for every keyframe (X-axis only)."""
        from shorts.smart_crop import generate_crop_keyframes
        data = _make_tracking_data()
        result = generate_crop_keyframes(data, target_aspect="9:16")

        for kf in result["keyframes"]:
            assert kf["crop_y"] == 0

    def test_crop_smoothing_reduces_jitter(self):
        """Smoothed output has lower variance than raw jittery input."""
        from shorts.smart_crop import generate_crop_keyframes

        # Create tracking with alternating positions (jitter)
        data = _make_tracking_data(num_frames=20)
        for i, frame in enumerate(data["frames"]):
            cx = 800 if i % 2 == 0 else 1100
            frame["persons"][0]["bbox"][0] = cx

        result = generate_crop_keyframes(data, target_aspect="9:16", smoothing_window=2.0)

        xs = [kf["crop_x"] for kf in result["keyframes"]]
        # Smoothed values should have less variance than the raw alternating pattern
        variance = sum((x - sum(xs) / len(xs)) ** 2 for x in xs) / len(xs)
        assert variance < 50000  # smoothed should be much lower than raw alternation

    def test_crop_speed_clamp(self):
        """Consecutive crop_x diff never exceeds max_pan_speed limit."""
        from shorts.smart_crop import generate_crop_keyframes

        # Create tracking with big jump
        data = _make_tracking_data(num_frames=10)
        data["frames"][5]["persons"][0]["bbox"][0] = 1800  # big jump

        result = generate_crop_keyframes(
            data, target_aspect="9:16", max_pan_speed=0.05, smoothing_window=0.0,
        )

        keyframes = result["keyframes"]
        max_allowed = 0.05 * 1920 / 30.0 * 3  # per sample interval
        for i in range(1, len(keyframes)):
            delta = abs(keyframes[i]["crop_x"] - keyframes[i - 1]["crop_x"])
            assert delta <= max_allowed + 2  # +2 for rounding

    def test_crop_dead_zone(self):
        """Centered subject -> crop_x stays constant."""
        from shorts.smart_crop import generate_crop_keyframes

        # Person centered at 960 (center of 1920)
        data = _make_tracking_data(num_frames=10, person_cx=960)
        result = generate_crop_keyframes(data, target_aspect="9:16", dead_zone=0.15)

        xs = [kf["crop_x"] for kf in result["keyframes"]]
        # All crop_x values should be identical (person in dead zone)
        assert len(set(xs)) == 1

    def test_crop_no_tracking_data(self):
        """Null primary -> static center crop."""
        from shorts.smart_crop import generate_crop_keyframes
        data = _make_tracking_no_persons()
        result = generate_crop_keyframes(data, target_aspect="9:16")

        center_x = (1920 - result["crop_width"]) // 2
        for kf in result["keyframes"]:
            assert kf["crop_x"] == center_x


# ===========================================================================
# face_zoom tests (5)
# ===========================================================================

class TestFaceZoom:
    """Tests for face_zoom.detect_face_zoom_points."""

    def _mock_face_landmarks(self, cx=0.5, cy=0.4, mar_open=True):
        """Create mock MediaPipe face landmarks with a large-enough face."""
        lms = [MagicMock() for _ in range(469)]
        # Spread landmarks to create ~30% face coverage
        for i, lm in enumerate(lms):
            lm.x = cx + (i % 20 - 10) * 0.015
            lm.y = cy + (i % 20 - 10) * 0.015

        # Lip landmarks for MAR
        lms[13].y = cy - (0.03 if mar_open else 0.005)  # upper lip
        lms[14].y = cy + (0.03 if mar_open else 0.005)  # lower lip
        lms[78].x = cx - 0.05  # left mouth
        lms[308].x = cx + 0.05  # right mouth

        return lms

    @patch("shorts.face_zoom.cv2")
    def test_face_detected_zoom_candidates(self, mock_cv2, tmp_path):
        """Face mesh -> zoom candidates generated."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {0: 30.0, 7: 300, 3: 1920, 4: 1080}.get(prop, 0)

        # 30 frames of speaking face (6 seconds at sample_fps=5)
        mock_cap.read.side_effect = [(True, MagicMock())] * 30 + [(False, None)]
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.cvtColor.return_value = MagicMock()
        mock_cv2.COLOR_BGR2RGB = 4
        mock_cv2.CAP_PROP_FPS = 0
        mock_cv2.CAP_PROP_FRAME_COUNT = 7
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

        mock_landmarks = self._mock_face_landmarks(mar_open=True)
        mock_face_result = MagicMock()
        mock_face_result.landmark = mock_landmarks

        with patch("shorts.face_zoom.mp") as mock_mp:
            mock_mesh = MagicMock()
            mock_mesh_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.multi_face_landmarks = [mock_face_result]
            mock_mesh_instance.process.return_value = mock_result
            mock_mp.solutions.face_mesh.FaceMesh.return_value = mock_mesh_instance

            (tmp_path / "test.mp4").touch()

            from shorts.face_zoom import detect_face_zoom_points
            result = detect_face_zoom_points(
                str(tmp_path / "test.mp4"), output_dir=str(tmp_path),
                sample_fps=5.0, min_zoom_duration=0.5,
            )

        assert len(result["zoom_candidates"]) >= 1
        assert result["zoom_candidates"][0]["is_speaking"] is True

    @patch("shorts.face_zoom.cv2")
    def test_face_speaking_filter(self, mock_cv2, tmp_path):
        """Non-speaking frames excluded by MAR."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {0: 30.0, 7: 150, 3: 1920, 4: 1080}.get(prop, 0)
        mock_cap.read.side_effect = [(True, MagicMock())] * 25 + [(False, None)]
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.cvtColor.return_value = MagicMock()
        mock_cv2.COLOR_BGR2RGB = 4
        mock_cv2.CAP_PROP_FPS = 0
        mock_cv2.CAP_PROP_FRAME_COUNT = 7
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

        # Closed mouth (not speaking)
        mock_landmarks = self._mock_face_landmarks(mar_open=False)
        mock_face_result = MagicMock()
        mock_face_result.landmark = mock_landmarks

        with patch("shorts.face_zoom.mp") as mock_mp:
            mock_mesh_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.multi_face_landmarks = [mock_face_result]
            mock_mesh_instance.process.return_value = mock_result
            mock_mp.solutions.face_mesh.FaceMesh.return_value = mock_mesh_instance

            (tmp_path / "test.mp4").touch()

            from shorts.face_zoom import detect_face_zoom_points
            result = detect_face_zoom_points(
                str(tmp_path / "test.mp4"), output_dir=str(tmp_path),
                min_zoom_duration=0.5,
            )

        # Non-speaking -> no zoom candidates
        assert len(result["zoom_candidates"]) == 0

    @patch("shorts.face_zoom.cv2")
    def test_face_no_detection(self, mock_cv2, tmp_path):
        """No face -> empty candidates list."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {0: 30.0, 7: 60, 3: 1920, 4: 1080}.get(prop, 0)
        mock_cap.read.side_effect = [(True, MagicMock())] * 10 + [(False, None)]
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.cvtColor.return_value = MagicMock()
        mock_cv2.COLOR_BGR2RGB = 4
        mock_cv2.CAP_PROP_FPS = 0
        mock_cv2.CAP_PROP_FRAME_COUNT = 7
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

        with patch("shorts.face_zoom.mp") as mock_mp:
            mock_mesh_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.multi_face_landmarks = None
            mock_mesh_instance.process.return_value = mock_result
            mock_mp.solutions.face_mesh.FaceMesh.return_value = mock_mesh_instance

            (tmp_path / "test.mp4").touch()

            from shorts.face_zoom import detect_face_zoom_points
            result = detect_face_zoom_points(
                str(tmp_path / "test.mp4"), output_dir=str(tmp_path),
            )

        assert result["zoom_candidates"] == []
        assert result["zoom_ratio"] == 0

    @patch("shorts.face_zoom.cv2")
    def test_face_zoom_clamped(self, mock_cv2, tmp_path):
        """Zoom crop never exceeds frame bounds."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {0: 30.0, 7: 300, 3: 1920, 4: 1080}.get(prop, 0)
        mock_cap.read.side_effect = [(True, MagicMock())] * 30 + [(False, None)]
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.cvtColor.return_value = MagicMock()
        mock_cv2.COLOR_BGR2RGB = 4
        mock_cv2.CAP_PROP_FPS = 0
        mock_cv2.CAP_PROP_FRAME_COUNT = 7
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

        # Face at extreme corner
        mock_landmarks = self._mock_face_landmarks(cx=0.95, cy=0.95, mar_open=True)
        mock_face_result = MagicMock()
        mock_face_result.landmark = mock_landmarks

        with patch("shorts.face_zoom.mp") as mock_mp:
            mock_mesh_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.multi_face_landmarks = [mock_face_result]
            mock_mesh_instance.process.return_value = mock_result
            mock_mp.solutions.face_mesh.FaceMesh.return_value = mock_mesh_instance

            (tmp_path / "test.mp4").touch()

            from shorts.face_zoom import detect_face_zoom_points
            result = detect_face_zoom_points(
                str(tmp_path / "test.mp4"), output_dir=str(tmp_path),
                min_zoom_duration=0.5,
            )

        for candidate in result["zoom_candidates"]:
            crop = candidate["zoom_crop"]
            assert crop["x"] >= 0
            assert crop["y"] >= 0
            assert crop["x"] + crop["w"] <= 1920
            assert crop["y"] + crop["h"] <= 1080

    @patch("shorts.face_zoom.cv2")
    def test_face_min_duration_filter(self, mock_cv2, tmp_path):
        """Zoom < min_zoom_duration filtered out."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {0: 30.0, 7: 60, 3: 1920, 4: 1080}.get(prop, 0)
        # Only 2 frames of face (< 2s min_zoom_duration)
        mock_cap.read.side_effect = [(True, MagicMock())] * 3 + [(False, None)]
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.cvtColor.return_value = MagicMock()
        mock_cv2.COLOR_BGR2RGB = 4
        mock_cv2.CAP_PROP_FPS = 0
        mock_cv2.CAP_PROP_FRAME_COUNT = 7
        mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        mock_cv2.CAP_PROP_FRAME_HEIGHT = 4

        mock_landmarks = self._mock_face_landmarks(mar_open=True)
        mock_face_result = MagicMock()
        mock_face_result.landmark = mock_landmarks

        with patch("shorts.face_zoom.mp") as mock_mp:
            mock_mesh_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.multi_face_landmarks = [mock_face_result]
            mock_mesh_instance.process.return_value = mock_result
            mock_mp.solutions.face_mesh.FaceMesh.return_value = mock_mesh_instance

            (tmp_path / "test.mp4").touch()

            from shorts.face_zoom import detect_face_zoom_points
            result = detect_face_zoom_points(
                str(tmp_path / "test.mp4"), output_dir=str(tmp_path),
                min_zoom_duration=2.0,
            )

        assert len(result["zoom_candidates"]) == 0


# ===========================================================================
# animated_captions tests (5)
# ===========================================================================

class TestAnimatedCaptions:
    """Tests for animated_captions.generate_animated_captions."""

    def test_captions_word_level(self, tmp_path):
        """Word timestamps -> one ASS event per word."""
        from shorts.animated_captions import generate_animated_captions
        transcript = _make_transcript_with_words()
        out = str(tmp_path / "captions.ass")
        result = generate_animated_captions(transcript, output_path=out)

        assert result["word_count"] == 8
        assert Path(out).exists()

    def test_captions_grouping(self, tmp_path):
        """Words grouped by words_per_group."""
        from shorts.animated_captions import generate_animated_captions
        transcript = _make_transcript_with_words()
        out = str(tmp_path / "captions.ass")
        result = generate_animated_captions(transcript, output_path=out, words_per_group=4)

        # 8 words / 4 per group = 2 groups
        assert result["group_count"] == 2

    def test_captions_highlight_style(self, tmp_path):
        """Current word has different ASS style tags."""
        from shorts.animated_captions import generate_animated_captions
        transcript = _make_transcript_with_words()
        out = str(tmp_path / "captions.ass")
        generate_animated_captions(transcript, output_path=out, style="highlight_word")

        content = Path(out).read_text(encoding="utf-8")
        # Should contain highlight color tag
        assert "\\c&H00FFFF&" in content

    def test_captions_segment_fallback(self, tmp_path):
        """No word timestamps -> segment-level subs."""
        from shorts.animated_captions import generate_animated_captions
        transcript = _make_transcript_segments_only()
        out = str(tmp_path / "captions.ass")
        result = generate_animated_captions(transcript, output_path=out)

        assert result["word_count"] == 2  # 2 segments
        content = Path(out).read_text(encoding="utf-8")
        assert "Hello world" in content

    def test_captions_valid_ass(self, tmp_path):
        """Output file starts with [Script Info] section."""
        from shorts.animated_captions import generate_animated_captions
        transcript = _make_transcript_with_words()
        out = str(tmp_path / "captions.ass")
        generate_animated_captions(transcript, output_path=out)

        content = Path(out).read_text(encoding="utf-8")
        assert content.startswith("[Script Info]")
        assert "[V4+ Styles]" in content
        assert "[Events]" in content


# ===========================================================================
# emphasis_zoom tests (4)
# ===========================================================================

class TestEmphasisZoom:
    """Tests for emphasis_zoom.detect_emphasis_points."""

    @patch("shorts.emphasis_zoom.subprocess.run")
    def test_emphasis_peaks_detected(self, mock_run, tmp_path):
        """Peaks above threshold returned."""
        import numpy as np
        mock_run.return_value = MagicMock(returncode=0)

        # Create fake audio with peaks
        audio = np.random.randn(16000 * 10).astype(np.float32) * 0.1
        audio[16000 * 3:16000 * 3 + 500] = 0.9  # peak at 3s
        audio[16000 * 7:16000 * 7 + 500] = 0.8  # peak at 7s

        wav_path = tmp_path / "test_audio.wav"
        (tmp_path / "test.mp4").touch()

        with patch("shorts.emphasis_zoom.librosa") as mock_librosa:
            mock_librosa.load.return_value = (audio, 16000)
            rms = np.array([np.sqrt(np.mean(audio[i:i + 512] ** 2))
                           for i in range(0, len(audio) - 512, 512)])
            mock_librosa.feature.rms.return_value = np.array([rms])

            from shorts.emphasis_zoom import detect_emphasis_points
            result = detect_emphasis_points(
                str(tmp_path / "test.mp4"), output_dir=str(tmp_path),
            )

        assert result["emphasis_count"] > 0
        for kf in result["keyframes"]:
            assert "timestamp" in kf
            assert "zoom_factor" in kf

    @patch("shorts.emphasis_zoom.subprocess.run")
    def test_emphasis_gap_filter(self, mock_run, tmp_path):
        """Peaks closer than min_gap filtered."""
        import numpy as np
        mock_run.return_value = MagicMock(returncode=0)

        audio = np.random.randn(16000 * 10).astype(np.float32) * 0.1
        # Two peaks very close together
        audio[16000 * 3:16000 * 3 + 500] = 0.9
        audio[16000 * 4:16000 * 4 + 500] = 0.85

        (tmp_path / "test.mp4").touch()

        with patch("shorts.emphasis_zoom.librosa") as mock_librosa:
            mock_librosa.load.return_value = (audio, 16000)
            rms = np.array([np.sqrt(np.mean(audio[i:i + 512] ** 2))
                           for i in range(0, len(audio) - 512, 512)])
            mock_librosa.feature.rms.return_value = np.array([rms])

            from shorts.emphasis_zoom import detect_emphasis_points
            result = detect_emphasis_points(
                str(tmp_path / "test.mp4"), output_dir=str(tmp_path),
                min_gap_seconds=3.0,
            )

        # With 3s min gap, close peaks should be filtered
        timestamps = [kf["timestamp"] for kf in result["keyframes"]]
        for i in range(1, len(timestamps)):
            assert timestamps[i] - timestamps[i - 1] >= 2.5  # allow rounding

    @patch("shorts.emphasis_zoom.subprocess.run")
    def test_emphasis_quiet_video(self, mock_run, tmp_path):
        """Flat audio -> 0 keyframes."""
        import numpy as np
        mock_run.return_value = MagicMock(returncode=0)

        audio = np.zeros(16000 * 5, dtype=np.float32)
        (tmp_path / "test.mp4").touch()

        with patch("shorts.emphasis_zoom.librosa") as mock_librosa:
            mock_librosa.load.return_value = (audio, 16000)
            rms = np.zeros(100)
            mock_librosa.feature.rms.return_value = np.array([rms])

            from shorts.emphasis_zoom import detect_emphasis_points
            result = detect_emphasis_points(
                str(tmp_path / "test.mp4"), output_dir=str(tmp_path),
            )

        assert result["emphasis_count"] == 0
        assert result["keyframes"] == []

    @patch("shorts.emphasis_zoom.subprocess.run")
    def test_emphasis_zoom_proportional(self, mock_run, tmp_path):
        """Higher energy -> higher zoom_factor."""
        import numpy as np
        mock_run.return_value = MagicMock(returncode=0)

        audio = np.random.randn(16000 * 20).astype(np.float32) * 0.1
        audio[16000 * 3:16000 * 3 + 500] = 0.5
        audio[16000 * 10:16000 * 10 + 500] = 1.0  # louder

        (tmp_path / "test.mp4").touch()

        with patch("shorts.emphasis_zoom.librosa") as mock_librosa:
            mock_librosa.load.return_value = (audio, 16000)
            rms = np.array([np.sqrt(np.mean(audio[i:i + 512] ** 2))
                           for i in range(0, len(audio) - 512, 512)])
            mock_librosa.feature.rms.return_value = np.array([rms])

            from shorts.emphasis_zoom import detect_emphasis_points
            result = detect_emphasis_points(
                str(tmp_path / "test.mp4"), output_dir=str(tmp_path),
                min_gap_seconds=3.0,
            )

        if len(result["keyframes"]) >= 2:
            # The louder peak should have higher zoom_factor
            kfs = sorted(result["keyframes"], key=lambda k: k["energy_level"])
            assert kfs[-1]["zoom_factor"] >= kfs[0]["zoom_factor"]


# ===========================================================================
# retention_pacer tests (4)
# ===========================================================================

class TestRetentionPacer:
    """Tests for retention_pacer.analyze_pacing."""

    def _mock_scenedetect(self, scene_times):
        """Create mock scenedetect objects."""
        mock_video = MagicMock()
        mock_video.frame_rate = 30.0
        mock_video.duration.get_frames.return_value = 1800  # 60s at 30fps

        scenes = []
        for start, end in scene_times:
            mock_start = MagicMock()
            mock_start.get_seconds.return_value = start
            mock_end = MagicMock()
            mock_end.get_seconds.return_value = end
            scenes.append((mock_start, mock_end))

        return mock_video, scenes

    @patch("shorts.retention_pacer.open_video")
    @patch("shorts.retention_pacer.SceneManager")
    def test_pacing_long_stretches(self, mock_sm_cls, mock_open, tmp_path):
        """Gaps > target identified."""
        mock_video, scenes = self._mock_scenedetect([(0, 30), (30, 60)])

        mock_open.return_value = mock_video
        mock_sm = MagicMock()
        mock_sm.get_scene_list.return_value = scenes
        mock_sm_cls.return_value = mock_sm

        (tmp_path / "test.mp4").touch()

        from shorts.retention_pacer import analyze_pacing
        result = analyze_pacing(
            str(tmp_path / "test.mp4"), output_dir=str(tmp_path),
            target_cut_interval=(2.0, 4.0),
        )

        assert result["duration"] == 60.0
        assert len(result["suggested_cuts"]) > 0

    @patch("shorts.retention_pacer.open_video")
    @patch("shorts.retention_pacer.SceneManager")
    def test_pacing_suggestions_generated(self, mock_sm_cls, mock_open, tmp_path):
        """Suggestions have timestamp + type + reason."""
        mock_video, scenes = self._mock_scenedetect([(0, 20), (20, 60)])

        mock_open.return_value = mock_video
        mock_sm = MagicMock()
        mock_sm.get_scene_list.return_value = scenes
        mock_sm_cls.return_value = mock_sm

        (tmp_path / "test.mp4").touch()

        from shorts.retention_pacer import analyze_pacing
        result = analyze_pacing(str(tmp_path / "test.mp4"), output_dir=str(tmp_path))

        for sug in result["suggested_cuts"]:
            assert "timestamp" in sug
            assert "type" in sug
            assert "reason" in sug

    @patch("shorts.retention_pacer.open_video")
    @patch("shorts.retention_pacer.SceneManager")
    def test_pacing_good_video(self, mock_sm_cls, mock_open, tmp_path):
        """Short cut intervals -> high score, few suggestions."""
        # Cuts every 3 seconds (within target)
        scene_times = [(i * 3, (i + 1) * 3) for i in range(20)]
        mock_video, scenes = self._mock_scenedetect(scene_times)

        mock_open.return_value = mock_video
        mock_sm = MagicMock()
        mock_sm.get_scene_list.return_value = scenes
        mock_sm_cls.return_value = mock_sm

        (tmp_path / "test.mp4").touch()

        from shorts.retention_pacer import analyze_pacing
        result = analyze_pacing(str(tmp_path / "test.mp4"), output_dir=str(tmp_path))

        assert result["retention_score"] >= 0.7
        assert len(result["suggested_cuts"]) == 0  # already well-paced

    @patch("shorts.retention_pacer.open_video")
    @patch("shorts.retention_pacer.SceneManager")
    def test_pacing_score_range(self, mock_sm_cls, mock_open, tmp_path):
        """retention_score always 0.0-1.0."""
        mock_video, scenes = self._mock_scenedetect([(0, 60)])

        mock_open.return_value = mock_video
        mock_sm = MagicMock()
        mock_sm.get_scene_list.return_value = scenes
        mock_sm_cls.return_value = mock_sm

        (tmp_path / "test.mp4").touch()

        from shorts.retention_pacer import analyze_pacing
        result = analyze_pacing(str(tmp_path / "test.mp4"), output_dir=str(tmp_path))

        assert 0.0 <= result["retention_score"] <= 1.0


# ===========================================================================
# shorts_assembler tests (5)
# ===========================================================================

class TestShortsAssembler:
    """Tests for shorts_assembler.assemble_short."""

    @patch("shorts.shorts_assembler.subprocess.run")
    @patch("shorts.shorts_assembler.retention_pacer.analyze_pacing")
    @patch("shorts.shorts_assembler.emphasis_zoom.detect_emphasis_points")
    @patch("shorts.shorts_assembler.face_zoom.detect_face_zoom_points")
    @patch("shorts.shorts_assembler.smart_crop.generate_crop_keyframes")
    @patch("shorts.shorts_assembler.person_tracker.track_persons")
    def test_assemble_full_pipeline(self, mock_track, mock_crop, mock_fz, mock_ez, mock_rp, mock_ffmpeg, tmp_path):
        """All steps called (mocked), manifest written."""
        (tmp_path / "test.mp4").touch()

        mock_track.return_value = _make_tracking_data()
        mock_crop.return_value = {
            "crop_width": 608, "crop_height": 1080,
            "source_resolution": [1920, 1080],
            "keyframes": [{"timestamp": 0.0, "crop_x": 656, "crop_y": 0}],
        }
        mock_fz.return_value = {"zoom_candidates": []}
        mock_ez.return_value = {"keyframes": []}
        mock_rp.return_value = {"retention_score": 0.8}
        mock_ffmpeg.return_value = MagicMock(returncode=0)

        from shorts.shorts_assembler import assemble_short
        result = assemble_short(
            str(tmp_path / "test.mp4"), output_dir=str(tmp_path / "out"),
        )

        assert result["source"] == str(tmp_path / "test.mp4")
        assert result["target_aspect"] == "9:16"
        assert "pipeline_steps" in result
        mock_track.assert_called_once()
        mock_crop.assert_called_once()

    @patch("shorts.shorts_assembler.subprocess.run")
    @patch("shorts.shorts_assembler.retention_pacer.analyze_pacing")
    @patch("shorts.shorts_assembler.emphasis_zoom.detect_emphasis_points")
    @patch("shorts.shorts_assembler.smart_crop.generate_crop_keyframes")
    @patch("shorts.shorts_assembler.person_tracker.track_persons")
    def test_assemble_face_zoom_disabled(self, mock_track, mock_crop, mock_ez, mock_rp, mock_ffmpeg, tmp_path):
        """enable_face_zoom=False -> step skipped."""
        (tmp_path / "test.mp4").touch()

        mock_track.return_value = _make_tracking_data()
        mock_crop.return_value = {
            "crop_width": 608, "crop_height": 1080,
            "source_resolution": [1920, 1080],
            "keyframes": [{"timestamp": 0.0, "crop_x": 656, "crop_y": 0}],
        }
        mock_ez.return_value = {"keyframes": []}
        mock_rp.return_value = {"retention_score": 0.8}
        mock_ffmpeg.return_value = MagicMock(returncode=0)

        from shorts.shorts_assembler import assemble_short
        result = assemble_short(
            str(tmp_path / "test.mp4"),
            output_dir=str(tmp_path / "out"),
            enable_face_zoom=False,
        )

        assert result["pipeline_steps"]["face_zoom"] is None
        assert result["settings"]["face_zoom_enabled"] is False

    def test_assemble_batch(self, tmp_path):
        """Processes list of videos."""
        in_dir = tmp_path / "input"
        in_dir.mkdir()
        (in_dir / "a.mp4").touch()
        (in_dir / "b.mp4").touch()

        with patch("shorts.shorts_assembler.assemble_short") as mock_assemble:
            mock_assemble.return_value = {"source": "test", "output": "out.mp4"}

            from shorts.shorts_assembler import batch_assemble_shorts
            result = batch_assemble_shorts(str(in_dir), output_dir=str(tmp_path / "out"))

        assert result["total"] == 2
        assert mock_assemble.call_count == 2

    @patch("shorts.shorts_assembler.subprocess.run")
    @patch("shorts.shorts_assembler.retention_pacer.analyze_pacing")
    @patch("shorts.shorts_assembler.emphasis_zoom.detect_emphasis_points")
    @patch("shorts.shorts_assembler.face_zoom.detect_face_zoom_points")
    @patch("shorts.shorts_assembler.smart_crop.generate_crop_keyframes")
    @patch("shorts.shorts_assembler.person_tracker.track_persons")
    def test_assemble_manifest_has_all_paths(self, mock_track, mock_crop, mock_fz, mock_ez, mock_rp, mock_ffmpeg, tmp_path):
        """All pipeline_steps paths present."""
        (tmp_path / "test.mp4").touch()

        mock_track.return_value = _make_tracking_data()
        mock_crop.return_value = {
            "crop_width": 608, "crop_height": 1080,
            "source_resolution": [1920, 1080],
            "keyframes": [{"timestamp": 0.0, "crop_x": 656, "crop_y": 0}],
        }
        mock_fz.return_value = {"zoom_candidates": []}
        mock_ez.return_value = {"keyframes": []}
        mock_rp.return_value = {"retention_score": 0.8}
        mock_ffmpeg.return_value = MagicMock(returncode=0)

        from shorts.shorts_assembler import assemble_short
        result = assemble_short(
            str(tmp_path / "test.mp4"), output_dir=str(tmp_path / "out"),
        )

        steps = result["pipeline_steps"]
        expected_keys = {"transcribe", "silence", "tracking", "crop",
                         "face_zoom", "emphasis", "pacing", "captions"}
        assert expected_keys == set(steps.keys())

    @patch("shorts.shorts_assembler.subprocess.run")
    @patch("shorts.shorts_assembler.retention_pacer.analyze_pacing")
    @patch("shorts.shorts_assembler.emphasis_zoom.detect_emphasis_points")
    @patch("shorts.shorts_assembler.face_zoom.detect_face_zoom_points")
    @patch("shorts.shorts_assembler.smart_crop.generate_crop_keyframes")
    @patch("shorts.shorts_assembler.person_tracker.track_persons")
    def test_assemble_max_duration(self, mock_track, mock_crop, mock_fz, mock_ez, mock_rp, mock_ffmpeg, tmp_path):
        """Output duration capped at max_duration."""
        (tmp_path / "test.mp4").touch()

        mock_track.return_value = _make_tracking_data()
        mock_crop.return_value = {
            "crop_width": 608, "crop_height": 1080,
            "source_resolution": [1920, 1080],
            "keyframes": [{"timestamp": 0.0, "crop_x": 656, "crop_y": 0}],
        }
        mock_fz.return_value = {"zoom_candidates": []}
        mock_ez.return_value = {"keyframes": []}
        mock_rp.return_value = {"retention_score": 0.8}
        mock_ffmpeg.return_value = MagicMock(returncode=0)

        from shorts.shorts_assembler import assemble_short
        result = assemble_short(
            str(tmp_path / "test.mp4"),
            output_dir=str(tmp_path / "out"),
            max_duration=30.0,
        )

        assert result["settings"]["max_duration"] == 30.0


# ===========================================================================
# NLP + executor tests (3)
# ===========================================================================

class TestNLPAndExecutor:
    """Tests for NLP pattern matching and executor dispatch."""

    def test_nlp_make_tiktok(self):
        """'convert to tiktok' -> assemble_short action."""
        from nlp_action import parse_command
        result = parse_command("convert to tiktok")
        assert result["action"] == "assemble_short"
        assert result["params"]["aspect"] == "9:16"

    def test_nlp_smart_crop(self):
        """'smart crop this' -> smart_crop action."""
        from nlp_action import parse_command
        result = parse_command("smart crop this video")
        assert result["action"] == "smart_crop"

    def test_executor_dispatches_assemble(self):
        """Action dict routes to assembler."""
        from executor import execute_action
        action = {
            "action": "assemble_short",
            "params": {"input": "C:/AT01/input/test.mp4", "target_aspect": "9:16"},
            "executor": "ffmpeg",
        }
        with patch("executor._execute_assemble_short") as mock_fn:
            mock_fn.return_value = {
                "status": "success", "action": "assemble_short",
                "input": "test.mp4", "output": "out.mp4",
                "duration_in": None, "duration_out": None,
                "ffmpeg_cmd": None, "elapsed_seconds": 1.0, "error": None,
            }
            result = execute_action(action)
        assert result["status"] == "success"
        assert result["action"] == "assemble_short"


# ===========================================================================
# Server endpoint tests (3)
# ===========================================================================

class TestServerEndpoints:
    """Tests for /api/shorts/* endpoints."""

    def test_api_shorts_assemble(self):
        """POST /api/shorts/assemble returns manifest."""
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot"))
        from fastapi.testclient import TestClient
        from server import app

        with patch("server.Path.exists", return_value=True), \
             patch("shorts.shorts_assembler.assemble_short") as mock_assemble:
            mock_assemble.return_value = {
                "source": "test.mp4", "output": "out.mp4",
                "target_aspect": "9:16", "pipeline_steps": {},
            }
            client = TestClient(app)
            resp = client.post("/api/shorts/assemble", json={
                "video_path": "C:/AT01/input/test.mp4",
                "target_aspect": "9:16",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "source" in data

    def test_api_shorts_batch(self):
        """POST /api/shorts/batch returns batch manifest."""
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot"))
        from fastapi.testclient import TestClient
        from server import app

        with patch("server.Path.exists", return_value=True), \
             patch("shorts.shorts_assembler.batch_assemble_shorts") as mock_batch:
            mock_batch.return_value = {
                "total": 2, "success": 2, "failed": 0, "results": [],
            }
            client = TestClient(app)
            resp = client.post("/api/shorts/batch", json={
                "input_dir": "C:/AT01/input",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 2

    def test_api_shorts_captions(self):
        """POST /api/shorts/captions returns caption manifest."""
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents" / "edbot"))
        from fastapi.testclient import TestClient
        from server import app

        with patch("server.Path.exists", return_value=True), \
             patch("server.Path.__init__", return_value=None), \
             patch("shorts.animated_captions.generate_animated_captions") as mock_caps:
            mock_caps.return_value = {
                "output_path": "temp/captions.ass",
                "word_count": 50,
                "group_count": 13,
            }
            client = TestClient(app)
            resp = client.post("/api/shorts/captions", json={
                "transcript_path": "output/transcript.json",
                "style": "highlight_word",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "word_count" in data
