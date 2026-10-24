"""Mock emergency roll call: simulated people, the 2-minute deadline and tool isolation (no API calls)."""

import json
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError
from shapely.geometry import Point

from final_agent.agent import BuildingAgent
from final_agent.building_map import BuildingMap, outline
from final_agent.emergency import (
    PENDING, ROLL_CALL_WINDOW_S, SAFE, SMARTPHONE, UNOCCUPIED_TYPES, UNSAFE, EmergencyError, EmergencyRollCall,
    simulate_people,
)
from final_agent.tools import make_emergency_tools

BUILDING = Path(__file__).resolve().parents[1] / "data" / "dev" / "proc-factory-dev-003"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class EmergencyRollCallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.map = BuildingMap.load(BUILDING)

    def test_people_are_seeded_and_placed_in_occupiable_rooms(self) -> None:
        people = simulate_people(self.map)
        self.assertEqual(people, simulate_people(self.map))
        self.assertTrue(any(person.reply_after_s is None for person in people))
        for person in people:
            space = self.map.spaces[person.space_id]
            self.assertNotIn(space["type"], UNOCCUPIED_TYPES)
            if person.tracker == SMARTPHONE:
                self.assertTrue(outline(space["polygon"]).buffer(1e-6).contains(Point(person.position)))
            else:
                self.assertIn(person.space_id, self.map.openings[person.badge_door_id]["space_ids"])

    def test_unconfirmed_people_become_unsafe_at_the_deadline_until_an_admin_marks_them(self) -> None:
        clock = FakeClock()
        roll_call = EmergencyRollCall(self.map, clock=clock)
        started = roll_call.trigger("Fire alarm")
        self.assertEqual(started["counts"][PENDING], len(roll_call.people))
        silent = sum(person.reply_after_s is None for person in roll_call.people.values())

        clock.now += ROLL_CALL_WINDOW_S - 0.1
        self.assertEqual(roll_call.report()["counts"][UNSAFE], 0)
        clock.now += 0.1
        report = roll_call.report()
        self.assertEqual(report["counts"][UNSAFE], silent)
        self.assertTrue(report["deadline_passed"])

        unsafe = next(person for person in report["people"] if person["status"] == UNSAFE)
        marked = roll_call.mark_safe(unsafe["name"].upper(), "at the assembly point, phone left inside")
        self.assertEqual(marked["marked_safe"]["status"], SAFE)
        self.assertEqual(marked["marked_safe"]["confirmed"]["via"], "admin")
        self.assertEqual(marked["counts"][UNSAFE], silent - 1)
        with self.assertRaises(EmergencyError):
            roll_call.mark_safe("Nobody Here", "")
        roll_call.end()
        with self.assertRaises(EmergencyError):
            roll_call.report()

    def test_tools_draw_maps_and_stay_out_of_benchmark_agents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_emergency_tools(self.map, Path(temporary))}
            started = json.loads(tools["trigger_emergency_roll_call"].call({"reason": "Gas leak"}))
            self.assertTrue(started["images"])
            self.assertTrue(all(Path(image).is_file() for image in started["images"]))
            later = json.loads(tools["emergency_roll_call_status"].call({"fast_forward_s": ROLL_CALL_WINDOW_S}))
            self.assertGreater(later["counts"][UNSAFE], 0)
            with self.assertRaises(ToolError):
                tools["trigger_emergency_roll_call"].call({"reason": "again"})

            benchmark_names = {tool.name for tool in BuildingAgent(self.map, Path(temporary), client=object()).tools}
            chat_names = {
                tool.name for tool in BuildingAgent(self.map, Path(temporary), client=object(), emergency=True).tools
            }
        self.assertNotIn("trigger_emergency_roll_call", benchmark_names)
        self.assertEqual(chat_names - benchmark_names, set(tools))


if __name__ == "__main__":
    unittest.main()
