# tests/test_common.py
import unittest
import sys
import os
import tempfile
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestSessionID(unittest.TestCase):
    def test_str_format(self):
        from resolve_common import SessionID
        sid = SessionID(human_name="KEYNOTE", date="20250220", seq=1)
        self.assertEqual(str(sid), "KEYNOTE_20250220_001")

    def test_seq_zero_padded(self):
        from resolve_common import SessionID
        sid = SessionID(human_name="LIVEJAM", date="20250301", seq=42)
        self.assertEqual(str(sid), "LIVEJAM_20250301_042")


class TestFeedID(unittest.TestCase):
    def test_str_format(self):
        from resolve_common import SessionID, FeedID
        sid = SessionID(human_name="KEYNOTE", date="20250220", seq=1)
        fid = FeedID(session=sid, feed_type="VRCAM", index=3)
        self.assertEqual(str(fid), "KEYNOTE_20250220_001_VRCAM-03")

    def test_different_feed_types(self):
        from resolve_common import SessionID, FeedID
        sid = SessionID(human_name="DEMO", date="20250220", seq=1)
        for ft in ["VRCAM", "STUDCAM", "MIC", "ENVAUD", "MRRENDER"]:
            fid = FeedID(session=sid, feed_type=ft, index=1)
            self.assertIn(ft, str(fid))


class TestClipColors(unittest.TestCase):
    def test_all_colors_present(self):
        from resolve_common import CLIP_COLORS
        expected = {"unreviewed", "select", "needs_review", "reject", "broll", "needs_fix"}
        self.assertEqual(set(CLIP_COLORS.keys()), expected)


class TestPathConstants(unittest.TestCase):
    def test_paths_are_under_nb11(self):
        from resolve_common import PROJECT_ROOT, INGEST_DIR, STAGING_DIR, ARCHIVE_DIR, DELIVERY_DIR, TOOLS_DIR
        for p in [INGEST_DIR, STAGING_DIR, ARCHIVE_DIR, DELIVERY_DIR, TOOLS_DIR]:
            self.assertTrue(str(p).startswith(str(PROJECT_ROOT)))

    def test_feed_subdirs(self):
        from resolve_common import FEED_SUBDIRS
        self.assertEqual(FEED_SUBDIRS, {"vrcam", "studcam", "mic", "envaud", "mrrender"})


class TestEnsureDirs(unittest.TestCase):
    def test_creates_ingest_subdirs(self):
        from resolve_common import ensure_dirs, INGEST_DIR, FEED_SUBDIRS
        ensure_dirs()
        for sub in FEED_SUBDIRS:
            self.assertTrue((INGEST_DIR / sub).is_dir())


class TestSessionRegistry(unittest.TestCase):
    def test_next_seq_new_session(self):
        from resolve_common import next_session_seq
        seq = next_session_seq("TESTNAME", "20250220", registry={})
        self.assertEqual(seq, 1)

    def test_next_seq_existing_session(self):
        from resolve_common import next_session_seq
        registry = {"TESTNAME_20250220": 3}
        seq = next_session_seq("TESTNAME", "20250220", registry=registry)
        self.assertEqual(seq, 4)


class TestDeterministicFeedHash(unittest.TestCase):
    def test_same_input_same_hash(self):
        from resolve_common import deterministic_feed_hash
        h1 = deterministic_feed_hash("/path/to/file.mp4", "20250220", 123456)
        h2 = deterministic_feed_hash("/path/to/file.mp4", "20250220", 123456)
        self.assertEqual(h1, h2)

    def test_different_input_different_hash(self):
        from resolve_common import deterministic_feed_hash
        h1 = deterministic_feed_hash("/path/to/a.mp4", "20250220", 100)
        h2 = deterministic_feed_hash("/path/to/b.mp4", "20250220", 200)
        self.assertNotEqual(h1, h2)


class TestValidateVideo(unittest.TestCase):
    def test_unsupported_extension_rejected(self):
        from resolve_common import validate_video
        result = validate_video("/fake/path/file.txt")
        self.assertEqual(result["validation_status"], "rejected")
        self.assertIn("unsupported", result["error"].lower())


class TestSidecarIO(unittest.TestCase):
    def test_write_and_read_sidecar(self):
        from resolve_common import write_sidecar, read_sidecar
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            data = {"feed_id": "TEST_20250220_001_VRCAM-01", "codec": "h264"}
            write_sidecar(path, data)
            loaded = read_sidecar(path)
            self.assertEqual(loaded["feed_id"], "TEST_20250220_001_VRCAM-01")


class TestSessionIO(unittest.TestCase):
    def test_write_and_read_session(self):
        from resolve_common import write_session_manifest, read_session_manifest
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "_session.json")
            data = {"session_id": "TEST_20250220_001", "feed_count": 2}
            write_session_manifest(path, data)
            loaded = read_session_manifest(path)
            self.assertEqual(loaded["session_id"], "TEST_20250220_001")


if __name__ == "__main__":
    unittest.main()
