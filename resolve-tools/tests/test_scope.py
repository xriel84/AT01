# tests/test_scope.py
import unittest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBuildTimelineRefusesEmpty(unittest.TestCase):
    def test_refuses_empty_session_id(self):
        from resolve_scope import build_timeline
        with self.assertRaises(ValueError):
            build_timeline("", resolve=None)

    def test_refuses_none_session_id(self):
        from resolve_scope import build_timeline
        with self.assertRaises(ValueError):
            build_timeline(None, resolve=None)


class TestBuildMultiTimelineRequiresName(unittest.TestCase):
    def test_refuses_without_name(self):
        from resolve_scope import build_multi_timeline
        with self.assertRaises(ValueError):
            build_multi_timeline(["S1", "S2"], name="", resolve=None)


if __name__ == "__main__":
    unittest.main()
