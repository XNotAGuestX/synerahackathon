"""Contract smoke against the fixture API server."""

from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"


def call(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8")), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8")), dict(error.headers)


def main() -> int:
    checks = []
    status, health, headers = call("GET", "/health")
    checks.append(("health", status == 200 and health["status"] == "ok" and "X-Request-Id" in headers))
    status, buildings, _ = call("GET", "/buildings")
    checks.append(("buildings", status == 200 and buildings["items"]))
    status, session, _ = call("POST", "/sessions", {"building_id": "proc-factory-dev-003"}, {"Idempotency-Key": "smoke-session"})
    checks.append(("session", status == 201 and session["id"]))
    status, floors, _ = call("GET", f"/sessions/{session['id']}/floors")
    checks.append(("floors", status == 200 and floors["floors"]))
    status, plan, _ = call("GET", f"/sessions/{session['id']}/floors/proc-factory-dev-003-F0/plan")
    checks.append(("plan", status == 200 and plan["spaces"]))
    status, places, _ = call("GET", f"/sessions/{session['id']}/places?q=cnc")
    checks.append(("places", status == 200 and "items" in places))
    status, route, _ = call("POST", f"/sessions/{session['id']}/routes", {"start": "a", "destination": "proc-factory-dev-003-A00001", "step_free": True}, {"Idempotency-Key": "smoke-route"})
    checks.append(("route", status == 201 and route["reachable"] is True))
    status, message, _ = call("POST", f"/sessions/{session['id']}/messages", {"text": "Where is the desk?", "input_mode": "text"}, {"Idempotency-Key": "smoke-message"})
    checks.append(("message", status == 201 and message["guide_message"]["effects"][0]["type"] == "ask"))
    status, missing, _ = call("POST", f"/sessions/{session['id']}/routes", {"start": "a", "destination": "b"})
    checks.append(("idempotency required", status == 400 and missing["code"] == "20010_idempotency_key_required" and missing["trace_id"]))
    status, mismatch, headers = call("POST", f"/sessions/{session['id']}/routes", {"start": "other", "destination": "b"}, {"Idempotency-Key": "smoke-route"})
    checks.append(("idempotency mismatch", status == 409 and mismatch["code"] == "20011_idempotency_key_mismatch" and headers.get("X-Request-Id")))
    status, conflict, _ = call("PUT", f"/sessions/{session['id']}/preferences", {"step_free": False}, {"If-Match": '"999"'})
    checks.append(("revision conflict", status == 409 and conflict["code"] == "30012_revision_conflict"))
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("OK" if ok else "FAIL"), name)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
