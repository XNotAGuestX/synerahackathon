"""Application state for the HTTP adapter. The building core stays independent of HTTP."""

import base64
import copy
import csv
import hashlib
import hmac
import json
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

import anthropic
from anthropic.lib.tools import BetaBuiltinFunctionTool, ToolError
from pydantic import BaseModel, ConfigDict

from .agent import EFFORT, VOICE_PROMPT, BuildingAgent, MissingCredentialsError
from .building_map import BuildingMap, MapError, RouteResult
from .live import LiveState
from .speech import ClipCache, SpeechError, SpeechProvider
from .storage import RoomNoteStore
from .tools import ArgumentCheckedTool, as_json, make_tools, route_json
from .viewer import landmark_targets, node_location, route_polylines


ERRORS = {
    "00001_internal": (500, "An internal error occurred."),
    "00002_rate_limited": (429, "Request rate limit exceeded."),
    "10001_unauthenticated": (401, "Authentication is required."),
    "20001_validation_failed": (400, "Request validation failed."),
    "20010_idempotency_key_required": (400, "Idempotency-Key is required."),
    "20011_idempotency_key_mismatch": (409, "Idempotency key does not match the request."),
    "20012_payload_too_large": (413, "Request body exceeds the size limit."),
    "30001_building_not_found": (404, "Building was not found."),
    "30002_session_not_found": (404, "Session was not found."),
    "30003_floor_not_found": (404, "Floor was not found."),
    "30004_place_not_found": (404, "Place was not found."),
    "30005_place_ambiguous": (409, "Place reference is ambiguous."),
    "30007_not_adjacent": (409, "Rooms do not share a suitable wall on the same floor."),
    "30008_action_not_found": (404, "Action was not found."),
    "30009_action_expired": (409, "Action has expired."),
    "30010_action_conflict": (409, "Action conflicts with the current state."),
    "30012_revision_conflict": (409, "Session revision has changed."),
    "30013_element_not_found": (404, "Element was not found."),
    "30014_speech_clip_not_found": (404, "Speech clip was not found."),
    "40001_model_unavailable": (503, "Model is unavailable."),
    "40002_model_rate_limited": (429, "Model rate limit exceeded."),
    "40003_model_timeout": (504, "Model timed out."),
    "40004_speech_unavailable": (503, "Speech service is unavailable."),
}


class ApiError(Exception):
    def __init__(self, code: str, details: list[dict] | None = None, retry_after: int | None = None) -> None:
        self.code = code
        self.status, self.message = ERRORS[code]
        self.details = details or []
        self.retry_after = retry_after
        super().__init__(self.message)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def identifier() -> str:
    return str(uuid4())


def project(record: dict, fields: str) -> dict:
    """Project source data onto the wire contract without leaking custom fields."""
    return {name: record[name] for name in fields.split()}


@dataclass
class SessionState:
    id: str
    map: BuildingMap
    created_at: str
    updated_at: str
    preferences: dict = field(default_factory=lambda: {"step_free": False})
    revision: int = 1
    last_route_id: str | None = None
    pending_action_id: str | None = None
    routes: dict[str, dict] = field(default_factory=dict)
    actions: dict[str, dict] = field(default_factory=dict)
    transcript: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    route_results: dict[str, Any] = field(default_factory=dict)  # route id -> RouteResult; never on the wire
    live: LiveState = field(default_factory=lambda: LiveState(utc_now, identifier), repr=False)


class AskChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    place_id: str | None


class ApiReply(BaseModel):
    """The model supplies wording and intent; the application supplies verified map facts/effects."""
    model_config = ConfigDict(extra="forbid")
    text: str
    intent: Literal["locate", "route", "count", "close", "add_door", "clarify", "unknown"]
    summary: str
    missing: list[Literal["start", "destination", "asset", "element"]]
    question: str | None
    options: list[AskChoice]


API_PROMPT = """

# HTTP session mode (overrides examples about immediate edits and PNG display)
Finish the turn with your normal reply; afterwards the application asks you to restate it in
its response schema. In that schema, text is the normal short user-facing reply, in their language. summary describes what you understood. The application
generates verified resolved ids, counts, map effects and route references from tool results.
Use intent clarify and missing slots when information is needed. question/options are only for
actual clarification; offer tool-backed place ids, never invented locations. Otherwise use
question=null, options=[] and missing=[]. Room-report tasks use intent unknown (the HTTP
contract has no separate report intent); still perform their tools and explain the result.

set_closed and add_door only PROPOSE an action in this mode. They do not apply or save a
building change. Say that confirmation is required; never say the lift is already closed or
the door was added. Confirmation/cancellation happens through the UI's action endpoints.
If an action is already pending, ask the user to confirm or cancel it before another proposal.
Do not silently replace it. Do not attempt to confirm an action by another tool.
show_location and show_route produce JSON map effects, not image files. A successful effect
can be described as sent to the map. Selected UI space is selection context, not proof of the
user's location. An explicit constraint in the user's sentence overrides turn/session defaults.
live_position with tracking=live comes from the building's positioning system and is the user's current
location; use its space_id as the route start. Selected UI space is still not proof of location.
start_guidance begins spoken step-by-step guidance for the route you just computed; stop_guidance ends it.
"""


class SessionService:
    def __init__(
        self, data_directory: Path, output_directory: Path, *, notes_database: Path | None = None,
        client_factory: Callable | None = None, clock: Callable = utc_now, new_id: Callable = identifier,
        model_timeout: float = 60, cursor_secret: bytes | None = None,
        speech: SpeechProvider | None = None,
    ) -> None:
        self.speech, self.clips = speech, ClipCache()
        self.data_directory = Path(data_directory).resolve()
        self.output_directory = Path(output_directory)
        self.notes_database = Path(notes_database) if notes_database is not None else Path("agent_output/room_notes.sqlite3")
        self.client_factory = client_factory or (lambda: anthropic.Anthropic(max_retries=0))
        self.clock, self.new_id = clock, new_id
        self.model_timeout = model_timeout
        self.sessions: dict[str, SessionState] = {}
        self._lock = threading.RLock()
        self._cursor_secret = cursor_secret if cursor_secret is not None else secrets.token_bytes(32)
        self._buildings: dict[str, dict] = {}
        with (self.data_directory / "manifest.csv").open(encoding="utf-8", newline="") as handle:
            self.manifest = {row["building_id"]: row for row in csv.DictReader(handle)}

    def building_data(self, building_id: str) -> dict:
        row = self.manifest.get(building_id)
        if row is None:
            raise ApiError("30001_building_not_found")
        with self._lock:
            if building_id not in self._buildings:
                path = (self.data_directory / row["path"]).resolve()
                if not path.is_relative_to(self.data_directory):
                    raise ValueError("Manifest path is outside the configured dataset directory.")
                self._buildings[building_id] = BuildingMap.load(path).data
            return self._buildings[building_id]

    def page(self, items: list, cursor: str | None, limit: int, scope: object) -> dict:
        scope_hash = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
        offset = 0
        if cursor is not None:
            try:
                decoded = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
                payload, signature = decoded[:-16], decoded[-16:]
                expected = hmac.digest(self._cursor_secret, payload, "sha256")[:16]
                if not hmac.compare_digest(signature, expected):
                    raise ValueError("Invalid cursor signature")
                cursor_scope, offset = json.loads(payload)
                if cursor_scope != scope_hash or type(offset) is not int or not 0 <= offset <= len(items):
                    raise ValueError("Invalid cursor scope or offset")
            except (ValueError, TypeError, UnicodeError):
                raise ApiError("20001_validation_failed", [{"field": "cursor", "code": "invalid"}]) from None
        end = min(offset + limit, len(items))
        next_cursor = None
        if end < len(items):
            payload = json.dumps([scope_hash, end], separators=(",", ":")).encode()
            next_cursor = base64.urlsafe_b64encode(payload + hmac.digest(self._cursor_secret, payload, "sha256")[:16]).decode().rstrip("=")
        return {"schema_version": 1, "items": items[offset:end], "next_cursor": next_cursor, "has_more": next_cursor is not None}

    def buildings(self, split: str | None, cursor: str | None, limit: int) -> dict:
        rows = []
        for key, row in sorted(self.manifest.items()):
            if split is not None and row["split"] != split:
                continue
            rows.append({
                "id": key, "name": row["name"], "source": row["source"], "split": row["split"],
                "license": row["license"], "level_count": int(row["floors"]),
                "levels": [int(level) for level in row["levels"].split(";")],
                "space_count": int(row["spaces"]), "asset_count": int(row["assets"]),
                **{name: row[name].lower() == "true" for name in ("has_stairs", "has_lift", "has_step_free_entrance")},
            })
        return self.page(rows, cursor, limit, ["buildings", split])

    @staticmethod
    def floors(building_map: BuildingMap) -> list[dict]:
        return [
            {**project(floor, "id level name elevation_m height_m"),
             "space_count": sum(space["floor_id"] == floor["id"] for space in building_map.spaces.values())}
            for floor in sorted(building_map.floors.values(), key=lambda item: (item["level"], item["id"]))
        ]

    def building(self, building_id: str) -> dict:
        data = self.building_data(building_id)
        summary = next(item for item in self.buildings(None, None, len(self.manifest))["items"] if item["id"] == building_id)
        return {"schema_version": 1, **summary, **project(data["building"], "units attribution"), "floors": self.floors(BuildingMap(data))}

    def create(self, building_id: str, preferences: dict) -> dict:
        now = timestamp(self.clock())
        session = SessionState(self.new_id(), BuildingMap(copy.deepcopy(self.building_data(building_id))), now, now, preferences,
                               live=LiveState(self.clock, self.new_id))
        with self._lock:
            self.sessions[session.id] = session
        return self.view(session)

    def get(self, session_id: str) -> SessionState:
        with self._lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise ApiError("30002_session_not_found")
        return session

    def delete(self, session_id: str) -> None:
        with self._lock:
            session = self.sessions.pop(session_id, None)
        if session is not None:
            session.live.close()

    def bump(self, session: SessionState) -> None:
        session.revision += 1
        session.updated_at = timestamp(self.clock())

    def expire(self, session: SessionState) -> None:
        if session.pending_action_id is None:
            return
        action = session.actions[session.pending_action_id]
        if self.clock() >= datetime.fromisoformat(action["expires_at"].replace("Z", "+00:00")):
            action.update(status="expired", resolved_at=action["expires_at"])
            session.pending_action_id = None
            self.bump(session)

    @staticmethod
    def match(session: SessionState, revision: int | None) -> None:
        if revision is not None and revision != session.revision:
            raise ApiError("30012_revision_conflict")

    def view(self, session: SessionState) -> dict:
        with session.lock:
            self.expire(session)
            return {
                "schema_version": 1, "id": session.id, "building_id": session.map.data["building"]["id"],
                "building_name": session.map.data["building"]["name"], "revision": session.revision,
                "preferences": dict(session.preferences), "closed_ids": sorted(session.map.closed),
                "last_route_id": session.last_route_id, "pending_action_id": session.pending_action_id,
                "created_at": session.created_at, "updated_at": session.updated_at,
            }

    def preferences(self, session: SessionState, preferences: dict, revision: int | None) -> dict:
        with session.lock:
            self.expire(session)
            self.match(session, revision)
            if session.preferences != preferences:
                session.preferences = dict(preferences)
                self.bump(session)
            return self.view(session)

    def floor_index(self, session: SessionState) -> dict:
        with session.lock:
            self.expire(session)
            return {"schema_version": 1, "session_id": session.id, "revision": session.revision, "floors": self.floors(session.map)}

    def floor_plan(self, session: SessionState, floor_id: str, included: list[str]) -> dict:
        with session.lock:
            self.expire(session)
            floor = next((floor for floor in self.floors(session.map) if floor["id"] == floor_id), None)
            if floor is None:
                raise ApiError("30003_floor_not_found")
            spaces = [space for space in session.map.spaces.values() if space["floor_id"] == floor_id]
            points = [point for space in spaces for point in space["polygon"]]
            bounds = {"min": [min((point[i] for point in points), default=0) for i in (0, 1)],
                      "max": [max((point[i] for point in points), default=0) for i in (0, 1)]}
            collections = {
                "spaces": [project(space, "id floor_id type room_type name ref polygon synthetic") for space in spaces],
                "openings": [self.opening(item) for item in session.map.openings.values() if item["floor_id"] == floor_id],
                "assets": [project(item, "id name category type space_id floor_id position footprint source")
                           for item in session.map.assets.values() if item["floor_id"] == floor_id],
                "connectors": [project(item, "id kind name floor_ids space_ids step_free synthetic")
                               for item in session.map.connectors.values() if floor_id in item["floor_ids"]],
            }
            return copy.deepcopy({
                "schema_version": 1, "session_id": session.id, "revision": session.revision,
                "floor": floor, "included": included, "closed_ids": sorted(session.map.closed), "bounds": bounds,
                **{name: items if name in included else [] for name, items in collections.items()},
            })

    @staticmethod
    def opening(record: dict) -> dict:
        return project(record, "id floor_id space_ids kind position width_m step_free synthetic")

    def places(self, session: SessionState, query: str, level: int | None, kind: str | None, cursor: str | None, limit: int) -> dict:
        with session.lock:
            self.expire(session)
            if level is not None and level not in {floor["level"] for floor in session.map.floors.values()}:
                raise ApiError("30003_floor_not_found")
            results = session.map.search(query, level, kind or "all")
            items = [self.place(session.map, item["id"], item["kind"]) for item in results]
            return self.page(items, cursor, limit, ["places", session.id, session.revision, query, level, kind])

    @staticmethod
    def place(building_map: BuildingMap, place_id: str, kind: str) -> dict:
        record = building_map.spaces[place_id] if kind == "space" else building_map.assets[place_id]
        floor = building_map.floors[record["floor_id"]]
        return {
            "kind": kind, "id": place_id, "name": record["name"], "floor_id": floor["id"],
            "floor_level": floor["level"], "floor_name": floor["name"],
            "space_id": place_id if kind == "space" else record["space_id"],
            "room_type": record["room_type"] if kind == "space" else None,
            "asset_type": record["type"] if kind == "asset" else None,
            "position": list(building_map.anchor(place_id)) if kind == "space" else list(record["position"]),
        }

    @staticmethod
    def resolve(building_map: BuildingMap, reference: str, field_name: str) -> str:
        try:
            return building_map.resolve_space(reference)
        except MapError as error:
            if error.reason == "ambiguous":
                raise ApiError("30005_place_ambiguous", [
                    {"field": field_name, "code": "ambiguous", "message": item["id"]} for item in error.candidates
                ]) from error
            raise ApiError("30004_place_not_found", [{"field": field_name, "code": "not_found"}]) from error

    def route_record(self, session: SessionState, route: RouteResult | None, stops: list[str], step_free: bool, reason: str = "") -> dict:
        directions = []
        legs = []
        if route is not None:
            # Associate each domain direction with its actual departure point, without parsing prose.
            locations = [node_location(session.map, route.node_path[0])]
            departure = route.node_path[0]
            for index, (current, element) in enumerate(zip(route.node_path[1:], route.edge_path), start=1):
                if element in session.map.connectors or (current.startswith("door:") and index < len(route.edge_path)):
                    locations.append(node_location(session.map, departure))
                    departure = current
            locations.append(node_location(session.map, departure))
            for index, text in enumerate(route.steps):
                location = locations[index] if index < len(locations) else None
                directions.append({"text": text, "floor_id": location[0] if location else None,
                                   "at": list(location[1]) if location else None})
            for floor_id, points in route_polylines(session.map, route):
                if len(points) == 1:
                    points = points * 2
                if points:
                    legs.append({"floor_id": floor_id, "floor_level": session.map.floor_level(floor_id), "points": [list(point) for point in points]})
        else:
            directions = [{"text": reason, "floor_id": None, "at": None}]
        return {
            "schema_version": 1, "id": self.new_id(), "session_id": session.id,
            "reachable": route is not None, "length_m": round(route.length_m, 2) if route else None,
            "step_free": step_free, "via": stops[1:-1], "closed_ids": sorted(session.map.closed),
            "start_space_id": stops[0], "destination_space_id": stops[-1],
            "space_path": list(route.space_path) if route else [], "directions": directions,
            "legs": legs, "created_at": timestamp(self.clock()),
        }

    def create_route(self, session: SessionState, body: dict, revision: int | None) -> dict:
        with session.lock:
            self.expire(session)
            self.match(session, revision)
            references = [body["start"], *body.get("via", []), body["destination"]]
            stops = [self.resolve(session.map, ref, "start" if i == 0 else "destination" if i == len(references) - 1 else "via")
                     for i, ref in enumerate(references)]
            step_free = body.get("step_free", session.preferences["step_free"])
            try:
                route = session.map.route(stops[0], stops[-1], step_free, stops[1:-1])
                result = self.route_record(session, route, stops, step_free)
            except MapError as error:
                if error.reason != "unreachable":
                    raise
                result = self.route_record(session, None, stops, step_free, str(error))
            session.routes[result["id"]] = result
            if result["reachable"]:
                session.route_results[result["id"]] = route
            session.last_route_id = result["id"]
            self.bump(session)
            return copy.deepcopy(result)

    @staticmethod
    def route(session: SessionState, route_id: str) -> dict:
        with session.lock:
            if route_id not in session.routes:
                # The contract has no dedicated route-not-found code.
                raise ApiError("30004_place_not_found", [{"field": "route_id", "code": "not_found"}])
            return copy.deepcopy(session.routes[route_id])

    def validate_proposal(self, session: SessionState, proposal: dict) -> dict:
        proposal = dict(proposal)
        if proposal["kind"] == "set_closed":
            try:
                proposal["element_ref"] = session.map.find_element(proposal["element_ref"])
            except MapError as error:
                if error.reason == "ambiguous":
                    raise ApiError("30005_place_ambiguous", [{"field": "element_ref", "code": "ambiguous", "message": item["id"]} for item in error.candidates]) from error
                raise ApiError("30013_element_not_found") from error
        else:
            for key in ("first_space", "second_space"):
                proposal[key] = self.resolve(session.map, proposal[key], key)
            proposal.setdefault("step_free", True)
            try:
                session.map.shared_wall(proposal["first_space"], proposal["second_space"])
                if not self.existing_door(session.map, proposal):
                    trial = copy.deepcopy(session.map)
                    trial.add_door(proposal["first_space"], proposal["second_space"], proposal["step_free"])
            except MapError as error:
                raise ApiError("30007_not_adjacent") from error
        return proposal

    @staticmethod
    def existing_door(building_map: BuildingMap, proposal: dict) -> dict | None:
        pair = {proposal["first_space"], proposal["second_space"]}
        return next((door for _, door in sorted(building_map.openings.items()) if door["kind"] == "door" and set(door["space_ids"]) == pair), None)

    def propose(self, session: SessionState, proposal: dict, revision: int | None) -> dict:
        with session.lock:
            self.expire(session)
            self.match(session, revision)
            if session.pending_action_id is not None:
                raise ApiError("30010_action_conflict")
            proposal = self.validate_proposal(session, proposal)
            if proposal["kind"] == "set_closed":
                element = proposal["element_ref"]
                record = session.map.spaces.get(element, session.map.connectors.get(element, session.map.openings.get(element, {})))
                summary = f"{'Close' if proposal['closed'] else 'Reopen'} {record.get('name', element)}."
                ids = [element] if element in session.map.spaces else session.map.connectors.get(element, session.map.openings.get(element, {})).get("space_ids", [])
                ids = [item for item in ids if item in session.map.spaces]
            else:
                ids = [proposal["first_space"], proposal["second_space"]]
                summary = f"Add a door between {session.map.spaces[ids[0]]['name']} and {session.map.spaces[ids[1]]['name']}."
            now = self.clock()
            action = {
                "schema_version": 1, "id": self.new_id(), "session_id": session.id, "status": "pending",
                "summary": summary, "proposal": proposal,
                "preview_effects": [{"type": "highlight_spaces", "space_ids": ids, "reason": "preview"}],
                "result": None, "created_at": timestamp(now), "expires_at": timestamp(now + timedelta(minutes=15)), "resolved_at": None,
            }
            session.actions[action["id"]] = action
            session.pending_action_id = action["id"]
            self.bump(session)
            return copy.deepcopy(action)

    def action(self, session: SessionState, action_id: str) -> dict:
        with session.lock:
            self.expire(session)
            if action_id not in session.actions:
                raise ApiError("30008_action_not_found")
            return copy.deepcopy(session.actions[action_id])

    def finish_action(self, session: SessionState, action_id: str, confirm: bool, revision: int | None) -> dict:
        with session.lock:
            self.expire(session)
            action = session.actions.get(action_id)
            if action is None:
                raise ApiError("30008_action_not_found")
            target = "confirmed" if confirm else "cancelled"
            if action["status"] == target:
                return copy.deepcopy(action)
            if action["status"] == "expired":
                raise ApiError("30009_action_expired")
            if action["status"] != "pending":
                raise ApiError("30010_action_conflict")
            self.match(session, revision)
            if confirm:
                proposal = self.validate_proposal(session, action["proposal"])
                with session.map.transaction():
                    if proposal["kind"] == "set_closed":
                        element_id = session.map.set_closed(proposal["element_ref"], proposal["closed"])
                        result = {"kind": "set_closed", "element_id": element_id, "closed": proposal["closed"], "closed_ids": sorted(session.map.closed)}
                    else:
                        opening = self.existing_door(session.map, proposal)
                        if opening is None:
                            opening = session.map.add_door(proposal["first_space"], proposal["second_space"], proposal["step_free"])
                        result = {"kind": "add_door", "opening": self.opening(opening)}
                action["result"] = result
                session.map.last_route = None
                session.map.active_request = None
                session.last_route_id = None
                if proposal["kind"] == "set_closed" and proposal["closed"] and session.live.blocked_by(session.map.closed):
                    session.live.stop("blocked", "Your route is blocked. Ask me for a new one.")
            action.update(status=target, resolved_at=timestamp(self.clock()))
            session.pending_action_id = None
            self.bump(session)
            return copy.deepcopy(action)

    def put_position(self, session_id: str, body: dict) -> dict:
        session = self.get(session_id)  # no view()/expire(): a fix must never bump the revision
        return {"schema_version": 1, **session.live.apply_fix(session.map, body)}

    def get_guidance(self, session_id: str, after: int, wait_s: float) -> dict:
        live = self.get(session_id).live
        events, cursor = live.events_after(after, wait_s)
        return {"schema_version": 1, "guidance": live.guidance_view(), "events": events, "cursor": cursor}

    def put_guidance(self, session_id: str, route_id: str) -> dict:
        session = self.get(session_id)
        with session.lock:
            record = self.route(session, route_id)
            result = session.route_results.get(route_id)
            if not record["reachable"] or result is None:
                raise ApiError("20001_validation_failed", [{"field": "route_id", "code": "unreachable"}])
            session.live.start(session.map, route_id, record, result, spoken=False)
        return self.get_guidance(session_id, 0, 0)

    def delete_guidance(self, session_id: str) -> None:
        self.get(session_id).live.stop("cancelled")

    AUDIO_TYPES = {"audio/wav", "audio/x-wav", "audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg"}

    def unavailable(self, reason: str) -> ApiError:
        return ApiError("40004_speech_unavailable", [{"field": "speech", "code": reason}], retry_after=1 if reason == "rate_limited" else None)

    def transcribe(self, session_id: str, audio: bytes, content_type: str) -> dict:
        self.get(session_id)
        base = content_type.split(";")[0].strip().lower()
        if base not in self.AUDIO_TYPES or not audio:
            raise ApiError("20001_validation_failed", [{"field": "Content-Type" if base not in self.AUDIO_TYPES else "body", "code": "invalid"}])
        if self.speech is None:
            raise self.unavailable("not_configured")
        try:
            text = self.speech.transcribe(audio, base)
        except SpeechError as error:
            raise self.unavailable(error.reason) from error
        return {"schema_version": 1, "text": text, "language": "en"}

    def speech_clip(self, session_id: str, clip_id: str) -> bytes:
        text = self.get(session_id).live.clip_text(clip_id)
        if text is None:
            raise ApiError("30014_speech_clip_not_found")
        speech = self.speech
        if speech is None:
            raise self.unavailable("not_configured")
        key = (speech.voice_id, speech.tts_model, "mp3_44100_64", text)
        try:
            return self.clips.get_or_make(key, lambda: speech.synthesize(text))
        except SpeechError as error:
            raise self.unavailable(error.reason) from error

    def message_page(self, session: SessionState, cursor: str | None, limit: int) -> dict:
        with session.lock:
            return self.page(copy.deepcopy(session.transcript), cursor, limit, ["messages", session.id])

    def working_copy(self, session: SessionState) -> SessionState:
        building_map = BuildingMap(copy.deepcopy(session.map.data))
        building_map.closed = set(session.map.closed)
        building_map.last_route = copy.deepcopy(session.map.last_route)
        building_map.active_request = copy.deepcopy(session.map.active_request)
        building_map.selection = copy.deepcopy(session.map.selection)
        return SessionState(
            session.id, building_map, session.created_at, session.updated_at, dict(session.preferences),
            session.revision, session.last_route_id, session.pending_action_id,
            copy.deepcopy(session.routes), copy.deepcopy(session.actions),
            copy.deepcopy(session.transcript), copy.deepcopy(session.history),
            route_results=dict(session.route_results), live=session.live,  # live is shared, never copied
        )

    @staticmethod
    def live_context(work: SessionState, live: LiveState) -> dict | None:
        """Position facts for the model. No ages or timestamps, so the cached system prompt stays stable."""
        position = live.position_view()
        if position is None or position["space_id"] is None or position["space_id"] not in work.map.spaces:
            return None
        space = work.map.spaces[position["space_id"]]
        return {"space_id": space["id"], "room": space["name"], "floor_level": work.map.floors[space["floor_id"]]["level"],
                "tracking": position["tracking"]}

    @staticmethod
    def guidance_context(live: LiveState) -> dict | None:
        view = live.guidance_view()
        if view["status"] == "idle":
            return None
        index = view["target_index"]
        waypoints = view["waypoints"]
        return {"status": view["status"], "destination_id": view["destination_space_id"],
                "destination_name": view["destination_name"], "target_index": index, "waypoint_count": len(waypoints),
                "next_instruction": waypoints[index]["text"] if index is not None else None}

    def message(self, session: SessionState, body: dict, revision: int | None) -> dict:
        with session.lock:
            self.expire(session)
            self.match(session, revision)
            work = self.working_copy(session)
            base_revision = session.revision
            history_length = len(session.history)
        context = body.get("client_context", {})
        level = context.get("floor_level")
        if level is not None and level not in {floor["level"] for floor in work.map.floors.values()}:
            raise ApiError("30003_floor_not_found")
        selected = context.get("selected_space_id")
        if selected is not None and selected not in work.map.spaces:
            raise ApiError("30004_place_not_found", [{"field": "selected_space_id", "code": "not_found"}])
        step_free = (context.get("preferences") or work.preferences)["step_free"]
        voice = body.get("input_mode") == "voice"
        store = RoomNoteStore(self.notes_database)
        client = None
        try:
            bridge = TurnTools(self, work, store, step_free)
            live_context = {"live_position": self.live_context(work, session.live), "guidance": self.guidance_context(session.live)}
            turn_context = API_PROMPT + ("" if not voice else VOICE_PROMPT)
            client = self.client_factory()
            agent = BuildingAgent(
                work.map, self.output_directory / session.id, client=client,
                registered_tools=bridge.tools, response_format=ApiReply,
                turn_context=turn_context + "\nCurrent turn context: " + json.dumps({**context, "step_free_default": step_free, **live_context}),
                request_timeout=self.model_timeout, effort="low" if voice else EFFORT,
            )
            agent.messages = work.history
            reply = ApiReply.model_validate_json(agent.ask(body["text"]))
            effects = bridge.effects
            if reply.intent == "locate" and not any(effect["type"] == "highlight_spaces" for effect in effects):
                if bridge.space_ids:
                    effects.append({"type": "highlight_spaces", "space_ids": sorted(bridge.space_ids), "reason": "match"})
                if bridge.asset_ids:
                    effects.append({"type": "highlight_assets", "asset_ids": sorted(bridge.asset_ids)})
                if len(bridge.space_ids) == 1:
                    space_id = next(iter(bridge.space_ids))
                    floor = work.map.floors[work.map.spaces[space_id]["floor_id"]]
                    effects.append({"type": "focus", "floor_id": floor["id"], "floor_level": floor["level"], "point": list(work.map.anchor(space_id))})
            if reply.question and reply.options:
                options = [option.model_dump() for option in reply.options]
                for option in options:
                    place_id = option["place_id"]
                    if place_id is not None and place_id not in work.map.spaces and place_id not in work.map.assets:
                        raise ValueError("Model returned an unverified clarification place.")
                effects.append({"type": "ask", "question": reply.question, "options": options})
            latest = work.routes.get(work.last_route_id)
            understood = {
                "intent": reply.intent, "summary": reply.summary,
                "constraints": {"step_free": latest["step_free"] if bridge.route_ids and latest else step_free,
                                "via": latest["via"] if bridge.route_ids and latest else [], "closed_ids": sorted(work.map.closed)},
                "resolved": {"start_space_id": latest["start_space_id"] if bridge.route_ids and latest else None,
                             "destination_space_id": latest["destination_space_id"] if bridge.route_ids and latest else None,
                             "space_ids": sorted(bridge.space_ids), "asset_ids": sorted(bridge.asset_ids),
                             "count": bridge.count if reply.intent == "count" else None},
                "missing": reply.missing,
            }
            now = timestamp(self.clock())
            user_message = {"id": self.new_id(), "session_id": session.id, "role": "user", "text": body["text"],
                            "created_at": now, "understood": None, "effects": [], "pending_action_id": None}
            guide_message = {"id": self.new_id(), "session_id": session.id, "role": "guide", "text": reply.text,
                             "created_at": now, "understood": understood, "effects": effects, "pending_action_id": work.pending_action_id}
            # Model work never holds the session lock. Competing turns cannot overwrite newer state.
            with session.lock:
                with self._lock:
                    if self.sessions.get(session.id) is not session:
                        raise ApiError("30002_session_not_found")
                self.expire(session)
                if session.revision != base_revision or len(session.history) != history_length:
                    raise ApiError("30012_revision_conflict")
                changed = (work.preferences != session.preferences or work.last_route_id != session.last_route_id or work.pending_action_id != session.pending_action_id)
                work.revision = session.revision
                work.updated_at = session.updated_at
                if changed:
                    self.bump(work)
                work.transcript.extend([user_message, guide_message])
                response = {
                    "schema_version": 1, "session": self.view(work), "user_message": user_message, "guide_message": guide_message,
                    "routes": [work.routes[key] for key in dict.fromkeys(bridge.route_ids)],
                    "pending_action": copy.deepcopy(work.actions[work.pending_action_id]) if work.pending_action_id else None,
                    "usage": project(agent.usage, "input_tokens output_tokens"),
                    "speech_clip_id": None,
                }
                # Validate JSON before committing session state. Room reports are already saved
                # per tool call; a retry cannot add votes because each chat counts once.
                json.dumps(response, allow_nan=False)
                for name in ("map", "revision", "updated_at", "last_route_id", "pending_action_id", "routes", "actions", "transcript", "history", "route_results"):
                    setattr(session, name, getattr(work, name))
                if bridge.guidance_request is not None:
                    action, route_id = bridge.guidance_request
                    if action == "start":
                        session.live.start(session.map, route_id, session.routes[route_id], session.route_results[route_id], spoken=voice)
                    else:
                        session.live.stop("user")
                if voice:
                    response["speech_clip_id"] = session.live.clip(reply.text)
                return response
        except anthropic.RateLimitError as error:
            raise ApiError("40002_model_rate_limited", retry_after=1) from error
        except (anthropic.APITimeoutError, TimeoutError) as error:
            raise ApiError("40003_model_timeout") from error
        except (anthropic.APIError, MissingCredentialsError, ValueError) as error:
            raise ApiError("40001_model_unavailable", retry_after=1) from error
        finally:
            if client is not None and hasattr(client, "close"):
                client.close()


class ObservedTool(BetaBuiltinFunctionTool):
    """Preserve SDK tool definitions while recording results for application-owned effects."""
    def __init__(self, tool, observer, step_free: bool, on_error):
        self.tool, self.observer, self.step_free = tool, observer, step_free
        self.on_error = on_error

    def to_dict(self):
        return self.tool.to_dict()

    def call(self, arguments: object) -> str:
        if isinstance(arguments, dict) and self.name in {"find_route", "find_best_tour", "plan_errand", "reachable_rooms"}:
            arguments = {"step_free": self.step_free, **arguments}
        try:
            result = self.tool.call(arguments)
        except ToolError:
            self.on_error(self.name)
            raise
        self.observer(self.name, arguments, json.loads(result))
        return result


class TurnTools:
    def __init__(self, service: SessionService, work: SessionState, store: RoomNoteStore, step_free: bool):
        self.service, self.work = service, work
        self.effects: list[dict] = []
        self.route_ids: list[str] = []
        self.space_ids: set[str] = set()
        self.asset_ids: set[str] = set()
        self.count: int | None = None
        self._route_objects: dict[int, str] = {}
        self.guided_route_id: str | None = None  # last reachable route this turn drew
        self.guidance_request: tuple[str, str | None] | None = None

        def set_closed(element: str, closed: bool) -> str:
            """Propose closing/reopening an element. No edit is applied; the UI must confirm the pending action.

            Args:
                element: Verified opening, room or connector id, or exact name.
                closed: True to propose closing, False to propose reopening.
            """
            return self.proposal({"kind": "set_closed", "element_ref": element, "closed": closed})

        def add_door(first_space: str, second_space: str, step_free: bool = True) -> str:
            """Propose a door between adjacent rooms. Nothing is changed until UI confirmation.

            Args:
                first_space: Verified room id or exact name/number on one side.
                second_space: Verified room id or exact name/number on the other side.
                step_free: Whether the proposed door has no step.
            """
            return self.proposal({"kind": "add_door", "first_space": first_space, "second_space": second_space, "step_free": step_free})

        def show_location(element: str) -> str:
            """Select a verified room or asset and send its highlight/focus to the frontend map. No PNG.

            Args:
                element: Space/asset id or exact unambiguous room/asset name.
            """
            try:
                return as_json({"selected": work.map.select(element)})
            except MapError as error:
                raise ToolError(str(error)) from error

        def show_route(landmark_ids: list[str] | None = None) -> str:
            """Send the active computed route to the frontend map. No PNG and no new route computation.

            Args:
                landmark_ids: Optional verified space/asset ids to highlight along the route.
            """
            if work.map.last_route is None:
                raise ToolError("No active route to draw. Call find_route first.")
            try:
                landmarks = landmark_targets(work.map, landmark_ids or [])
            except MapError as error:
                raise ToolError(str(error)) from error
            for kind, item_id in landmarks:
                if kind == "space":
                    self.effects.append({"type": "highlight_spaces", "space_ids": [item_id], "reason": "selected"})
                else:
                    self.effects.append({"type": "highlight_assets", "asset_ids": [item_id]})
            return as_json(route_json(work.map.last_route))

        def start_guidance() -> str:
            """Start spoken step-by-step guidance along the route computed this turn. Starts after this reply."""
            route_id = self.guided_route_id
            if route_id is None:
                raise ToolError("Call find_route from the user's live position first.")
            record = work.routes[route_id]
            position = work_live.position_view()
            if position and position["tracking"] == "live" and position["space_id"] not in (None, record["start_space_id"]):
                names = [work.map.spaces[space]["name"] for space in (position["space_id"], record["start_space_id"])]
                raise ToolError(f"The user is in {names[0]}, but the route starts in {names[1]}. Call find_route from the live position first.")
            self.guidance_request = ("start", route_id)
            return as_json({"guidance": "will start after this reply", "destination": work.map.spaces[record["destination_space_id"]]["name"]})

        def stop_guidance() -> str:
            """Stop the running spoken guidance. Takes effect after this reply."""
            self.guidance_request = ("stop", None)
            return as_json({"guidance": "will stop after this reply"})

        work_live = work.live
        overrides = {function.__name__: ArgumentCheckedTool(function) for function in (set_closed, add_door, show_location, show_route)}
        originals = make_tools(work.map, service.output_directory / work.id, notes_store=store, session_id=work.id)
        self.tools = [ObservedTool(overrides.get(tool.name, tool), self.observe, step_free, self.failed) for tool in originals]
        self.tools += [ArgumentCheckedTool(function) for function in (start_guidance, stop_guidance)]

    def failed(self, name: str) -> None:
        if name == "find_route":
            self.work.last_route_id = None
            self.guided_route_id = None
            self.effects.append({"type": "clear_route"})

    def proposal(self, proposal: dict) -> str:
        try:
            action = self.service.propose(self.work, proposal, None)
            self.effects.extend(action["preview_effects"])
            return as_json({"applied": False, "confirmation_required": True, "pending_action": action})
        except ApiError as error:
            raise ToolError(f"{error.message} {as_json(error.details)} Confirm or cancel the current pending action if one exists.") from error

    def observe(self, name: str, arguments: dict, result: dict) -> None:
        if name in {"search_building", "list_spaces", "spatial_search"}:
            self.count = result["matches"]
            for item in result["results"]:
                if item["kind"] == "space":
                    self.space_ids.add(item["id"])
                elif item["kind"] == "asset":
                    self.asset_ids.add(item["id"])
                    self.space_ids.add(item["space_id"])
        if name == "inspect_space":
            self.space_ids.add(result["space"]["id"])
        if name in {"find_largest_room", "find_stacked_room"} and result.get("room"):
            self.space_ids.add(result["room"]["id"])
        if isinstance(result.get("note"), dict) and result["note"].get("space_id") in self.work.map.spaces:
            self.space_ids.add(result["note"]["space_id"])
        if name == "get_room_notes":
            self.space_ids.update(result["checked_space_ids"])
        if name in {"reachable_rooms", "count_shared_walls", "analyze_what_if_door"}:
            self.count = result["count"]
        if name == "show_location":
            selection = self.work.map.selection
            space_id = selection["space_id"]
            self.space_ids.add(space_id)
            self.effects.append({"type": "highlight_spaces", "space_ids": [space_id], "reason": "selected"})
            if selection["kind"] == "asset":
                self.asset_ids.add(selection["id"])
                self.effects.append({"type": "highlight_assets", "asset_ids": [selection["id"]]})
            floor = self.work.map.floors[selection["floor_id"]]
            self.effects.append({"type": "focus", "floor_id": floor["id"], "floor_level": floor["level"], "point": list(self.work.map.anchor(space_id))})
        if name in {"find_route", "show_route", "find_best_tour", "plan_errand"}:
            active = name in {"find_route", "show_route"} or arguments.get("activate", name == "find_best_tour")
            route = self.work.map.last_route
            if active and route is not None:
                key = id(route)
                if key not in self._route_objects:
                    record = self.service.route_record(self.work, route, route.stops, route.step_free)
                    self.work.routes[record["id"]] = record
                    self.work.route_results[record["id"]] = route
                    self.work.last_route_id = record["id"]
                    self._route_objects[key] = record["id"]
                route_id = self._route_objects[key]
                self.route_ids.append(route_id)
                self.guided_route_id = route_id
                self.space_ids.update(route.space_path)
                self.effects.append({"type": "draw_route", "route_id": route_id})
