import tempfile
import unittest
from pathlib import Path

from final_agent.campus_demo import run_campus_walkway


class CampusDemoTests(unittest.TestCase):
    def test_walkway_demo_returns_short_detour_and_recovered_lengths(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_campus_walkway(Path(temporary))
        self.assertEqual(result["lengths_m"], [35.0, 57.0, 35.0])
        self.assertTrue(result["matches_expected"])
        self.assertTrue(all(image["name"].endswith(".png") for stage in result["stages"] for image in stage["images"]))


if __name__ == "__main__":
    unittest.main()
