"""Integration checks of the agent surface: tool schemas, prompt/tool agreement, real tool calls,
answer-line formats against the unchanged scorer and the submission validator. No API calls."""

import csv
import inspect
import json
import re
import tempfile
import unittest
from pathlib import Path

from benchmark.score import score_reply
from final_agent.agent import SYSTEM_PROMPT
from final_agent.benchmark import validate_submission
from final_agent.building_map import BuildingMap
from final_agent.tools import make_tools
from test_storage import example_building

ROOT = Path(__file__).resolve().parents[1]
BUILDING = ROOT / "data" / "dev" / "proc-factory-dev-003"
TEMPLATE = ROOT / "data" / "test" / "submission_template.csv"

# Tools other features add; the coordinator empties this set once they are merged.
UPCOMING = {"analyze_what_if_door", "show_location", "describe_destination_context"}

# Every tool the prompt names; each must be registered (or upcoming).
PROMPT_TOOLS = {
    "building_overview", "search_building", "list_spaces", "spatial_search", "inspect_space", "find_route",
    "reachable_rooms", "find_largest_room", "sum_floor_area", "straight_line_distance_3d", "find_stacked_room",
    "count_shared_walls", "plan_errand", "find_best_tour", "analyze_what_if_door", "find_navigation_landmarks",
    "describe_destination_context", "set_closed", "add_door", "show_route", "show_location",
}
TOOL_LIKE = re.compile(
    r"\b(?:find|show|set|add|list|plan|count|sum|search|inspect|analyze|describe|reachable|straight_line|"
    r"building|spatial)_[a-z0-9_]+\b"
)

OFFICE, NEIGHBOUR_OFFICE, THIRD_OFFICE, MEETING = "Office 0.23", "Office 0.25", "Office 0.26", "Meeting room 0.24"
# One real call per tool; order matters (show_route needs a route, edits come last).
CALLS = {
    "building_overview": {},
    "search_building": {"query": "", "asset_type": "stove"},
    "list_spaces": {"floor_level": 0, "room_type": "office", "page_size": 3},
    "spatial_search": {"x_m": 2.5, "y_m": 20, "floor_level": 0, "radius_m": 3},
    "inspect_space": {"space": OFFICE},
    "find_route": {"start": OFFICE, "destination": NEIGHBOUR_OFFICE},
    "reachable_rooms": {"start": OFFICE, "floor_level": 0, "step_free": True},
    "find_largest_room": {"room_type": "office", "floor_level": 0},
    "sum_floor_area": {"room_type": "office", "floor_level": 0},
    "straight_line_distance_3d": {"first": OFFICE, "second": NEIGHBOUR_OFFICE},
    "find_stacked_room": {"space": OFFICE, "direction": "above"},
    "count_shared_walls": {"space": OFFICE},
    "plan_errand": {
        "start": OFFICE, "asset_type": "stove", "destination_room_type": "meeting_room", "destination_floor_level": 0,
    },
    "find_best_tour": {"start": OFFICE, "stops": [NEIGHBOUR_OFFICE, THIRD_OFFICE], "destination": OFFICE, "activate": False},
    "find_navigation_landmarks": {"x_m": 2.5, "y_m": 20, "floor_level": 0, "inner_radius": 5, "outer_radius": 10},
    "show_route": {},
    "show_location": {"element": OFFICE},
    "describe_destination_context": {"space": OFFICE},
    "analyze_what_if_door": {"first_space": OFFICE, "second_space": MEETING, "floor_level": 1},
    "set_closed": {"element": "Office lift", "closed": True},
    "add_door": {"first_space": OFFICE, "second_space": MEETING},
}


def number_answer(value: float, tolerance: float = 0.0) -> dict:
    return {"type": "number", "value": value, "relative_tolerance": tolerance, "absolute_tolerance": 0.0}


def room_label(room: dict) -> str:
    """The prompt's naming rule: the name, plus the ref in parentheses unless the name has it."""
    return room["name"] if room["ref"] in room["name"] else f"{room['name']} ({room['ref']})"


class ToolContractTests(unittest.TestCase):
    def test_every_tool_has_a_name_description_and_valid_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            tools = make_tools(BuildingMap(example_building()), Path(temporary))
        self.assertEqual(len({tool.name for tool in tools}), len(tools), "duplicate tool names")
        for tool in tools:
            with self.subTest(tool=tool.name):
                self.assertTrue(tool.name.strip())
                self.assertTrue(tool.description.strip())
                schema = tool.to_dict()["input_schema"]
                json.dumps(schema)
                self.assertEqual(schema["type"], "object")
                parameters = inspect.signature(tool.func).parameters
                self.assertEqual(set(schema["properties"]), set(parameters))
                required = {name for name, parameter in parameters.items() if parameter.default is parameter.empty}
                self.assertEqual(set(schema.get("required", [])), required)

    def test_prompt_and_registered_tools_agree(self):
        with tempfile.TemporaryDirectory() as temporary:
            registered = {tool.name for tool in make_tools(BuildingMap(example_building()), Path(temporary))}
        mentioned = set(TOOL_LIKE.findall(SYSTEM_PROMPT))
        self.assertEqual(mentioned - registered - UPCOMING, set(), "prompt names a tool that does not exist")
        self.assertEqual(PROMPT_TOOLS - registered - UPCOMING, set())
        self.assertEqual(registered - mentioned, set(), "registered tool the prompt never explains")
        self.assertEqual(registered - set(CALLS), set(), "add a CALLS entry for the new tool")
        self.assertTrue(UPCOMING <= set(CALLS))


@unittest.skipUnless(BUILDING.exists(), "dev building data not available")
class RealToolCallTests(unittest.TestCase):
    def test_each_registered_tool_returns_parseable_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_tools(BuildingMap.load(BUILDING), Path(temporary))}
            for name, arguments in CALLS.items():
                if name not in tools:
                    self.assertIn(name, UPCOMING)
                    continue
                with self.subTest(tool=name):
                    self.assertIsInstance(json.loads(tools[name].call(arguments)), (dict, list))

    def test_answer_lines_built_from_tool_results_pass_the_scorer(self):
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_tools(BuildingMap.load(BUILDING), Path(temporary))}
            call = lambda name: json.loads(tools[name].call(CALLS[name]))  # noqa: E731
            area, distance = call("sum_floor_area")["area_m2"], call("straight_line_distance_3d")["distance_m"]
            walls, reachable = call("count_shared_walls")["count"], call("reachable_rooms")["count"]
            errand = json.loads(tools["plan_errand"].call(CALLS["plan_errand"]))["length_m"]
            largest = call("find_largest_room")
        numeric = {
            "floor_area_total": (area, 0.05), "straight_line_3d": (distance, 0.02), "errand": (errand, 0.01),
            "shared_walls_count": (walls, 0.0), "wide_delivery_count": (reachable, 0.0),
        }
        for kind, (value, tolerance) in numeric.items():
            with self.subTest(kind=kind):
                reply = f"Computed with the tools: {value} (see steps).\nAnswer: {value}"
                self.assertTrue(score_reply(number_answer(value, tolerance), reply))
        expected = {
            "type": "space", "accept": [largest["room"]["ref"], largest["room"]["name"]], "reject": ["Meeting room 0.24"],
            "area": number_answer(largest["area_m2"], 0.05),
        }
        reply = f"Largest office.\nAnswer: {room_label(largest['room'])}, {largest['area_m2']} m²"
        self.assertTrue(score_reply(expected, reply))



class AnswerFormatTests(unittest.TestCase):
    def test_formats_the_prompt_forbids_fail(self):
        answer = number_answer(12)
        self.assertTrue(score_reply(answer, "Reasoning with 3 steps.\n**Answer:** 12"))
        for reply in ("Answer: between 10 and 14", "Answer: 12 rooms on floor 2", "Answer: Office 0.23, 12", "It is 12."):
            with self.subTest(reply=reply):
                self.assertFalse(score_reply(answer, reply))

    def test_room_label_passes_for_names_without_the_ref(self):
        room = {"name": "Büro", "ref": "1.02"}
        expected = {"type": "space", "accept": ["1.02", "Büro"], "reject": ["Büro (3.04)"]}
        self.assertEqual(room_label(room), "Büro (1.02)")
        self.assertTrue(score_reply(expected, f"Answer: {room_label(room)}"))
        self.assertEqual(room_label({"name": "Office 0.23", "ref": "0.23"}), "Office 0.23")


class SubmissionValidatorTests(unittest.TestCase):
    def check(self, rows: list[list[str]], header=("question_id", "answer")) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            template = Path(temporary) / "template.csv"
            template.write_text("question_id,answer\na,\nb,\nc,\n", encoding="utf-8")
            submission = Path(temporary) / "submission.csv"
            with submission.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(header)
                writer.writerows(rows)
            return validate_submission(submission, template)

    def test_valid_file_with_multiline_unicode_replies_passes(self):
        replies = [["a", "Line one\nAnswer: 12"], ["b", 'Quoted "text", commas\nAnswer: Büro (1.02), 24 m²'], ["c", "Answer: 3"]]
        self.assertEqual(self.check(replies), [])

    def test_each_defect_is_reported(self):
        good = [["a", "Answer: 1"], ["b", "Answer: 2"], ["c", "Answer: 3"]]
        cases = {
            "missing": (good[:2], "missing"),
            "duplicate": (good + [["a", "Answer: 9"]], "duplicate"),
            "extra": (good + [["zzz", "Answer: 9"]], "not in the template"),
            "empty": ([good[0], good[1], ["c", "  "]], "empty"),
            "no answer line": ([good[0], good[1], ["c", "It is 3."]], "Answer:"),
        }
        for label, (rows, fragment) in cases.items():
            with self.subTest(defect=label):
                problems = self.check(rows)
                self.assertTrue(any(fragment in problem for problem in problems), problems)
        self.assertTrue(any("header" in problem for problem in self.check(good, header=("id", "answer"))))

    def test_template_in_repository_lists_145_unique_ids(self):
        if not TEMPLATE.exists():
            self.skipTest("public test template not available")
        with TEMPLATE.open(encoding="utf-8", newline="") as handle:
            ids = [row[0] for row in list(csv.reader(handle))[1:]]
        self.assertEqual((len(ids), len(set(ids))), (145, 145))


if __name__ == "__main__":
    unittest.main()
