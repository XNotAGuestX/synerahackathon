"""Fixture-backed /api/v1 server for contract smoke tests.

    uv run python scripts/serve_api.py
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from final_agent.building_map import MapError
from final_agent.guide_session import GuideSession, available_buildings, validate_plan

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs" / "api" / "examples"
SESSION_ID = "11111111-1111-4111-8111-111111111111"
HOST = "0.0.0.0"
PORT = 8000

idempotency: dict[str, tuple[str, int, dict]] = {}
revision = 2
step_free = True
closed_ids: list[str] = []
last_route_id: str | None = None
pending_action_id: str | None = None
computed: dict[str, GuideSession] = {}
building_dirs = {path.name: path for path in available_buildings()}


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def error(code: str, message: str, status: int, trace_id: str) -> tuple[int, dict]:
    return status, {"code": code, "message": message, "trace_id": trace_id, "details": []}


def session_body() -> dict:
    body = load("session.json")
    body["revision"] = revision
    body["preferences"] = {"step_free": step_free}
    body["closed_ids"] = list(closed_ids)
    body["last_route_id"] = last_route_id
    body["pending_action_id"] = pending_action_id
    return body


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, payload: dict, request_id: str, location: str | None = None) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Request-Id", request_id)
        self.send_header("X-API-Version", "1")
        self.send_header("X-Schema-Version", "1")
        if "revision" in payload:
            self.send_header("ETag", f'"{payload["revision"]}"')
        if location:
            self.send_header("Location", location)
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _request_id(self) -> str:
        return self.headers.get("X-Request-Id") or "11111111-1111-4111-8111-1111111111a1"

    def _require_key(self, body: dict, request_id: str) -> tuple[str, tuple[int, dict] | None]:
        key = self.headers.get("Idempotency-Key", "")
        if not key:
            return "", error("20010_idempotency_key_required", "Idempotency-Key is required.", 400, request_id)
        signature = json.dumps(body, sort_keys=True)
        previous = idempotency.get(key)
        if previous and previous[0] != signature:
            return key, error("20011_idempotency_key_mismatch", "Idempotency-Key was reused with a different body.", 409, request_id)
        if previous:
            return key, (previous[1], previous[2])
        return key, None

    def _remember(self, key: str, body: dict, status: int, payload: dict) -> None:
        if key and status < 500:
            idempotency[key] = (json.dumps(body, sort_keys=True), status, payload)

    def _if_match_ok(self, request_id: str) -> tuple[int, dict] | None:
        header = self.headers.get("If-Match")
        if header and header.strip('"') != str(revision):
            return error("30012_revision_conflict", "If-Match does not match the session revision.", 409, request_id)
        return None

    def do_GET(self) -> None:  # noqa: N802
        request_id = self._request_id()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)
        if path == "/api/v1/health":
            self._send(200, load("health.json"), request_id)
            return
        if path == "/api/v1/buildings":
            if "computed" in query:
                items = [GuideSession(directory).building_summary() for directory in building_dirs.values()]
                self._send(200, {"items": items, "page": 1, "page_size": len(items), "total": len(items)}, request_id)
                return
            self._send(200, load("buildings-page.json"), request_id)
            return
        if path.startswith("/api/v1/sessions/") and path.split("/")[4] in computed:
            self._computed_get(path, query, request_id)
            return
        if path == f"/api/v1/sessions/{SESSION_ID}":
            self._send(200, session_body(), request_id)
            return
        if path == f"/api/v1/sessions/{SESSION_ID}/floors":
            self._send(200, load("floor-index.json"), request_id)
            return
        if path == f"/api/v1/sessions/{SESSION_ID}/floors/proc-factory-dev-003-F0/plan":
            plan = load("floor-plan-closed.json" if closed_ids else "floor-plan.json")
            plan["closed_ids"] = list(closed_ids)
            plan["revision"] = revision
            self._send(200, plan, request_id)
            return
        if path == f"/api/v1/sessions/{SESSION_ID}/floors/proc-factory-dev-003-F1/plan":
            plan = load("floor-plan-f1.json")
            plan["revision"] = revision
            self._send(200, plan, request_id)
            return
        if path == f"/api/v1/sessions/{SESSION_ID}/places":
            needle = (query.get("q") or [""])[0].lower()
            page = load("places-page.json")
            page["items"] = [item for item in page["items"] if needle in item["name"].lower() or needle in (item.get("asset_type") or "")]
            self._send(200, page, request_id)
            return
        if path.startswith(f"/api/v1/sessions/{SESSION_ID}/routes/"):
            route_id = path.rsplit("/", 1)[-1]
            route = load("route.json")
            unreachable = load("route-unreachable.json")
            if route_id == route["id"]:
                self._send(200, route, request_id)
                return
            if route_id == unreachable["id"]:
                self._send(200, unreachable, request_id)
                return
            status, payload = error("30004_place_not_found", "Route was not found.", 404, request_id)
            self._send(status, payload, request_id)
            return
        if path == f"/api/v1/sessions/{SESSION_ID}/actions/{pending_action_id or ''}":
            self._send(200, load("action-pending.json"), request_id)
            return
        status, payload = error("30002_session_not_found", "Resource was not found.", 404, request_id)
        self._send(status, payload, request_id)

    def do_POST(self) -> None:  # noqa: N802
        global last_route_id, pending_action_id, revision, closed_ids
        request_id = self._request_id()
        path = urlparse(self.path).path.rstrip("/")
        body = self._read_json()
        key, replay = self._require_key(body, request_id)
        if replay:
            self._send(replay[0], replay[1], request_id)
            return
        conflict = self._if_match_ok(request_id)
        if conflict:
            self._send(conflict[0], conflict[1], request_id)
            return
        if path == "/api/v1/sessions":
            if body.get("engine") == "computed":
                directory = building_dirs.get(str(body.get("building_id")))
                if directory is None:
                    status, payload = error("30001_building_not_found", "This building is not loaded.", 404, request_id)
                    self._send(status, payload, request_id)
                    return
                session = GuideSession(directory)
                computed[session.id] = session
                payload = {"id": session.id, "building_id": session.building_summary()["id"], "building_name": session.building_summary()["name"], "revision": session.revision, "preferences": {"step_free": session.step_free}}
                self._send(201, payload, request_id, f"/api/v1/sessions/{session.id}")
                return
            payload = session_body()
            self._remember(key, body, 201, payload)
            self._send(201, payload, request_id, f"/api/v1/sessions/{SESSION_ID}")
            return
        if path.startswith("/api/v1/sessions/") and path.split("/")[4] in computed:
            self._computed_post(path, body, request_id)
            return
        if path == f"/api/v1/sessions/{SESSION_ID}/routes":
            destination = str(body.get("destination", ""))
            saved = load("route.json")
            if destination in {saved["destination_space_id"], "proc-factory-dev-003-A00001"} and body.get("step_free", step_free):
                payload = saved
                last_route_id = saved["id"]
            else:
                payload = load("route-unreachable.json")
                last_route_id = payload["id"]
            self._remember(key, body, 201, payload)
            self._send(201, payload, request_id)
            return
        if path == f"/api/v1/sessions/{SESSION_ID}/messages":
            text = str(body.get("text", "")).lower()
            if "desk" in text:
                payload = load("message-clarify.json")
            elif "closed" in text:
                payload = load("message-pending-action.json")
                pending_action_id = payload["pending_action"]["id"]
            else:
                payload = load("message-accepted.json")
                last_route_id = payload["routes"][0]["id"]
            self._remember(key, body, 201, payload)
            self._send(201, payload, request_id)
            return
        if path.endswith("/confirmations"):
            action_id = path.split("/")[-2]
            if action_id != "55555555-5555-4555-8555-555555555555":
                status, payload = error("30008_action_not_found", "Action was not found.", 404, request_id)
                self._send(status, payload, request_id)
                return
            if pending_action_id is None:
                status, payload = error("30009_action_expired", "Action is no longer pending.", 409, request_id)
                self._send(status, payload, request_id)
                return
            payload = load("action-confirmed.json")
            closed_ids = payload["result"]["closed_ids"]
            pending_action_id = None
            revision += 1
            self._remember(key, body, 200, payload)
            self._send(200, payload, request_id)
            return
        if path.endswith("/cancellations"):
            pending_action_id = None
            payload = {"schema_version": 1, "id": path.split("/")[-2], "status": "cancelled", "summary": "Change cancelled."}
            self._remember(key, body, 200, payload)
            self._send(200, payload, request_id)
            return
        status, payload = error("30002_session_not_found", "Resource was not found.", 404, request_id)
        self._send(status, payload, request_id)

    def do_PUT(self) -> None:  # noqa: N802
        global step_free, revision
        request_id = self._request_id()
        path = urlparse(self.path).path.rstrip("/")
        body = self._read_json()
        conflict = self._if_match_ok(request_id)
        if conflict:
            self._send(conflict[0], conflict[1], request_id)
            return
        if path.startswith("/api/v1/sessions/") and path.split("/")[4] in computed and path.endswith("/preferences"):
            session = computed[path.split("/")[4]]
            session.step_free = bool(body.get("step_free"))
            session.revision += 1
            self._send(200, {"id": session.id, "building_id": session.building_summary()["id"], "building_name": session.building_summary()["name"], "revision": session.revision, "preferences": {"step_free": session.step_free}}, request_id)
            return
        if path == f"/api/v1/sessions/{SESSION_ID}/preferences":
            step_free = bool(body.get("step_free"))
            revision += 1
            self._send(200, session_body(), request_id)
            return
        status, payload = error("30002_session_not_found", "Resource was not found.", 404, request_id)
        self._send(status, payload, request_id)


    def _computed_get(self, path: str, query: dict, request_id: str) -> None:
        session = computed[path.split("/")[4]]
        parts = path.split("/")
        if parts[-1] == session.id:
            self._send(200, {"id": session.id, "building_id": session.building_summary()["id"], "building_name": session.building_summary()["name"], "revision": session.revision, "preferences": {"step_free": session.step_free}, "closed_ids": sorted(session.map.closed), "last_route_id": session.last_route_id, "pending_action_id": None if not session.pending else session.pending["id"]}, request_id)
            return
        if parts[-1] == "floors":
            self._send(200, {"floors": session.floors()}, request_id)
            return
        if parts[-1] == "plan":
            self._send(200, session.floor_plan(parts[-2]), request_id)
            return
        if parts[-1] == "places":
            page = int((query.get("page") or ["1"])[0])
            self._send(200, session.search((query.get("q") or [""])[0], page), request_id)
            return
        if "actions" in parts:
            action_id = parts[-1]
            if session.pending and session.pending["id"] == action_id:
                self._send(200, {
                    "id": session.pending["id"],
                    "status": "pending",
                    "summary": session.pending["summary"],
                    "closed_ids": [],
                    "proposal": {
                        "kind": "set_closed",
                        "element_ref": session.pending["element_id"],
                        "closed": session.pending["closed"],
                    },
                }, request_id)
                return
            status, payload = error("30009_action_expired", "Action is no longer pending.", 409, request_id)
            self._send(status, payload, request_id)
            return
        if "routes" in parts:
            route = session.routes.get(parts[-1])
            if route is None:
                status, payload = error("30004_place_not_found", "Route was not found.", 404, request_id)
                self._send(status, payload, request_id)
                return
            self._send(200, route, request_id)
            return
        status, payload = error("30002_session_not_found", "Resource was not found.", 404, request_id)
        self._send(status, payload, request_id)

    def _computed_post(self, path: str, body: dict, request_id: str) -> None:
        session = computed[path.split("/")[4]]
        if path.endswith("/messages") or path.endswith("/message"):
            self._send(201, session.message(str(body.get("text", ""))), request_id)
            return
        if path.endswith("/routes"):
            try:
                route = session.create_route(str(body.get("start")), str(body.get("destination")), bool(body.get("step_free")), body.get("via") or [])
            except MapError as route_error:
                status, payload = error("30004_place_not_found", str(route_error), 422, request_id)
                self._send(status, payload, request_id)
                return
            self._send(201, route, request_id)
            return
        if path.endswith("/confirmations"):
            try:
                payload = session.confirm()
            except Exception as error:
                status, body_error = error("30009_action_expired", str(error), 409, request_id)
                self._send(status, body_error, request_id)
                return
            self._send(200, payload, request_id)
            return
        if path.endswith("/cancellations"):
            self._send(200, session.cancel(), request_id)
            return
        if path.endswith("/validations"):
            self._send(200, {"issues": validate_plan(body)}, request_id)
            return
        status, payload = error("30002_session_not_found", "Resource was not found.", 404, request_id)
        self._send(status, payload, request_id)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"API fixture server on http://{HOST}:{PORT}/api/v1")
    server.serve_forever()


if __name__ == "__main__":
    main()
