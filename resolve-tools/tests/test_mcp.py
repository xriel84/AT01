"""Tests for resolve_mcp_server.py -- MCP server for DaVinci Resolve."""
import unittest
import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestAuditLog(unittest.TestCase):
    def test_audit_entry_format(self):
        from resolve_mcp_server import format_audit_entry
        entry = format_audit_entry("resolve_list_sessions", {"limit": 10}, {"sessions": []})
        self.assertIn("resolve_list_sessions", entry)
        self.assertIn("limit", entry)

    def test_not_implemented_response(self):
        from resolve_mcp_server import not_implemented_response
        resp = not_implemented_response("resolve_ingest")
        self.assertEqual(resp["error"], "not_implemented")
        self.assertEqual(resp["tool"], "resolve_ingest")


class TestToolRegistry(unittest.TestCase):
    def test_all_read_tools(self):
        from resolve_mcp_server import TOOLS
        read_tools = [
            "resolve_list_sessions", "resolve_list_feeds", "resolve_get_metadata",
            "resolve_list_timelines", "resolve_query_markers", "resolve_render_status",
            "resolve_delivery_status", "resolve_search_clips",
        ]
        for tool in read_tools:
            self.assertIn(tool, TOOLS, f"Missing read tool: {tool}")

    def test_all_write_tools(self):
        from resolve_mcp_server import TOOLS
        write_tools = [
            "resolve_ingest", "resolve_build_timeline", "resolve_build_feed_timeline",
            "resolve_add_marker", "resolve_process_markers", "resolve_render",
            "resolve_set_clip_color", "resolve_promote_to_selects",
        ]
        for tool in write_tools:
            self.assertIn(tool, TOOLS, f"Missing write tool: {tool}")


if __name__ == "__main__":
    unittest.main()
