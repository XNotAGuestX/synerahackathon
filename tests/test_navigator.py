"""Navigator: reached rules, skip-ahead, wrong-way latch, ignored fixes, phrase rendering."""

import math
import unittest
from datetime import datetime, timedelta, timezone

from final_agent.building_map import BuildingMap
from final_agent.narration import render
from final_agent.navigator import Fix, Navigator
from final_agent.waypoints import RouteWalk, WalkSegment, Waypoint, route_walk, space_containing

BASE = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def rect(space_id, name, x0, y0, x1, y1, floor="F0"):
    return {"id": space_id, "name": name, "floor_id": floor, "room_type": "office",
            "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


def three_rooms() -> BuildingMap:
    """A, B, C in a row (doors at x=12 and x=24), D above A (off route), Upper on F1 via stairs in C."""
    opening = lambda i, a, b, x, y: {"id": i, "floor_id": "F0", "space_ids": [a, b], "kind": "door",
                                     "position": [x, y], "width_m": 1, "step_free": True}
    return BuildingMap({
        "building": {"id": "t", "name": "T", "units": "m", "source": "test"},
        "floors": [{"id": "F0", "level": 0, "name": "Ground", "elevation_m": 0.0},
                   {"id": "F1", "level": 1, "name": "First", "elevation_m": 3.0}],
        "spaces": [rect("a", "Room A", 0, 0, 12, 12), rect("b", "Room B", 12, 0, 24, 12),
                   rect("c", "Room C", 24, 0, 36, 12), rect("d", "Room D", 0, 12, 12, 24),
                   rect("u", "Upper", 0, 0, 12, 12, "F1")],
        "assets": [], "openings": [opening("ab", "a", "b", 12, 3), opening("bc", "b", "c", 24, 9),
                                   opening("ad", "a", "d", 6, 12)],
        "vertical_connectors": [{"id": "st", "kind": "stairs", "name": "Stairs", "step_free": False,
                                 "floor_ids": ["F0", "F1"], "space_ids": ["c", "u"]}],
        "custom_metadata": {}})


def straight_walk() -> RouteWalk:
    """Hand-built walk along y=0 in room a: turns at x=10 and x=20, arrival at x=40."""
    def waypoint(index, kind, x, **fields):
        return Waypoint(index=index, kind=kind, floor_id="F0", at=(x, 0.0), space_id="a", next_space_id=fields.pop("into", None),
                        name=fields.pop("name", None), side=fields.pop("side", None), distance_m=10.0 if index else x, arc_m=x)
    waypoints = (waypoint(0, "turn", 10.0, side="left"), waypoint(1, "turn", 20.0, side="right"),
                 waypoint(2, "arrival", 40.0, into="a", name="Room A"))
    return RouteWalk(waypoints, (WalkSegment("F0", "a", ((0.0, 0.0), (40.0, 0.0)), 0.0),), 40.0, frozenset({"a"}))


class Feeder:
    """Feeds fixes with increasing timestamps; the navigator clock follows the last fix."""

    def __init__(self, walk, building=None):
        self.now, self.seconds, self.building = BASE, 0, building
        self.navigator = Navigator(walk, "Room C", clock=lambda: self.now)

    def fix(self, point, floor="F0", space="a", source="simulated", age=0, at=None):
        self.seconds += 1
        self.now = BASE + timedelta(seconds=self.seconds)
        if self.building is not None:
            space = space_containing(self.building, floor, point, prefer=self.navigator.walk.space_ids)
        measured = at if at is not None else self.now - timedelta(seconds=age)
        return self.navigator.on_fix(Fix(floor, point, measured, self.now, source, space))

    def walk_x(self, *xs, **kwargs):
        return [event for x in xs for event in self.fix((float(x), 0.0), **kwargs)]


class NavigatorTests(unittest.TestCase):
    def test_sampled_route_gives_one_instruction_per_waypoint_then_arrived(self):
        building = three_rooms()
        walk = route_walk(building, building.compute_route("a", "c"))
        feeder = Feeder(walk, building)
        events = []
        for segment in walk.segments:
            for first, second in zip(segment.points, segment.points[1:]):
                steps = max(1, round(math.dist(first, second) / 0.5))
                for step in range(steps + 1):
                    events += feeder.fix((first[0] + (second[0] - first[0]) * step / steps,
                                          first[1] + (second[1] - first[1]) * step / steps), floor=segment.floor_id)
        self.assertEqual([(e.kind, e.waypoint_index) for e in events],
                         [("instruction", i) for i in range(1, len(walk.waypoints))] + [("arrived", len(walk.waypoints) - 1)])

    def test_turn_reached_at_2_9_m_not_3_1_m(self):
        self.assertEqual(Feeder(straight_walk()).walk_x(7.1)[0].waypoint_index, 1)
        self.assertEqual(Feeder(straight_walk()).walk_x(6.9), [])

    def test_off_route_neighbour_room_does_not_reach(self):
        self.assertEqual(Feeder(straight_walk()).walk_x(8, space="x"), [])

    def test_first_fix_near_door_in_start_room_does_not_skip_it(self):
        waypoints = (Waypoint(0, "turn", "F0", (5.0, 0.0), "a", None, None, "left", 5.0, 5.0),
                     Waypoint(1, "door", "F0", (8.0, 0.0), "a", "b", "Room B", None, 3.0, 8.0),
                     Waypoint(2, "arrival", "F0", (20.0, 0.0), "b", "b", "Room B", None, 12.0, 20.0))
        walk = RouteWalk(waypoints, straight_walk().segments, 20.0, frozenset({"a", "b"}))
        feeder = Feeder(walk)
        events = feeder.fix((6.0, 0.0))
        self.assertEqual([(e.kind, e.waypoint_index) for e in events], [("instruction", 1)])
        self.assertEqual(feeder.navigator.target, 1)

    def test_wrong_way_warns_once_per_target_and_rearms(self):
        feeder = Feeder(straight_walk())
        feeder.walk_x(5)
        kinds = [e.kind for e in feeder.walk_x(4, 3, 2, 1)]
        self.assertEqual(kinds, ["wrong_way"])
        self.assertEqual(feeder.walk_x(0, 1, 0), [])
        self.assertEqual([(e.kind, e.waypoint_index) for e in feeder.walk_x(2, 3, 4, 5, 6, 7)], [("instruction", 1)])
        feeder.walk_x(8, 9, 10, 11, 12)
        self.assertEqual([e.kind for e in feeder.walk_x(11, 10, 9, 8)], ["wrong_way"])

    def test_manual_jump_backwards_is_not_wrong_way(self):
        feeder = Feeder(straight_walk())
        feeder.walk_x(4, 5)
        self.assertEqual(feeder.fix((0.0, 0.0), source="manual"), [])
        self.assertEqual(feeder.walk_x(0.5, 1.0), [])

    def test_stale_and_out_of_order_fixes_are_ignored(self):
        feeder = Feeder(straight_walk())
        self.assertEqual(feeder.walk_x(9, age=20), [])
        self.assertEqual(len(feeder.walk_x(9)), 1)
        self.assertEqual(feeder.walk_x(19, at=BASE), [])  # measured before the applied fix
        self.assertEqual(feeder.navigator.target, 1)

    def test_connector_exit_reached_by_any_fix_on_target_floor(self):
        building = three_rooms()
        walk = route_walk(building, building.compute_route("a", "u"))
        exit_index = next(w.index for w in walk.waypoints if w.kind == "connector_exit")
        feeder = Feeder(walk, building)
        feeder.navigator.target = exit_index
        events = feeder.fix((1.0, 1.0), floor="F1")
        self.assertEqual([(e.kind, e.waypoint_index) for e in events], [("instruction", exit_index + 1)])

    def test_render_falls_back_and_words_distance_and_side(self):
        turn = Waypoint(0, "turn", "F0", (0.0, 0.0), "a", None, None, "slight_left", 12.4, 12.4)
        self.assertEqual(render(turn), "In 12 metres, turn slightly left.")
        self.assertEqual(render(turn, "turn_past"), "In 12 metres, turn slightly left.")  # landmark missing
        self.assertEqual(render(turn, "door_walk"), "In 12 metres, turn slightly left.")  # wrong kind
        self.assertEqual(render(turn, "turn_at", "the printer"), "Turn slightly left at the printer.")
        door = Waypoint(1, "door", "F0", (0.0, 0.0), "a", "b", "Room B", None, 2.0, 2.0)
        self.assertEqual(render(door, "door_then_turn"), "Walk a few metres to the door into Room B.")  # no side
        sharp = Waypoint(2, "turn", "F0", (0.0, 0.0), "a", None, None, "sharp_right", 47.0, 59.0)
        self.assertEqual(render(sharp), "In about 45 metres, turn sharp right.")


if __name__ == "__main__":
    unittest.main()
