"""Route results, constraints, active-route state, door placement and edit rollback on tiny buildings."""

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shapely.geometry import LineString

from anthropic.lib.tools import ToolError

from final_agent.building_map import BuildingMap, MapError, outline, walking_lengths, walking_path
from final_agent.tools import make_tools
from final_agent.viewer import route_polylines
from test_storage import example_building


def door(opening_id, first, second, x, y, width=0.9, step_free=True, kind="door"):
    return {"id": opening_id, "floor_id": "F0", "space_ids": [first, second], "kind": kind,
            "position": [x, y], "width_m": width, "step_free": step_free}


def connector(connector_id, kind, step_free):
    return {"id": connector_id, "kind": kind, "name": connector_id, "step_free": step_free,
            "floor_ids": ["F0", "F1"], "space_ids": ["left", "upstairs"]}


def make_map(openings=(), connectors=()) -> BuildingMap:
    data = example_building()
    data["building"]["source"] = "test"
    data["openings"] = list(openings)
    data["vertical_connectors"] = list(connectors)
    return BuildingMap(data)


def entrance_map(**entrance_options) -> BuildingMap:
    return make_map([
        door("E1", "left", "outside", -4, 0, kind="entrance"),
        door("E2", "right", "outside", 4, 0, kind="entrance", **entrance_options),
    ])


class RouteResultTests(unittest.TestCase):
    def test_step_free_never_uses_stairs_even_if_mislabelled(self):
        building = make_map(connectors=[connector("stairs", "stairs", True)])
        self.assertEqual(building.route("left", "upstairs").element_path, ["stairs"])
        with self.assertRaises(MapError):
            building.route("left", "upstairs", step_free=True)

    def test_parallel_stairs_and_lift_record_the_chosen_connector(self):
        building = make_map(connectors=[connector("V1", "stairs", False), connector("V2", "lift", True)])
        self.assertEqual(building.route("left", "upstairs").element_path, ["V1"])
        result = building.route("left", "upstairs", step_free=True)
        self.assertEqual((result.element_path, result.length_m), (["V2"], 18.0))
        self.assertIn("Take V2 (lift) to First.", result.steps)
        self.assertEqual([segment["floor_id"] for segment in result.floor_segments], ["F0", "F1"])

    def test_lift_skips_intermediate_stop_and_charges_wait_once(self):
        data = example_building()
        data["floors"].append({"id": "F3", "level": 3, "name": "Third", "elevation_m": 11.4})
        data["spaces"].append({**data["spaces"][2], "id": "top", "name": "Top", "floor_id": "F3"})
        lift = connector("lift", "lift", True)
        lift["floor_ids"].append("F3")
        lift["space_ids"].append("top")
        data["vertical_connectors"] = [lift]
        building = BuildingMap(data)
        result = building.route("left", "top", step_free=True)
        self.assertEqual(result.node_path, ["left", "top"])
        self.assertEqual(result.element_path, ["lift"])
        self.assertAlmostEqual(result.length_m, 26.4)
        building.set_closed("upstairs", True)
        self.assertAlmostEqual(building.route("left", "top", step_free=True).length_m, 26.4)

    def test_door_to_door_path_includes_corridor_without_visiting_its_anchor(self):
        data = example_building()
        data["spaces"][1]["polygon"] = [[12, -2], [16, -2], [16, 2], [12, 2]]
        data["spaces"].append({"id": "hall", "name": "Hall", "floor_id": "F0", "room_type": "corridor",
                               "polygon": [[0, -2], [12, -2], [12, 8], [0, 8]]})
        data["openings"] = [door("D1", "left", "hall", 0, 0), door("D2", "hall", "right", 12, 0)]
        building = BuildingMap(data)
        result = building.route("left", "right")
        self.assertAlmostEqual(result.length_m, 16.0)
        self.assertEqual(result.space_path, ["left", "hall", "right"])
        self.assertNotIn("hall", result.node_path)
        self.assertEqual(result.element_path, ["D1", "D2"])
        points = route_polylines(building, result)[0][1]
        self.assertNotIn(building.anchor("hall"), points)
        self.assertTrue(all(y == 0 for _, y in points))

    def test_l_shaped_walk_goes_around_the_inner_corner(self):
        polygon = outline([(0, 0), (6, 0), (6, 2), (2, 2), (2, 6), (0, 6)])
        start, end = (5.0, 1.0), (1.0, 5.0)
        points = walking_path(polygon, start, end)
        length = walking_lengths(polygon, [start, end])[(0, 1)]
        self.assertGreater(length, math.dist(start, end) + 0.5)
        self.assertAlmostEqual(sum(math.dist(a, b) for a, b in zip(points, points[1:])), length)
        self.assertTrue(polygon.buffer(-0.15).buffer(0.02).covers(LineString(points)))

    def test_parallel_doors_use_the_recorded_cheapest_door(self):
        building = make_map([door("far", "left", "right", 0, 1.5), door("D1", "left", "right", 0, 0)])
        result = building.route("left", "right")
        self.assertEqual(result.element_path, ["D1"])
        self.assertEqual(result.node_path, ["left", "door:D1", "right"])
        self.assertEqual(
            route_polylines(building, result),
            [("F0", [building.anchor("left"), (-0.3, 0.0), (0, 0), (0.3, 0.0), building.anchor("right")])],
        )

    def test_same_room_and_repeated_stop(self):
        building = make_map([door("D1", "left", "right", 0, 0)])
        same = building.route("left", "left")
        self.assertEqual((same.length_m, same.space_path, same.element_path), (0.0, ["left"], []))
        repeated = building.route("left", "right", via=["right"])
        self.assertEqual(repeated.stops, ["left", "right", "right"])
        self.assertEqual(repeated.legs[1]["length_m"], 0.0)
        self.assertEqual(repeated.element_path, repeated.legs[0]["element_path"])

    def test_separate_entrances_do_not_connect_through_outside(self):
        building = entrance_map()
        with self.assertRaisesRegex(MapError, "No route"):
            building.route("left", "right")
        self.assertIsNone(building.last_route)
        self.assertNotIn("outside", building.graph())

    def test_min_width_equality_passes_and_narrower_fails_with_leg_and_constraints(self):
        building = make_map([door("D1", "left", "right", 0, 0, width=0.9)])
        self.assertEqual(building.route("left", "right", min_width_m=0.9).element_path, ["D1"])
        with self.assertRaisesRegex(MapError, r"leg 1 of 1.*step_free=True.*min_width_m=0.91.*closed=\[\]"):
            building.route("left", "right", step_free=True, min_width_m=0.91)
        with self.assertRaises(MapError):
            building.route("left", "right", min_width_m=-1)

    def test_closed_endpoints_are_named_and_failure_clears_the_route(self):
        building = make_map([door("D1", "left", "right", 0, 0)])
        self.assertIsNotNone(building.route("left", "right"))
        building.set_closed("right", True)
        for start, destination in (("left", "right"), ("right", "left")):
            with self.assertRaisesRegex(MapError, "Right .* is closed.*closed=\\['right'\\]"):
                building.route(start, destination)
        building.set_closed("right", False)
        building.route("left", "right")
        with self.assertRaisesRegex(MapError, "leg 1 of 1"):
            building.route("left", "upstairs")
        self.assertIsNone(building.last_route)

    def test_entrance_identity_is_validated_against_the_constraints(self):
        building = entrance_map(step_free=False, width=0.8)
        self.assertEqual([entrance["id"] for entrance in building.entrances_into("left")], ["E1"])
        cases = [
            ({"entrance": "nope"}, "Unknown entrance"),
            ({"entrance": "E1", "start": "right", "destination": "left"}, "does not open into"),
            ({"entrance": "E2", "start": "right", "destination": "left", "step_free": True}, "has steps"),
            ({"entrance": "E2", "start": "right", "destination": "left", "min_width_m": 0.9}, "narrower"),
        ]
        for options, message in cases:
            arguments = {"start": "left", "destination": "right", **options}
            with self.subTest(message=message), self.assertRaisesRegex(MapError, message):
                building.compute_route(**arguments)
        building.set_closed("E1", True)
        with self.assertRaisesRegex(MapError, "Entrance E1 is closed"):
            building.compute_route("left", "right", entrance="E1")
        with self.assertRaisesRegex(MapError, "not an entrance"):
            make_map([door("D1", "left", "right", 0, 0)]).compute_route("left", "right", entrance="D1")

    def test_compute_route_is_pure_and_closure_recomputes_the_active_route(self):
        building = make_map([door("near", "left", "right", 0, 0), door("far", "left", "right", 0, 1.5)])
        building.compute_route("left", "right")
        self.assertIsNone(building.last_route)
        self.assertIsNone(building.active_request)
        building.route("left", "right", min_width_m=0.5)
        building.set_closed("near", True)
        self.assertIsNone(building.last_route)
        self.assertEqual(building.recompute_active_route().element_path, ["far"])
        building.set_closed("far", True)
        with self.assertRaises(MapError):
            building.recompute_active_route()
        self.assertIsNone(building.last_route)
        building.set_closed("far", False)
        self.assertEqual(building.recompute_active_route().min_width_m, 0.5)


class DoorPlacementTests(unittest.TestCase):
    def test_door_sits_at_the_shared_wall_midpoint_with_a_unique_id(self):
        building = make_map([door("F0-O-new1", "left", "right", 0, 1.9)])
        opening = building.add_door("left", "right", width_m=1.2)
        self.assertEqual(opening["position"], [0, 0])
        self.assertEqual((opening["id"], opening["width_m"], opening["synthetic"]), ("F0-O-new2", 1.2, True))
        self.assertEqual((opening["floor_id"], opening["space_ids"]), ("F0", ["left", "right"]))
        self.assertIn(opening, building.data["openings"])
        with self.assertRaisesRegex(MapError, "already joins"):
            building.add_door("right", "left")

    def test_invalid_doors_are_rejected_without_changes(self):
        data = example_building()
        data["spaces"].append({"id": "corner", "name": "Corner", "floor_id": "F0", "room_type": "office",
                               "polygon": [[-8, 2], [-4, 2], [-4, 6], [-8, 6]]})
        building = BuildingMap(data)
        for arguments in (("left", "left"), ("left", "upstairs"), ("left", "corner"),
                          ("left", "right", True, 0), ("left", "right", True, 5)):
            with self.subTest(arguments=arguments), self.assertRaises(MapError):
                building.add_door(*arguments)
        self.assertEqual((building.openings, data["openings"]), ({}, []))

    def test_shared_wall_reports_runs_and_midpoint(self):
        building = make_map()
        wall = building.shared_wall("left", "right")
        # Outline stretches beside the wall ends (within 0.35 m) are not wall: exactly the 4 m wall.
        self.assertAlmostEqual(wall["total_length_m"], 4.0, places=3)
        self.assertEqual(len(wall["runs"]), 1)
        self.assertAlmostEqual(wall["midpoint"][0], 0)
        self.assertAlmostEqual(wall["midpoint"][1], 0)
        self.assertAlmostEqual(building.shared_wall("left", "right", tolerance_m=0)["total_length_m"], 4.0)


class EditRollbackAndToolTests(unittest.TestCase):
    def test_tools_report_the_active_route_after_an_edit(self):
        building = make_map([door("near", "left", "right", 0, 1)])
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_tools(building, Path(temporary))}
            route = json.loads(tools["find_route"].call({"start": "left", "destination": "right"}))
            self.assertEqual(route["length_m"], round(route["length_m"], 2))
            added = json.loads(tools["add_door"].call({"first_space": "left", "second_space": "right",
                                                        "width_m": 0.5}))
            self.assertIn("active_route", added)
            closed = json.loads(tools["set_closed"].call({"element": "near", "closed": True}))
            self.assertEqual(closed["active_route"]["element_path"], [added["added"]["id"]])
            building.set_closed(added["added"]["id"], True)
            failed = json.loads(tools["set_closed"].call({"element": "right", "closed": True}))
            self.assertIn("is closed", failed["active_route_error"])

    def test_failed_save_restores_the_map_and_reports_not_applied(self):
        building = make_map([door("near", "left", "right", 0, 1.5)])
        building.spatial_search(0, 0, 0)
        building.route("left", "right")
        before = (set(building.closed), dict(building.openings), list(building.data["openings"]))
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_tools(building, Path(temporary))}
            with patch("final_agent.building_map.JsonBuildingStore.save", side_effect=OSError("disk full")):
                for name, arguments in (
                    ("set_closed", {"element": "near", "closed": True}),
                    ("add_door", {"first_space": "left", "second_space": "right", "width_m": 0.3}),
                ):
                    with self.subTest(tool=name), self.assertRaisesRegex(ToolError, "NOT applied.*disk full"):
                        tools[name].call(arguments)
                    self.assertEqual(
                        (building.closed, building.openings, building.data["openings"]), before
                    )
                    self.assertIsNone(building._spatial_index)
                    self.assertIsNotNone(building.last_route)


if __name__ == "__main__":
    unittest.main()
