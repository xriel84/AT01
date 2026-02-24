"""Integration tests for the full pipeline (filesystem only, no Resolve)."""
import unittest
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestIngestToScopeContract(unittest.TestCase):
    """Verify ingest output is valid input for scope."""

    def test_session_manifest_readable_by_scope(self):
        from resolve_ingest import build_session_manifest
        from resolve_common import write_session_manifest, read_session_manifest

        manifest = build_session_manifest("TEST_20250220_001", "TEST", ["VRCAM-01", "MIC-01"])

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "_session.json")
            write_session_manifest(path, manifest)
            loaded = read_session_manifest(path)

            # Scope needs these fields
            self.assertIn("session_id", loaded)
            self.assertIn("feed_list", loaded)
            self.assertIn("feed_count", loaded)

    def test_feed_sidecar_has_duration(self):
        from resolve_ingest import build_feed_sidecar

        sidecar = build_feed_sidecar(
            feed_id="T_20250220_001_VRCAM-01",
            session_id="T_20250220_001",
            feed_type="VRCAM",
            source_path="test.mp4",
            original_filename="test.mp4",
            creation_date="20250220",
            validation={
                "duration": 30.5,
                "codec": "h264",
                "width": 1920,
                "height": 1080,
                "fps": 30.0,
                "validation_status": "valid",
            },
        )
        self.assertGreater(sidecar["duration"], 0)


class TestDeliverManifestSchema(unittest.TestCase):
    """Verify delivery manifest matches expected schema."""

    def test_manifest_round_trip(self):
        from resolve_deliver import build_manifest

        manifest = build_manifest(
            "S1",
            "tl",
            120.0,
            ["V-01"],
            [
                {
                    "platform": "youtube",
                    "filename": "out.mp4",
                    "resolution": "1920x1080",
                    "duration_sec": 120.0,
                    "file_size_bytes": 5000000,
                    "codec": "h264",
                    "render_preset": "YouTube 16:9",
                }
            ],
        )

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "_manifest.json")
            with open(path, "w") as f:
                json.dump(manifest, f)
            with open(path) as f:
                loaded = json.load(f)

            self.assertEqual(loaded["session_id"], "S1")
            self.assertEqual(len(loaded["deliverables"]), 1)
            self.assertIn("social_metadata", loaded)
            self.assertIn("analytics_hooks", loaded)
            self.assertIn("feedback_loop", loaded)


class TestMCPToolRegistry(unittest.TestCase):
    """Verify all expected MCP tools are registered."""

    def test_all_read_tools(self):
        from resolve_mcp_server import TOOLS

        read_tools = [
            "resolve_list_sessions",
            "resolve_list_feeds",
            "resolve_get_metadata",
            "resolve_list_timelines",
            "resolve_query_markers",
            "resolve_render_status",
            "resolve_delivery_status",
            "resolve_search_clips",
        ]
        for tool in read_tools:
            self.assertIn(tool, TOOLS)

    def test_all_write_tools(self):
        from resolve_mcp_server import TOOLS

        write_tools = [
            "resolve_ingest",
            "resolve_build_timeline",
            "resolve_build_feed_timeline",
            "resolve_add_marker",
            "resolve_process_markers",
            "resolve_render",
            "resolve_set_clip_color",
            "resolve_promote_to_selects",
        ]
        for tool in write_tools:
            self.assertIn(tool, TOOLS)


class TestIDDeterminism(unittest.TestCase):
    """Verify the two-tier ID system produces deterministic results."""

    def test_same_input_same_session_id(self):
        from resolve_common import SessionID

        a = SessionID(human_name="KEYNOTE", date="20250220", seq=1)
        b = SessionID(human_name="KEYNOTE", date="20250220", seq=1)
        self.assertEqual(str(a), str(b))

    def test_feed_id_deterministic(self):
        from resolve_common import deterministic_feed_hash

        h1 = deterministic_feed_hash(r"C:\test\clip.mp4", "20250220", 999999)
        h2 = deterministic_feed_hash(r"C:\test\clip.mp4", "20250220", 999999)
        self.assertEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
