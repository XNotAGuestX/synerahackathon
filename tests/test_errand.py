"""plan_errand: nearest pickup by route distance first, then the largest destination; no fallbacks."""

import json
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError

from final_agent.building_map import BuildingMap, MapError
from final_agent.tools import make_tools

# Room centres; a door at each edge's midpoint makes the route cost equal the straight distance.
POINTS = {
    "s": (0, 0),     # start
    "a": (1, 0),     # Euclidean-nearest pickup, but only reachable through the hub
    "b": (-5, 0),    # route-nearest pickup, next to the start
    "h": (0, 10),    # hub
    "d": (0, 20),    # destination
    "c": (2, 0),     # island with an asset: unreachable
    "z": (30, 30),   # island meeting room (a second, unreachable destination type)
}
ROOM_TYPES = {"d": "meeting_room", "z": "lab"}
EDGES = [("s", "b"), ("s", "h"), ("h", "a"), ("h", "d")]


def errand_map(assets: dict[str, str], edges=EDGES, stepped=()) -> BuildingMap:
    """assets maps asset id -> 'space:type'. Edges in stepped are not step-free."""
    spaces = [
        {"id": name, "name": name.upper(), "floor_id": "F0", "type": "room",
         "room_type": ROOM_TYPES.get(name, "office"),
         "polygon": [[x - 1, y - 1], [x + 1, y - 1], [x + 1, y + 1], [x - 1, y + 1]]}
        for name, (x, y) in POINTS.items()
    ]
    openings = [
        {"id": f"{p}-{q}", "floor_id": "F0", "space_ids": [p, q], "kind": "door", "width_m": 1.0,
         "position": [(POINTS[p][0] + POINTS[q][0]) / 2, (POINTS[p][1] + POINTS[q][1]) / 2],
         "step_free": (p, q) not in stepped}
        for p, q in edges
    ]
    assets_list = [
        {"id": asset_id, "name": asset_id, "space_id": spec.split(":")[0], "type": spec.split(":")[1],
         "floor_id": "F0", "position": list(POINTS[spec.split(":")[0]])}
        for asset_id, spec in assets.items()
    ]
    return BuildingMap({
        "building": {"id": "errand", "name": "Errand", "units": "m"},
        "floors": [{"id": "F0", "level": 0, "name": "Ground"}],
        "spaces": spaces, "assets": assets_list, "openings": openings, "vertical_connectors": [],
    })


ASSETS = {"p1": "a:printer", "p2": "b:printer", "p3": "c:printer"}


class ErrandTests(unittest.TestCase):
    def test_route_nearest_pickup_beats_euclidean_nearest(self):
        result = errand_map(ASSETS).plan_errand("s", "printer", "meeting_room", 0)
        self.assertEqual(result["pickup"]["id"], "b")
        self.assertAlmostEqual(result["pickup"]["distance_m"], 5.0)
        self.assertEqual(result["destination"]["id"], "d")
        self.assertAlmostEqual(result["length_m"], 29.59)

    def test_total_is_the_sum_of_two_legs(self):
        result = errand_map(ASSETS).plan_errand("s", "printer", "meeting_room", 0)
        first, second = result["leg_routes"]
        self.assertEqual((first.stops, second.stops), (["s", "b"], ["b", "d"]))
        self.assertAlmostEqual(result["length_m"], first.length_m + second.length_m)
        self.assertEqual(second.space_path, ["b", "s", "h", "d"])

    def test_unreachable_pickup_is_skipped_and_counted(self):
        result = errand_map({"p3": "c:printer", "p2": "b:printer"}).plan_errand("s", "printer", "meeting_room", 0)
        self.assertEqual(result["pickup"]["id"], "b")
        self.assertEqual((result["pickup_candidates"], result["unreachable_candidates"]), (2, 1))
        with self.assertRaisesRegex(MapError, "None of the 1 rooms"):
            errand_map({"p3": "c:printer"}).plan_errand("s", "printer", "meeting_room", 0)

    def test_several_assets_in_one_room_are_one_candidate(self):
        assets = {**ASSETS, "p4": "b:Printer", "p5": "b:printer"}
        result = errand_map(assets).plan_errand("s", "printer", "meeting_room", 0)
        self.assertEqual(result["pickup_candidates"], 3)
        self.assertEqual(result["pickup"]["asset_ids"], ["p2", "p4", "p5"])

    def test_start_room_with_the_asset_is_nearest(self):
        result = errand_map({**ASSETS, "p6": "s:printer"}).plan_errand("s", "printer", "meeting_room", 0)
        self.assertEqual(result["pickup"]["id"], "s")
        self.assertAlmostEqual(result["length_m"], 20.0)

    def test_missing_asset_type_lists_similar_types(self):
        building = errand_map({"x": "b:3d printer"})
        with self.assertRaisesRegex(MapError, r"No asset of type 'printer'.*3d_printer"):
            building.plan_errand("s", "printer", "meeting_room", 0)
        with self.assertRaisesRegex(MapError, "No similar asset type"):
            building.plan_errand("s", "forklift", "meeting_room", 0)

    def test_stairs_allowed_or_step_free_changes_pickup_or_reachability(self):
        building = errand_map(ASSETS, stepped={("s", "b")})
        self.assertEqual(building.plan_errand("s", "printer", "meeting_room", 0)["pickup"]["id"], "b")
        step_free = building.plan_errand("s", "printer", "meeting_room", 0, step_free=True)
        self.assertEqual(step_free["pickup"]["id"], "a")
        only_b = errand_map({"p2": "b:printer"}, stepped={("s", "b")})
        with self.assertRaisesRegex(MapError, "step_free=True"):
            only_b.plan_errand("s", "printer", "meeting_room", 0, step_free=True)

    def test_unreachable_destination_names_leg_two_without_fallback(self):
        building = errand_map(ASSETS)
        building.spaces["z"]["room_type"] = "meeting_room"
        building.spaces["z"]["polygon"] = [[0, 30], [100, 30], [100, 130], [0, 130]]  # the largest one
        with self.assertRaisesRegex(MapError, r"leg 2 of 2.*B .*\[b\].*Z \[z\].*no other pickup"):
            building.plan_errand("s", "printer", "meeting_room", 0)

    def test_missing_destination_type_lists_room_types(self):
        with self.assertRaisesRegex(MapError, "Room types on that floor.*meeting_room"):
            errand_map(ASSETS).plan_errand("s", "printer", "ballroom", 0)

    def test_inactive_errand_keeps_the_active_route_and_activation_replaces_it(self):
        building = errand_map(ASSETS)
        existing = building.route("s", "h")
        request = dict(building.active_request)
        building.plan_errand("s", "printer", "meeting_room", 0)
        self.assertIs(building.last_route, existing)
        self.assertEqual(building.active_request, request)
        result = building.plan_errand("s", "printer", "meeting_room", 0, activate=True)
        self.assertIs(building.last_route, result["route"])
        self.assertEqual(building.active_request["via"], ["b"])
        self.assertAlmostEqual(building.last_route.length_m, result["length_m"])

    def test_tool_returns_one_number_and_two_legs(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = {tool.name: tool for tool in make_tools(errand_map(ASSETS), Path(directory))}
            data = json.loads(tools["plan_errand"].call(
                {"start": "s", "asset_type": "printer", "destination_room_type": "meeting_room",
                 "destination_floor_level": 0}
            ))
            self.assertEqual(data["length_m"], 29.59)
            self.assertEqual([leg["length_m"] for leg in data["legs"]], [5.0, 24.59])
            self.assertEqual(data["distance_model"], "kit-1.1.0")
            self.assertEqual(data["pickup"]["distance_m"], 5.0)
            with self.assertRaises(ToolError):
                tools["plan_errand"].call(
                    {"start": "s", "asset_type": "forklift", "destination_room_type": "meeting_room",
                     "destination_floor_level": 0}
                )


if __name__ == "__main__":
    unittest.main()
