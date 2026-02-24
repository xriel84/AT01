# tests/test_detect.py
import unittest
import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestDetectorInterface(unittest.TestCase):
    def test_detector_has_name(self):
        from resolve_detect_test import SilenceDetector
        d = SilenceDetector()
        self.assertEqual(d.name, "silence")

    def test_all_detectors_registered(self):
        from resolve_detect_test import ALL_DETECTORS
        names = {d.name for d in ALL_DETECTORS}
        self.assertIn("silence", names)
        self.assertIn("scene_change", names)
        self.assertIn("black_frame", names)
        self.assertIn("audio_peak", names)
        self.assertIn("speaker_change", names)
        self.assertIn("breath", names)


class TestDetectionResult(unittest.TestCase):
    def test_dataclass_fields(self):
        from resolve_detect_test import DetectionResult
        r = DetectionResult(
            start_tc=1.0, end_tc=2.0, confidence=0.95,
            label="silence", detector_name="silence",
        )
        self.assertEqual(r.start_tc, 1.0)
        self.assertEqual(r.confidence, 0.95)


class TestStubDetectors(unittest.TestCase):
    def test_speaker_change_returns_empty(self):
        from resolve_detect_test import SpeakerChangeDetector
        d = SpeakerChangeDetector()
        results = d.detect("nonexistent.mp4")
        self.assertEqual(results, [])

    def test_breath_returns_empty(self):
        from resolve_detect_test import BreathDetector
        d = BreathDetector()
        results = d.detect("nonexistent.mp4")
        self.assertEqual(results, [])


class TestResultsSerialization(unittest.TestCase):
    def test_results_to_json(self):
        from resolve_detect_test import DetectionResult, results_to_json
        results = [
            DetectionResult(1.0, 2.0, 0.9, "silence", "silence"),
            DetectionResult(5.0, 5.5, 0.8, "scene", "scene_change"),
        ]
        j = results_to_json(results)
        parsed = json.loads(j)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["label"], "silence")


if __name__ == "__main__":
    unittest.main()
