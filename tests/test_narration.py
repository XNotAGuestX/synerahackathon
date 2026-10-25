"""AI narrator: validated phrase choice, landmark candidates and the LiveState hook. No model calls."""

import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from final_agent.building_map import BuildingMap
from final_agent.narration import NarrationChoice, NarrationPlan, landmark_candidates, narrate, render
from final_agent.live import LiveState
from final_agent.waypoints import route_walk
from test_hull import ScriptedClient

DEV = Path(__file__).resolve().parent.parent / "data" / "dev"
LANDMARK_PHRASE = {"turn": "turn_past", "door": "door_by", "connector_entry": "connector_by", "stop": "stop_past",
                   "arrival": "arrival_past"}
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


class NarrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.building = BuildingMap.load(DEV / "proc-factory-dev-003" / "building.json")
        stairs = next(iter(cls.building.connectors.values()))
        cls.route = cls.building.compute_route("proc-factory-dev-003-F0-S001", stairs["space_ids"][1])
        cls.walk = route_walk(cls.building, cls.route)
        cls.candidates = {w.index: [{"id": f"asset-{w.index}", "name": f"Lathe {w.index}", "distance_m": 2.0}] for w in cls.walk.waypoints}
        cls.landmarked = next(w for w in cls.walk.waypoints if w.kind in LANDMARK_PHRASE and render(w, LANDMARK_PHRASE[w.kind], "x") != render(w))

    def narrate(self, plan_or_error):
        client = ScriptedClient([], parsed=[plan_or_error])
        texts = narrate(client, "claude-haiku-5-5", self.walk, self.candidates)
        self.assertEqual(client.parse_requests[0]["output_format"], NarrationPlan)
        self.assertEqual(set(texts), {w.index for w in self.walk.waypoints})
        return texts

    def defaults(self):
        return {w.index: render(w) for w in self.walk.waypoints}

    def test_valid_plan_uses_landmark_for_chosen_index_and_metres_for_others(self):
        w = self.landmarked
        plan = NarrationPlan(choices=[NarrationChoice(index=w.index, phrase_id=LANDMARK_PHRASE[w.kind], landmark_id=f"asset-{w.index}")])
        texts = self.narrate(plan)
        self.assertIn(f"Lathe {w.index}", texts[w.index])
        self.assertEqual({i: t for i, t in texts.items() if i != w.index}, {i: t for i, t in self.defaults().items() if i != w.index})

    def test_invalid_phrase_or_unknown_landmark_falls_back_to_default(self):
        w = self.landmarked
        for choice in (NarrationChoice(index=w.index, phrase_id="no_such_phrase", landmark_id=None),
                       NarrationChoice(index=w.index, phrase_id="arrival_ahead" if w.kind != "arrival" else "turn_in", landmark_id=None),
                       NarrationChoice(index=w.index, phrase_id=LANDMARK_PHRASE[w.kind], landmark_id="invented")):
            self.assertEqual(self.narrate(NarrationPlan(choices=[choice])), self.defaults())

    def test_failing_parse_gives_defaults(self):
        self.assertEqual(self.narrate(RuntimeError("model down")), self.defaults())

    def test_landmark_candidates_are_unambiguous_assets_only(self):
        found = [item for w in self.walk.waypoints for item in landmark_candidates(self.building, w)]
        self.assertTrue(found)
        for item in found:
            self.assertIn(item["id"], self.building.assets)
            self.assertTrue(next(c for c in self.building.find_navigation_landmarks(
                *self.building.assets[item["id"]]["position"], self.building.floors[self.building.spaces[self.building.assets[item["id"]]["space_id"]]["floor_id"]]["level"],
                inner_radius=0.5, outer_radius=15.0, kind="asset")["candidates"] if c["id"] == item["id"])["is_unambiguous"])

    def test_first_event_uses_default_text_when_narrator_is_slow_then_narrated_text_applies(self):
        release = threading.Event()
        texts = {w.index: f"Narrated {w.index}." for w in self.walk.waypoints}

        def slow(building_map, walk):
            release.wait(5)
            return texts

        live = LiveState(lambda: NOW, iter(f"id{n}" for n in range(1000)).__next__, narrate=slow, first_wait_s=0.1)
        record = {"destination_space_id": self.route.destination_space_id}
        live.start(self.building, "r1", record, self.route, spoken=False)
        first = live.events_after(0, 0)[0][0]
        self.assertEqual(first["text"], render(self.walk.waypoints[0]))
        release.set()
        for _ in range(100):
            if live.guidance_view()["waypoints"][0]["text"] == texts[0]:
                break
            threading.Event().wait(0.02)
        self.assertEqual(live.guidance_view()["waypoints"][0]["text"], "Narrated 0.")
        w0 = self.walk.waypoints[0]
        live.apply_fix(self.building, {"floor_id": w0.floor_id, "x_m": w0.at[0], "y_m": w0.at[1], "measured_at": NOW, "source": "simulated"})
        self.assertEqual(live.events_after(first["seq"], 0)[0][0]["text"], "Narrated 1.")

    def test_fast_narrator_text_is_in_first_event_and_late_result_after_stop_is_discarded(self):
        live = LiveState(lambda: NOW, iter(f"id{n}" for n in range(1000)).__next__, narrate=lambda b, w: {0: "Narrated 0."}, first_wait_s=2.0)
        live.start(self.building, "r1", {"destination_space_id": self.route.destination_space_id}, self.route, spoken=False)
        self.assertEqual(live.events_after(0, 0)[0][0]["text"], "Narrated 0.")
        release = threading.Event()
        late = LiveState(lambda: NOW, iter(f"id{n}" for n in range(1000)).__next__, narrate=lambda b, w: release.wait(5) and {0: "Late."}, first_wait_s=0.05)
        late.start(self.building, "r1", {"destination_space_id": self.route.destination_space_id}, self.route, spoken=False)
        late.stop("cancelled")
        release.set()
        threading.Event().wait(0.2)
        self.assertEqual(late.guidance_view()["waypoints"], [])


if __name__ == "__main__":
    unittest.main()
