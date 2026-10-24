"""Rebuild the dev catalog, labelled train supplements and coverage reports."""

from collections import Counter
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CASES_PER_KIND = 5

# Status is an audit of the exposed final_agent tools, not live LLM accuracy.
TYPES = [
    ("locate", "warm-up", "Yes, tool core", "search_building", "None for resolved asset lookup; interactive highlight still missing", "Asset ID, containing room, floor; fixture also records XY", "resplan-8269-Q01"),
    ("count", "warm-up", "Partial", "search_building", "query_inventory: exact asset type + floor + complete count", "Exact number of assets, excluding matching room names and other types", "osm-way22744230-Q04; swiss-5097-Q02"),
    ("route", "warm-up", "Yes, local model", "find_route", "None for local length/space path; retain selected openings/connectors for route validation", "Reachable route: length_m, ordered spaces and actual opening/connector path", "osm-way27917482-Q05"),
    ("route_step_free", "warm-up", "Yes, local model", "find_route(step_free=True)", "None for resolved-input step-free search; explicit unreachable reply still needs live verification", "Constrained route OR explicit unreachable; same floor does not imply reachable", "swiss-5097-Q06"),
    ("route_with_closure", "warm-up", "Yes, tool core", "set_closed + find_route", "None for isolated resolved-input closure routing; stale-route invalidation remains open", "Route avoiding closed connector OR explicit unreachable", "proc-campus-dev-009-Q09; osm-way27326387-Q06"),
    ("tour", "warm-up", "Yes, local model", "find_route(via=[...])", "None for fixed-order total; expose leg boundaries and selected elements", "Ordered stop visits, per-leg paths/lengths in fixture, total distance", "proc-campus-dev-001-Q10"),
    ("largest_room", "scored", "No", "No area tool", "room_area_summary", "Answer: selected room first, area within 5%", "swiss-450-H01"),
    ("floor_area_total", "scored", "No", "No area aggregation", "room_area_summary", "Answer: exactly one number; total polygon area within 5%", "swiss-1689-H01"),
    ("straight_line_3d", "scored", "No", "No centroid/elevation distance tool", "straight_line_distance_3d", "Answer: exactly one number; Euclidean XYZ metres within 2%", "proc-factory-dev-005-H06"),
    ("room_stacked", "scored", "No", "spatial_search is only a point/radius query", "stacked_room", "Answer: room with greatest overlap on next higher/lower available floor", "osm-way27326387-H05; osm-way22744230-H05"),
    ("shared_walls_count", "scored", "No", "No boundary adjacency tool", "shared_wall_neighbors", "Answer: exact eligible-neighbour count; >=1 m within 0.35 m", "proc-factory-dev-003-H05"),
    ("wide_delivery_count", "scored", "No", "Step-free route exists, width filtering/count do not", "reachable_rooms (minimum width + step-free)", "Answer: exact reachable type=room count on target floor, including start if eligible", "resplan-8269-H01; proc-campus-dev-009-H03"),
    ("step_free_reachable_count", "scored", "No", "Closure and pairwise route primitives exist", "reachable_rooms (isolated closure + step-free)", "Answer: exact reachable room count after named closure", "osm-way22744230-H03"),
    ("errand", "scored", "No", "find_route(via=...) cannot select pickup/destination", "query_inventory + room_area_summary + plan_errand", "Answer: one total distance, nearest pickup first; within max(1%, 1 m)", "swiss-460-H03"),
    ("what_if_door", "scored", "No", "add_door persists edits and has no impact analysis", "simulate_door_exit_improvement + shared-wall midpoint", "Answer: exact other-floor room count with exit-distance improvement strictly >1 m", "osm-way27917482-H08; osm-way27917482-H09"),
]


def write_csv(name: str, rows: list[dict]) -> None:
    with (HERE / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def expected_result(question: dict) -> str:
    answer = question["answer"]
    if answer.get("type") == "number":
        return f"Answer: {answer['value']} ({answer['unit']}); tolerance max({answer['relative_tolerance'] * 100:g}%, {answer['absolute_tolerance']:g})"
    if answer.get("type") == "space":
        label = answer["accept"][-1]
        return f"Answer: {label}" + (f", {answer['area']['value']} m² (±5%)" if "area" in answer else "")
    if "asset_id" in answer:
        return f"{answer['asset_id']}; {answer['space_name']}; floor {answer['floor_level']}"
    if "count" in answer:
        return f"{answer['count']} assets, exact type={answer['asset_type']}, floor={answer['floor_level']}"
    if answer.get("reachable") is False:
        return "Explicit unreachable result; preserve requested constraints"
    if "stops" in answer:
        return f"{answer['optimal_length_m']} m total; {len(answer['stops'])} stops in specified order"
    return f"{answer['optimal_length_m']} m; ordered space/element path from fixture"


def classify(question: dict, building: dict) -> tuple[str, list[str]]:
    """Normalize independent reviewers' terminology using actual question metadata."""
    kind, answer = question["kind"], question["answer"]
    inputs = question.get("inputs", {})
    spaces = {space["id"]: space for space in building["spaces"]}
    connectors = {connector["id"]: connector for connector in building["vertical_connectors"]}
    flags = []
    levels = sorted(floor["level"] for floor in building["floors"])
    if any(high - low > 1 for low, high in zip(levels, levels[1:])):
        flags.append("building_has_floor_gap")
    paths = [answer.get("space_path", [])] + [leg.get("space_path", []) for leg in answer.get("legs", [])]
    outside = any("outside" in path for path in paths)
    if outside:
        flags.append("local_outside_transition")
    if answer.get("reachable") is False:
        flags.append("expected_unreachable")
    if answer.get("space_id") in spaces and spaces[answer["space_id"]]["type"] == "hall":
        flags.append("selected_space_is_hall")
    if answer.get("via") in spaces and spaces[answer["via"]]["type"] == "outdoor":
        flags.append("pickup_is_outdoor")
    if kind == "count" and answer["count"] > 15:
        flags.append("inventory_exceeds_display_page")
    for key in ("from_space_id", "to_space_id"):
        if key in answer:
            endpoint = spaces[answer[key]]
            if sum(other["name"] == endpoint["name"] and other["floor_id"] == endpoint["floor_id"]
                   for other in spaces.values()) > 1:
                flags.append("same_floor_duplicate_endpoint_name")
                break

    if kind == "locate":
        subtype = "named_asset_lookup"
    elif kind == "count":
        subtype = "exact_asset_type_on_floor"
    elif kind in {"route", "route_step_free"}:
        same_floor = spaces[answer["from_space_id"]]["floor_id"] == spaces[answer["to_space_id"]]["floor_id"]
        floor = "same_floor" if same_floor else "cross_floor"
        outcome = "unreachable" if answer.get("reachable") is False else "via_outside" if outside else "indoor"
        subtype = f"{floor}_{outcome}"
    elif kind == "route_with_closure":
        closed = connectors.get(answer["closed_element_id"], {})
        outcome = "unreachable" if answer.get("reachable") is False else "reachable"
        subtype = f"{closed.get('kind', 'element')}_closure_{outcome}"
    elif kind == "tour":
        stop_floors = {spaces[stop]["floor_id"] for stop in answer["stops"]}
        subtype = "ordered_tour_via_outside" if outside else "ordered_tour_cross_floor" if len(stop_floors) > 1 else "ordered_tour_same_floor"
    elif kind == "largest_room":
        subtype = "exact_room_type_floor_maximum"
    elif kind == "floor_area_total":
        subtype = "exact_room_type_floor_sum"
    elif kind == "room_stacked":
        subtype = f"{inputs['direction']}_maximum_overlap"
    elif kind == "shared_walls_count":
        subtype = "same_floor_tolerant_wall_count"
    elif kind == "straight_line_3d":
        subtype = "centroid_xyz_distance"
    elif kind == "wide_delivery_count":
        same_floor = spaces[inputs["start"]]["floor_id"] == inputs["floor_id"]
        subtype = "same_floor_step_free_width" if same_floor else "cross_floor_step_free_width"
    elif kind == "step_free_reachable_count":
        subtype = "lift_outage_step_free_room_count"
    elif kind == "errand":
        same_floor = spaces[inputs["start"]]["floor_id"] == inputs["floor_id"]
        subtype = "nearest_pickup_then_largest_same_floor" if same_floor else "nearest_pickup_then_largest_cross_floor"
    elif kind == "what_if_door":
        first, second = (spaces[inputs[key]]["type"] for key in ("first", "second"))
        subtype = f"{first}_to_{second}_other_floor_exit_improvement"
    else:
        raise ValueError(f"Unreviewed question kind: {kind}")
    return subtype, flags


def main() -> None:
    buildings = json.loads((HERE / "buildings.json").read_text(encoding="utf-8"))
    assert len(buildings) == 20 and len({b["building_id"] for b in buildings}) == 20
    annotations = {}
    supplemental = json.loads((HERE / "supplemental_annotations.json").read_text(encoding="utf-8"))
    for path in [*sorted((HERE / "reviews").glob("*_annotations.json")), HERE / "supplemental_annotations.json"]:
        for row in json.loads(path.read_text(encoding="utf-8")):
            if row["question_id"] in annotations:
                raise ValueError(f"Duplicate annotation: {row['question_id']}")
            annotations[row["question_id"]] = row
    cases = json.loads((HERE / "test_cases.json").read_text(encoding="utf-8"))
    assert {case["tier"] for case in cases} == {"easy", "medium", "hard"}
    assert {b["building_id"] for b in buildings} <= {case["building_id"] for case in cases}
    selected = {case["question_id"]: case for case in cases}
    assert len(selected) == len(cases), "Representative IDs must be unique"
    assert {row["question_id"] for row in supplemental} <= set(selected)
    # Keep the original family-balanced dev sample intact. Add only the scarce
    # labelled train questions, rather than silently adding their whole building.
    sources = [(building, filename, None) for building in buildings
               for filename in ("questions.jsonl", "questions_basic.jsonl")]
    for source_file in sorted({row["source_file"] for row in supplemental}):
        source = Path(source_file)
        assert source.parts[:2] == ("data", "train")
        building = {"building_id": source.parent.name, "path": str(source.parent), "family": "osm"}
        sources.append((building, source.name, {row["question_id"] for row in supplemental
                                              if row["source_file"] == source_file}))
    questions = []
    originals = {}
    for building, filename, only_ids in sources:
        building_data = json.loads((ROOT / building["path"] / "building.json").read_text(encoding="utf-8"))
        source = Path(building["path"]) / filename
        for line_number, line in enumerate((ROOT / source).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            question = json.loads(line)
            qid = question["id"]
            if only_ids is not None and qid not in only_ids:
                continue
            if qid in originals:
                raise ValueError(f"Duplicate source question: {qid}")
            originals[qid] = question
            annotation = annotations[qid]
            assert annotation["kind"] == question["kind"] and annotation["building_id"] == building["building_id"]
            assert annotation["source_file"] == str(source)
            subtype, flags = classify(question, building_data)
            questions.append({
                "question_id": qid, "building_id": building["building_id"], "family": building["family"],
                "scope": "scored" if filename == "questions.jsonl" else "warm-up",
                "split": source.parts[1],
                "kind": question["kind"], "subtype": subtype, "flags": json.dumps(flags),
                "reviewer_subtype": annotation["subtype"],
                "tier": selected.get(qid, annotation)["tier"], "representative": qid in selected,
                "source_file": str(source), "source_line": line_number,
                "question": question["question"], "expected_result": expected_result(question),
                "expected_json": json.dumps(question["answer"], ensure_ascii=False, sort_keys=True),
                "review_note": annotation["note"],
            })
    assert set(annotations) == set(originals), "Annotations must cover exactly the dev sample and supplements"
    assert set(selected) <= set(originals)
    for qid, case in selected.items():
        assert all(case[key] == annotations[qid][key] for key in ("kind", "building_id", "source_file")), qid
    # Availability is audited from labelled train/dev only; test has no labels.
    available = Counter()
    for split in ("train", "dev"):
        for path in sorted((ROOT / "data" / split).glob("*/questions*.jsonl")):
            available.update(json.loads(line)["kind"] for line in path.read_text(encoding="utf-8").splitlines()
                             if line.strip())
    case_counts = Counter(case["kind"] for case in cases)
    assert set(case_counts) == {row[0] for row in TYPES}
    assert all(case_counts[kind] == min(CASES_PER_KIND, available[kind]) for kind in case_counts), "Top up underrepresented kinds"
    write_csv("questions.csv", questions)
    subtype_rows = []
    for kind, subtype in sorted({(q["kind"], q["subtype"]) for q in questions}):
        matching = [q for q in questions if q["kind"] == kind and q["subtype"] == subtype]
        subtype_rows.append({"kind": kind, "subtype": subtype, "questions": len(matching),
                             "buildings": len({q["building_id"] for q in matching}),
                             "example_id": matching[0]["question_id"]})
    write_csv("question_subtypes.csv", subtype_rows)
    subtype_text = ["# Normalized request subtypes", "",
                    f"These analysis subtypes normalize reviewer vocabulary; they are not new official kind labels. Each of the {len(questions)} source questions has one subtype. Overlapping edge characteristics are recorded separately as flags in `questions.csv`.", "",
                    "| Kind | Subtype | Questions | Buildings | Example |", "|---|---|---:|---:|---|"]
    subtype_text += ["| " + " | ".join(cell(value) for value in row.values()) + " |" for row in subtype_rows]
    subtype_text += ["", "| Additional flag | Questions |", "|---|---:|"]
    flag_counts = Counter(flag for q in questions for flag in json.loads(q["flags"]))
    subtype_text += [f"| `{flag}` | {count} |" for flag, count in sorted(flag_counts.items())]
    subtype_text += ["", "Flags overlap and should not be summed as a question total. Reviewer notes and family reports contain finer distinctions such as hall eligibility and counterfactual geometry.", ""]
    (HERE / "question_subtypes.md").write_text("\n".join(subtype_text), encoding="utf-8")
    counts = Counter(question["kind"] for question in questions)
    catalog = []
    for kind, scope, status, existing, missing, output, example in TYPES:
        matching = [question for question in questions if question["kind"] == kind]
        catalog.append({"question_type": kind, "scope": scope, "questions": counts[kind],
                        "representative_cases": case_counts[kind], "labelled_available": available[kind],
                        "buildings": len({q["building_id"] for q in matching}), "implemented": status,
                        "existing_tool": existing, "missing_tool": missing,
                        "expected_result": output, "representative_ids": example})
    assert set(counts) == {row[0] for row in TYPES}, "Unexpected kind: extend audit rather than hiding it"
    write_csv("question_types.csv", catalog)
    sample_csv = [{**building, "levels": json.dumps(building["levels"])} for building in buildings]
    write_csv("building_sample.csv", sample_csv)
    rows = ["# Question types and implementation coverage", "",
            "Status audits the exposed `final_agent` tools. Yes means a resolved-input local-model primitive exists; it does not claim live conversational accuracy or complete rendering. Partial count support is not a complete exact inventory tool. All nine scored kinds lack a complete exposed solution.", "",
            f"Runnable selection targets {CASES_PER_KIND} distinct questions per kind, preserving all original cases. Two kinds exhaust the labelled train/dev supply below that target. The full ledger retains the original dev distribution plus three explicitly marked train supplements; its raw counts are not balanced. See [selection balance](tests.md#selection-balance).", "",
            "| Type | Questions / buildings | Runnable / labelled available | Implemented | Existing tool | Missing tool or work | Expected result |",
            "|---|---:|---:|---|---|---|---|"]
    for row in catalog:
        rows.append("| " + " | ".join(cell(value) for value in [f"`{row['question_type']}` ({row['scope']})", f"{row['questions']} / {row['buildings']}", f"{row['representative_cases']} / {row['labelled_available']}", row['implemented'], row['existing_tool'], row['missing_tool'], row['expected_result']]) + " |")
    rows += ["", "Evidence: [full question ledger](questions.csv), [selected runnable cases](tests.md), [tool contracts](tools_needed.md), and the three independent [family reviews](reviews/). `final_agent/tools.py` exposes seven tools; the implementation assessment is based on code and offline probes, not the older README baseline alone.", ""]
    (HERE / "question_types.md").write_text("\n".join(rows), encoding="utf-8")
    tests = ["# Representative runnable tests", "",
             f"{len(cases)} unique question IDs across {len({c['building_id'] for c in cases})} buildings and all 15 kinds. The original 45 cases remain; 26 additions bring every kind to five cases where labelled train/dev supply permits. Exact duplicate warm-up requests are not selected twice. Labels are development assertions, with train supplements explicitly identified. Difficulty follows the operation, not equal tier quotas: easy means one lookup/route/area operation; medium adds geometry or constraints; hard adds state, compound selection, ambiguity or large-map cross-floor effects.", "",
             "Offline execution uses resolved fixture inputs to probe real tools; unsupported analyses are GAP. Agent execution sends only the original question text and building directory and runs the unmodified official scorer afterward; it selects the scored cases only. See [commands and limits](README.md).",
             "", "The hard `osm-way27917482-Q09` offline probe tests safe ambiguity rejection, not the labelled route: the text cannot uniquely identify its start even with the floor. A clarification turn is required."]
    tests += ["", "## Selection balance", "",
              "Availability counts every supplied labelled train/dev question of that kind. No held-out test questions, invented labels or repeated IDs are added. Three train questions supplement kinds whose dev supply was already exhausted. The original 20-building dev ledger remains complete; the full ledger is not a balanced evaluation set.", "",
              "| Kind | Selected | Target | Labelled train/dev available | Remaining shortage |",
              "|---|---:|---:|---:|---:|"]
    tests += [f"| `{kind}` | {case_counts[kind]} | {CASES_PER_KIND} | {available[kind]} | {max(0, CASES_PER_KIND - case_counts[kind])} |"
              for kind in sorted(case_counts)]
    for tier in ("easy", "medium", "hard"):
        tests += ["", f"## {tier.title()} ({sum(c['tier'] == tier for c in cases)} cases)", "", "| Question ID / kind / split | Actual request | Expected result | Selection reason |", "|---|---|---|---|"]
        for case in cases:
            if case["tier"] != tier:
                continue
            question = originals[case["question_id"]]
            tests.append("| " + " | ".join(cell(value) for value in [f"`{case['question_id']}` / `{case['kind']}` / {Path(case['source_file']).parts[1]}", question['question'], expected_result(question), case['reason']]) + " |")
    tests += ["", "## Additional regressions once the corresponding tools exist", "",
              "These are proposed tests, not observations or passing checks: width exactly at threshold; blocked/narrow entrance versus already-inside start; equality at 1 m shared wall and >1 m exit improvement; corner contact; no overlap/ties on a missing adjacent floor; unreachable-before/reachable-after what-if distances; failed-save rollback; stale-route clearing; repeated stops; Synera forklift-only openings and destination-only bays. Keep physical routing separate from the local anchor fixtures.", ""]
    (HERE / "tests.md").write_text("\n".join(tests), encoding="utf-8")
    building_families = {q["building_id"]: q["family"] for q in questions}
    summary = {"buildings": len(building_families), "base_dev_buildings": len(buildings),
               "families": dict(Counter(building_families.values())),
               "questions": len(questions), "scored": sum(q["scope"] == "scored" for q in questions),
               "questions_by_split": dict(Counter(q["split"] for q in questions)),
               "warmup": sum(q["scope"] == "warm-up" for q in questions), "by_kind": dict(sorted(counts.items())),
               "representative_cases": len(cases), "cases_by_tier": dict(Counter(c["tier"] for c in cases)),
               "cases_by_kind": dict(sorted(case_counts.items())), "target_cases_per_kind": CASES_PER_KIND,
               "cases_by_split": dict(Counter(Path(c["source_file"]).parts[1] for c in cases)),
               "labelled_available_by_kind": dict(sorted(available.items())),
               "shortfalls": {kind: CASES_PER_KIND - count for kind, count in sorted(case_counts.items())
                              if count < CASES_PER_KIND},
               "agent_mode_scored_cases": sum(Path(c["source_file"]).name == "questions.jsonl" for c in cases),
               "unknown_kinds": []}
    (HERE / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
