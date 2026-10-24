import json
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError
from shapely.geometry import Point

from final_agent.building_map import BuildingMap, MapError
from final_agent.tools import make_tools


def room(space_id: str, name: str, floor_id: str, polygon: list, **extra) -> dict:
    return {"id": space_id, "floor_id": floor_id, "type": "room", "room_type": "office", "name": name,
            "ref": name.split()[-1], "polygon": polygon, "synthetic": False, **extra}


def inspection_building() -> dict:
    square = [[0, 0], [4, 0], [4, 4], [0, 4]]
    l_shape = [[0, 0], [4, 0], [4, 2], [2, 2], [2, 4], [0, 4]]
    return {
        "building": {"id": "t", "name": "T", "units": "m"},
        "floors": [
            {"id": "F0", "level": 0, "name": "Ground", "elevation_m": 0.0, "height_m": 3.5},
            {"id": "F1", "level": 1, "name": "First"},
        ],
        "spaces": [
            room("L", "Lab 1.1", "F0", l_shape, custom_field={"owner": "ACME"}),
            room("N", "North 1.2", "F0", [[0, 4], [4, 4], [4, 8], [0, 8]]),
            room("E", "East 1.3", "F0", [[4, 0], [8, 0], [8, 2], [4, 2]]),
            room("D1", "Dup 1.4", "F0", [[8, 4], [9, 4], [9, 5], [8, 5]], name_clash=True),
            room("D2", "Dup 1.5", "F0", [[8, 6], [9, 6], [9, 7], [8, 7]]),
            room("U", "Upper 2.1", "F1", square),
        ],
        "openings": [
            {"id": "O1", "floor_id": "F0", "space_ids": ["L", "N"], "kind": "door", "position": [1, 4],
             "width_m": 0.9, "step_free": True, "synthetic": False},
            {"id": "O2", "floor_id": "F0", "space_ids": ["L", "E"], "kind": "opening", "position": [4, 1],
             "width_m": 1.6, "step_free": True, "synthetic": True},
            {"id": "O3", "floor_id": "F0", "space_ids": ["outside", "L"], "kind": "entrance",
             "position": [0, 1], "width_m": 1.2, "step_free": False, "synthetic": False},
        ],
        "vertical_connectors": [
            {"id": "V1", "kind": "stairs", "name": "Main stairs", "floor_ids": ["F1", "F0"],
             "space_ids": ["U", "L"], "step_free": False, "synthetic": False},
        ],
        "assets": [
            {"id": "A2", "name": "Bench", "floor_id": "F0", "space_id": "L", "position": [1, 1], "type": "bench"},
            {"id": "A1", "name": "Mill", "floor_id": "F0", "space_id": "L", "position": [1, 1], "type": "mill"},
            {"id": "A3", "name": "Desk", "floor_id": "F0", "space_id": "N", "position": [1, 5], "type": "desk"},
        ],
        "navigation_state": {"closed": ["O2"]},
    }


class InspectSpaceTests(unittest.TestCase):
    def setUp(self):
        self.building = BuildingMap(inspection_building())
        self.result = self.building.inspect_space("L")

    def test_irregular_polygon_geometry_and_anchor_are_separate(self):
        derived = self.result["derived"]
        self.assertEqual(derived["area_m2"], 12.0)
        self.assertEqual(derived["perimeter_m"], 16.0)
        self.assertEqual(derived["centroid"], [1.667, 1.667])
        self.assertEqual(derived["bounds"], {"min_x": 0.0, "min_y": 0.0, "max_x": 4.0, "max_y": 4.0})
        anchor = self.building.anchor("L")
        self.assertEqual(derived["representative_point"], [round(anchor[0], 3), round(anchor[1], 3)])
        self.assertTrue(self.building.space_polygon("L").covers(Point(anchor)))

    def test_source_record_is_unchanged_and_custom_fields_kept(self):
        self.assertEqual(self.result["space"], inspection_building()["spaces"][0])
        self.assertEqual(self.result["space"]["custom_field"], {"owner": "ACME"})
        self.result["space"]["polygon"].append([9, 9])
        self.assertEqual(len(self.building.spaces["L"]["polygon"]), 6)

    def test_openings_include_entrance_closed_and_other_side(self):
        openings = {item["id"]: item for item in self.result["openings"]}
        self.assertEqual(list(openings), ["O1", "O2", "O3"])
        self.assertEqual(openings["O1"]["other_side"]["id"], "N")
        self.assertEqual(openings["O1"]["width_m"], 0.9)
        self.assertFalse(openings["O1"]["closed"])
        self.assertTrue(openings["O2"]["closed"])
        self.assertTrue(openings["O2"]["synthetic"])
        self.assertEqual(openings["O3"]["other_side"], "outside")
        self.assertFalse(openings["O3"]["step_free"])

    def test_vertical_connector_stops_are_ordered_by_level(self):
        (connector,) = self.result["connectors"]
        self.assertEqual(connector["kind"], "stairs")
        self.assertEqual([stop["floor_level"] for stop in connector["stops"]], [0, 1])
        self.assertEqual([stop["space_id"] for stop in connector["stops"]], ["L", "U"])
        self.assertEqual(self.building.inspect_space("U")["connectors"][0]["id"], "V1")

    def test_assets_sorted_and_truncated_with_paging_hint(self):
        assets = self.result["assets"]
        self.assertEqual((assets["count"], assets["ids"], assets["truncated"]), (2, ["A1", "A2"], False))
        self.assertEqual((assets["page"], assets["has_more"], assets["next_page"]), (1, False, None))
        for index in range(60):
            self.building.assets[f"X{index:02d}"] = {"id": f"X{index:02d}", "name": f"X{index}", "space_id": "E"}
        assets = self.building.inspect_space("E")["assets"]
        self.assertEqual((assets["count"], len(assets["ids"]), assets["truncated"]), (60, 50, True))
        self.assertIn("inspect_space", assets["note"])
        second = self.building.inspect_space("E", page=assets["next_page"])["assets"]
        self.assertEqual(second["ids"], [f"X{index:02d}" for index in range(50, 60)])
        self.assertFalse(second["has_more"])

    def test_asset_reference_resolves_to_its_room(self):
        for reference in ("A3", "Desk"):
            result = self.building.inspect_space(reference)
            self.assertEqual(result["space"]["id"], "N")
            self.assertEqual(result["resolved_from_asset"], {"id": "A3", "name": "Desk"})
        self.assertNotIn("resolved_from_asset", self.building.inspect_space("N"))

    def test_floor_reports_stored_values_and_missing_elevation(self):
        self.assertEqual(self.result["floor"], {"id": "F0", "level": 0, "name": "Ground",
                                                "elevation_m": 0.0, "height_m": 3.5})
        upper = self.building.inspect_space("U")["floor"]
        self.assertIsNone(upper["elevation_m"])
        self.assertIn("elevation_m", upper["note"])

    def test_closed_space_flag(self):
        self.building.closed.add("N")
        self.assertTrue(self.building.inspect_space("N")["closed"])
        self.assertFalse(self.result["closed"])

    def test_unknown_and_ambiguous_references_fail_with_candidates(self):
        with self.assertRaisesRegex(MapError, "No place matches"):
            self.building.inspect_space("Nowhere")
        with self.assertRaisesRegex(MapError, "D1.*D2"):
            self.building.inspect_space("Dup")

    def test_tool_returns_json_and_tool_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_tools(self.building, Path(temporary))}
        self.assertEqual(json.loads(tools["inspect_space"].call({"space": "Lab 1.1"}))["space"]["id"], "L")
        with self.assertRaises(ToolError):
            tools["inspect_space"].call({"space": "Dup"})


if __name__ == "__main__":
    unittest.main()
