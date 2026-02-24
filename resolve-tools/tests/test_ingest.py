# tests/test_ingest.py
import unittest
import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestScanIngestDir(unittest.TestCase):
    def test_maps_subdirs_to_feed_types(self):
        from resolve_ingest import scan_ingest_dir
        with tempfile.TemporaryDirectory() as td:
            vrcam = os.path.join(td, "vrcam")
            os.makedirs(vrcam)
            open(os.path.join(vrcam, "clip1.mp4"), "w").close()
            open(os.path.join(vrcam, "clip2.mp4"), "w").close()
            mic = os.path.join(td, "mic")
            os.makedirs(mic)
            open(os.path.join(mic, "audio1.wav"), "w").close()
            result = scan_ingest_dir(td)
            self.assertIn("VRCAM", result)
            self.assertEqual(len(result["VRCAM"]), 2)
            self.assertIn("MIC", result)
            self.assertEqual(len(result["MIC"]), 1)

    def test_ignores_unknown_subdirs(self):
        from resolve_ingest import scan_ingest_dir
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "randomdir"))
            open(os.path.join(td, "randomdir", "file.mp4"), "w").close()
            result = scan_ingest_dir(td)
            self.assertNotIn("randomdir", result)
            self.assertNotIn("RANDOMDIR", result)


class TestBuildFeedSidecar(unittest.TestCase):
    def test_sidecar_has_required_fields(self):
        from resolve_ingest import build_feed_sidecar
        sidecar = build_feed_sidecar(
            feed_id="TEST_20250220_001_VRCAM-01",
            session_id="TEST_20250220_001",
            feed_type="VRCAM",
            source_path=r"C:\test\clip.mp4",
            original_filename="clip.mp4",
            creation_date="20250220",
            validation={"duration": 30.5, "codec": "h264", "resolution": "1920x1080", "fps": 30.0, "validation_status": "valid"},
        )
        required = {"feed_id", "session_id", "feed_type", "source_path",
                     "original_filename", "creation_date", "duration",
                     "codec", "resolution", "fps", "validation_status", "ingest_timestamp"}
        self.assertTrue(required.issubset(set(sidecar.keys())))


class TestBuildSessionManifest(unittest.TestCase):
    def test_manifest_has_required_fields(self):
        from resolve_ingest import build_session_manifest
        manifest = build_session_manifest(
            session_id="TEST_20250220_001",
            human_name="TEST",
            feeds=["VRCAM-01", "MIC-01"],
        )
        self.assertEqual(manifest["session_id"], "TEST_20250220_001")
        self.assertEqual(manifest["human_name"], "TEST")
        self.assertEqual(manifest["feed_count"], 2)
        self.assertEqual(manifest["sync_method"], "TBD")
        self.assertIsNone(manifest["sync_offset_stub"])


if __name__ == "__main__":
    unittest.main()
