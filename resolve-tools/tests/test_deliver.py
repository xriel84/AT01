# tests/test_deliver.py
import unittest
import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestManifestSchema(unittest.TestCase):
    def test_manifest_has_required_fields(self):
        from resolve_deliver import build_manifest
        manifest = build_manifest(
            session_id="TEST_20250220_001",
            timeline_name="test_timeline",
            duration_sec=120.5,
            feeds_used=["VRCAM-01", "STUDCAM-02"],
            deliverables=[],
        )
        required = {"session_id", "generated_at", "source_timeline",
                     "total_duration_sec", "feeds_used", "deliverables",
                     "social_metadata", "analytics_hooks", "feedback_loop"}
        self.assertTrue(required.issubset(set(manifest.keys())))

    def test_social_metadata_placeholders(self):
        from resolve_deliver import build_manifest
        manifest = build_manifest("S1", "tl", 60, [], [])
        sm = manifest["social_metadata"]
        self.assertIn("PLACEHOLDER", sm["title"])
        self.assertIn("PLACEHOLDER", sm["description"])

    def test_feedback_loop_defaults(self):
        from resolve_deliver import build_manifest
        manifest = build_manifest("S1", "tl", 60, [], [])
        fl = manifest["feedback_loop"]
        self.assertEqual(fl["status"], "pending_review")
        self.assertIsNone(fl["reviewer"])


class TestAnalyticsSchema(unittest.TestCase):
    def test_empty_analytics(self):
        from resolve_deliver import build_analytics
        analytics = build_analytics("TEST_20250220_001")
        self.assertEqual(analytics["session_id"], "TEST_20250220_001")
        self.assertEqual(analytics["platform_results"], [])


class TestDeliverableEntry(unittest.TestCase):
    def test_deliverable_fields(self):
        from resolve_deliver import build_deliverable_entry
        entry = build_deliverable_entry(
            platform="youtube",
            filename="test.mp4",
            resolution="1920x1080",
            duration_sec=120.5,
            file_size_bytes=50000000,
            codec="h264",
            render_preset="YouTube 16:9",
        )
        self.assertEqual(entry["platform"], "youtube")
        self.assertEqual(entry["render_preset"], "YouTube 16:9")


if __name__ == "__main__":
    unittest.main()
