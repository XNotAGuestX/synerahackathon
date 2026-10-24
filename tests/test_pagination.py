"""Exercise formerly capped lists through actual tools, including complete totals and isolated what-ifs."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError

from final_agent.building_map import BuildingMap
from final_agent.tools import make_tools


def inventory_map(connected_exit: bool = True) -> BuildingMap:
    spaces = [
        {"id": f"r{i:03}", "name": f"Room {i:03}", "floor_id": "F0", "type": "room", "room_type": "office",
         "polygon": [[-4 * (i + 1), -2], [-4 * i, -2], [-4 * i, 2], [-4 * (i + 1), 2]]}
        for i in range(65)
    ]
    spaces.append({"id": "exit", "name": "Exit", "floor_id": "F0", "type": "hall", "room_type": "lobby",
                   "polygon": [[0, -2], [4, -2], [4, 2], [0, 2]]})

    def door(identifier, first, second, x, y):
        return {"id": identifier, "floor_id": "F0", "kind": "door", "space_ids": [first, second],
                "position": [x, y], "width_m": 1.0, "step_free": True}

    openings = [door(f"d{i}", f"r{i-1:03}", f"r{i:03}", -4 * i, 0) for i in range(1, 65)]
    openings.append(door("entry", "exit", "outside", 4, 0))
    if connected_exit:
        openings.append(door("detour", "r000", "exit", 0, 1.5))
    return BuildingMap({
        "building": {"id": "pages", "name": "Pages", "units": "m"},
        "floors": [{"id": "F0", "level": 0, "name": "Ground", "elevation_m": 0}],
        "spaces": spaces, "openings": openings, "vertical_connectors": [],
        "assets": [{"id": f"a{i:03}", "name": f"Bin {i}", "type": "bin", "space_id": "r000",
                    "floor_id": "F0", "position": [-2, 0]} for i in range(65)],
    })


class PaginationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.building = inventory_map()
        self.tools = {tool.name: tool for tool in make_tools(self.building, Path(self.directory.name))}

    def call(self, tool, **arguments):
        return json.loads(self.tools[tool].call(arguments))

    def test_room_pages_preserve_complete_counts_areas_ids_and_active_route(self):
        self.building.route("r000", "r001")
        route, request = self.building.last_route, self.building.active_request
        cases = [
            ("reachable_rooms", {"start": "r000", "floor_level": 0}, "room_ids"),
            ("sum_floor_area", {"room_type": "office", "floor_level": 0}, "space_ids"),
        ]
        for name, arguments, ids_key in cases:
            with self.subTest(tool=name):
                first = self.call(name, **arguments)
                second = self.call(name, **arguments, page=first["next_page"])
                self.assertEqual((first["count"], second["count"], first["matches"]), (65, 65, 65))
                self.assertEqual(first[ids_key], second[ids_key])
                self.assertEqual([r["id"] for r in first["rooms"] + second["rooms"]], first[ids_key])
                self.assertFalse(second["has_more"])
                if name == "sum_floor_area":
                    self.assertEqual((first["area_m2"], second["area_m2"]), (1040, 1040))
                empty = self.call(name, **arguments, page=3)
                self.assertEqual((empty["count"], empty["rooms"], empty["next_page"]), (65, [], None))
        self.assertIs(self.building.last_route, route)
        self.assertIs(self.building.active_request, request)

    def test_landmark_candidates_and_competitors_can_both_be_exhausted(self):
        arguments = dict(x_m=-2, y_m=0, floor_level=0, inner_radius=1, outer_radius=1)
        ids, page = [], 1
        while page is not None:
            result = self.call("find_navigation_landmarks", **arguments, page=page)
            ids.extend(item["id"] for item in result["candidates"])
            self.assertEqual((result["candidate_count"], result["unambiguous_count"]), (65, 0))
            page = result["next_page"]
        self.assertEqual(ids, [f"a{i:03}" for i in range(65)])
        rivals, page = [], 1
        while page is not None:
            candidate = self.call("find_navigation_landmarks", **arguments, competitor_page=page)["candidates"][0]
            self.assertEqual((candidate["similar_count_outer"], candidate["is_unambiguous"]), (64, False))
            rivals.extend(candidate["competitor_ids"])
            page = candidate["competitors_page"]["next_page"]
        self.assertEqual(rivals, [f"a{i:03}" for i in range(1, 65)])

    def test_destination_context_is_filtered_before_paging_the_full_inventory(self):
        arguments = dict(space="exit", radius_m=300, min_area_m2=0, page_size=100)
        complete = self.call("describe_destination_context", **arguments)
        self.assertEqual((complete["candidate_count"], len(complete["context"])), (65, 65))
        first = self.call("describe_destination_context", **{**arguments, "page_size": 50})
        second = self.call("describe_destination_context", **{**arguments, "page_size": 50}, page=first["next_page"])
        self.assertEqual(first["context"] + second["context"], complete["context"])
        self.assertEqual(second["candidate_count"], 65)
        self.assertFalse(second["has_more"])

    def test_what_if_pages_preserve_both_count_kinds_without_mutating_the_building(self):
        for connected, list_key in ((True, "improved_rooms"), (False, "newly_reachable")):
            with self.subTest(connected=connected):
                building = inventory_map(connected)
                before = copy.deepcopy(building.data)
                tools = {tool.name: tool for tool in make_tools(building, Path(self.directory.name))}
                args = dict(first_space="r000", second_space="exit", floor_level=0, improvement_threshold_m=0.5)
                first = json.loads(tools["analyze_what_if_door"].call(args))
                second = json.loads(tools["analyze_what_if_door"].call({**args, "page": first[list_key + "_page"]["next_page"]}))
                self.assertEqual((first["count"], second["count"]), (65, 65))
                combined = first[list_key] + second[list_key]
                ids = [item["id"] if isinstance(item, dict) else item for item in combined]
                self.assertEqual(sorted(ids), [f"r{i:03}" for i in range(65)])
                self.assertFalse(second[list_key + "_page"]["has_more"])
                self.assertEqual(building.data, before)
                self.assertIsNone(building.last_route)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_invalid_paging_is_an_actionable_tool_error(self):
        cases = [
            ("inspect_space", {"space": "r000"}),
            ("reachable_rooms", {"start": "r000"}),
            ("sum_floor_area", {"room_type": "office", "floor_level": 0}),
            ("analyze_what_if_door", {"first_space": "r000", "second_space": "exit", "floor_level": 0}),
            ("find_navigation_landmarks", dict(x_m=-2, y_m=0, floor_level=0, inner_radius=1, outer_radius=1)),
            ("describe_destination_context", {"space": "r000"}),
        ]
        for name, arguments in cases:
            for bad in ({"page": 0}, {"page_size": 101}):
                with self.subTest(tool=name, bad=bad), self.assertRaises(ToolError):
                    self.call(name, **arguments, **bad)
        with self.assertRaises(ToolError):
            self.call("find_navigation_landmarks", **cases[4][1], competitor_page=0)


if __name__ == "__main__":
    unittest.main()
