"""analyze_what_if_door: strict threshold, cross-floor effects, infinity handling and zero side effects."""

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError

from final_agent.building_map import BuildingMap, MapError
from final_agent.tools import make_tools


def space(space_id, floor_id, x, y, kind="room"):
    return {"id": space_id, "name": space_id, "floor_id": floor_id, "type": kind, "room_type": kind,
            "polygon": [[x, y], [x + 4, y], [x + 4, y + 4], [x, y + 4]]}


def opening(opening_id, spaces, x, y, kind="door"):
    return {"id": opening_id, "floor_id": "F0", "space_ids": spaces, "kind": kind, "position": [x, y],
            "width_m": 1.0, "step_free": True}


def make_map(far_y: float | None = 1.5, closed=()) -> BuildingMap:
    """Ground X(-4..0) | Y(0..4) with the entrance at (4, 0); a detour door X-Y at (0, far_y) when given.

    X's anchor is (-2, 0) and Y's (2, 0), so the midpoint door (0, 0) shortens X's exit by
    2*sqrt(4 + far_y^2) - 4: exactly 1.0 m for far_y = 1.5. U above X (stairs), Z isolated, C touches X's corner.
    """
    openings = [opening("E", ["Y", "outside"], 4, 0, "entrance")]
    if far_y is not None:
        openings.append(opening("far", ["X", "Y"], 0, far_y))
    return BuildingMap({
        "building": {"id": "test", "name": "Test", "units": "m"},
        "floors": [{"id": "F0", "level": 0, "name": "Ground"}, {"id": "F1", "level": 1, "name": "First"}],
        "spaces": [
            space("X", "F0", -4, -2), space("Y", "F0", 0, -2), space("U", "F1", -4, -2),
            space("Z", "F0", 20, 0), space("C", "F0", -8, 2),
            space("H", "F0", 0, 2, "hall"),
        ],
        "assets": [], "openings": openings,
        "vertical_connectors": [{"id": "V", "kind": "stairs", "name": "V", "step_free": False,
                                 "floor_ids": ["F0", "F1"], "space_ids": ["X", "U"]}],
        "navigation_state": {"closed": list(closed)},
    })


def far_y_for_gain(gain: float) -> float:
    return math.sqrt(((gain + 4) / 2) ** 2 - 4)


def snapshot(building: BuildingMap) -> tuple:
    return (json.dumps(building.data, sort_keys=True), sorted(building.closed), sorted(building.openings),
            building.last_route, building.active_request, building._spatial_index)


class WhatIfCountTests(unittest.TestCase):
    def test_only_improvements_strictly_above_the_threshold_count(self):
        for gain, expected in ((0.99, 0), (1.0, 0), (1.01, 1)):
            with self.subTest(gain=gain):
                result = make_map(far_y_for_gain(gain)).analyze_what_if_door("X", "Y", floor_level=1)
                self.assertEqual(result["count"], expected)
        exact = make_map(1.5).analyze_what_if_door("X", "Y", floor_level=1, improvement_threshold_m=0.5)
        self.assertEqual([r["improvement_m"] for r in exact["improved_rooms"]], [1.0])

    def test_door_floor_may_differ_from_target_floor(self):
        building = make_map(far_y_for_gain(3.0))
        upper = building.analyze_what_if_door("X", "Y", floor_level=1)
        self.assertEqual((upper["door_floor_level"], upper["target_floor_level"]), (0, 1))
        self.assertEqual([(r["id"], r["improvement_m"]) for r in upper["improved_rooms"]], [("U", 3.0)])
        ground = building.analyze_what_if_door("X", "Y", floor_level=0)
        self.assertEqual([r["id"] for r in ground["improved_rooms"]], ["X"])
        self.assertEqual(ground["eligible_rooms"], 4)  # X, Y, Z, C: the hall is not a room
        self.assertEqual(upper["proposed_door"]["position"], [0, 0])
        self.assertEqual(upper["proposed_door"]["space_ids"], ["X", "Y"])

    def test_unreachable_before_is_newly_reachable_and_unreachable_in_both_never_counts(self):
        for building in (make_map(far_y=None), make_map(closed=["far"])):
            result = building.analyze_what_if_door("X", "Y", floor_level=0)
            self.assertEqual((result["count"], result["newly_reachable"], result["improved_rooms"]), (1, ["X"], []))
            self.assertEqual(result["newly_reachable_count"], 1)
        # Z and C stay unreachable in both states; U follows X through the stairs.
        floor_one = make_map(far_y=None).analyze_what_if_door("X", "Y", floor_level=1)
        self.assertEqual((floor_one["count"], floor_one["newly_reachable"]), (1, ["U"]))

    def test_invalid_proposed_doors_raise_without_changing_state(self):
        building = make_map()
        building.route("X", "Y")
        before = snapshot(building)
        for arguments in (("X", "Z", 0), ("X", "C", 0), ("X", "U", 0), ("X", "X", 0), ("X", "Y", 5),
                          ("X", "nowhere", 0)):
            with self.subTest(arguments=arguments), self.assertRaises(MapError):
                building.analyze_what_if_door(*arguments)
        with self.assertRaises(MapError):
            building.analyze_what_if_door("X", "Y", 0, improvement_threshold_m=-1)
        self.assertEqual(snapshot(building), before)


class WhatIfIsolationTests(unittest.TestCase):
    def test_original_map_and_saved_file_are_unchanged_after_success_and_failure(self):
        building = make_map(closed=["far"])
        building.spatial_search(0, 0, 0)
        building.route("X", "U")
        building.active_request = {"kind": "route"}
        route, index, request = building.last_route, building._spatial_index, building.active_request
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "building.json"
            building.save(path)
            saved = path.read_bytes()
            before = snapshot(building)
            data_copy = copy.deepcopy(building.data)
            tools = {tool.name: tool for tool in make_tools(building, Path(temporary))}
            result = json.loads(tools["analyze_what_if_door"].call(
                {"first_space": "X", "second_space": "Y", "floor_level": 1}))
            self.assertTrue(result["simulated"])
            self.assertEqual(result["count"], 1)
            with self.assertRaises(ToolError):
                tools["analyze_what_if_door"].call({"first_space": "X", "second_space": "Z", "floor_level": 1})
            self.assertEqual(snapshot(building), before)
            self.assertEqual(building.data, data_copy)
            self.assertEqual(sorted(building.openings), ["E", "far"])
            self.assertEqual(building.closed, {"far"})
            self.assertIs(building.last_route, route)
            self.assertIs(building._spatial_index, index)
            self.assertIs(building.active_request, request)
            self.assertEqual(path.read_bytes(), saved)

    def test_short_shared_wall_gets_a_narrower_what_if_door(self):
        data = make_map(far_y=None).data
        data["spaces"].append({"id": "N", "name": "N", "floor_id": "F0", "type": "room", "room_type": "room",
                               "polygon": [[-4, 2], [-3.5, 2], [-3.5, 3], [-4, 3]]})
        result = BuildingMap(data).analyze_what_if_door("X", "N", floor_level=0)
        self.assertAlmostEqual(result["proposed_door"]["width_m"], 0.5, places=2)


if __name__ == "__main__":
    unittest.main()
