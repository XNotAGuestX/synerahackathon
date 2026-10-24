"""Checks for sum_floor_area on a compact synthetic building (no API calls)."""

import json
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError

from final_agent.building_map import BuildingMap, MapError
from final_agent.tools import make_tools


def square(x: float, size: float) -> list[list[float]]:
    return [[x, 0], [x + size, 0], [x + size, size], [x, size]]


def space(space_id: str, floor_id: str, room_type: str, polygon: list, kind: str = "room") -> dict:
    return {"id": space_id, "name": space_id, "floor_id": floor_id, "type": kind,
            "room_type": room_type, "polygon": polygon}


def area_building() -> dict:
    spaces = [space(f"o{i}", "F0", "office", square(i * 3, 2)) for i in range(20)]  # 20 x 4 m2
    spaces += [
        space("l-shape", "F0", "lab", [[0, 10], [6, 10], [6, 12], [2, 12], [2, 16], [0, 16]]),  # 12 + 8
        space("zone", "F0", "warehouse_zone", square(0, 5), kind="hall"),  # 25
        space("depot", "F0", "warehouse_zone", square(10, 3)),  # 9
        space("hall-office", "F0", "office_annex", square(30, 10), kind="hall"),  # other type
        space("up-office", "F1", "office", square(0, 7)),  # other floor
    ]
    return {
        "building": {"id": "area", "name": "Area", "units": "m", "source": "test"},
        "floors": [{"id": "F0", "level": 0, "name": "Ground"}, {"id": "F1", "level": 1, "name": "First"}],
        "spaces": spaces, "assets": [], "openings": [], "vertical_connectors": [],
    }


class SumFloorAreaTests(unittest.TestCase):
    def setUp(self):
        self.building = BuildingMap(area_building())

    def test_total_spans_more_than_one_search_page(self):
        result = self.building.sum_floor_area("office", 0)
        self.assertEqual(result["count"], 20)
        self.assertGreater(result["count"], 15)
        self.assertEqual(result["area_m2"], 80.0)
        self.assertEqual(result["space_ids"], sorted(f"o{i}" for i in range(20)))
        self.assertEqual(result["floor"], "Ground")

    def test_irregular_polygon_uses_actual_area(self):
        self.assertEqual(self.building.sum_floor_area("lab", 0)["area_m2"], 20.0)

    def test_hall_with_matching_room_type_is_included(self):
        result = self.building.sum_floor_area("Warehouse-Zone", 0)
        self.assertEqual(result["room_type"], "warehouse_zone")
        self.assertEqual(result["space_ids"], ["depot", "zone"])
        self.assertEqual(result["area_m2"], 34.0)

    def test_empty_match_is_normal_result_with_hint(self):
        result = self.building.sum_floor_area("toilet", 0)
        self.assertEqual((result["count"], result["area_m2"], result["space_ids"]), (0, 0.0, []))
        self.assertIn("office", result["available_room_types"])

    def test_floor_and_type_are_strictly_isolated(self):
        self.assertEqual(self.building.sum_floor_area("office", 1)["area_m2"], 49.0)
        self.assertEqual(self.building.sum_floor_area("office_annex", 0)["area_m2"], 100.0)
        self.assertEqual(self.building.sum_floor_area("office", 0)["area_m2"], 80.0)

    def test_unknown_floor_is_an_error(self):
        with self.assertRaises(MapError):
            self.building.sum_floor_area("office", 9)

    def test_room_list_is_capped_but_totals_stay_complete(self):
        data = area_building()
        data["spaces"] += [space(f"x{i}", "F1", "cell", square(i, 1)) for i in range(60)]
        result = BuildingMap(data).sum_floor_area("cell", 1)
        self.assertEqual((result["count"], result["area_m2"], len(result["space_ids"])), (60, 60.0, 60))
        self.assertEqual(len(result["rooms"]), 50)
        self.assertTrue(result["rooms_truncated"])

    def test_tool_returns_json_and_reports_unknown_floor(self):
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_tools(self.building, Path(temporary))}
        result = json.loads(tools["sum_floor_area"].call({"room_type": "lab", "floor_level": 0}))
        self.assertEqual(result["area_m2"], 20.0)
        with self.assertRaises(ToolError):
            tools["sum_floor_area"].call({"room_type": "lab", "floor_level": 9})


if __name__ == "__main__":
    unittest.main()
