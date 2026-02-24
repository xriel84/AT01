# tests/test_markers.py
import unittest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestPairMarkers(unittest.TestCase):
    def test_basic_pair(self):
        from resolve_markers import pair_markers
        markers = {
            100: {"color": "Green", "name": "Start 1", "note": "", "duration": 1},
            200: {"color": "Red", "name": "End 1", "note": "", "duration": 1},
        }
        pairs = pair_markers(markers)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0], (100, 200))

    def test_multiple_pairs(self):
        from resolve_markers import pair_markers
        markers = {
            100: {"color": "Green", "name": "", "note": "", "duration": 1},
            200: {"color": "Red", "name": "", "note": "", "duration": 1},
            500: {"color": "Green", "name": "", "note": "", "duration": 1},
            700: {"color": "Red", "name": "", "note": "", "duration": 1},
        }
        pairs = pair_markers(markers)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0], (100, 200))
        self.assertEqual(pairs[1], (500, 700))

    def test_unpaired_green_skipped(self):
        from resolve_markers import pair_markers
        markers = {
            100: {"color": "Green", "name": "", "note": "", "duration": 1},
        }
        pairs = pair_markers(markers)
        self.assertEqual(len(pairs), 0)

    def test_overlapping_uses_outermost(self):
        from resolve_markers import pair_markers
        markers = {
            100: {"color": "Green", "name": "", "note": "", "duration": 1},
            150: {"color": "Green", "name": "", "note": "", "duration": 1},
            200: {"color": "Red", "name": "", "note": "", "duration": 1},
            250: {"color": "Red", "name": "", "note": "", "duration": 1},
        }
        pairs = pair_markers(markers)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0], (100, 250))


if __name__ == "__main__":
    unittest.main()
