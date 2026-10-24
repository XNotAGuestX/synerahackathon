import json
import tempfile
import unittest

from anthropic.lib.tools import ToolError

from final_agent.building_map import BuildingMap, MapError
from final_agent.tools import make_tools


def box(x: float, y: float, width: float, height: float) -> list[list[float]]:
    return [[x, y], [x + width, y], [x + width, y + height], [x, y + height]]


def space(space_id: str, floor_id: str, room_type: str, polygon: list, kind: str = "room") -> dict:
    return {"id": space_id, "name": space_id.title(), "floor_id": floor_id, "type": kind,
            "room_type": room_type, "polygon": polygon}


def fixture() -> BuildingMap:
    spaces = [
        # Concave L: bounding box 6x6 = 36 m2 but polygon area 20 m2, smaller than the 24 m2 rectangle.
        space("l_shape", "F0", "office", [[0, 0], [6, 0], [6, 2], [2, 2], [2, 6], [0, 6]]),
        space("plain", "F0", "office", box(10, 0, 6, 4)),
        space("big_other_type", "F0", "storage", box(20, 0, 10, 10)),
        space("big_upstairs", "F1", "office", box(0, 0, 10, 10)),
        space("hall_lobby", "F0", "lobby", box(40, 0, 5, 5), kind="hall"),
        space("small_lobby", "F0", "lobby", box(50, 0, 2, 2)),
        space("meet_b", "F0", "meeting_room", box(60, 0, 3, 3)),
        space("meet_a", "F0", "meeting_room", box(70, 0, 3, 3)),
    ]
    # 17 candidates (more than the search page size); the largest is not first in name or id order.
    spaces += [space(f"cell_{i:02d}", "F1", "cell", box(100 + 10 * i, 0, 1 + i, 1)) for i in range(17)]
    data = {
        "building": {"id": "t", "name": "T", "units": "m"},
        "floors": [{"id": "F0", "level": 0, "name": "Ground"}, {"id": "F1", "level": 1, "name": "First"}],
        "spaces": spaces, "assets": [], "openings": [], "vertical_connectors": [],
    }
    return BuildingMap(data)


class LargestRoomTests(unittest.TestCase):
    def setUp(self):
        self.building = fixture()

    def test_concave_polygon_ranked_by_area_not_bounding_box(self):
        result = self.building.find_largest_room("Office", 0)
        self.assertEqual(result["room"]["id"], "plain")
        self.assertEqual(result["area_m2"], 24.0)
        self.assertEqual(result["candidates"], 2)
        self.assertEqual(result["runners_up"], [{"id": "l_shape", "name": "L_Shape", "area_m2": 20.0}])
        self.assertFalse(result["tie"])

    def test_more_than_fifteen_candidates_and_runners_up_limit(self):
        result = self.building.find_largest_room("cell", 1)
        self.assertEqual(result["candidates"], 17)
        self.assertEqual(result["room"]["id"], "cell_16")
        self.assertEqual(result["area_m2"], 17.0)
        self.assertEqual([item["id"] for item in result["runners_up"]], ["cell_15", "cell_14", "cell_13"])

    def test_other_floor_and_other_type_are_excluded(self):
        self.assertEqual(self.building.find_largest_room("office", 1)["room"]["id"], "big_upstairs")
        self.assertNotIn("big_other_type", [self.building.find_largest_room("office", 0)["room"]["id"]])

    def test_hall_subtype_is_included(self):
        result = self.building.find_largest_room("lobby", 0)
        self.assertEqual(result["room"]["id"], "hall_lobby")
        self.assertEqual(result["room"]["type"], "hall")

    def test_tie_is_broken_by_id_and_reported(self):
        result = self.building.find_largest_room("meeting room", 0)
        self.assertEqual(result["room"]["id"], "meet_a")
        self.assertTrue(result["tie"])
        self.assertEqual(result["runners_up"][0]["id"], "meet_b")

    def test_no_match_is_explicit_and_lists_types(self):
        result = self.building.find_largest_room("cell", 0)
        self.assertIsNone(result["room"])
        self.assertIsNone(result["area_m2"])
        self.assertEqual(result["candidates"], 0)
        self.assertEqual(result["available_room_types"],
                         ["lobby", "meeting_room", "office", "storage"])

    def test_tool_returns_json_and_unknown_floor_is_tool_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_tools(self.building, temporary)}
        result = json.loads(tools["find_largest_room"].call({"room_type": "office", "floor_level": 0}))
        self.assertEqual(result["room"]["name"], "Plain")
        with self.assertRaises(ToolError):
            tools["find_largest_room"].call({"room_type": "office", "floor_level": 7})
        with self.assertRaises(MapError):
            self.building.find_largest_room("office", 7)


if __name__ == "__main__":
    unittest.main()
