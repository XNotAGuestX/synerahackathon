"""Checks for straight_line_distance_3d on a compact synthetic building (no API calls)."""

import json
import math
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError

from final_agent.building_map import BuildingMap, MapError
from final_agent.tools import make_tools


def square(x: float, y: float, size: float = 4) -> list[list[float]]:
    return [[x, y], [x + size, y], [x + size, y + size], [x, y + size]]


# Concave L whose centroid (116/36, 116/36) lies outside the shape, unlike its representative point.
L_SHAPE = [[0, 0], [10, 0], [10, 2], [2, 2], [2, 10], [0, 10]]


def room(space_id: str, floor_id: str, polygon: list[list[float]]) -> dict:
    return {"id": space_id, "name": space_id.upper(), "type": "room", "room_type": "office",
            "floor_id": floor_id, "polygon": polygon}


def building(source: str = "test", **elevations: object) -> dict:
    floor_elevations = {"B": -3.0, "G": 0.0, "F2": 7.5, **elevations}
    levels = {"B": -1, "G": 0, "F2": 2, "BAD": 3}
    return {
        "building": {"id": "t", "name": "T", "source": source, "units": "m"},
        "floors": [
            {"id": floor_id, "level": levels[floor_id], "name": floor_id, "elevation_m": elevation,
             "height_m": 4.0}
            for floor_id, elevation in floor_elevations.items()
        ] + [{"id": "NONE", "level": 4, "name": "NONE"}],
        "spaces": [
            room("a", "G", square(0, 0)), room("b", "G", square(10, 0)), room("l", "G", L_SHAPE),
            room("basement", "B", square(0, 0)), room("top", "F2", square(3, 0)),
            room("nan", "BAD", square(0, 0)), room("missing", "NONE", square(0, 0)),
        ],
        "assets": [{"id": "printer", "name": "Printer", "floor_id": "F2", "space_id": "top",
                    "position": [4, 1], "type": "printer"}],
        "openings": [],
        "vertical_connectors": [],
    }


class StraightLineDistance3dTests(unittest.TestCase):
    def distance(self, first: str, second: str, **elevations: object) -> dict:
        return BuildingMap(building(**elevations)).straight_line_distance_3d(first, second)

    def test_same_floor_uses_centroids(self):
        result = self.distance("a", "b")
        self.assertAlmostEqual(result["distance_m"], 10.0)
        self.assertEqual(result["vertical_m"], 0.0)
        self.assertEqual(result["first"]["point"], [2.0, 2.0, 0.0])
        self.assertNotIn("frame_note", result)

    def test_basement_uses_negative_elevation(self):
        self.assertAlmostEqual(self.distance("a", "basement")["distance_m"], 3.0)

    def test_nonconsecutive_floors_use_elevation_not_level_or_height(self):
        result = self.distance("a", "top")
        self.assertAlmostEqual(result["vertical_m"], 7.5)
        self.assertAlmostEqual(result["horizontal_m"], 3.0)
        self.assertAlmostEqual(result["distance_m"], math.hypot(3, 7.5))
        self.assertAlmostEqual(self.distance("basement", "top")["vertical_m"], 10.5)

    def test_concave_polygon_uses_centroid_not_representative_point(self):
        result = self.distance("a", "l")
        centroid = 116 / 36
        self.assertAlmostEqual(result["second"]["centroid"][0], centroid)
        self.assertAlmostEqual(result["distance_m"], math.dist((2, 2), (centroid, centroid)))
        anchor = BuildingMap(building()).anchor("l")
        self.assertNotAlmostEqual(anchor[0], centroid)

    def test_asset_resolves_to_containing_room_and_says_so(self):
        result = self.distance("printer", "a")
        self.assertEqual(result["first"]["id"], "top")
        self.assertEqual(result["first"]["resolved_from_asset"], "printer")
        self.assertNotIn("resolved_from_asset", result["second"])

    def test_missing_or_nonfinite_elevation_is_an_error(self):
        for second in ("missing", "nan"):
            with self.subTest(second=second):
                with self.assertRaisesRegex(MapError, "elevation"):
                    self.distance("a", second, BAD=float("nan"))
        with self.assertRaisesRegex(MapError, "elevation"):
            self.distance("a", "nan", BAD=float("inf"))

    def test_swiss_dwellings_cross_floor_adds_frame_note(self):
        swiss = BuildingMap(building(source="swiss_dwellings"))
        self.assertIn("frame_note", swiss.straight_line_distance_3d("a", "top"))
        self.assertNotIn("frame_note", swiss.straight_line_distance_3d("a", "b"))

    def test_tool_returns_json_and_actionable_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_tools(BuildingMap(building()), Path(temporary))}
        result = json.loads(tools["straight_line_distance_3d"].call({"first": "a", "second": "top"}))
        self.assertEqual(result["distance_m"], round(math.hypot(3, 7.5), 3))
        with self.assertRaises(ToolError):
            tools["straight_line_distance_3d"].call({"first": "a", "second": "missing"})


if __name__ == "__main__":
    unittest.main()
