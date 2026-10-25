"""Synera logistics rules on actual polygons and selected openings, without model calls."""

import json
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError

from final_agent.building_map import BuildingMap, MapError
from final_agent.tools import make_tools
from final_agent.viewer import route_polylines


def factory_map() -> BuildingMap:
    spaces = []
    for name, bounds, room_type, broad_type in [
        ("left", (0, 0, 4, 4), "logistics_zone", "room"),
        ("bay", (4, 0, 8, 4), "production_zone", "hall"),
        ("right", (8, 0, 12, 4), "warehouse_zone", "room"),
        ("aisle", (0, 4, 12, 8), "corridor", "corridor"),
    ]:
        x0, y0, x1, y1 = bounds
        spaces.append({"id": name, "name": name.title(), "floor_id": "F0", "type": broad_type,
                       "room_type": room_type, "ref": name, "synthetic": False, "forklift_access": True,
                       "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]})
    openings = [
        {"id": name, "floor_id": "F0", "space_ids": [first, second], "kind": "opening",
         "position": position, "width_m": 3.0, "step_free": True, "synthetic": False, "forklift_access": True}
        for name, first, second, position in [
            ("left-bay", "left", "bay", [4, 2]), ("bay-right", "bay", "right", [8, 2]),
            ("left-aisle", "left", "aisle", [2, 4]), ("aisle-right", "aisle", "right", [10, 4]),
        ]
    ]
    return BuildingMap({
        "building": {"id": "test", "name": "Factory", "units": "m", "source": "test", "split": "dev",
                     "license": "CC0-1.0", "attribution": "Test fixture"},
        "floors": [{"id": "F0", "name": "Ground", "level": 0, "elevation_m": 0, "height_m": 4}],
        "spaces": spaces, "openings": openings, "vertical_connectors": [],
        "assets": [{"id": "machine", "name": "Machine", "type": "machine", "category": "machine",
                    "space_id": "bay", "floor_id": "F0", "position": [7.5, 0.5], "source": "test",
                    "footprint": {"width_m": 1, "depth_m": 1, "rotation_deg": 0}}],
    })


class RouteRulesTests(unittest.TestCase):
    def assert_unreachable(self, building, start="left", destination="right"):
        with self.assertRaises(MapError) as raised:
            building.route(start, destination, travel_mode="forklift")
        self.assertEqual(raised.exception.reason, "unreachable")

    def test_bay_shortcut_is_replaced_with_drawable_aisle_route(self):
        building = factory_map()
        self.assertEqual(building.route("left", "right").space_path, ["left", "bay", "right"])
        route = building.route("left", "right", travel_mode="forklift")
        self.assertEqual(route.space_path, ["left", "aisle", "right"])
        self.assertEqual(route.element_path, ["left-aisle", "aisle-right"])
        self.assertEqual((route.step_free, route.min_width_m, route.strict_geometry), (True, 3, True))
        polylines = route_polylines(building, route)
        self.assertTrue(polylines)
        self.assertGreater(sum(len(points) for _, points in polylines), 2)

    def test_production_bay_is_valid_start_destination_or_explicit_stop(self):
        building = factory_map()
        self.assertEqual(building.route("left", "machine", travel_mode="forklift").destination_space_id, "bay")
        self.assertEqual(building.route("bay", "right", travel_mode="forklift").space_path, ["bay", "right"])
        route = building.route("left", "right", via=["bay"], travel_mode="forklift")
        self.assertEqual([leg["space_path"] for leg in route.legs], [["left", "bay"], ["bay", "right"]])
        for room_type in ("assembly_zone", "additive_zone"):
            building.spaces["bay"]["room_type"] = room_type
            self.assertEqual(building.route("left", "right", travel_mode="forklift").space_path, ["left", "aisle", "right"])

    def test_exact_width_threshold_and_stronger_load_width(self):
        building = factory_map()
        building.route("left", "right", travel_mode="forklift")  # Exactly 3 m is allowed.
        building.openings["left-aisle"]["width_m"] = 2.999
        self.assert_unreachable(building)
        building.openings["left-aisle"]["width_m"] = 3
        with self.assertRaises(MapError):
            building.route("left", "right", min_width_m=3.1, travel_mode="forklift")

    def test_pedestrian_aisle_and_denied_opening_are_excluded(self):
        building = factory_map()
        building.spaces["aisle"]["forklift_access"] = False
        self.assert_unreachable(building)
        building.spaces["aisle"]["forklift_access"] = True
        building.openings["left-aisle"]["forklift_access"] = False
        self.assert_unreachable(building)

    def test_closures_steps_and_vertical_connectors_cannot_bypass_rules(self):
        for closure in ("aisle", "left-aisle"):
            building = factory_map()
            building.set_closed(closure, True)
            self.assert_unreachable(building)
        building = factory_map()
        building.openings["left-aisle"]["step_free"] = False
        building.data["vertical_connectors"].append({"id": "lift", "kind": "lift", "name": "Lift",
            "space_ids": ["left", "right"], "floor_ids": ["F0", "F0"], "step_free": True})
        building.connectors["lift"] = building.data["vertical_connectors"][0]
        self.assert_unreachable(building)

    def test_missing_designations_are_unverified_not_unreachable(self):
        for record in ("space", "opening"):
            building = factory_map()
            item = building.spaces["aisle"] if record == "space" else building.openings["left-aisle"]
            del item["forklift_access"]
            with self.assertRaises(MapError) as raised:
                building.route("left", "right", travel_mode="forklift")
            self.assertEqual(raised.exception.reason, "access_unverified")
            self.assertIsNone(building.last_route)

    def test_reroute_retains_mode_and_can_recover_after_reopening(self):
        building = factory_map()
        building.route("left", "right", travel_mode="forklift")
        building.set_closed("aisle", True)
        with self.assertRaises(MapError):
            building.recompute_active_route()
        self.assertEqual(building.active_request["travel_mode"], "forklift")
        self.assertIsNone(building.last_route)
        building.set_closed("aisle", False)
        self.assertEqual(building.recompute_active_route().space_path, ["left", "aisle", "right"])

    def test_errand_tour_and_counts_obey_the_same_rules(self):
        building = factory_map()
        errand = building.plan_errand("left", "machine", "warehouse_zone", 0, travel_mode="forklift", activate=True)
        self.assertEqual([leg.space_path for leg in errand["leg_routes"]], [["left", "bay"], ["bay", "right"]])
        tour = building.find_best_tour("left", ["bay"], "right", travel_mode="forklift")
        self.assertEqual(tour["route"].travel_mode, "forklift")
        building.set_closed("aisle", True)
        self.assertEqual(building.reachable_rooms("left", travel_mode="forklift")["room_ids"], ["left"])

    def test_forklift_excludes_inherited_geometry_estimates(self):
        building = factory_map()
        building.spaces["left"]["polygon"] = [[0, 0], [4, 0], [4, 2], [0.1, 2], [0.1, 10], [0, 10]]
        building.openings["left-bay"]["position"] = [4, 1]
        building.set_closed("aisle", True)
        self.assertTrue(building.route("left", "bay").length_m > 0)
        self.assert_unreachable(building, destination="bay")

    def test_tour_can_reorder_through_an_explicit_bay_and_reports_impossible_order(self):
        building = factory_map()
        building.set_closed("aisle", True)
        tour = building.find_best_tour("left", ["right", "bay"], "right", travel_mode="forklift")
        self.assertEqual(tour["stop_sequence"], ["left", "bay", "right", "right"])
        self.assertIsNone(tour["given_order_length_m"])
        with self.assertRaisesRegex(MapError, "no valid visiting order"):
            building.find_best_tour("bay", ["left"], "right", travel_mode="forklift")

    def test_unverified_start_cannot_count_as_a_reachable_delivery_room(self):
        building = factory_map()
        del building.spaces["left"]["forklift_access"]
        with self.assertRaises(MapError) as raised:
            building.reachable_rooms("left", travel_mode="forklift")
        self.assertEqual(raised.exception.reason, "access_unverified")

    def test_workspace_preserves_forklift_mode_on_failed_route_and_resume(self):
        from final_agent.workspace import Workspace, make_workspace_tools
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory_map().save(root / "factory.json")
            workspace = Workspace(root / "session")
            workspace.register(str(root / "factory.json"))
            tools = {tool.name: tool for tool in make_workspace_tools(workspace)}
            tools["find_route"].call({"start": "left", "destination": "right", "travel_mode": "forklift"})
            building = workspace.building()["map"]
            building.set_closed("aisle", True)
            with self.assertRaises(ToolError):
                tools["find_route"].call({"start": "left", "destination": "right"})
            self.assertEqual(building.active_request["travel_mode"], "forklift")
            restored = Workspace(workspace.directory).building()["map"]
            self.assertEqual(restored.active_request["travel_mode"], "forklift")

    def test_tool_output_save_reload_and_invalid_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            building = factory_map()
            tools = {tool.name: tool for tool in make_tools(building, Path(temporary))}
            route = json.loads(tools["find_route"].call({"start": "left", "destination": "right", "travel_mode": "forklift"}))
            self.assertEqual((route["travel_mode"], route["space_path"]), ("forklift", ["left", "aisle", "right"]))
            followup = json.loads(tools["find_route"].call({"start": "right", "destination": "left"}))
            self.assertEqual(followup["travel_mode"], "forklift")
            with self.assertRaises(ToolError):
                tools["find_route"].call({"start": "left", "destination": "right", "travel_mode": "flying"})
            building.save(Path(temporary) / "building.json")
            self.assertEqual(BuildingMap.load(Path(temporary)).route("left", "right", travel_mode="forklift").space_path,
                             ["left", "aisle", "right"])
        invalid = factory_map().data
        invalid["spaces"][0]["forklift_access"] = "yes"
        with self.assertRaises(MapError):
            BuildingMap(invalid)
