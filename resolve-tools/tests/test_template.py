# tests/test_template.py
import unittest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBinStructure(unittest.TestCase):
    def test_expected_bins(self):
        from resolve_template import EXPECTED_BINS
        expected = {"RAW FOOTAGE", "SELECTS", "SUBCLIPS", "B-ROLL",
                    "GRAPHICS", "MUSIC & SFX", "TIMELINES", "EXPORTS"}
        self.assertEqual(set(EXPECTED_BINS), expected)


class TestSmartBinDefs(unittest.TestCase):
    def test_color_smart_bins(self):
        from resolve_template import COLOR_SMART_BINS
        self.assertIn("Unreviewed", COLOR_SMART_BINS)
        self.assertEqual(COLOR_SMART_BINS["Unreviewed"], "Blue")

    def test_feed_smart_bins(self):
        from resolve_template import FEED_SMART_BINS
        self.assertIn("VR Cameras", FEED_SMART_BINS)


class TestRenderPresets(unittest.TestCase):
    def test_all_presets_defined(self):
        from resolve_template import RENDER_PRESETS
        expected = {"YouTube 16:9", "TikTok 9:16", "IG Square 1:1", "Archive", "Thumbnail"}
        self.assertEqual(set(RENDER_PRESETS.keys()), expected)

    def test_youtube_preset_values(self):
        from resolve_template import RENDER_PRESETS
        yt = RENDER_PRESETS["YouTube 16:9"]
        self.assertEqual(yt["width"], 1920)
        self.assertEqual(yt["height"], 1080)


if __name__ == "__main__":
    unittest.main()
