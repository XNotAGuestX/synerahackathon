import unittest

from final_agent.building_map import BuildingMap, MapError


def box(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def make_map(source: str = "procedural") -> BuildingMap:
    """Levels 0 and 2 only (a gap). Source A (0..10) overlaps B (0..7) more than C (7..10)."""
    spaces = [
        ("A", "F0", box(0, 0, 10, 10)),
        ("LONE", "F0", box(50, 50, 52, 52)),
        ("B", "F2", box(0, 0, 7, 10)),
        ("C", "F2", box(7, 0, 12, 10)),
        ("D", "F2", box(0, 20, 10, 30)),
    ]
    return BuildingMap({
        "building": {"name": "T", "source": source},
        "floors": [
            {"id": "F0", "name": "Ground", "level": 0},
            {"id": "F2", "name": "Second", "level": 2},
        ],
        "spaces": [
            {"id": sid, "name": sid, "ref": None, "type": "room", "room_type": "office",
             "floor_id": floor, "polygon": polygon}
            for sid, floor, polygon in spaces
        ],
        "assets": [], "vertical_connectors": [], "openings": [],
    })


class StackedRoomTest(unittest.TestCase):
    def test_skips_level_gap_and_picks_largest_overlap(self) -> None:
        result = make_map().find_stacked_room("A", "above")
        self.assertEqual(result["target_floor_level"], 2)
        self.assertEqual(result["room"]["id"], "B")
        self.assertEqual(result["overlap_area_m2"], 70.0)
        self.assertEqual(result["overlap_fraction"], 0.7)
        self.assertEqual([item["id"] for item in result["runners_up"]], ["C"])
        self.assertFalse(result["tie"])
        self.assertNotIn("frame_warning", result)

    def test_below_from_upper_floor_and_direction_aliases(self) -> None:
        building = make_map()
        self.assertEqual(building.find_stacked_room("B", " Below ")["room"]["id"], "A")
        self.assertEqual(building.find_stacked_room("B", "down")["target_floor_level"], 0)

    def test_tie_is_broken_by_id(self) -> None:
        building = make_map()
        building.spaces["C"]["polygon"] = box(5, 0, 10, 10)
        building.spaces["B"]["polygon"] = box(0, 0, 5, 10)
        result = building.find_stacked_room("A", "above")
        self.assertTrue(result["tie"])
        self.assertEqual(result["room"]["id"], "B")

    def test_non_overlapping_room(self) -> None:
        result = make_map().find_stacked_room("LONE", "above")
        self.assertIsNone(result["room"])
        self.assertEqual(result["target_floor_level"], 2)
        self.assertIn("no overlapping space", result["reason"])

    def test_no_floor_in_direction(self) -> None:
        building = make_map()
        self.assertIn("no floor above", building.find_stacked_room("B", "above")["reason"])
        self.assertIn("no floor below", building.find_stacked_room("A", "below")["reason"])
        self.assertIsNone(building.find_stacked_room("A", "below")["room"])

    def test_bad_direction_and_unknown_space(self) -> None:
        with self.assertRaises(MapError):
            make_map().find_stacked_room("A", "sideways")
        with self.assertRaises(MapError):
            make_map().find_stacked_room("missing", "above")

    def test_unshared_frame_source_warns(self) -> None:
        result = make_map("swiss_dwellings").find_stacked_room("A", "above")
        self.assertIn("frame_warning", result)


if __name__ == "__main__":
    unittest.main()
