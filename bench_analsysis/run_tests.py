"""Run the selected dev cases without confusing missing tools with passing tests.

Offline mode probes existing tools with labelled, resolved inputs (an input oracle).
Agent mode sends only building directory + question text to an answer callable and
uses the unchanged official scorer afterward. It selects scored questions only.
"""

import argparse
from collections import Counter
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from anthropic.lib.tools import ToolError

from benchmark.score import score_reply
from final_agent.building_map import BuildingMap
from final_agent.tools import make_tools


MISSING = {
    "largest_room": "room_area_summary: exact floor/type filter, largest polygon and area",
    "floor_area_total": "room_area_summary: sum every eligible matching polygon",
    "straight_line_3d": "straight_line_distance_3d: polygon centroids at elevation_m",
    "room_stacked": "stacked_room: next available floor and maximum overlap",
    "shared_walls_count": "shared_wall_neighbors: tolerant boundary length and per-kind eligibility",
    "wide_delivery_count": "reachable_rooms: step-free + minimum width + eligible target-room count",
    "step_free_reachable_count": "reachable_rooms: isolated closure + step-free target-room count",
    "errand": "plan_errand: nearest reachable pickup first, then largest destination",
    "what_if_door": "simulate_door_exit_improvement: midpoint door and isolated before/after exit distances",
}


def load_question(case: dict) -> dict:
    path = ROOT / case["source_file"]
    questions = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    matches = [question for question in questions if question["id"] == case["question_id"]]
    if len(matches) != 1:
        raise ValueError(f"Expected one source question: {case['question_id']}")
    question = matches[0]
    if question["kind"] != case["kind"] or question["building_id"] != case["building_id"]:
        raise ValueError(f"Stale case metadata: {case['question_id']}")
    return question


def offline_case(case: dict, question: dict, output: Path) -> tuple[str, str]:
    """Exercise real tool wrappers; no substitute geometry or missing-tool solver."""
    kind = question["kind"]
    if kind in MISSING:
        return "GAP", MISSING[kind]
    building_path = ROOT / "data" / "dev" / case["building_id"] / "building.json"
    original = building_path.read_bytes()
    building = BuildingMap.load(building_path)
    tools = {tool.name: tool for tool in make_tools(building, output)}
    expected = question["answer"]

    def call(name: str, arguments: dict) -> dict:
        return json.loads(tools[name].call(arguments))

    try:
        if kind == "locate":
            # The fixture supplies a resolved subject, not an invented answer ID.
            asset = building.assets[expected["asset_id"]]
            result = call("search_building", {"query": asset["name"], "floor_level": expected["floor_level"]})
            found = [row for row in result["results"] if row["id"] == asset["id"]]
            assert found and found[0]["kind"] == "asset", "Expected asset missing from tool output"
            assert expected["space_id"] in found[0]["in"], "Incorrect containing room"
            return "PASS", "Resolved asset search returns the expected asset, room and floor"

        if kind == "count":
            result = call("search_building", {
                "query": expected["asset_type"], "floor_level": expected["floor_level"],
            })
            return "GAP", (
                f"No exact inventory count tool; substring search reports {result['matches']} matches, "
                f"displays {len(result['results'])}, labelled asset count is {expected['count']}"
            )

        if case.get("probe") == "ambiguity":
            references = {"start": expected["from_space_id"], "destination": expected["to_space_id"]}
            same_name = []
            for argument, space_id in references.items():
                space = building.spaces[space_id]
                duplicates = [other for other in building.spaces.values()
                              if other["name"] == space["name"] and other["floor_id"] == space["floor_id"]]
                if len(duplicates) > 1:
                    references[argument] = space["name"]
                    same_name = duplicates
                    break
            assert same_name, "Duplicate reference fixture changed"
            try:
                call("find_route", references)
            except ToolError as error:
                assert "ambiguous" in str(error).lower(), str(error)
                return "PASS", f"Safely rejects {len(same_name)} same-name rooms on one floor; user clarification still required"
            raise AssertionError("Ambiguous room name was silently resolved")

        if "closed_element_id" in expected:
            result = call("set_closed", {"element": expected["closed_element_id"], "closed": True})
            assert expected["closed_element_id"] in result["all_closed"]
            saved = BuildingMap.load(Path(result["saved_to"]))
            assert expected["closed_element_id"] in saved.closed, "Closure did not round-trip"

        if kind == "tour":
            stops = expected["stops"]
            arguments = {"start": stops[0], "destination": stops[-1], "via": stops[1:-1]}
        else:
            arguments = {
                "start": expected["from_space_id"], "destination": expected["to_space_id"],
                "step_free": kind == "route_step_free",
            }
        try:
            result = call("find_route", arguments)
        except ToolError as error:
            if expected.get("reachable") is False and str(error).startswith("No ") and "route from" in str(error):
                assert building.last_route is None, "Unreachable request retained a prior route"
                return "PASS", "Explicit unreachable error with constraints preserved"
            raise
        assert expected.get("reachable") is not False, "Returned a route for an unreachable fixture"
        # Same deterministic model: use centimetre precision, tighter than warm-up scoring.
        assert abs(result["length_m"] - expected["optimal_length_m"]) <= 0.011, (
            f"Length {result['length_m']} differs from {expected['optimal_length_m']}"
        )
        assert result["start_space_id"] == arguments["start"]
        assert result["destination_space_id"] == arguments["destination"]
        if kind == "tour":
            remaining = iter(result["space_path"])
            assert all(any(node == stop for node in remaining) for stop in expected["stops"]), "Tour stop order changed"
        else:
            assert result["space_path"] == expected["space_path"], "Room sequence differs from local fixture"
        assert result["step_free"] == arguments.get("step_free", False)
        return "PASS", f"Local-model route {result['length_m']:.2f} m; room sequence/stop order checked"
    finally:
        assert building_path.read_bytes() == original, "Probe changed the source building"


def format_checks() -> list[dict]:
    """Check output-format acceptance with fabricated values, not copied answers."""
    number = {"type": "number", "value": 42, "relative_tolerance": 0, "absolute_tolerance": 0}
    room = {"type": "space", "accept": ["Room A"], "reject": ["Room B"],
            "area": {"value": 20, "relative_tolerance": 0.05, "absolute_tolerance": 0}}
    checks = [
        ("single_number", number, "Answer: 42", True),
        ("no_answer_line", number, "The count is 42", False),
        ("multiple_numbers", number, "Answer: 42 rooms on floor 2", False),
        ("last_answer_commits", number, "Answer: 41\nAnswer: 42", True),
        ("room_then_area", room, "Answer: Room A, 20 m²", True),
        ("runner_up_first", room, "Answer: Room B or Room A, 20 m²", False),
    ]
    return [{"check": name, "status": "PASS" if score_reply(answer, reply) == wanted else "FAIL"}
            for name, answer, reply, wanted in checks]


def fingerprint() -> dict[str, str]:
    paths = [*sorted((ROOT / "final_agent").glob("*.py")), ROOT / "benchmark" / "score.py"]
    return {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest() for path in paths}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=["all", "easy", "medium", "hard"], default="all")
    parser.add_argument("--mode", choices=["offline", "agent"], default="offline")
    parser.add_argument("--agent", default="final_agent.benchmark:answer", help="Agent mode only; may use API credits")
    parser.add_argument("--question", action="append", help="Restrict to an exact selected question ID; repeatable")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero for GAP as well as FAIL")
    parser.add_argument("--results", type=Path, help="Write a JSON evidence file")
    args = parser.parse_args()
    cases = json.loads((HERE / "test_cases.json").read_text(encoding="utf-8"))
    if args.question and set(args.question) - {case["question_id"] for case in cases}:
        parser.error("--question must name selected cases in test_cases.json")
    selected = [case for case in cases if (args.tier == "all" or case["tier"] == args.tier)
                and (not args.question or case["question_id"] in args.question)]
    if args.mode == "agent":
        selected = [case for case in selected if Path(case["source_file"]).name == "questions.jsonl"]
        module, name = args.agent.split(":", 1)
        answer_function = getattr(importlib.import_module(module), name)
    if not selected:
        parser.error("No cases selected for this mode")

    rows = []
    for case in selected:
        question = load_question(case)
        try:
            if args.mode == "offline":
                with TemporaryDirectory(prefix="building-analysis-") as temporary:
                    status, detail = offline_case(case, question, Path(temporary))
                row = {**case, "status": status, "detail": detail}
            else:
                # Labels/inputs are never passed into the production answer callable.
                reply = answer_function(ROOT / "data" / "dev" / case["building_id"], question["question"])
                row = {**case, "status": "PASS" if score_reply(question["answer"], reply) else "FAIL", "reply": reply}
        except Exception as error:
            row = {**case, "status": "FAIL", "detail": f"{type(error).__name__}: {error}"}
        rows.append(row)
        print(f"{row['status']:4} {case['tier']:6} {case['question_id']}: {row.get('detail', 'official scored reply')}")

    formats = format_checks()
    counts = dict(Counter(row["status"] for row in rows))
    evidence = {
        "mode": args.mode, "tier": args.tier, "agent": args.agent if args.mode == "agent" else None,
        "scope": "Resolved-input tool probes; GAP is not a passing test" if args.mode == "offline" else "Scored text questions only",
        "source_sha256": fingerprint(), "counts": counts,
        "format_checks": formats, "cases": rows,
    }
    if args.results:
        args.results.parent.mkdir(parents=True, exist_ok=True)
        args.results.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nCases: {counts}; output-format checks: {dict(Counter(row['status'] for row in formats))}")
    print("Offline results do not measure natural-language accuracy or the Synera route model." if args.mode == "offline" else "Warm-up cases are excluded in agent mode.")
    failed = counts.get("FAIL", 0) or any(row["status"] == "FAIL" for row in formats)
    return 1 if failed or (args.strict and counts.get("GAP", 0)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
