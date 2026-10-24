"""Turn-by-turn guidance on proc-factory-dev-003: checkpoints, phrasing and the walk-through state.

A fake clock drives tracking. Nothing here calls a model or the network.
"""

import itertools
import json
import math
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError

from final_agent.building_map import BuildingMap, MapError
from final_agent.guidance import (
    CHECKPOINT_RADIUS_M, STALE_POSITION_S, Checkpoint, Guidance, _bend_degrees, _heading_change, _turn_label,
    _walk_turns, instruction, route_checkpoints, spoken_distance,
)
from final_agent.tools import make_tools

BUILDING = Path(__file__).resolve().parents[1] / "data" / "dev" / "proc-factory-dev-003"
P = "proc-factory-dev-003-"
ARRIVED = "You've arrived — this is Kitchen 1.08."
LOST = "I've lost your position for a moment — just tell me when you get there."
WALKS = {}  # walking lengths of the unchanged building, shared by every test


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class GuidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.map = BuildingMap.load_cached(BUILDING, WALKS)
        cls.route = cls.map.route(P + "F0-S023", P + "F1-S008")
        cls.checkpoints = route_checkpoints(cls.map, cls.route)

    def new_guidance(self, clock: FakeClock | None = None) -> Guidance:
        return Guidance(self.map, clock or FakeClock())

    def test_route_checkpoints_end_with_arrival_and_cross_floors(self):
        self.assertGreaterEqual(len(self.checkpoints), 2)
        self.assertEqual(self.checkpoints[-1].kind, "arrival")
        self.assertEqual(self.checkpoints[-1].name, "Kitchen 1.08")
        connector = next(cp for cp in self.checkpoints if cp.kind == "connector")
        self.assertEqual((connector.name, connector.target_floor_id), ("Office staircase", P + "F1"))
        self.assertTrue(all(cp.distance_m >= 0 for cp in self.checkpoints))
        # Orientation is unknown at the start and after stairs, so neither gets a departure turn.
        after_connector = self.checkpoints[self.checkpoints.index(connector) + 1]
        self.assertEqual((self.checkpoints[0].departure, after_connector.departure), (None, None))

    def test_heading_change_labels_the_bend_at_a_point(self):
        east_then_north = [(0.0, (0.0, 0.0)), (10.0, (10.0, 0.0)), (20.0, (10.0, 10.0))]
        east_then_south = [(0.0, (0.0, 0.0)), (10.0, (10.0, 0.0)), (20.0, (10.0, -10.0))]
        self.assertEqual(_heading_change(east_then_north, 10.0), "left")
        self.assertEqual(_heading_change(east_then_south, 10.0), "right")
        self.assertIsNone(_heading_change(east_then_north, 0.3))   # under 0.5 m of path before the point
        self.assertIsNone(_heading_change(east_then_north, 19.8))  # and under 0.5 m after it

    def test_door_departure_turn_is_spoken_on_a_dev_route(self):
        for start, goal in itertools.permutations(list(self.map.spaces)[:30], 2):
            checkpoints = route_checkpoints(self.map, self.map.route(start, goal))
            doors = [(i, cp) for i, cp in enumerate(checkpoints) if cp.kind == "door" and cp.departure]
            if doors:
                index, door = doors[0]
                self.assertIn("turn", instruction(door, index, self.map, "en"))
                return
        self.fail("no route among the first 30 rooms has a door with a departure turn")

    def test_departure_phrases_and_german_openers(self):
        door = Checkpoint(
            kind="door", floor_id=P + "F0", position=(0.0, 0.0), space_id=P + "F0-S023", distance_m=8.0,
            name="Assembly hall", next_space_id=P + "F0-S016", departure="left",
        )
        self.assertEqual(
            instruction(door, 0, self.map, "en"), "Turn left, then walk 8 metres to the door into Assembly hall.",
        )
        self.assertEqual(
            instruction(door, 2, self.map, "de"), "Jetzt bieg links ab und geh 8 Meter bis zur Tür in Assembly hall.",
        )
        german = [instruction(cp, index, self.map, "de") for cp in self.checkpoints for index in range(4)]
        self.assertFalse(any("Jetzt," in text for text in german))

    def test_english_articles_skip_names_ending_in_a_number(self):
        lift = Checkpoint(
            kind="connector", floor_id=P + "F1", position=(0.0, 0.0), space_id=P + "F1-S002", distance_m=0.0,
            name="Lift 2", next_space_id=P + "F0-S017", connector_kind="lift", target_floor_id=P + "F0",
        )
        stairs = Checkpoint(
            kind="connector", floor_id=P + "F0", position=(0.0, 0.0), space_id=P + "F0-S017", distance_m=0.0,
            name="Office staircase", next_space_id=P + "F1-S002", connector_kind="stairs", target_floor_id=P + "F1",
        )
        self.assertEqual(instruction(lift, 0, self.map, "en"), "Take Lift 2 down to the Ground floor.")
        self.assertEqual(instruction(stairs, 0, self.map, "en"), "Take the Office staircase up to Floor 1.")
        self.assertEqual(instruction(stairs, 0, self.map, "de"), "Nimm Office staircase nach oben zu Floor 1.")

    def test_turn_labels_follow_bend_sign_and_size(self):
        def label(degrees: float):
            radians = math.radians(degrees)
            return _turn_label(_bend_degrees((0.0, 0.0), (1.0, 0.0), (1.0 + math.cos(radians), math.sin(radians))))

        self.assertEqual(
            [label(90), label(-90), label(45), label(-150), label(120), label(20)],
            ["left", "right", "slight left", "sharp right", "left", None],
        )
        # Turns need a segment of at least 1.5 m before them; the L-shaped walk turns after 5 m.
        self.assertEqual(_walk_turns([(0.0, 0.0), (5.0, 0.0), (5.0, 5.0)]), [(5.0, (5.0, 0.0), "left")])
        self.assertEqual(_walk_turns([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]), [])
        self.assertEqual(spoken_distance(2.0), "a few metres")
        self.assertEqual(spoken_distance(12.4), "12 metres")
        self.assertEqual(spoken_distance(44.0, "de"), "etwa 45 Meter")

    def test_space_at_finds_the_room_and_rejects_far_points(self):
        x, y = self.map.anchor(P + "F0-S023")
        self.assertEqual(self.map.space_at(0, x, y), P + "F0-S023")
        self.assertIsNotNone(self.map.space_at(0, *self.map.openings[P + "F0-O0028"]["position"]))
        self.assertIsNone(self.map.space_at(0, 500.0, 500.0))
        with self.assertRaises(MapError):
            self.map.space_at(7, x, y)
        with self.assertRaises(MapError):
            self.map.space_at(0, math.nan, y)

    def test_confirm_mode_walks_every_step_to_arrival(self):
        guidance = self.new_guidance()
        guidance.start(self.route)
        said = guidance.drain()
        while guidance.active:
            guidance.confirm()
            said += guidance.drain()
        self.assertEqual(said[-1], ARRIVED)
        self.assertEqual(len(said), len(self.checkpoints) + 1)
        self.assertEqual(["Tell me when you're there" in text for text in said[:3]], [True, True, False])

    def test_no_confirm_reads_the_whole_route_in_one_utterance(self):
        guidance = self.new_guidance()
        guidance.confirm_each_step = False
        guidance.start(self.route)
        said = guidance.drain()
        self.assertEqual(len(said), 1)
        self.assertIn("Office staircase up to Floor 1", said[0])
        self.assertTrue(said[0].endswith("I'll be here if you need me."))
        self.assertTrue(guidance.active)
        guidance.confirm()
        self.assertEqual(guidance.drain(), [ARRIVED])
        self.assertFalse(guidance.active)

    def test_live_positions_walk_every_checkpoint_without_confirmation(self):
        guidance = self.new_guidance()
        guidance.update_position(0, *self.map.anchor(P + "F0-S023"))
        guidance.start(self.route)
        said = guidance.drain()
        for checkpoint in self.checkpoints:
            if checkpoint.kind == "connector":  # a connector counts once the user is on its far floor
                far_level = self.map.floor_level(checkpoint.target_floor_id)
                guidance.update_position(far_level, *self.map.anchor(checkpoint.next_space_id))
            else:
                guidance.update_position(self.map.floor_level(checkpoint.floor_id), *checkpoint.position)
            said += guidance.drain()
        self.assertFalse(guidance.active)
        self.assertEqual(said[-1], ARRIVED)
        self.assertFalse(any("Tell me" in text for text in said))

    def test_a_loose_fix_at_the_start_does_not_skip_the_first_door(self):
        start = self.map.anchor(P + "F0-S023")
        door = self.checkpoints[0].position
        self.assertLessEqual(math.dist(start, door), CHECKPOINT_RADIUS_M)  # the old radius skipped it
        guidance = self.new_guidance()
        guidance.start(self.route)
        guidance.drain()
        guidance.update_position(0, *start, accuracy_m=6.0)
        self.assertEqual(guidance.status()["next"]["index"], 0)
        self.assertEqual(guidance.drain(), [])
        guidance.update_position(0, *self.map.anchor(P + "F0-S016"), accuracy_m=6.0)  # the room behind the first door
        self.assertEqual(guidance.status()["next"]["index"], 1)
        self.assertEqual(guidance.drain(), [instruction(self.checkpoints[1], 1, self.map)])

    def test_two_fixes_off_the_route_trigger_a_reroute(self):
        guidance = self.new_guidance()
        guidance.update_position(0, *self.map.anchor(P + "F0-S023"))
        guidance.start(self.route)
        old = guidance.route
        guidance.drain()
        away = self.map.anchor(P + "F0-S001")  # a ground-floor room that the route does not use
        guidance.update_position(0, *away)
        self.assertEqual(guidance.drain(), [])
        guidance.update_position(0, *away)
        said = guidance.drain()
        self.assertTrue(said[0].startswith("No problem, let me reroute you. "), said)
        self.assertIsNot(guidance.route, old)
        self.assertIs(self.map.last_route, guidance.route)
        self.assertEqual(guidance.route.start_space_id, P + "F0-S001")

    def test_tracking_loss_is_announced_once(self):
        clock = FakeClock()
        guidance = self.new_guidance(clock)
        start = self.map.anchor(P + "F0-S023")
        guidance.update_position(0, *start)
        guidance.start(self.route)
        guidance.drain()
        clock.now = STALE_POSITION_S + 1
        guidance.tick()
        guidance.tick()
        self.assertEqual(guidance.drain(), [LOST])
        guidance.update_position(0, *start)
        guidance.tick()
        self.assertNotIn(LOST, guidance.drain())

    def test_german_phrasing_and_arrival(self):
        guidance = self.new_guidance()
        guidance.language = "de"
        guidance.start(self.route)
        said = guidance.drain()
        self.assertEqual(said, ["Geh ein paar Meter bis zur Tür und dann in Office corridor 0.16. Sag Bescheid, wenn du da bist."])
        while guidance.active:
            guidance.confirm()
            said += guidance.drain()
        self.assertEqual(said[-1], "Du bist da — das ist Kitchen 1.08.")

    def test_adopt_restarts_for_the_same_destination_and_stops_when_blocked(self):
        guidance = self.new_guidance()
        guidance.start(self.route)
        guidance.drain()
        lift = self.map.route(P + "F0-S023", P + "F1-S008", step_free=True)
        guidance.adopt(lift)
        self.assertTrue(guidance.drain()[0].startswith("The route changed — "))
        self.assertIs(guidance.route, lift)
        guidance.adopt(self.map.route(P + "F0-S023", P + "F0-S001"))  # another destination is ignored
        self.assertIs(guidance.route, lift)
        guidance.adopt(None)
        self.assertEqual(guidance.drain(), ["That way is blocked now and I can't find another route."])
        self.assertFalse(guidance.active)

    def test_status_reports_destination_next_step_and_progress(self):
        guidance = self.new_guidance()
        self.assertEqual(guidance.status()["progress"], [0, 0])
        with self.assertRaises(MapError):
            guidance.update_position(7, 0.0, 0.0)
        guidance.start(self.route)
        status = guidance.status()
        self.assertEqual(
            set(status),
            {"active", "destination", "next", "progress", "remaining_m", "tracking", "confirm_each_step", "language"},
        )
        self.assertEqual(status["destination"], {"id": P + "F1-S008", "name": "Kitchen 1.08"})
        self.assertEqual((status["next"]["index"], status["next"]["kind"]), (0, "door"))
        self.assertEqual(status["progress"], [0, len(self.checkpoints)])
        self.assertTrue(guidance.stop())
        self.assertEqual(guidance.drain()[-1], "Okay, stopping navigation.")
        self.assertFalse(guidance.stop())

    def test_same_room_route_is_arrived_at_at_once(self):
        guidance = self.new_guidance()
        guidance.start(self.map.route(P + "F0-S023", P + "F0-S023"))
        self.assertEqual(guidance.drain(), ["You've arrived — this is Office 0.23."])
        self.assertFalse(guidance.active)

    def test_guidance_next_step_tool_moves_on_and_needs_active_guidance(self):
        guidance = self.new_guidance()
        with tempfile.TemporaryDirectory() as directory:
            tools = {tool.name: tool for tool in make_tools(self.map, Path(directory), guidance=guidance)}
            with self.assertRaisesRegex(ToolError, "No guidance is running."):
                tools["guidance_next_step"].call({})
            guidance.start(self.route)
            guidance.drain()
            status = json.loads(tools["guidance_next_step"].call({}))
        self.assertEqual(status["progress"], [1, len(self.checkpoints)])
        prompt = " Tell me when you're there."
        self.assertEqual(guidance.drain(), [instruction(self.checkpoints[1], 1, self.map) + prompt])


if __name__ == "__main__":
    unittest.main()
