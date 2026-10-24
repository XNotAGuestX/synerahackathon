"""reachable_rooms: one traversal under step-free, width, entrance and temporary-closure constraints."""

import json
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError

from final_agent.building_map import BuildingMap, MapError
from final_agent.tools import make_tools


def square(x, y):
    return [[x, y], [x + 2, y], [x + 2, y + 2], [x, y + 2]]


def space(space_id, floor_id, kind, x, y):
    return {"id": space_id, "name": space_id, "floor_id": floor_id, "type": kind, "room_type": kind,
            "polygon": square(x, y)}


def opening(opening_id, first, second, width=1.2, step_free=True, floor_id="F0"):
    kind = "entrance" if "outside" in (first, second) else "door"
    return {"id": opening_id, "floor_id": floor_id, "space_ids": [first, second], "kind": kind,
            "position": [0, 0], "width_m": width, "step_free": step_free}


def lift(connector_id, low_space, high_space, name):
    return {"id": connector_id, "kind": "lift", "name": name, "step_free": True,
            "floor_ids": ["F0", "F1"], "space_ids": [low_space, high_space]}


def make_map(extra_openings=(), connectors=(), width=1.2) -> BuildingMap:
    """Ground: start S - hall H - rooms A, B; corridor K behind A. Lift lobbies LL/LL2 on ground, UL/UL2 up."""
    spaces = [
        space("S", "F0", "room", 0, 0), space("H", "F0", "hall", 2, 0), space("A", "F0", "room", 4, 0),
        space("B", "F0", "room", 2, 2), space("K", "F0", "corridor", 6, 0), space("LL", "F0", "lift", 0, 4),
        space("LL2", "F0", "lift", 2, 4),
        space("U1", "F1", "room", 0, 0), space("U2", "F1", "room", 2, 0), space("UL", "F1", "lift", 0, 4),
        space("UL2", "F1", "lift", 2, 4),
    ]
    openings = [
        opening("D-SH", "S", "H", width), opening("D-HA", "H", "A", width), opening("D-HB", "H", "B", width),
        opening("D-AK", "A", "K", width), opening("D-HL", "H", "LL", width), opening("D-HL2", "H", "LL2", width),
        opening("D-U1", "UL", "U1", width, floor_id="F1"), opening("D-U2", "UL2", "U2", width, floor_id="F1"),
        *extra_openings,
    ]
    return BuildingMap({
        "building": {"id": "test", "name": "Test", "units": "m"},
        "floors": [{"id": "F0", "level": 0, "name": "Ground"}, {"id": "F1", "level": 1, "name": "First"}],
        "spaces": spaces, "assets": [], "openings": openings, "vertical_connectors": list(connectors),
    })


TWO_LIFTS = [lift("V1", "LL", "UL", "Lift 1"), lift("V2", "LL2", "UL2", "Lift 2")]


class ReachableRoomsTests(unittest.TestCase):
    def test_counts_rooms_once_and_only_type_room_including_start(self):
        result = make_map().reachable_rooms("S", floor_level=0)
        self.assertEqual((result["count"], result["room_ids"]), (3, ["A", "B", "S"]))
        self.assertEqual(result["excluded_reachable"], {"corridor": 1, "hall": 1, "lift": 2})
        self.assertFalse(result["rooms_truncated"])
        self.assertEqual([room["id"] for room in result["rooms"]], ["A", "B", "S"])

    def test_door_width_equal_passes_and_narrower_blocks(self):
        self.assertEqual(make_map(width=1.0).reachable_rooms("S", 0, min_width_m=1.0)["count"], 3)
        self.assertEqual(make_map(width=0.99).reachable_rooms("S", 0, min_width_m=1.0)["room_ids"], ["S"])

    def test_narrow_explicit_entrance_fails_despite_wide_interior(self):
        building = make_map([opening("E1", "S", "outside", width=0.8)])
        with self.assertRaisesRegex(MapError, "0.8 m wide, narrower than the required 1 m"):
            building.reachable_rooms("S", 0, min_width_m=1.0, entrance="E1")
        self.assertEqual(building.reachable_rooms("S", 0, min_width_m=0.8, entrance="E1")["count"], 3)

    def test_room_entrance_reports_narrow_width_as_warning(self):
        building = make_map([opening("E1", "S", "outside", width=0.8)])
        result = building.reachable_rooms("S", 0, min_width_m=1.0, entrance="S")
        self.assertEqual(result["count"], 3)
        self.assertIn("E1", result["entry"]["warnings"][0])

    def test_stepped_entrance_is_rejected_when_step_free(self):
        building = make_map([opening("E1", "S", "outside", step_free=False)])
        with self.assertRaisesRegex(MapError, "has steps"):
            building.reachable_rooms("S", 0, step_free=True, entrance="S")
        self.assertEqual(building.reachable_rooms("S", 0, entrance="S")["count"], 3)

    def test_entrance_must_open_into_the_start(self):
        building = make_map([opening("E1", "A", "outside")])
        with self.assertRaisesRegex(MapError, "does not open into"):
            building.reachable_rooms("S", 0, entrance="E1")
        with self.assertRaisesRegex(MapError, "but the start is"):
            building.reachable_rooms("S", 0, entrance="A")
        with self.assertRaisesRegex(MapError, "no entrance from outside"):
            building.reachable_rooms("S", 0, entrance="S")

    def test_materially_different_entrances_are_ambiguous_and_equal_ones_are_all_reported(self):
        building = make_map([
            opening("E1", "S", "outside"), opening("E2", "S", "outside", step_free=False),
        ])
        with self.assertRaisesRegex(MapError, r"several entrances.*E1.*E2"):
            building.reachable_rooms("S", 0, step_free=True, entrance="S")
        result = building.reachable_rooms("S", 0, entrance="S")
        self.assertEqual([entrance["id"] for entrance in result["entry"]["entrances"]], ["E1", "E2"])
        building.closed.update(["E1", "E2"])
        with self.assertRaisesRegex(MapError, "No usable entrance.*closed"):
            building.reachable_rooms("S", 0, entrance="S")

    def test_closed_lift_with_alternative_lift_still_reaches_upstairs(self):
        building = make_map(connectors=TWO_LIFTS)
        self.assertEqual(building.reachable_rooms("S", 1, step_free=True)["room_ids"], ["U1", "U2"])
        one_closed = building.reachable_rooms("S", 1, step_free=True, closed_elements=["Lift 1"])
        self.assertEqual(one_closed["room_ids"], ["U2"])
        self.assertEqual(one_closed["constraints"]["temporarily_closed"], ["V1"])
        both = building.reachable_rooms("S", 1, step_free=True, closed_elements=["Lift 1", "V2"])
        self.assertEqual((both["count"], both["room_ids"]), (0, []))

    def test_no_lift_means_upper_floor_is_unreachable_step_free_only(self):
        stairs = {**lift("V3", "LL", "UL", "Stairs"), "kind": "stairs", "step_free": False}
        building = make_map(connectors=[stairs])
        self.assertEqual(building.reachable_rooms("S", 1, step_free=True)["count"], 0)
        self.assertEqual(building.reachable_rooms("S", 1)["room_ids"], ["U1"])

    def test_floor_filter_counts_only_that_floor_but_traverses_others(self):
        # Reaching ground room B from upstairs requires going down through the other floor's lift.
        building = make_map(connectors=TWO_LIFTS)
        ground = building.reachable_rooms("U1", 0, step_free=True)
        self.assertEqual(ground["room_ids"], ["A", "B", "S"])
        self.assertEqual(ground["excluded_reachable"], {"corridor": 1, "hall": 1, "lift": 2})
        everywhere = building.reachable_rooms("U1")
        self.assertEqual(everywhere["room_ids"], ["A", "B", "S", "U1", "U2"])

    def test_room_type_filter_limits_counted_rooms_only(self):
        building = make_map()
        building.spaces["A"]["room_type"] = "office"
        result = building.reachable_rooms("S", 0, room_type="Office")
        self.assertEqual(result["room_ids"], ["A"])

    def test_closed_room_is_not_counted_and_closed_start_is_an_error(self):
        building = make_map()
        building.set_closed("B", True)
        self.assertEqual(building.reachable_rooms("S", 0)["room_ids"], ["A", "S"])
        with self.assertRaisesRegex(MapError, "is closed"):
            building.reachable_rooms("S", 0, closed_elements=["S"])
        building.set_closed("D-HA", True)
        self.assertEqual(building.reachable_rooms("S", 0)["room_ids"], ["S"])

    def test_valid_start_without_eligible_rooms_returns_zero(self):
        building = make_map(connectors=TWO_LIFTS)
        result = building.reachable_rooms("LL", 1, step_free=True, closed_elements=["Lift 1", "Lift 2"])
        self.assertEqual((result["count"], result["room_ids"]), (0, []))

    def test_invalid_inputs_are_actionable_errors(self):
        building = make_map()
        with self.assertRaisesRegex(MapError, "Unknown floor level"):
            building.reachable_rooms("S", 7)
        with self.assertRaises(MapError):
            building.reachable_rooms("S", 0, min_width_m=-1)
        with self.assertRaises(MapError):
            building.reachable_rooms("S", 0, min_width_m=float("nan"))
        with self.assertRaises(MapError):
            building.reachable_rooms("Nowhere", 0)
        with self.assertRaises(MapError):
            building.reachable_rooms("S", 0, closed_elements=["Nowhere"])

    def test_temporary_closure_leaves_state_and_files_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            building = make_map(connectors=TWO_LIFTS)
            building.route("S", "U1", step_free=True)
            route, request, closed = building.last_route, dict(building.active_request), set(building.closed)
            path = Path(temporary) / "building.json"
            building.save(path)
            before = path.read_bytes()
            building.reachable_rooms("S", 1, step_free=True, closed_elements=["Lift 1", "Lift 2"])
            self.assertEqual((building.closed, building.active_request), (closed, request))
            self.assertIs(building.last_route, route)
            self.assertEqual(path.read_bytes(), before)

    def test_tool_returns_json_and_converts_errors(self):
        building = make_map(connectors=TWO_LIFTS)
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_tools(building, Path(temporary))}
        result = json.loads(tools["reachable_rooms"].call(
            {"start": "S", "floor_level": 1, "step_free": True, "closed_elements": ["Lift 1"]}
        ))
        self.assertEqual(result["count"], 1)
        self.assertIn("exactly one", tools["reachable_rooms"].to_dict()["description"])
        with self.assertRaises(ToolError):
            tools["reachable_rooms"].call({"start": "Nowhere"})


if __name__ == "__main__":
    unittest.main()
