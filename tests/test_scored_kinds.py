"""Labelled dev checks for the nine scored geometry tools. Answers are used only here."""

import json
import unittest
from pathlib import Path

from benchmark.score import score_reply
from final_agent.building_map import BuildingMap, MapError
from final_agent.scored import answer_line

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "dev"


def questions():
    found = []
    for path in sorted(DEV.glob("*/questions.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                found.append((path.parent, json.loads(line)))
    return found


def compute(building: BuildingMap, question: dict) -> dict:
    kind = question["kind"]
    inputs = question["inputs"]
    if kind == "largest_room":
        return building.largest_room(inputs["floor_id"], inputs["room_type"])
    if kind == "floor_area_total":
        return building.floor_area_total(inputs["floor_id"], inputs["room_type"])
    if kind == "straight_line_3d":
        return building.straight_line_3d(inputs["first"], inputs["second"])
    if kind == "room_stacked":
        return building.room_stacked(inputs["start"], inputs["direction"])
    if kind == "shared_walls_count":
        return building.shared_walls_count(inputs["start"])
    if kind == "wide_delivery_count":
        return building.wide_delivery_count(inputs["start"], inputs["floor_id"], inputs["min_width"])
    if kind == "step_free_reachable_count":
        return building.step_free_reachable_count(inputs["start"], inputs["floor_id"], inputs.get("closed"))
    if kind == "errand":
        return building.errand(inputs["start"], inputs["asset_type"], inputs["floor_id"], inputs["room_type"])
    if kind == "what_if_door":
        return building.what_if_door(inputs["first"], inputs["second"], inputs["floor_id"])
    raise MapError(kind)


def matches(kind: str, got: dict, answer: dict) -> bool:
    if kind in {"largest_room", "room_stacked"}:
        return got.get("space_id") == answer["space_id"]
    if kind == "floor_area_total":
        return abs(got["area_m2"] - answer["value"]) <= max(0.05 * answer["value"], answer.get("absolute_tolerance", 0))
    if kind == "straight_line_3d":
        return abs(got["distance_m"] - answer["value"]) <= max(0.02 * answer["value"], answer.get("absolute_tolerance", 0))
    if kind == "errand":
        tolerance = max(0.01 * answer["value"], answer.get("absolute_tolerance", 1))
        return abs(got["length_m"] - answer["value"]) <= tolerance and got["pickup"] == answer["via"] and got["destination"] == answer["target"]
    return got["count"] == answer["value"]


class ScoredKindTests(unittest.TestCase):
    def test_dev_questions_match_labels(self) -> None:
        failures = []
        for directory, question in questions():
            building = BuildingMap.load(directory)
            try:
                got = compute(building, question)
                ok = matches(question["kind"], got, question["answer"])
            except MapError as error:
                got = str(error)
                ok = False
            if not ok:
                failures.append(f"{question['id']} {question['kind']} {got}")
        self.assertEqual(failures, [])

    def test_question_text_formats_answer_lines(self) -> None:
        failures = []
        for directory, question in questions():
            reply = answer_line(BuildingMap.load(directory), question["question"])
            if not reply or not score_reply(question["answer"], reply):
                failures.append(question["id"])
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
