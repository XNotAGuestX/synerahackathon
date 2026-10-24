"""Checks for locate/selection, route drawing and destination context (no API calls)."""

import json
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError

from final_agent import viewer
from final_agent.building_map import BuildingMap, MapError
from final_agent.tools import make_tools


def box(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def space(space_id: str, floor: str, polygon: list, name: str, room_type: str = "office", kind: str = "room") -> dict:
    return {"id": space_id, "name": name, "type": kind, "room_type": room_type, "floor_id": floor, "polygon": polygon}


def door(opening_id: str, floor: str, spaces: list[str], x: float, y: float) -> dict:
    return {"id": opening_id, "floor_id": floor, "space_ids": spaces, "kind": "door", "position": [x, y],
            "width_m": 1.0, "step_free": True}


def chair(number: int, floor: str, room: str) -> dict:
    return {"id": f"chair-{number:02d}", "name": f"Chair {number:02d}", "type": "chair", "space_id": room,
            "floor_id": floor, "position": [2 + number % 5, 3 + number % 4]}


def make_map() -> BuildingMap:
    """Floor G: office A, canteen B (shares a 10 m wall with A), hall F (corner contact only), hall H (0.5 m)."""
    return BuildingMap({
        "building": {"id": "t", "name": "Test building", "source": "test", "units": "m"},
        "floors": [{"id": "G", "level": 0, "name": "Ground", "elevation_m": 0.0},
                   {"id": "F1", "level": 1, "name": "First", "elevation_m": 4.0}],
        "spaces": [
            space("A", "G", box(0, 0, 10, 10), "Office A"),
            space("B", "G", box(10.2, 0, 30, 10), "Canteen", "canteen"),
            space("F", "G", box(10.2, -12.2, 30, -0.2), "Big hall", "warehouse_zone", "hall"),
            space("H", "G", box(-10, 9.5, -0.2, 20), "West hall", "warehouse_zone", "hall"),
            space("K", "G", box(0, 10, 30, 14), "Corridor", "corridor", "corridor"),
            space("LG", "G", box(30, 10, 34, 14), "Lift G", "lift", "lift"),
            space("L1", "F1", box(0, 0, 4, 4), "Lift 1", "lift", "lift"),
            space("U1", "F1", box(4, 0, 14, 10), "Upstairs office"),
        ],
        "assets": [chair(n, "G", "A") for n in range(1, 11)] + [chair(n, "F1", "U1") for n in range(11, 21)],
        "openings": [
            door("A-K2", "G", ["A", "K"], 0.5, 10), door("A-K", "G", ["A", "K"], 5, 10),
            door("B-K", "G", ["B", "K"], 20, 10), door("K-LG", "G", ["K", "LG"], 30, 12),
            door("L1-U1", "F1", ["L1", "U1"], 4, 2),
        ],
        "vertical_connectors": [{"id": "V1", "kind": "lift", "name": "Lift", "floor_ids": ["G", "F1"],
                                 "space_ids": ["LG", "L1"], "step_free": True}],
    })


class MapDisplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.map = make_map()
        self.tools = {tool.name: tool for tool in make_tools(self.map, Path(self.directory.name))}

    def call(self, name: str, **arguments: object) -> dict:
        return json.loads(self.tools[name].call(arguments))

    def test_locate_asset_from_search_page_two_selects_asset_room_and_floor(self) -> None:
        page = self.call("search_building", query="chair", page=2)
        self.assertEqual((page["page"], page["total_pages"], page["matches"]), (2, 2, 20))
        hit = page["results"][0]
        shown = self.call("show_location", element=hit["id"])
        self.assertEqual(self.map.selection["id"], hit["id"])
        self.assertEqual((shown["selected"]["room"]["id"], shown["floor_level"]), ("U1", 1))
        self.assertTrue(Path(shown["image"]).read_bytes().startswith(b"\x89PNG"))
        with self.assertRaises(ToolError):
            self.call("show_location", element="Chair")  # ambiguous: several chairs, no guess

    def test_search_landmarks_previews_and_analysis_keep_the_selection(self) -> None:
        self.call("show_location", element="chair-03")
        selection = dict(self.map.selection)
        self.call("search_building", query="office")
        self.call("spatial_search", x_m=5, y_m=5, floor_level=0)
        self.call("find_navigation_landmarks", x_m=5, y_m=5, floor_level=0, inner_radius=20, outer_radius=25, kind="space")
        self.call("find_best_tour", start="A", stops=["B"], destination="A", activate=False)
        self.call("describe_destination_context", space="A")
        self.call("count_shared_walls", space="A")
        self.assertEqual(self.map.selection, selection)
        self.call("show_location", element="Canteen")
        self.assertEqual(self.map.selection["kind"], "space")

    def test_show_route_reports_no_route_after_unreachable_request_and_closure(self) -> None:
        self.call("find_route", start="A", destination="U1", step_free=True)
        self.assertEqual(self.call("show_route")["floor_levels"], [0, 1])
        self.call("set_closed", element="Lift", closed=True)
        with self.assertRaisesRegex(ToolError, "No active route"):
            self.call("show_route")
        with self.assertRaises(ToolError):
            self.call("find_route", start="A", destination="U1", step_free=True)
        with self.assertRaisesRegex(ToolError, "No active route"):
            self.call("show_route")

    def test_step_free_connector_endpoints_are_included_in_route_floor_views(self) -> None:
        building = BuildingMap.load(Path(__file__).parents[1] / "data/dev/proc-campus-dev-002/building.json")
        route = building.compute_route("proc-campus-dev-002-F0-S005", "proc-campus-dev-002-F3-S005", step_free=True)
        building.last_route = route
        floor_ids = viewer.route_floor_ids(building, route)
        self.assertEqual(floor_ids, ["proc-campus-dev-002-F0", "proc-campus-dev-002-F3"])
        images = viewer.draw_route(building, Path(self.directory.name) / "campus-route")
        self.assertEqual(len(images), 2)
        self.assertTrue(all(path.read_bytes().startswith(b"\x89PNG") for path in images))
        self.assertTrue(any("Lift" in label for _, _, label in viewer.route_handoffs(building, route)))

    def test_plan_preview_overlays_calibrated_candidate_on_source_and_marks_issues(self) -> None:
        source = Path(__file__).parents[1] / "data/dev/proc-campus-dev-002/floor_0.png"
        path = viewer.draw_plan_preview(
            self.map.data, Path(self.directory.name) / "preview.png", source,
            {"pixel_to_metre": {"scale_m_per_px": 1, "origin_px": [0, 0], "origin_m": [0, 0],
                                 "rotation_rad": 0, "y_axis_inverted": False}},
            issues=[{"severity": "error", "element_id": "A", "reason": "Review boundary"}],
            changed_ids=["A"],
        )
        self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))

    def test_campus_route_returns_ordered_floor_and_walkway_views(self) -> None:
        route = {"reachable": True, "route_id": "campus-r1", "campus_revision": 3,
                 "building_revisions": {"t": 4}, "step_free": True, "min_width_m": 0,
                 "legs": [{"kind": "indoor", "building_id": "t", "from_node": "A", "to_node": "B",
                           "node_path": ["A", "door:A-K", "K", "door:B-K", "B"],
                           "edge_ids": ["A", "K", "B"], "length_m": 5},
                          {"kind": "walkway", "walkway_id": "w1", "name": "Covered link", "length_m": 12,
                           "from": {"building_id": "t", "opening_id": "A-K"},
                           "to": {"building_id": "t", "opening_id": "B-K"}}]}
        route["legs"][0].update(from_node="door:A-K", to_node="door:B-K")
        views = viewer.draw_campus_route({"t": {"map": self.map}}, route, Path(self.directory.name) / "campus")
        self.assertEqual([view["kind"] for view in views], ["floor", "walkway"])
        self.assertTrue(all(Path(view["image"]).read_bytes().startswith(b"\x89PNG") for view in views))
        self.assertEqual(views[1]["departure_handoff"]["opening_id"], "A-K")
        with self.assertRaisesRegex(MapError, "stale"):
            viewer.draw_campus_route({"buildings": {"t": {"map": self.map, "revision": 5}}, "revision": 4},
                                     {**route, "campus_revision": 3}, Path(self.directory.name) / "stale")

    def test_plan_preview_keeps_invalid_candidate_renderable(self) -> None:
        draft = make_map().data
        draft["spaces"][0]["polygon"] = []
        path = viewer.draw_plan_preview(
            draft, Path(self.directory.name) / "invalid-preview.png",
            Path(__file__).parents[1] / "data/dev/proc-campus-dev-002/floor_0.png",
            {"pixel_to_metre": {"scale_m_per_px": 1, "origin_px": [0, 0], "origin_m": [0, 0],
                                 "rotation_rad": 0, "y_axis_inverted": False}},
            issues=[{"severity": "error", "element_id": "A", "reason": "Boundary is empty"}],
        )
        self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))
    def test_route_is_drawn_through_the_selected_doors_with_handoffs_and_numbered_stops(self) -> None:
        self.call("find_route", start="A", destination="U1", via=["B"])
        route = self.map.last_route
        used = {self.map.openings[node.removeprefix("door:")]["id"]: tuple(self.map.openings[node.removeprefix("door:")]["position"])
                for node in route.node_path if node.startswith("door:")}
        self.assertIn("A-K", used)
        self.assertNotIn("A-K2", used)
        points = {point for _, polyline in viewer.route_polylines(self.map, route) for point in polyline}
        self.assertTrue(set(used.values()) <= points)
        self.assertNotIn((0.5, 10), points)
        labels = [label for _, _, label in viewer.route_handoffs(self.map, route)]
        self.assertEqual(labels, ["Lift → First", "Lift from Ground"])
        shown = self.call("show_route", landmark_ids=["B", "chair-15"])
        self.assertEqual([stop["role"] for stop in shown["stops"]], ["start", "stop", "destination"])
        self.assertEqual([item["drawn"] for item in shown["landmarks"]], [True, True])
        self.assertEqual(len(shown["images"]), 2)
        with self.assertRaises(ToolError):
            self.call("show_route", landmark_ids=["nowhere"])

    def test_destination_context_marks_adjacent_only_with_a_one_metre_wall(self) -> None:
        result = self.call("describe_destination_context", space="A", radius_m=15, min_area_m2=40)
        rooms = {room["id"]: room for room in result["context"]}
        self.assertEqual(set(rooms), {"B", "F", "H"})  # corridor, lift and the destination itself are left out
        self.assertEqual((rooms["B"]["relation"], rooms["B"]["shared_wall_m"]), ("adjacent", 10.0))
        for near in ("F", "H"):  # corner contact / a 0.5 m wall only
            self.assertEqual(rooms[near]["relation"], "near")
            self.assertNotIn("shared_wall_m", rooms[near])
        self.assertEqual(result["context"][0]["id"], "B")
        self.assertEqual(result["query"], {"radius_m": 15.0, "min_area_m2": 40.0, "from_outline": True})
        self.assertEqual(self.call("describe_destination_context", space="A", radius_m=0.1)["context"][0]["id"], "B")
        empty = self.call("describe_destination_context", space="A", min_area_m2=5000)
        self.assertEqual(empty["context"], [])
        self.assertIn("omit", empty["hint"])
        asset = self.call("describe_destination_context", space="chair-01")
        self.assertEqual((asset["asset"]["id"], asset["destination"]["id"]), ("chair-01", "A"))
        with self.assertRaises(ToolError):
            self.call("describe_destination_context", space="A", radius_m=-1)


if __name__ == "__main__":
    unittest.main()
