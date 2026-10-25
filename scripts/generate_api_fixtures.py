"""Generate deterministic frontend examples from the dev building; never call a model."""

import argparse
import json
import sys
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from final_agent.api import error_response
from final_agent.api_session import ApiError, SessionService, timestamp
from scripts.generate_frontend_fixtures import generate_frontend


def unavailable_model():
    raise RuntimeError("Fixtures never call a model.")


def generate(data: Path, output: Path) -> list[dict]:
    sequence = count(1)
    now = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
    with TemporaryDirectory(prefix="api-fixtures-") as temporary:
        service = SessionService(data, Path(temporary), notes_database=Path(temporary) / "notes.sqlite3",
                                 clock=lambda: now, client_factory=unavailable_model, new_id=lambda: str(UUID(int=next(sequence))),
                                 cursor_secret=b"deterministic-frontend-fixtures-only")
        session = service.create("proc-factory-dev-003", {"step_free": False})
        state = service.get(session["id"])
        route = service.create_route(state, {"start": "H-A2", "destination": "H-A1"}, None)
        floor_id = state.map.spaces[route["destination_space_id"]]["floor_id"]
        user = {"id": service.new_id(), "session_id": state.id, "role": "user", "text": "How do I get from H-A2 to H-A1?",
                "created_at": timestamp(now), "understood": None, "effects": [], "pending_action_id": None}
        guide = {"id": service.new_id(), "session_id": state.id, "role": "guide", "text": f"The route is {route['length_m']} m.",
                 "created_at": timestamp(now), "pending_action_id": None, "effects": [{"type": "draw_route", "route_id": route["id"]}],
                 "understood": {"intent": "route", "summary": "Walking route from H-A2 to H-A1.",
                                "constraints": {"step_free": False, "via": [], "closed_ids": []},
                                "resolved": {"start_space_id": route["start_space_id"], "destination_space_id": route["destination_space_id"],
                                             "space_ids": route["space_path"], "asset_ids": [], "count": None}, "missing": []}}
        accepted = {"schema_version": 1, "session": service.view(state), "user_message": user, "guide_message": guide,
                    "routes": [route], "pending_action": None, "usage": None, "speech_clip_id": None}
        examples = {
            "health": ("Health", {"schema_version": 1, "status": "ok", "api_version": "1"}),
            "buildings": ("BuildingPage", service.buildings("dev", None, 20)),
            "building": ("BuildingDetail", service.building("proc-factory-dev-003")),
            "session": ("Session", service.view(state)),
            "floors": ("FloorIndex", service.floor_index(state)),
            "plan": ("FloorPlan", service.floor_plan(state, floor_id, ["spaces", "openings", "assets", "connectors"])),
            "places": ("PlacePage", service.places(state, "CNC mill", None, "asset", None, 15)),
            "route": ("Route", route),
            "message": ("MessageAccepted", accepted),
            "messages": ("MessagePage", {"schema_version": 1, "items": [user, guide], "next_cursor": None, "has_more": False}),
        }
        element_id = next(iter(state.map.connectors))
        action = service.propose(state, {"kind": "set_closed", "element_ref": element_id, "closed": True}, None)
        examples["action_pending"] = ("Action", action)
        examples["session_pending"] = ("Session", service.view(state))
        examples["action_confirmed"] = ("Action", service.finish_action(state, action["id"], True, None))
        examples["session_confirmed"] = ("Session", service.view(state))
        examples["plan_confirmed"] = ("FloorPlan", service.floor_plan(state, floor_id, ["spaces", "openings", "assets", "connectors"]))
        start = route["start_space_id"]
        floor = state.map.spaces[start]["floor_id"]
        x_m, y_m = state.map.anchor(start)
        position = service.put_position(state.id, {"floor_id": floor, "x_m": x_m, "y_m": y_m, "measured_at": now,
                                                   "source": "simulated", "accuracy_m": 1.5})
        examples["position-accepted"] = ("PositionAccepted", position)
        examples["guidance-feed"] = ("GuidanceFeed", service.put_guidance(state.id, route["id"]))
        service.delete_guidance(state.id)
        examples["transcription"] = ("Transcription", {"schema_version": 1, "text": "How do I get from H-A2 to H-A1?", "language": "en"})
        # Object editor: catalog, one add_object proposal with its preview, its confirmation and a broken rule.
        examples["object_types"] = ("ObjectCatalog", service.object_types())
        edit = service.propose(state, {"kind": "add_object", "type": "desk", "space": "H-A1"}, None)
        examples["action_add_object_pending"] = ("Action", edit)
        examples["action_add_object_confirmed"] = ("Action", service.finish_action(state, edit["id"], True, None))
        try:
            service.propose(state, {"kind": "add_object", "type": "desk", "space": "H-A1", "position": [0, 0]}, None)
            raise RuntimeError("The invalid placement example was accepted.")
        except ApiError as error:
            examples["error_invalid_placement"] = ("Error", json.loads(error_response(error, str(UUID(int=999))).body))
        for code, name in (("20001_validation_failed", "error_validation"), ("30002_session_not_found", "error_not_found"), ("40001_model_unavailable", "error_model")):
            response = error_response(ApiError(code), str(UUID(int=999)))
            examples[name] = ("Error", json.loads(response.body))
        output.mkdir(parents=True, exist_ok=True)
        index = []
        for name, (schema, value) in examples.items():
            # The frontend imports these shared names using its fixed demo session.
            filename = ("backend-" if name in {"session", "route"} else "") + name + ".json"
            (output / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            index.append({"file": filename, "schema": schema})
        for filename, schema in generate_frontend(data, output).items():
            if (output / filename).is_file():
                index = [entry for entry in index if entry["file"] != filename]
                index.append({"file": filename, "schema": schema})
        (output / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
        return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("docs/api/examples"))
    args = parser.parse_args()
    print(f"Generated {len(generate(args.data, args.output))} examples in {args.output} (no API calls).")


if __name__ == "__main__":
    main()
