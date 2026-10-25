"""Emergency mode: simulated evacuation, inside/outside rules, real phones, manual marks and tool isolation (no API calls)."""

import json
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError
from shapely.geometry import Point

from final_agent.agent import BuildingAgent
from final_agent.building_map import BuildingMap, outline
from final_agent.emergency import (
    INSIDE, OUTSIDE_AUTO, OUTSIDE_MANUAL, PRE_MARKED, PRE_MARKED_BY, STALE_S, UNOCCUPIED_TYPES, EmergencyMode, EmergencyNotActive, PersonNotFound,
    PhoneFix, classify, simulate_people,
)
from final_agent.tools import make_emergency_tools

BUILDING = Path(__file__).resolve().parents[1] / "data" / "dev" / "proc-factory-dev-003"
GROUND, UPPER = "proc-factory-dev-003-F0", "proc-factory-dev-003-F1"
OFF_PLAN = (-60.0, 25.65)  # west of the entrance at (-43.5, 25.65)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


class EmergencyModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.map = BuildingMap.load(BUILDING)

    def test_people_are_seeded_start_in_rooms_and_some_stay(self) -> None:
        people = simulate_people(self.map)
        self.assertEqual([(p.name, p.start, p.leave_after_s) for p in people],
                         [(p.name, p.start, p.leave_after_s) for p in simulate_people(self.map)])
        self.assertTrue(any(person.leave_after_s is None for person in people))
        for person in people:
            space = self.map.spaces[person.space_id]
            self.assertNotIn(space["type"], UNOCCUPIED_TYPES)
            self.assertTrue(outline(space["polygon"]).buffer(1e-6).contains(Point(person.start)))

    def test_classify_counts_off_plan_points_as_outside_only_on_entrance_floors(self) -> None:
        self.assertEqual(classify(self.map, GROUND, OFF_PLAN), (OUTSIDE_AUTO, None))
        self.assertEqual(classify(self.map, UPPER, OFF_PLAN), (INSIDE, None))
        anchor = self.map.anchor(next(iter(self.map.spaces)))
        floor = self.map.spaces[next(iter(self.map.spaces))]["floor_id"]
        self.assertEqual(classify(self.map, floor, anchor)[0], INSIDE)

    def test_leavers_walk_out_while_stayers_remain_until_marked(self) -> None:
        clock = FakeClock()
        emergency = EmergencyMode(self.map, clock=clock)
        started = emergency.start("Fire alarm")
        showcase = [p for p in started["people"] if p["status"] == OUTSIDE_MANUAL]
        self.assertEqual(len(showcase), PRE_MARKED)
        self.assertTrue(all(p["manual"]["marked_by"] == PRE_MARKED_BY and p["auto_status"] == OUTSIDE_AUTO for p in showcase))
        self.assertEqual(started["counts"][INSIDE], started["counts"]["total"] - PRE_MARKED)
        emergency.fast_forward(60)  # demo pace: everyone who leaves is out within a minute
        report = emergency.report()
        stayers = {pid for pid, person in emergency.people.items() if person.leave_after_s is None}
        self.assertEqual({p["id"] for p in report["people"] if p["status"] == INSIDE}, stayers)
        self.assertEqual(report["people"][0]["status"], INSIDE)  # still inside sorts first

        stayer = next(iter(stayers))
        record = emergency.mark_outside(emergency.people[stayer].name.upper(), "at the assembly point", "Ada")
        self.assertEqual((record["status"], record["auto_status"]), (OUTSIDE_MANUAL, INSIDE))
        self.assertEqual(record["manual"]["marked_by"], "Ada")
        emergency.clear_mark(stayer)
        self.assertEqual(emergency.record(stayer)["status"], INSIDE)
        with self.assertRaises(PersonNotFound):
            emergency.mark_outside("Nobody Here", "", "Ada")

        emergency.end()
        self.assertEqual((emergency.people, emergency.phones, emergency.marks), ({}, {}, {}))
        with self.assertRaises(EmergencyNotActive):
            emergency.report()

    def test_real_phones_get_opaque_ids_and_stale_inside_stays_inside(self) -> None:
        clock = FakeClock()
        emergency = EmergencyMode(self.map, clock=clock)
        emergency.start("Gas leak")
        room = next(iter(self.map.spaces))
        floor = self.map.spaces[room]["floor_id"]
        emergency.observe([
            PhoneFix("session-in", "Bo", floor, self.map.anchor(room), clock.now),
            PhoneFix("session-out", None, GROUND, OFF_PLAN, clock.now),
            PhoneFix("session-gone", "Old", GROUND, OFF_PLAN, clock.now - 3600),  # before the alarm: ignored
        ])
        phones = {p["id"]: p for p in emergency.report()["people"] if p["kind"] == "session"}
        self.assertEqual(sorted(phones), ["D01", "D02"])
        self.assertNotIn("session-in", json.dumps(list(phones.values())))
        self.assertEqual((phones["D01"]["status"], phones["D02"]["status"]), (INSIDE, OUTSIDE_AUTO))

        clock.now += STALE_S + 1
        phones = {p["id"]: p for p in emergency.report()["people"] if p["kind"] == "session"}
        self.assertTrue(phones["D01"]["stale"] and phones["D02"]["stale"])
        self.assertEqual((phones["D01"]["status"], phones["D02"]["status"]), (INSIDE, OUTSIDE_AUTO))
        self.assertEqual(emergency.report()["people"][0]["id"], "D01")  # stale and inside comes first

    def test_tools_draw_maps_and_stay_out_of_benchmark_agents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_emergency_tools(self.map, Path(temporary))}
            started = json.loads(tools["start_emergency_mode"].call({"reason": "Gas leak"}))
            self.assertTrue(started["images"])
            self.assertTrue(all(Path(image).is_file() for image in started["images"]))
            later = json.loads(tools["emergency_status"].call({"fast_forward_s": 600}))
            self.assertGreater(later["counts"][OUTSIDE_AUTO], 0)
            with self.assertRaises(ToolError):
                tools["start_emergency_mode"].call({"reason": "again"})

            benchmark_names = {tool.name for tool in BuildingAgent(self.map, Path(temporary), client=object()).tools}
            chat_names = {
                tool.name for tool in BuildingAgent(self.map, Path(temporary), client=object(), emergency=True).tools
            }
        self.assertNotIn("start_emergency_mode", benchmark_names)
        self.assertEqual(chat_names - benchmark_names, set(tools))


if __name__ == "__main__":
    unittest.main()
