"""Shared-wall measurement and count on tiny synthetic floors (no doors anywhere)."""

import json
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError

from final_agent.building_map import BuildingMap, MapError
from final_agent.tools import make_tools


def rectangle(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def space(space_id, polygon, space_type="room", room_type="office", floor_id="F0"):
    return {"id": space_id, "name": space_id, "floor_id": floor_id, "type": space_type,
            "room_type": room_type, "polygon": polygon}


def make_map(*spaces) -> BuildingMap:
    return BuildingMap({
        "building": {"id": "test", "name": "Test", "units": "m", "source": "test"},
        "floors": [{"id": "F0", "level": 0, "name": "Ground"}, {"id": "F1", "level": 1, "name": "First"}],
        "spaces": list(spaces), "assets": [], "openings": [], "vertical_connectors": [],
    })


def neighbour_ids(building, source="A"):
    return [item["id"] for item in building.count_shared_walls(source)["neighbours"]]


def source_and_neighbour(length, gap=0.0):
    """A is 4 m tall; B stands to its right with `length` metres of parallel wall, `gap` m away."""
    return make_map(
        space("A", rectangle(0, 0, 4, 4)),
        space("B", rectangle(4 + gap, 1, 8, 1 + length)),
    )


class WallLengthTests(unittest.TestCase):
    def test_rectangles_measure_the_wall_without_corner_caps(self):
        building = make_map(space("A", rectangle(0, 0, 4, 4)), space("B", rectangle(4, 0, 8, 4)))
        wall = building.shared_wall("A", "B")
        self.assertAlmostEqual(wall["total_length_m"], 4.0)
        self.assertEqual(len(wall["runs"]), 1)
        self.assertEqual(wall["midpoint"], [4.0, 2.0])

    def test_shared_run_just_below_at_and_above_one_metre(self):
        for length, counted in ((0.99, False), (1.0, True), (1.01, True)):
            with self.subTest(length=length):
                self.assertEqual(neighbour_ids(source_and_neighbour(length)), ["B"] if counted else [])

    def test_wall_gap_just_below_at_and_above_the_tolerance(self):
        for gap, counted in ((0.34, True), (0.35, True), (0.36, False)):
            with self.subTest(gap=gap):
                self.assertEqual(neighbour_ids(source_and_neighbour(2.0, gap)), ["B"] if counted else [])

    def test_corner_only_contact_has_no_wall_length(self):
        building = make_map(space("A", rectangle(0, 0, 4, 4)), space("B", rectangle(4, 4, 8, 8)))
        self.assertAlmostEqual(building.shared_wall("A", "B")["total_length_m"], 0.0)
        self.assertEqual(building.shared_wall("A", "B")["midpoint"], None)
        self.assertEqual(building.count_shared_walls("A")["count"], 0)

    def test_corner_near_miss_does_not_count_the_perpendicular_outline(self):
        building = make_map(space("A", rectangle(0, 0, 4, 4)), space("B", rectangle(4.2, 4.2, 8, 8)))
        self.assertEqual(building.shared_wall("A", "B")["total_length_m"], 0.0)

    def test_l_shaped_wall_adds_both_legs(self):
        l_room = space("L", [[0, 0], [6, 0], [6, 2], [2, 2], [2, 6], [0, 6]])
        # B fills the inner corner: it touches the horizontal leg for 4 m and the vertical leg for 4 m.
        corner = space("B", [[2, 2], [6, 2], [6, 6], [2, 6]])
        building = make_map(l_room, corner)
        self.assertAlmostEqual(building.shared_wall("L", "B")["total_length_m"], 8.0)
        self.assertEqual(len(building.shared_wall("L", "B")["runs"]), 1)

    def test_irregular_wall_with_a_vertex_in_it_is_one_run(self):
        # Wall x=4 from y=0..4 is split by an extra vertex at (4, 2) on both outlines.
        first = space("A", [[0, 0], [4, 0], [4, 2], [4, 4], [0, 4]])
        second = space("B", [[4, 0], [8, 0], [8, 4], [4, 4], [4, 2]])
        building = make_map(first, second)
        wall = building.shared_wall("A", "B")
        self.assertAlmostEqual(wall["total_length_m"], 4.0)
        self.assertEqual(len(wall["runs"]), 1)

    def test_diagonal_wall_counts_its_true_length(self):
        first = space("A", [[0, 0], [4, 4], [0, 4]])
        second = space("B", [[0.2, -0.2], [4.2, 3.8], [4.2, -0.2]])
        wall = make_map(first, second).shared_wall("A", "B")
        self.assertAlmostEqual(wall["total_length_m"], 4 * 2 ** 0.5, places=3)
        gap_free = make_map(space("A", [[0, 0], [4, 4], [0, 4]]), space("B", [[0, 0], [4, 4], [4, 0]]))
        self.assertAlmostEqual(gap_free.shared_wall("A", "B")["total_length_m"], 4 * 2 ** 0.5, places=3)

    def test_perpendicular_walls_across_a_gap_are_not_shared(self):
        building = make_map(space("A", rectangle(0, 0, 4, 4)), space("B", rectangle(4.2, 5, 9, 5.3)))
        self.assertEqual(building.shared_wall("A", "B")["total_length_m"], 0.0)

    def test_shared_wall_rejects_other_floors_and_self(self):
        building = make_map(space("A", rectangle(0, 0, 4, 4)), space("U", rectangle(0, 0, 4, 4), floor_id="F1"))
        for arguments in (("A", "A"), ("A", "U")):
            with self.subTest(arguments=arguments), self.assertRaises(MapError):
                building.shared_wall(*arguments)


class CountSharedWallsTests(unittest.TestCase):
    def test_shared_wall_without_a_door_counts_and_reports_evidence(self):
        building = make_map(space("A", rectangle(0, 0, 4, 4)), space("B", rectangle(4, 0, 8, 4)))
        result = building.count_shared_walls("A")
        self.assertEqual((result["count"], result["excluded"]), (1, []))
        self.assertEqual(result["neighbours"][0]["id"], "B")
        self.assertAlmostEqual(result["neighbours"][0]["shared_length_m"], 4.0)
        self.assertEqual((result["min_shared_length_m"], result["wall_tolerance_m"]), (1.0, 0.35))
        self.assertEqual(result["space"]["id"], "A")
        self.assertEqual(building.openings, {})

    def test_corridor_stairwell_and_lift_are_excluded_with_reasons(self):
        building = make_map(
            space("A", rectangle(0, 0, 4, 4)),
            space("corridor", rectangle(4, 0, 6, 4), "corridor", "corridor"),
            space("stairwell", rectangle(-2, 0, 0, 4), "corridor", "stairwell"),
            space("stair", rectangle(0, 4, 4, 6), "stair", "stairwell"),
            space("lift", rectangle(0, -2, 4, 0), "lift", "lift"),
        )
        result = building.count_shared_walls("A")
        self.assertEqual(result["count"], 0)
        self.assertEqual(
            {item["id"] for item in result["excluded"]}, {"corridor", "stairwell", "stair", "lift"}
        )
        self.assertTrue(all("never counted" in item["reason"] for item in result["excluded"]))

    def test_outdoor_neighbour_is_excluded(self):
        building = make_map(
            space("A", rectangle(0, 0, 4, 4)), space("balcony", rectangle(4, 0, 6, 4), "outdoor", "balcony")
        )
        result = building.count_shared_walls("A")
        self.assertEqual((result["count"], [item["id"] for item in result["excluded"]]), (0, ["balcony"]))

    def test_hall_bays_and_lobbies_are_counted(self):
        building = make_map(
            space("A", rectangle(0, 0, 4, 4)),
            space("bay", rectangle(4, 0, 8, 4), "hall", "production_zone"),
            space("lobby", rectangle(-4, 0, 0, 4), "hall", "lobby"),
        )
        self.assertEqual(neighbour_ids(building), ["bay", "lobby"])

    def test_short_contact_is_listed_as_excluded(self):
        result = source_and_neighbour(0.6).count_shared_walls("A")
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["excluded"][0]["id"], "B")
        self.assertIn("below 1 m", result["excluded"][0]["reason"])

    def test_other_floors_and_distant_rooms_are_ignored(self):
        building = make_map(
            space("A", rectangle(0, 0, 4, 4)),
            space("upstairs", rectangle(4, 0, 8, 4), floor_id="F1"),
            space("far", rectangle(20, 0, 24, 4)),
        )
        result = building.count_shared_walls("A")
        self.assertEqual((result["count"], result["excluded"]), (0, []))

    def test_source_is_not_its_own_neighbour_and_reference_is_resolved(self):
        building = make_map(space("A", rectangle(0, 0, 4, 4)), space("B", rectangle(4, 0, 8, 4)))
        self.assertEqual(building.count_shared_walls("B")["neighbours"][0]["id"], "A")
        with self.assertRaises(MapError):
            building.count_shared_walls("nowhere")

    def test_tool_returns_json_and_reports_errors(self):
        building = make_map(space("A", rectangle(0, 0, 4, 4)), space("B", rectangle(4, 0, 8, 4)))
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_tools(building, Path(temporary))}
            result = json.loads(tools["count_shared_walls"].call({"space": "A"}))
            self.assertEqual(result["count"], 1)
            with self.assertRaises(ToolError):
                tools["count_shared_walls"].call({"space": "nowhere"})


if __name__ == "__main__":
    unittest.main()
