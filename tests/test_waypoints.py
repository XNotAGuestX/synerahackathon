"""Waypoint geometry: turns, doors, connectors, distances, containment, spoken distance."""

import math
import unittest
from pathlib import Path

from final_agent.building_map import BuildingMap
from final_agent.viewer import route_polylines
from final_agent.waypoints import detect_turns, route_walk, space_containing, spoken_distance, turn_label
from test_routing import door
from test_storage import example_building

DEV = Path(__file__).resolve().parent.parent / "data" / "dev"


def drawn_length(building_map, route) -> float:
    return sum(math.dist(a, b) for _, line in route_polylines(building_map, route) for a, b in zip(line, line[1:]))


def path(*moves):
    """Polyline from (heading degrees, length) moves, starting at the origin."""
    points = [(0.0, 0.0)]
    for heading, length in moves:
        x, y = points[-1]
        points.append((x + length * math.cos(math.radians(heading)), y + length * math.sin(math.radians(heading))))
    return points


class WaypointRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.building = BuildingMap.load(DEV / "proc-factory-dev-003" / "building.json")
        stairs = next(iter(cls.building.connectors.values()))
        cls.route = cls.building.compute_route("proc-factory-dev-003-F0-S001", stairs["space_ids"][1])
        cls.walk = route_walk(cls.building, cls.route)

    def test_multi_floor_route_is_consistent(self):
        walk = self.walk
        kinds = [waypoint.kind for waypoint in walk.waypoints]
        self.assertEqual(kinds[-1], "arrival")
        self.assertIn("connector_entry", kinds)
        self.assertEqual(kinds[kinds.index("connector_entry") + 1], "connector_exit")
        entry, exit_ = (w for w in walk.waypoints if w.kind.startswith("connector"))
        self.assertEqual(entry.arc_m, exit_.arc_m)
        self.assertAlmostEqual(sum(w.distance_m for w in walk.waypoints), walk.total_m, delta=0.01)
        self.assertAlmostEqual(walk.total_m, drawn_length(self.building, self.route), delta=0.5)

    def test_multi_floor_stair_run_is_one_pair(self):
        building = BuildingMap.load(DEV / "swiss-460" / "building.json")
        route = building.compute_route("swiss-460-F0-S001", "swiss-460-F4-S018")
        self.assertTrue(any(a in building.connectors and b in building.connectors for a, b in zip(route.edge_path, route.edge_path[1:])))
        pair = [w for w in route_walk(building, route).waypoints if w.kind.startswith("connector")]
        self.assertEqual([w.kind for w in pair], ["connector_entry", "connector_exit"])
        self.assertEqual((pair[0].floor_id, pair[1].floor_id), ("swiss-460-F0", "swiss-460-F4"))
        self.assertEqual({w.target_floor_id for w in pair}, {"swiss-460-F4"})
        self.assertEqual({w.direction for w in pair}, {"up"})

    def test_sample_of_dev_routes_sums_to_total(self):
        for folder in sorted(DEV.iterdir(), key=lambda folder: (folder / "building.json").stat().st_size)[:8]:
            building = BuildingMap.load(folder / "building.json")
            ids = list(building.spaces)
            for start, end in ((ids[0], ids[-1]), (ids[1], ids[len(ids) // 2])):
                try:
                    route = building.compute_route(start, end)
                except ValueError:
                    continue
                walk = route_walk(building, route)
                self.assertAlmostEqual(sum(w.distance_m for w in walk.waypoints), walk.total_m, delta=0.01)
                self.assertEqual(walk.waypoints[-1].kind, "arrival")

    def test_start_point_changes_first_distance(self):
        first = self.walk.waypoints[0]
        anchor = self.building.anchor(self.route.start_space_id)
        moved = next(point for point in ((anchor[0] + dx, anchor[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                     if space_containing(self.building, first.floor_id, point) == self.route.start_space_id)
        moved_walk = route_walk(self.building, self.route, start_point=moved)
        self.assertNotAlmostEqual(moved_walk.waypoints[0].distance_m, first.distance_m, places=2)

    def test_project_clips_to_arc_range(self):
        segment = self.walk.segments[0]
        arc, lateral = self.walk.project(segment.floor_id, segment.points[0], 0, self.walk.total_m)
        self.assertAlmostEqual(arc, 0, places=6)
        self.assertAlmostEqual(lateral, 0, places=6)
        self.assertIsNone(self.walk.project("no-such-floor", (0, 0), 0, self.walk.total_m))


class TurnTests(unittest.TestCase):
    def test_side_and_label_table(self):
        self.assertEqual(turn_label(90), "left")
        self.assertEqual(turn_label(-90), "right")
        self.assertEqual(turn_label(45), "slight_left")
        self.assertEqual(turn_label(-45), "slight_right")
        self.assertEqual(turn_label(150), "sharp_left")
        self.assertEqual(turn_label(-150), "sharp_right")
        self.assertIsNone(turn_label(30))
        self.assertEqual(detect_turns(path((0, 5), (90, 5))), [(1, "left")])
        self.assertEqual(detect_turns(path((0, 5), (-90, 5))), [(1, "right")])
        self.assertEqual(detect_turns(path((0, 5), (45, 5))), [(1, "slight_left")])
        self.assertEqual(detect_turns(path((0, 5), (-160, 5))), [(1, "sharp_right")])

    def test_gradual_bend_is_one_turn(self):
        points = path((0, 5), (15, 1), (30, 1), (45, 1), (45, 5))
        self.assertEqual(detect_turns(points), [(3, "slight_left")])

    def test_s_bend_gives_both_turns(self):
        self.assertEqual(detect_turns(path((0, 5), (90, 2.5), (0, 5))), [(1, "left"), (2, "right")])

    def test_door_folds_following_turn(self):
        data = example_building()
        data["spaces"] = [
            {"id": "hall", "name": "Hall", "floor_id": "F0", "room_type": "corridor", "polygon": [[-6, -1], [0, -1], [0, 1], [-6, 1]]},
            {"id": "lab", "name": "Lab", "floor_id": "F0", "room_type": "lab", "polygon": [[0, -6], [2, -6], [2, 1], [0, 1]]},
        ]
        data["assets"], data["openings"] = [], [door("D1", "hall", "lab", 0, 0.5)]
        walk = route_walk(BuildingMap(data), BuildingMap(data).compute_route("hall", "lab"))
        kinds = [w.kind for w in walk.waypoints]
        self.assertEqual(kinds, ["door", "arrival"])
        self.assertEqual(walk.waypoints[0].side, "right")


class ContainmentTests(unittest.TestCase):
    def setUp(self):
        data = example_building()
        data["spaces"].append({"id": "lobby", "name": "Lobby", "floor_id": "F0", "room_type": "hall",
                               "polygon": [[-1, -1], [1, -1], [1, 1], [-1, 1]]})
        self.building = BuildingMap(data)

    def test_overlap_prefers_preferred_room_then_smallest(self):
        self.assertEqual(space_containing(self.building, "F0", (-0.5, 0)), "lobby")
        self.assertEqual(space_containing(self.building, "F0", (-0.5, 0), prefer=("left",)), "left")

    def test_outside_every_room_is_none(self):
        self.assertIsNone(space_containing(self.building, "F0", (500, 500)))


class SpokenDistanceTests(unittest.TestCase):
    def test_spoken_distance(self):
        self.assertEqual(spoken_distance(3.9), "a few metres")
        self.assertEqual(spoken_distance(12.4), "12 metres")
        self.assertEqual(spoken_distance(12.5), "13 metres")
        self.assertEqual(spoken_distance(22.5), "about 25 metres")


if __name__ == "__main__":
    unittest.main()
