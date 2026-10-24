"""Erzeugt API-v1-Beispiele aus dem Datensatz.

    uv run python scripts/generate_api_fixtures.py
"""

from __future__ import annotations

import base64
import csv
import itertools
import json
import sys
from pathlib import Path

import networkx as nx

from starter_agent.building_map import OUTSIDE, MapError, BuildingMap
from starter_agent.viewer import route_points_on_floor

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "docs" / "api" / "examples"
BUILDING_ID = "proc-factory-dev-003"
CREATED_AT = "2026-10-24T12:00:00Z"
CONFIRMED_AT = "2026-10-24T12:01:00Z"
EXPIRES_AT = "2026-10-24T12:15:00Z"

SESSION_ID = "11111111-1111-4111-8111-111111111111"
USER_MESSAGE_ID = "22222222-2222-4222-8222-222222222222"
GUIDE_MESSAGE_ID = "33333333-3333-4333-8333-333333333333"
ROUTE_ID = "44444444-4444-4444-8444-444444444444"
ACTION_ID = "55555555-5555-4555-8555-555555555555"
CLARIFY_USER_ID = "66666666-6666-4666-8666-666666666666"
CLARIFY_GUIDE_ID = "77777777-7777-4777-8777-777777777777"
UNREACHABLE_ROUTE_ID = "88888888-8888-4888-8888-888888888888"
PENDING_USER_ID = "99999999-9999-4999-8999-999999999999"
PENDING_GUIDE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRACE_ID = "11111111-1111-4111-8111-1111111111a1"

ROUTE_TEXT = "I am at the main entrance. How do I reach the CNC mill without stairs?"
CLARIFY_TEXT = "Where is the desk?"
PAGE_LIMIT = 20
PLACE_LIMIT = 15
ERROR_CODES = {
    "00001_internal",
    "00002_rate_limited",
    "10001_unauthenticated",
    "10002_forbidden",
    "20001_validation_failed",
    "20010_idempotency_key_required",
    "20011_idempotency_key_mismatch",
    "20012_payload_too_large",
    "30001_building_not_found",
    "30002_session_not_found",
    "30003_floor_not_found",
    "30004_place_not_found",
    "30005_place_ambiguous",
    "30007_not_adjacent",
    "30008_action_not_found",
    "30009_action_expired",
    "30010_action_conflict",
    "30012_revision_conflict",
    "30013_element_not_found",
    "40001_model_unavailable",
    "40002_model_rate_limited",
    "40003_model_timeout",
}


def write_json(name: str, payload: object) -> None:
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def opaque_cursor(last_id: str) -> str:
    token = base64.urlsafe_b64encode(last_id.encode("utf-8")).decode("ascii").rstrip("=")
    return f"v1.{token}"


def parse_bool(value: str) -> bool:
    return value == "True"


def load_manifest() -> list[dict[str, str]]:
    with (DATA / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def building_summary(row: dict[str, str]) -> dict:
    levels = [int(level) for level in row["levels"].split(";") if level]
    return {
        "id": row["building_id"],
        "name": row["name"],
        "source": row["source"],
        "split": row["split"],
        "license": row["license"],
        "level_count": int(row["floors"]),
        "levels": levels,
        "space_count": int(row["spaces"]),
        "asset_count": int(row["assets"]),
        "has_stairs": parse_bool(row["has_stairs"]),
        "has_lift": parse_bool(row["has_lift"]),
        "has_step_free_entrance": parse_bool(row["has_step_free_entrance"]),
    }


def floor_item(building_map: BuildingMap, floor: dict) -> dict:
    space_count = sum(1 for space in building_map.spaces.values() if space["floor_id"] == floor["id"])
    return {
        "id": floor["id"],
        "level": floor["level"],
        "name": floor["name"],
        "elevation_m": floor["elevation_m"],
        "height_m": floor["height_m"],
        "space_count": space_count,
    }


def copy_space(space: dict) -> dict:
    return {
        "id": space["id"],
        "floor_id": space["floor_id"],
        "type": space["type"],
        "room_type": space["room_type"],
        "name": space["name"],
        "ref": space.get("ref"),
        "polygon": space["polygon"],
        "synthetic": bool(space.get("synthetic", False)),
    }


def copy_opening(opening: dict) -> dict:
    return {
        "id": opening["id"],
        "floor_id": opening["floor_id"],
        "space_ids": list(opening["space_ids"]),
        "kind": opening["kind"],
        "position": list(opening["position"]),
        "width_m": opening["width_m"],
        "step_free": opening["step_free"],
        "synthetic": bool(opening.get("synthetic", False)),
    }


def copy_asset(asset: dict) -> dict:
    footprint = asset["footprint"]
    return {
        "id": asset["id"],
        "name": asset["name"],
        "category": asset["category"],
        "type": asset["type"],
        "space_id": asset["space_id"],
        "floor_id": asset["floor_id"],
        "position": list(asset["position"]),
        "footprint": {
            "width_m": footprint["width_m"],
            "depth_m": footprint["depth_m"],
            "rotation_deg": footprint["rotation_deg"],
        },
        "source": asset["source"],
    }


def copy_connector(connector: dict) -> dict:
    return {
        "id": connector["id"],
        "kind": connector["kind"],
        "name": connector["name"],
        "floor_ids": list(connector["floor_ids"]),
        "space_ids": list(connector["space_ids"]),
        "step_free": connector["step_free"],
        "synthetic": bool(connector.get("synthetic", False)),
    }


def build_floor_plan(
    building_map: BuildingMap,
    floor: dict,
    *,
    revision: int = 1,
    closed_ids: list[str] | None = None,
) -> dict:
    floor_id = floor["id"]
    spaces = [copy_space(space) for space in building_map.spaces.values() if space["floor_id"] == floor_id]
    openings = [copy_opening(opening) for opening in building_map.openings.values() if opening["floor_id"] == floor_id]
    assets = [copy_asset(asset) for asset in building_map.assets.values() if asset["floor_id"] == floor_id]
    connectors = [
        copy_connector(connector)
        for connector in building_map.connectors.values()
        if floor_id in connector["floor_ids"]
    ]
    return {
        "schema_version": 1,
        "session_id": SESSION_ID,
        "revision": revision,
        "floor": floor_item(building_map, floor),
        "included": ["spaces", "openings", "assets", "connectors"],
        "spaces": spaces,
        "openings": openings,
        "assets": assets,
        "connectors": connectors,
        "closed_ids": list(closed_ids or []),
        "bounds": bounds_for(spaces, openings, assets),
    }


def bounds_for(spaces: list[dict], openings: list[dict], assets: list[dict]) -> dict:
    points: list[list[float]] = []
    for space in spaces:
        points.extend(space["polygon"])
    points.extend(opening["position"] for opening in openings)
    points.extend(asset["position"] for asset in assets)
    if not points:
        raise SystemExit("floor plan has no coordinates")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return {"min": [min(xs), min(ys)], "max": [max(xs), max(ys)]}


def entrance_space_id(building_map: BuildingMap) -> str:
    for opening in building_map.openings.values():
        if opening["kind"] == "entrance" and OUTSIDE in opening["space_ids"]:
            return building_map.other_side(opening, OUTSIDE)
    raise SystemExit("building has no entrance")


def round_point(point: tuple[float, float] | list[float]) -> list[float]:
    return [round(float(point[0]), 3), round(float(point[1]), 3)]


def structured_directions(building_map: BuildingMap, graph, nodes: list[str]) -> list[dict]:
    directions = [
        {
            "text": f"Start in {building_map.describe_space(nodes[0])}.",
            "floor_id": building_map.spaces[nodes[0]]["floor_id"],
            "at": round_point(building_map.anchor(nodes[0])),
        }
    ]
    walked = 0.0
    for previous, current in itertools.pairwise(nodes):
        edge = min(graph[previous][current].values(), key=lambda candidate: candidate["weight"])
        walked += edge["weight"]
        element = edge["via"]
        if element in building_map.connectors:
            connector = building_map.connectors[element]
            verb = "Take" if connector["kind"] == "lift" else "Use"
            floor_id = building_map.spaces[current]["floor_id"]
            directions.append(
                {
                    "text": (
                        f"{verb} {connector['name']} ({connector['kind']}) to "
                        f"{building_map.floor_name(floor_id)}."
                    ),
                    "floor_id": floor_id,
                    "at": round_point(building_map.anchor(current)),
                }
            )
            walked = 0.0
        elif current == OUTSIDE:
            opening = building_map.openings[element]
            directions.append(
                {
                    "text": f"Walk about {walked:.0f} m and leave the building through the entrance.",
                    "floor_id": building_map.spaces[previous]["floor_id"],
                    "at": round_point(opening["position"]),
                }
            )
            walked = 0.0
        elif not current.startswith("door:"):
            opening = building_map.openings[element]
            passage = {"door": "through the door", "entrance": "outside to the entrance and in"}.get(
                opening["kind"], "through the opening"
            )
            directions.append(
                {
                    "text": f"Walk about {walked:.0f} m {passage} into {building_map.spaces[current]['name']}.",
                    "floor_id": building_map.spaces[current]["floor_id"],
                    "at": round_point(opening["position"]),
                }
            )
            walked = 0.0
    directions.append(
        {
            "text": f"You have arrived at {building_map.describe_space(nodes[-1])}.",
            "floor_id": building_map.spaces[nodes[-1]]["floor_id"],
            "at": round_point(building_map.anchor(nodes[-1])),
        }
    )
    return directions


def build_route(building_map: BuildingMap, start: str, destination: str, step_free: bool) -> dict:
    result = building_map.route(start, destination, step_free)
    graph = building_map.graph(step_free)
    nodes: list[str] = []
    stops = [building_map.resolve_space(start), building_map.resolve_space(destination)]
    for leg_start, leg_end in itertools.pairwise(stops):
        _length, leg_nodes = nx.single_source_dijkstra(graph, leg_start, leg_end, weight="weight")
        nodes += leg_nodes if not nodes else leg_nodes[1:]
    floor_ids = list(
        dict.fromkeys(
            building_map.spaces[space_id]["floor_id"]
            for space_id in result.space_path
            if space_id in building_map.spaces
        )
    )
    legs = []
    for floor_id in floor_ids:
        points = [round_point(point) for point in route_points_on_floor(building_map, floor_id)]
        if len(points) < 2:
            raise SystemExit(f"route on {floor_id} has fewer than 2 points")
        legs.append(
            {
                "floor_id": floor_id,
                "floor_level": building_map.floors[floor_id]["level"],
                "points": points,
            }
        )
    return route_document(
        ROUTE_ID,
        reachable=True,
        length_m=result.length_m,
        step_free=step_free,
        closed_ids=sorted(building_map.closed),
        start_space_id=result.start_space_id,
        destination_space_id=result.destination_space_id,
        space_path=result.space_path,
        directions=structured_directions(building_map, graph, nodes),
        legs=legs,
    )


def route_document(
    route_id: str,
    *,
    reachable: bool,
    length_m: float | None,
    step_free: bool,
    closed_ids: list[str],
    start_space_id: str,
    destination_space_id: str,
    space_path: list[str],
    directions: list[dict],
    legs: list[dict],
) -> dict:
    return {
        "schema_version": 1,
        "id": route_id,
        "session_id": SESSION_ID,
        "reachable": reachable,
        "length_m": length_m,
        "step_free": step_free,
        "via": [],
        "closed_ids": closed_ids,
        "start_space_id": start_space_id,
        "destination_space_id": destination_space_id,
        "space_path": space_path,
        "directions": directions,
        "legs": legs,
        "created_at": CREATED_AT,
    }


def empty_resolved() -> dict:
    return {
        "start_space_id": None,
        "destination_space_id": None,
        "space_ids": [],
        "asset_ids": [],
        "count": None,
    }


def session_payload(building_name: str, *, revision: int, closed_ids: list[str], last_route_id: str | None, pending_action_id: str | None, updated_at: str) -> dict:
    return {
        "schema_version": 1,
        "id": SESSION_ID,
        "building_id": BUILDING_ID,
        "building_name": building_name,
        "revision": revision,
        "preferences": {"step_free": True},
        "closed_ids": closed_ids,
        "last_route_id": last_route_id,
        "pending_action_id": pending_action_id,
        "created_at": CREATED_AT,
        "updated_at": updated_at,
    }


def place_from_hit(building_map: BuildingMap, hit: dict) -> dict:
    if hit["kind"] == "space":
        space = building_map.spaces[hit["id"]]
        floor = building_map.floors[space["floor_id"]]
        return {
            "kind": "space",
            "id": space["id"],
            "name": space["name"],
            "floor_id": space["floor_id"],
            "floor_level": floor["level"],
            "floor_name": floor["name"],
            "space_id": space["id"],
            "room_type": space["room_type"],
            "asset_type": None,
            "position": round_point(building_map.anchor(space["id"])),
        }
    asset = building_map.assets[hit["id"]]
    floor = building_map.floors[asset["floor_id"]]
    return {
        "kind": "asset",
        "id": asset["id"],
        "name": asset["name"],
        "floor_id": asset["floor_id"],
        "floor_level": floor["level"],
        "floor_name": floor["name"],
        "space_id": asset["space_id"],
        "room_type": building_map.spaces[asset["space_id"]]["room_type"],
        "asset_type": asset["type"],
        "position": list(asset["position"]),
    }


def require(payload: dict, *keys: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise SystemExit(f"fixture missing {missing}")


def check_page(payload: dict) -> None:
    require(payload, "schema_version", "items", "next_cursor", "has_more")
    if payload["schema_version"] != 1:
        raise SystemExit("schema_version must stay 1")
    if payload["has_more"] and not payload["next_cursor"]:
        raise SystemExit("has_more requires next_cursor")
    if not payload["has_more"] and payload["next_cursor"] is not None:
        raise SystemExit("terminal page must set next_cursor to null")


def check_floor_plan(payload: dict) -> None:
    require(payload, "schema_version", "spaces", "openings", "bounds", "closed_ids", "included")
    if not payload["spaces"]:
        raise SystemExit("floor plan has no spaces")
    for space in payload["spaces"]:
        if len(space["polygon"]) < 3:
            raise SystemExit(f"polygon too short: {space['id']}")
    if payload["included"] != ["spaces", "openings", "assets", "connectors"]:
        raise SystemExit("default include list drifted")


def check_route(payload: dict) -> None:
    require(payload, "reachable", "legs", "directions", "length_m")
    if not payload["reachable"] or not payload["legs"]:
        raise SystemExit("fixture route must be drawable")
    for leg in payload["legs"]:
        if len(leg["points"]) < 2:
            raise SystemExit("route leg needs two points")
    for direction in payload["directions"]:
        require(direction, "text", "floor_id", "at")


def check_unreachable(payload: dict) -> None:
    require(payload, "reachable", "length_m", "legs", "directions", "space_path", "start_space_id")
    if payload["reachable"] or payload["length_m"] is not None or payload["legs"] or payload["directions"]:
        raise SystemExit("unreachable fixture must carry an empty route")


def check_error(payload: dict) -> None:
    require(payload, "code", "message", "trace_id", "details")
    if payload["code"] not in ERROR_CODES:
        raise SystemExit(f"unknown error code {payload['code']}")
    if "schema_version" in payload:
        raise SystemExit("error envelope must not carry schema_version")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [row for row in load_manifest() if row["split"] == "dev"]
    rows.sort(key=lambda row: row["building_id"])
    first, second = rows[:PAGE_LIMIT], rows[PAGE_LIMIT:]
    page = {
        "schema_version": 1,
        "items": [building_summary(row) for row in first],
        "next_cursor": opaque_cursor(first[-1]["building_id"]) if second else None,
        "has_more": bool(second),
    }
    check_page(page)
    write_json("buildings-page.json", page)
    if second:
        page_two = {
            "schema_version": 1,
            "items": [building_summary(row) for row in second],
            "next_cursor": None,
            "has_more": False,
        }
        check_page(page_two)
        write_json("buildings-page-2.json", page_two)

    building_map = BuildingMap.load(DATA / "dev" / BUILDING_ID)
    info = building_map.data["building"]
    floors = [floor_item(building_map, floor) for floor in sorted(building_map.floors.values(), key=lambda item: item["level"])]
    detail = {
        "schema_version": 1,
        **building_summary(next(row for row in rows if row["building_id"] == BUILDING_ID)),
        "units": info["units"],
        "attribution": info["attribution"],
        "floors": floors,
    }
    require(detail, "schema_version", "id", "floors", "attribution", "units")
    write_json("building-detail.json", detail)

    idle_session = session_payload(info["name"], revision=1, closed_ids=[], last_route_id=None, pending_action_id=None, updated_at=CREATED_AT)
    write_json("session.json", idle_session)

    floor_index = {
        "schema_version": 1,
        "session_id": SESSION_ID,
        "revision": 1,
        "floors": floors,
    }
    write_json("floor-index.json", floor_index)

    ground = next(floor for floor in building_map.floors.values() if floor["level"] == 0)
    plan = build_floor_plan(building_map, ground)
    check_floor_plan(plan)
    write_json("floor-plan.json", plan)
    for floor in sorted(building_map.floors.values(), key=lambda item: item["level"]):
        if floor["id"] == ground["id"]:
            continue
        extra = build_floor_plan(building_map, floor)
        check_floor_plan(extra)
        write_json(f"floor-plan-f{floor['level']}.json", extra)

    hits = building_map.search("cnc", 0)[:PLACE_LIMIT]
    places = {
        "schema_version": 1,
        "items": [place_from_hit(building_map, hit) for hit in hits],
        "next_cursor": None,
        "has_more": False,
    }
    check_page(places)
    if not any(item["kind"] == "asset" and item["id"].endswith("A00001") for item in places["items"]):
        raise SystemExit("expected the CNC mill in the cnc search fixture")
    write_json("places-page.json", places)

    start = entrance_space_id(building_map)
    destination = "proc-factory-dev-003-A00001"
    route = build_route(building_map, start, destination, step_free=True)
    check_route(route)
    write_json("route.json", route)

    upper = next(space["id"] for space in building_map.spaces.values() if space["floor_id"].endswith("-F1") and space["type"] == "room")
    lift_id = "proc-factory-dev-003-V02"
    building_map.closed.add(lift_id)
    try:
        building_map.route(start, upper, step_free=True)
        raise SystemExit("expected the step-free route to fail while the lift is closed")
    except MapError:
        unreachable = route_document(
            UNREACHABLE_ROUTE_ID,
            reachable=False,
            length_m=None,
            step_free=True,
            closed_ids=[lift_id],
            start_space_id=building_map.resolve_space(start),
            destination_space_id=building_map.resolve_space(upper),
            space_path=[],
            directions=[],
            legs=[],
        )
    finally:
        building_map.closed.discard(lift_id)
    check_unreachable(unreachable)
    write_json("route-unreachable.json", unreachable)

    closed_plan = {**plan, "revision": 3, "closed_ids": [lift_id]}
    write_json("floor-plan-closed.json", closed_plan)
    write_json(
        "health.json",
        {"schema_version": 1, "status": "ok", "api_version": "1"},
    )

    asset = building_map.assets[destination]
    understood = {
        "intent": "route",
        "summary": "Main entrance to CNC mill, no stairs",
        "constraints": {"step_free": True, "via": [], "closed_ids": []},
        "resolved": {
            "start_space_id": route["start_space_id"],
            "destination_space_id": route["destination_space_id"],
            "space_ids": [route["start_space_id"], route["destination_space_id"]],
            "asset_ids": [destination],
            "count": None,
        },
        "missing": [],
    }
    effects = [
        {
            "type": "focus",
            "floor_id": asset["floor_id"],
            "floor_level": building_map.floors[asset["floor_id"]]["level"],
            "point": list(asset["position"]),
        },
        {"type": "highlight_assets", "asset_ids": [destination]},
        {"type": "draw_route", "route_id": ROUTE_ID},
    ]
    routed_session = session_payload(
        info["name"],
        revision=2,
        closed_ids=[],
        last_route_id=ROUTE_ID,
        pending_action_id=None,
        updated_at=CREATED_AT,
    )
    user_message = {
        "id": USER_MESSAGE_ID,
        "session_id": SESSION_ID,
        "role": "user",
        "text": ROUTE_TEXT,
        "created_at": CREATED_AT,
        "understood": None,
        "effects": [],
        "pending_action_id": None,
    }
    guide_message = {
        "id": GUIDE_MESSAGE_ID,
        "session_id": SESSION_ID,
        "role": "guide",
        "text": f"Step-free route is {route['length_m']} m. Follow the tape on the plan.",
        "created_at": CREATED_AT,
        "understood": understood,
        "effects": effects,
        "pending_action_id": None,
    }
    accepted = {
        "schema_version": 1,
        "session": routed_session,
        "user_message": user_message,
        "guide_message": guide_message,
        "routes": [route],
        "pending_action": None,
        "usage": {"input_tokens": None, "output_tokens": None},
    }
    write_json("message-accepted.json", accepted)
    write_json(
        "message-page.json",
        {
            "schema_version": 1,
            "items": [user_message, guide_message],
            "next_cursor": None,
            "has_more": False,
        },
    )

    desk_hits = [hit for hit in building_map.search("desk") if hit["kind"] == "asset"][:3]
    if len(desk_hits) < 2:
        raise SystemExit("need at least two desks for the clarify fixture")
    options = []
    for hit in desk_hits:
        item = place_from_hit(building_map, hit)
        options.append({"id": item["id"], "label": f"{item['name']}, {item['floor_name']}", "place_id": item["id"]})
    clarify_understood = {
        "intent": "clarify",
        "summary": "Which desk?",
        "constraints": {"step_free": True, "via": [], "closed_ids": []},
        "resolved": empty_resolved(),
        "missing": ["asset"],
    }
    ask = {"type": "ask", "question": "Which desk?", "options": options}
    clarify = {
        "schema_version": 1,
        "session": idle_session,
        "user_message": {
            "id": CLARIFY_USER_ID,
            "session_id": SESSION_ID,
            "role": "user",
            "text": CLARIFY_TEXT,
            "created_at": CREATED_AT,
            "understood": None,
            "effects": [],
            "pending_action_id": None,
        },
        "guide_message": {
            "id": CLARIFY_GUIDE_ID,
            "session_id": SESSION_ID,
            "role": "guide",
            "text": "Which desk?",
            "created_at": CREATED_AT,
            "understood": clarify_understood,
            "effects": [ask],
            "pending_action_id": None,
        },
        "routes": [],
        "pending_action": None,
        "usage": None,
    }
    write_json("message-clarify.json", clarify)

    lift = building_map.connectors["proc-factory-dev-003-V02"]
    preview = {"type": "highlight_spaces", "space_ids": list(lift["space_ids"]), "reason": "preview"}
    pending = {
        "schema_version": 1,
        "id": ACTION_ID,
        "session_id": SESSION_ID,
        "status": "pending",
        "summary": "Close Office lift",
        "proposal": {"kind": "set_closed", "element_ref": lift["id"], "closed": True},
        "preview_effects": [preview],
        "result": None,
        "created_at": CREATED_AT,
        "expires_at": EXPIRES_AT,
        "resolved_at": None,
    }
    write_json("action-pending.json", pending)
    pending_session = session_payload(
        info["name"],
        revision=2,
        closed_ids=[],
        last_route_id=None,
        pending_action_id=ACTION_ID,
        updated_at=CREATED_AT,
    )
    write_json(
        "message-pending-action.json",
        {
            "schema_version": 1,
            "session": pending_session,
            "user_message": {
                "id": PENDING_USER_ID,
                "session_id": SESSION_ID,
                "role": "user",
                "text": "The office lift is closed for maintenance.",
                "created_at": CREATED_AT,
                "understood": None,
                "effects": [],
                "pending_action_id": None,
            },
            "guide_message": {
                "id": PENDING_GUIDE_ID,
                "session_id": SESSION_ID,
                "role": "guide",
                "text": "I can close Office lift. Confirm before I change the map.",
                "created_at": CREATED_AT,
                "understood": {
                    "intent": "close",
                    "summary": "Close Office lift",
                    "constraints": {"step_free": True, "via": [], "closed_ids": []},
                    "resolved": empty_resolved(),
                    "missing": [],
                },
                "effects": [preview],
                "pending_action_id": ACTION_ID,
            },
            "routes": [],
            "pending_action": pending,
            "usage": None,
        },
    )
    confirmed = {
        **pending,
        "status": "confirmed",
        "preview_effects": [{"type": "highlight_spaces", "space_ids": list(lift["space_ids"]), "reason": "closed"}],
        "result": {
            "kind": "set_closed",
            "element_id": lift["id"],
            "closed": True,
            "closed_ids": [lift["id"]],
        },
        "resolved_at": CONFIRMED_AT,
    }
    write_json("action-confirmed.json", confirmed)

    validation = {
        "code": "20001_validation_failed",
        "message": "Request validation failed.",
        "trace_id": TRACE_ID,
        "details": [{"field": "text", "code": "too_long"}],
    }
    ambiguous = {
        "code": "30005_place_ambiguous",
        "message": "Place reference is ambiguous.",
        "trace_id": TRACE_ID,
        "details": [
            {"field": "destination", "code": "ambiguous", "message": options[0]["label"]},
            {"field": "destination", "code": "ambiguous", "message": options[1]["label"]},
        ],
    }
    check_error(validation)
    check_error(ambiguous)
    write_json("error-validation.json", validation)
    write_json("error-ambiguous.json", ambiguous)

    print(f"Wrote fixtures to {OUT.relative_to(ROOT)}")
    print(f"Route {route['length_m']} m, {len(route['legs'])} floor leg(s), {len(route['directions'])} directions")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
