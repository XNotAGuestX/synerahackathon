"""find_best_tour: exact optimum, tie-breaks, endpoints, repeats, limits, infeasible stops and state safety."""

import itertools
import json
import math
import random
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError

from final_agent.building_map import BuildingMap, MapError
from final_agent.tools import make_tools


def graph_map(points: dict[str, tuple[float, float]], edges: list[tuple], blocked=()) -> BuildingMap:
    """Rooms are small squares around points; midpoint doors include kit 1.1.0 landing costs.

    Edges listed in blocked get a step (not step-free).
    """
    spaces = [
        {"id": name, "name": name.upper(), "floor_id": "F0", "room_type": "office", "type": "room",
         "polygon": [[x - 0.2, y - 0.2], [x + 0.2, y - 0.2], [x + 0.2, y + 0.2], [x - 0.2, y + 0.2]]}
        for name, (x, y) in points.items()
    ]
    openings = []
    for first, second in edges:
        (x1, y1), (x2, y2) = points[first], points[second]
        openings.append({
            "id": f"{first}-{second}", "floor_id": "F0", "space_ids": [first, second], "kind": "door",
            "position": [(x1 + x2) / 2, (y1 + y2) / 2], "width_m": 1.0,
            "step_free": (first, second) not in blocked,
        })
    return BuildingMap({
        "building": {"id": "tour", "name": "Tour", "units": "m"},
        "floors": [{"id": "F0", "level": 0, "name": "Ground"}],
        "spaces": spaces, "assets": [], "openings": openings, "vertical_connectors": [],
    })


def line_map(positions: dict[str, float], **options) -> BuildingMap:
    names = sorted(positions, key=positions.get)
    return graph_map({name: (positions[name], 0.0) for name in names}, list(itertools.pairwise(names)), **options)


def brute_force_length(building, start, stops, destination, **options) -> float:
    return min(
        building.compute_route(start, destination, via=list(order), **options).length_m
        for order in itertools.permutations(stops)
    )


class BestTourTests(unittest.TestCase):
    def test_equals_exhaustive_permutations_on_random_graphs(self):
        rng = random.Random(7)
        for case in range(15):
            names = [f"r{i}" for i in range(7)]
            points = {name: (rng.uniform(0, 20), rng.uniform(0, 20)) for name in names}
            edges = [(names[i], names[rng.randrange(i)]) for i in range(1, 7)]
            edges += [tuple(rng.sample(names, 2)) for _ in range(3)]
            building = graph_map(points, list({frozenset(edge): edge for edge in edges}.values()))
            start, destination, *stops = rng.sample(names, 6)
            with self.subTest(case=case):
                result = building.find_best_tour(start, stops, destination, activate=False)
                self.assertAlmostEqual(
                    result["length_m"], brute_force_length(building, start, stops, destination), places=6
                )

    def test_nearest_neighbour_order_is_not_chosen_when_worse(self):
        building = line_map({"p": -1, "q": 2, "start": 0, "end": -10})
        result = building.find_best_tour("start", ["p", "q"], "end")
        self.assertEqual(result["stop_sequence"], ["start", "q", "p", "end"])
        self.assertAlmostEqual(result["length_m"], 14.6)
        self.assertAlmostEqual(result["given_order_length_m"], 16.9)
        self.assertAlmostEqual(result["saving_m"], 2.3)

    def test_equal_cost_orders_use_stop_id_order_whatever_the_input_order(self):
        building = line_map({"b": -1, "s": 0, "a": 1})
        for stops in (["a", "b"], ["b", "a"]):
            result = building.find_best_tour("s", stops, "s", activate=False)
            self.assertEqual(result["stop_sequence"], ["s", "a", "b", "s"])
            self.assertAlmostEqual(result["length_m"], 4.6)

    def test_round_trip_and_fixed_endpoints(self):
        building = line_map({"s": 0, "a": 3, "b": 5, "z": -4})
        trip = building.find_best_tour("s", ["a", "b"], "s")
        self.assertEqual((trip["stop_sequence"][0], trip["stop_sequence"][-1]), ("s", "s"))
        self.assertAlmostEqual(trip["length_m"], 10.6)
        open_end = building.find_best_tour("s", ["a", "b"], "z", activate=False)
        self.assertEqual(open_end["stop_sequence"], ["s", "a", "b", "z"])
        self.assertAlmostEqual(open_end["length_m"], 14.75)

    def test_repeated_stops_are_distinct_visits_with_zero_length_leg(self):
        building = line_map({"s": 0, "a": 3, "b": 5})
        result = building.find_best_tour("s", ["a", "b", "a"], "s", activate=False)
        sequence = result["stop_sequence"]
        self.assertEqual(len(sequence), 5)
        self.assertEqual(sorted(sequence[1:4]), ["a", "a", "b"])
        self.assertEqual([leg["length_m"] for leg in result["route"].legs].count(0.0), 1)
        self.assertAlmostEqual(result["length_m"], 10.6)

    def test_no_stops_is_a_normal_route(self):
        building = line_map({"s": 0, "a": 3})
        result = building.find_best_tour("s", [], "a", activate=False)
        plain = building.compute_route("s", "a")
        self.assertEqual(result["stop_sequence"], ["s", "a"])
        self.assertEqual(result["route"].node_path, plain.node_path)
        self.assertEqual((result["length_m"], result["saving_m"]), (plain.length_m, 0.0))

    def test_ten_stops_accepted_and_eleven_rejected(self):
        building = line_map({f"r{i:02d}": i for i in range(13)})
        ten = [f"r{i:02d}" for i in range(10, 0, -1)]
        result = building.find_best_tour("r00", ten, "r12", activate=False)
        self.assertEqual(result["stop_sequence"][1:-1], sorted(ten))
        self.assertAlmostEqual(result["length_m"], 13.8)
        building.last_route = building.compute_route("r00", "r01")
        with self.assertRaisesRegex(MapError, "11 stops is too many.*at most 10"):
            building.find_best_tour("r00", [f"r{i:02d}" for i in range(1, 12)], "r12")
        self.assertIsNone(building.last_route)

    def test_closed_stop_makes_the_tour_infeasible(self):
        building = line_map({"s": 0, "a": 3, "b": 5})
        building.set_closed("a", True)
        with self.assertRaisesRegex(MapError, r"A \[a\].*is closed"):
            building.find_best_tour("s", ["a", "b"], "s")

    def test_unreachable_stop_is_named_with_constraints_and_never_dropped(self):
        building = line_map({"s": 0, "a": 3, "b": 5}, blocked={("a", "b")})
        self.assertAlmostEqual(building.find_best_tour("s", ["a", "b"], "s")["length_m"], 10.6)
        with self.assertRaisesRegex(MapError, r"B \[b\] on Ground cannot be reached.*step_free=True"):
            building.find_best_tour("s", ["a", "b"], "s", step_free=True)
        building.set_closed("a-b", True)
        with self.assertRaisesRegex(MapError, r"B \[b\] on Ground cannot be reached.*a-b"):
            building.find_best_tour("s", ["a", "b"], "s")

    def test_legs_sum_to_length_and_route_visits_stops_in_returned_order(self):
        building = line_map({"p": -1, "q": 2, "start": 0, "end": -10})
        result = building.find_best_tour("start", ["p", "q"], "end", activate=False)
        route = result["route"]
        self.assertAlmostEqual(sum(leg["length_m"] for leg in route.legs), result["length_m"])
        self.assertAlmostEqual(route.length_m, result["length_m"])
        nodes = iter(route.node_path)
        for stop in result["stop_sequence"]:
            self.assertIn(stop, nodes)
        self.assertEqual([leg["to_space_id"] for leg in route.legs], result["stop_sequence"][1:])
        self.assertEqual(route.stops, result["stop_sequence"])

    def test_preview_keeps_state_and_activation_records_the_chosen_order(self):
        building = line_map({"p": -1, "q": 2, "start": 0, "end": -10})
        active = building.route("start", "end", via=["p", "q"])
        request = dict(building.active_request)
        preview = building.find_best_tour("start", ["p", "q"], "end", activate=False)
        self.assertFalse(preview["activated"])
        self.assertIs(building.last_route, active)
        self.assertEqual(building.active_request, request)
        self.assertEqual(building.closed, set())
        chosen = building.find_best_tour("start", ["p", "q"], "end")
        self.assertTrue(chosen["activated"])
        self.assertIs(building.last_route, chosen["route"])
        self.assertEqual(building.active_request["via"], ["q", "p"])
        self.assertEqual(building.recompute_active_route().stops, ["start", "q", "p", "end"])

    def test_tool_returns_rounded_json_with_leg_details(self):
        building = line_map({"p": -1, "q": 2, "start": 0, "end": -10})
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_tools(building, Path(temporary))}
            result = json.loads(tools["find_best_tour"].call(
                {"start": "start", "stops": ["p", "q"], "destination": "end", "activate": False}
            ))
            self.assertEqual(
                (result["optimal"], result["distance_model"], result["activated"], result["length_m"]),
                (True, "kit-1.1.0", False, 14.6),
            )
            self.assertEqual([leg["to"] for leg in result["legs"]], ["q", "p", "end"])
            self.assertTrue(all("space_path" in leg and "element_path" in leg for leg in result["legs"]))
            self.assertEqual(result["route"]["length_m"], 14.6)
            self.assertEqual(result["constraints"]["step_free"], False)
            with self.assertRaisesRegex(ToolError, "too many"):
                tools["find_best_tour"].call(
                    {"start": "start", "stops": ["p"] * 11, "destination": "end"}
                )


if __name__ == "__main__":
    unittest.main()
