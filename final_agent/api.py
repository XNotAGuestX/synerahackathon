"""HTTP v1 adapter. Run with ``uv run python -m final_agent.api`` (one worker)."""

import argparse
import asyncio
import copy
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

import uvicorn
import yaml
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware

from .api_session import ApiError, SessionService, identifier

LOG = logging.getLogger("final_agent.api")
MAX_BODY = 65536
API_ROOT = "/api/v1"
EXPOSE_HEADERS = ["ETag", "Location", "X-Request-Id", "X-API-Version", "X-Schema-Version", "Retry-After"]
DEFAULT_ORIGINS = [f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (3000, 5173)]

Reference = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Preferences(Input):
    step_free: bool


class SessionCreate(Input):
    building_id: Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
    preferences: Preferences = Field(default_factory=lambda: Preferences(step_free=False))


class RouteCreate(Input):
    start: Reference
    destination: Reference
    step_free: bool | None = None
    via: list[Reference] = Field(default_factory=list, max_length=8)


class ClientContext(Input):
    floor_level: int | None = None
    selected_space_id: str | None = None
    preferences: Preferences | None = None


class MessageCreate(Input):
    text: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    input_mode: Literal["text", "transcript"] = "text"
    client_context: ClientContext = Field(default_factory=ClientContext)


class SetClosedProposal(Input):
    kind: Literal["set_closed"]
    element_ref: Reference
    closed: bool


class AddDoorProposal(Input):
    kind: Literal["add_door"]
    first_space: Reference
    second_space: Reference
    step_free: bool = True


FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class PositionFix(Input):
    floor_id: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    x_m: FiniteFloat
    y_m: FiniteFloat
    accuracy_m: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    measured_at: str
    source: Literal["simulated", "wifi", "manual"]

    @field_validator("measured_at")
    @classmethod
    def rfc3339(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)", value):
            raise ValueError("measured_at must be RFC 3339")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class GuidanceStart(Input):
    route_id: Reference


ActionCreate = Annotated[SetClosedProposal | AddDoorProposal, Field(discriminator="kind")]


def load_contract() -> dict:
    source = Path(__file__).resolve().parents[1] / "openapi.yaml"
    if not source.is_file():
        source = Path(__file__).with_name("openapi.yaml")
    return yaml.safe_load(source.read_text(encoding="utf-8"))


def error_response(error: ApiError, trace_id: str) -> JSONResponse:
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after is not None else {}
    return JSONResponse({"code": error.code, "message": error.message, "trace_id": trace_id, "details": error.details},
                        status_code=error.status, headers=headers)


def revision(request: Request) -> int | None:
    value = request.headers.get("If-Match")
    if value is None:
        return None
    if not re.fullmatch(r'"[1-9][0-9]*"', value):
        raise ApiError("20001_validation_failed", [{"field": "If-Match", "code": "invalid"}])
    return int(value[1:-1])


def respond(body: dict, *, status: int = 200, location: str | None = None, etag: int | None = None) -> JSONResponse:
    headers = {}
    if location is not None:
        headers["Location"] = location
    if etag is not None:
        headers["ETag"] = f'"{etag}"'
    return JSONResponse(body, status_code=status, headers=headers)


class TraceMiddleware:
    """Request tracing also wraps auth failures and browser preflight responses."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin1")
        trace_id = incoming if 1 <= len(incoming) <= 128 else identifier()
        scope.setdefault("state", {})["trace_id"] = trace_id
        started = time.monotonic()
        status = 500

        async def traced(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [(key, value) for key, value in message.get("headers", []) if key.lower() not in {b"x-request-id", b"x-api-version", b"x-schema-version"}]
                message["headers"] = headers + [(b"x-request-id", trace_id.encode("latin1")), (b"x-api-version", b"1"), (b"x-schema-version", b"1")]
            await send(message)

        try:
            await self.app(scope, receive, traced)
        finally:
            match = re.search(r"/sessions/([^/]+)", scope["path"])
            LOG.info("trace_id=%s method=%s path=%s status=%s duration_ms=%.1f session_id=%s",
                     trace_id, scope["method"], scope["path"], status, (time.monotonic() - started) * 1000,
                     match.group(1) if match else "-")


class ProtocolMiddleware:
    """Bounded JSON bodies, optional auth and process-local exactly-once POST handling."""
    def __init__(self, app, service: SessionService, contract: dict, token: str, rate_limit: int):
        self.app, self.service, self.token, self.rate_limit = app, service, token, rate_limit
        self.lock = threading.Lock()
        self.records: dict[str, dict] = {}
        self.rates: dict[str, tuple[int, float]] = {}
        self.operations = []
        for path, methods in contract["paths"].items():
            pattern = re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "$")
            for method, operation in methods.items():
                allowed = set()
                for parameter in operation.get("parameters", []):
                    if "$ref" in parameter:
                        parameter = contract["components"]["parameters"][parameter["$ref"].split("/")[-1]]
                    if parameter["in"] == "query":
                        allowed.add(parameter["name"])
                self.operations.append((pattern, method.upper(), allowed))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        trace_id = scope["state"]["trace_id"]
        record = None
        mismatch_record = None
        key = None
        try:
            if self.token and not (scope["path"] == API_ROOT + "/health" and scope["method"] == "GET"):
                authorization = request.headers.get("Authorization", "")
                if not hmac.compare_digest(authorization.encode(), ("Bearer " + self.token).encode()):
                    raise ApiError("10001_unauthenticated")
            incoming_id = request.headers.get("X-Request-Id")
            if incoming_id is not None and not 1 <= len(incoming_id) <= 128:
                raise ApiError("20001_validation_failed", [{"field": "X-Request-Id", "code": "invalid"}])
            if scope["method"] == "POST":
                key = request.headers.get("Idempotency-Key")
                if key is None:
                    raise ApiError("20010_idempotency_key_required")
                if not re.fullmatch(r"[\x21-\x7e]{1,128}", key):
                    raise ApiError("20001_validation_failed", [{"field": "Idempotency-Key", "code": "invalid"}])
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > MAX_BODY:
                    raise ApiError("20012_payload_too_large")
                if not message.get("more_body", False):
                    break
            raw_body = bytes(body)
            if key is not None:
                try:
                    canonical = json.dumps(json.loads(raw_body or b"null"), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                except (ValueError, UnicodeError):
                    canonical = raw_body
                fingerprint = hashlib.sha256(scope["method"].encode() + scope["path"].encode() + canonical).hexdigest()
                while True:
                    cached = None
                    with self.lock:
                        now = self.service.clock()
                        for expired in [name for name, item in self.records.items() if item.get("expires", now + timedelta(days=1)) <= now]:
                            self.records.pop(expired, None)
                        existing = self.records.get(key)
                        if existing is not None and existing.get("expires", now + timedelta(days=1)) <= now:
                            self.records.pop(key)
                            existing = None
                        if existing is None:
                            record = {"fingerprint": fingerprint, "event": threading.Event()}
                            self.records[key] = record
                            break
                        if existing["fingerprint"] != fingerprint:
                            cached = existing.get("mismatches", {}).get(fingerprint)
                            if cached is None:
                                mismatch_record = existing
                                raise ApiError("20011_idempotency_key_mismatch")
                        else:
                            cached = existing.get("response")
                        event = existing["event"]
                    if cached is not None:
                        await self.replay(cached, trace_id, send)
                        return
                    await asyncio.to_thread(event.wait)
            if self.rate_limit and scope["path"] != API_ROOT + "/health":
                address = scope.get("client", ("local", 0))[0]
                with self.lock:
                    now = time.monotonic()
                    count, began = self.rates.get(address, (0, now))
                    if now - began >= 60:
                        count, began = 0, now
                    if count >= self.rate_limit:
                        raise ApiError("00002_rate_limited", retry_after=max(1, int(60 - (now - began))))
                    self.rates[address] = count + 1, began
            for pattern, method, allowed in self.operations:
                if method == scope["method"] and pattern.fullmatch(scope["path"]):
                    unknown = set(request.query_params) - allowed
                    if unknown:
                        raise ApiError("20001_validation_failed", [{"field": field, "code": "unknown_field"} for field in sorted(unknown)])
                    break
            received = False

            async def replay_body():
                nonlocal received
                if received:
                    return {"type": "http.disconnect"}
                received = True
                return {"type": "http.request", "body": raw_body, "more_body": False}

            messages = []

            async def collect(message):
                messages.append(message)

            try:
                await self.app(scope, replay_body, collect)
            except Exception:
                LOG.exception("Unhandled API failure trace_id=%s", trace_id)
                messages = []
                await error_response(ApiError("00001_internal"), trace_id)(scope, replay_body, collect)
            if record is not None:
                status = messages[0]["status"]
                error_code = None
                if status >= 400:
                    payload = b"".join(message.get("body", b"") for message in messages)
                    error_code = json.loads(payload).get("code")
                with self.lock:
                    if status < 500 and status != 429 and error_code != "30012_revision_conflict":
                        record["response"] = copy.deepcopy(messages)
                        record["expires"] = self.service.clock() + timedelta(hours=24)
                    else:
                        self.records.pop(key, None)
                    record["event"].set()
            for message in messages:
                await send(message)
        except ApiError as error:
            response = error_response(error, trace_id)
            captured = []

            async def capture(message):
                captured.append(message)

            await response(scope, receive, capture)
            if mismatch_record is not None:
                with self.lock:
                    mismatch_record.setdefault("mismatches", {})[fingerprint] = copy.deepcopy(captured)
            if record is not None:
                with self.lock:
                    if error.status < 500 and error.status != 429 and error.code != "30012_revision_conflict":
                        record["response"] = copy.deepcopy(captured)
                        record["expires"] = self.service.clock() + timedelta(hours=24)
                    else:
                        self.records.pop(key, None)
                    record["event"].set()
            for message in captured:
                await send(message)
        finally:
            if record is not None and not record["event"].is_set():
                with self.lock:
                    self.records.pop(key, None)
                    record["event"].set()

    @staticmethod
    async def replay(messages: list, trace_id: str, send) -> None:
        messages = copy.deepcopy(messages)
        if messages[0]["status"] >= 400:
            payload = json.loads(b"".join(message.get("body", b"") for message in messages))
            payload["trace_id"] = trace_id
            body = json.dumps(payload, separators=(",", ":")).encode()
            messages = [messages[0], {"type": "http.response.body", "body": body}]
            messages[0]["headers"] = [(key, str(len(body)).encode() if key.lower() == b"content-length" else value) for key, value in messages[0]["headers"]]
        for message in messages:
            await send(message)


def create_app(
    data_directory: Path = Path("data"), output_directory: Path = Path("agent_output/api"), *,
    notes_database: Path | None = None, api_token: str | None = None, cors_origins: list[str] | None = None,
    client_factory=None, clock=None, new_id=None, rate_limit: int = 0, model_timeout: float = 60,
) -> FastAPI:
    options = {name: value for name, value in (("clock", clock), ("new_id", new_id)) if value is not None}
    service = SessionService(data_directory, output_directory, notes_database=notes_database,
                             client_factory=client_factory, model_timeout=model_timeout, **options)
    contract = load_contract()
    app = FastAPI(title=contract["info"]["title"], version="1.0.0")
    app.openapi_schema = contract
    app.state.service = service
    app.add_middleware(ProtocolMiddleware, service=service, contract=contract,
                       token=os.environ.get("API_TOKEN", "") if api_token is None else api_token, rate_limit=rate_limit)
    if cors_origins is None:
        cors_origins = [origin.strip() for origin in os.environ.get("CORS_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(",") if origin.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                       allow_headers=["Content-Type", "Authorization", "X-Request-Id", "Idempotency-Key", "If-Match"], expose_headers=EXPOSE_HEADERS)
    app.add_middleware(TraceMiddleware)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError):
        return error_response(error, request.state.trace_id)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        details = []
        for item in error.errors():
            location = item["loc"]
            code = "unknown_field" if item["type"] == "extra_forbidden" else "required" if item["type"] == "missing" else "too_long" if "too_long" in item["type"] else "invalid"
            details.append({"field": ".".join(str(part) for part in location[1:]), "code": code})
        return error_response(ApiError("20001_validation_failed", details), request.state.trace_id)

    @app.exception_handler(HTTPException)
    async def framework_error(request: Request, error: HTTPException):
        code = "30004_place_not_found" if error.status_code == 404 else "20001_validation_failed"
        return error_response(ApiError(code, [{"field": "path", "code": "not_found" if error.status_code == 404 else "method_not_allowed"}]), request.state.trace_id)

    @app.get(API_ROOT + "/health", operation_id="get_health")
    def get_health():
        return {"schema_version": 1, "status": "ok", "api_version": "1"}

    @app.get(API_ROOT + "/buildings", operation_id="list_buildings")
    def list_buildings(split: Literal["train", "dev", "test"] | None = None,
                       cursor: str | None = Query(None, min_length=1, max_length=512), limit: int = Query(20, ge=1, le=100)):
        return service.buildings(split, cursor, limit)

    @app.get(API_ROOT + "/buildings/{building_id}", operation_id="get_building")
    def get_building(building_id: str):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", building_id):
            raise ApiError("20001_validation_failed", [{"field": "building_id", "code": "invalid"}])
        return service.building(building_id)

    @app.post(API_ROOT + "/sessions", operation_id="create_session")
    def create_session(body: SessionCreate):
        result = service.create(body.building_id, body.preferences.model_dump())
        return respond(result, status=201, location=f"{API_ROOT}/sessions/{result['id']}", etag=result["revision"])

    @app.get(API_ROOT + "/sessions/{session_id}", operation_id="get_session")
    def get_session(session_id: UUID):
        result = service.view(service.get(str(session_id)))
        return respond(result, etag=result["revision"])

    @app.delete(API_ROOT + "/sessions/{session_id}", operation_id="delete_session")
    def delete_session(session_id: UUID):
        service.delete(str(session_id))
        return Response(status_code=204)

    @app.put(API_ROOT + "/sessions/{session_id}/preferences", operation_id="put_preferences")
    def put_preferences(session_id: UUID, body: Preferences, request: Request):
        result = service.preferences(service.get(str(session_id)), body.model_dump(), revision(request))
        return respond(result, etag=result["revision"])

    @app.get(API_ROOT + "/sessions/{session_id}/floors", operation_id="list_floors")
    def list_floors(session_id: UUID):
        result = service.floor_index(service.get(str(session_id)))
        return respond(result, etag=result["revision"])

    @app.get(API_ROOT + "/sessions/{session_id}/floors/{floor_id}/plan", operation_id="get_floor_plan")
    def get_floor_plan(session_id: UUID, floor_id: str, include: str | None = None):
        if include is None:
            included = ["spaces", "openings", "assets", "connectors"]
        else:
            included = list(dict.fromkeys(include.split(","))) if include else []
        if not 1 <= len(floor_id) <= 160 or any(value not in {"spaces", "openings", "assets", "connectors"} for value in included):
            raise ApiError("20001_validation_failed", [{"field": "include" if len(floor_id) <= 160 else "floor_id", "code": "not_in_whitelist"}])
        result = service.floor_plan(service.get(str(session_id)), floor_id, included)
        return respond(result, etag=result["revision"])

    @app.get(API_ROOT + "/sessions/{session_id}/places", operation_id="search_places")
    def search_places(session_id: UUID, q: str = Query(min_length=1, max_length=200), floor_level: int | None = None,
                      kind: Literal["space", "asset"] | None = None, cursor: str | None = Query(None, min_length=1, max_length=512),
                      limit: int = Query(15, ge=1, le=50)):
        if not q.strip():
            raise ApiError("20001_validation_failed", [{"field": "q", "code": "required"}])
        return service.places(service.get(str(session_id)), q, floor_level, kind, cursor, limit)

    @app.post(API_ROOT + "/sessions/{session_id}/routes", operation_id="create_route")
    def create_route(session_id: UUID, body: RouteCreate, request: Request):
        if "step_free" in body.model_fields_set and body.step_free is None:
            raise ApiError("20001_validation_failed", [{"field": "step_free", "code": "invalid"}])
        state = service.get(str(session_id))
        with state.lock:
            result = service.create_route(state, body.model_dump(exclude_none=True), revision(request))
            return respond(result, status=201, location=f"{API_ROOT}/sessions/{session_id}/routes/{result['id']}", etag=state.revision)

    @app.get(API_ROOT + "/sessions/{session_id}/routes/{route_id}", operation_id="get_route")
    def get_route(session_id: UUID, route_id: UUID):
        return service.route(service.get(str(session_id)), str(route_id))

    @app.get(API_ROOT + "/sessions/{session_id}/messages", operation_id="list_messages")
    def list_messages(session_id: UUID, cursor: str | None = Query(None, min_length=1, max_length=512), limit: int = Query(20, ge=1, le=100)):
        return service.message_page(service.get(str(session_id)), cursor, limit)

    @app.post(API_ROOT + "/sessions/{session_id}/messages", operation_id="create_message")
    def create_message(session_id: UUID, body: MessageCreate, request: Request):
        if not body.text.strip():
            raise ApiError("20001_validation_failed", [{"field": "text", "code": "required"}])
        LOG.debug("trace_id=%s user_text=%s", request.state.trace_id, body.text)
        result = service.message(service.get(str(session_id)), body.model_dump(), revision(request))
        return respond(result, status=201, location=f"{API_ROOT}/sessions/{session_id}/messages/{result['user_message']['id']}", etag=result["session"]["revision"])

    @app.post(API_ROOT + "/sessions/{session_id}/actions", operation_id="create_action")
    def create_action(session_id: UUID, body: ActionCreate, request: Request):
        state = service.get(str(session_id))
        with state.lock:
            result = service.propose(state, body.model_dump(), revision(request))
            return respond(result, status=201, location=f"{API_ROOT}/sessions/{session_id}/actions/{result['id']}", etag=state.revision)

    @app.get(API_ROOT + "/sessions/{session_id}/actions/{action_id}", operation_id="get_action")
    def get_action(session_id: UUID, action_id: UUID):
        return service.action(service.get(str(session_id)), str(action_id))

    @app.post(API_ROOT + "/sessions/{session_id}/actions/{action_id}/confirmations", operation_id="confirm_action")
    def confirm_action(session_id: UUID, action_id: UUID, request: Request):
        state = service.get(str(session_id))
        with state.lock:
            result = service.finish_action(state, str(action_id), True, revision(request))
            return respond(result, etag=state.revision)

    @app.post(API_ROOT + "/sessions/{session_id}/actions/{action_id}/cancellations", operation_id="cancel_action")
    def cancel_action(session_id: UUID, action_id: UUID, request: Request):
        state = service.get(str(session_id))
        with state.lock:
            result = service.finish_action(state, str(action_id), False, revision(request))
            return respond(result, etag=state.revision)

    @app.put(API_ROOT + "/sessions/{session_id}/position", operation_id="put_position")
    def put_position(session_id: UUID, body: PositionFix):
        values = body.model_dump()
        values["measured_at"] = datetime.fromisoformat(values["measured_at"].replace("Z", "+00:00"))
        if values["measured_at"].tzinfo is None:
            values["measured_at"] = values["measured_at"].replace(tzinfo=timezone.utc)
        values["measured_at"] = values["measured_at"].astimezone(timezone.utc)
        if values["measured_at"] > service.clock() + timedelta(seconds=2):
            raise ApiError("20001_validation_failed", [{"field": "measured_at", "code": "invalid"}])
        return service.put_position(str(session_id), values)

    @app.get(API_ROOT + "/sessions/{session_id}/guidance", operation_id="get_guidance")
    def get_guidance(session_id: UUID, after: int = Query(0, ge=0), wait_s: float = Query(0, ge=0, le=25)):
        return service.get_guidance(str(session_id), after, wait_s)

    @app.put(API_ROOT + "/sessions/{session_id}/guidance", operation_id="put_guidance")
    def put_guidance(session_id: UUID, body: GuidanceStart):
        return service.put_guidance(str(session_id), str(body.route_id))

    @app.delete(API_ROOT + "/sessions/{session_id}/guidance", operation_id="delete_guidance")
    def delete_guidance(session_id: UUID):
        service.delete_guidance(str(session_id))
        return Response(status_code=204)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Building Guide HTTP v1 contract (one worker).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("agent_output/api"))
    parser.add_argument("--notes-db", type=Path, default=Path("agent_output/room_notes.sqlite3"))
    parser.add_argument("--rate-limit", type=int, default=0, help="requests per IP per minute; 0 disables the app limit")
    parser.add_argument("--model-timeout", type=float, default=60)
    args = parser.parse_args()
    if args.rate_limit < 0 or args.model_timeout <= 0:
        parser.error("--rate-limit must be non-negative and --model-timeout must be positive")
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(args.data, args.output, notes_database=args.notes_db, rate_limit=args.rate_limit,
                           model_timeout=args.model_timeout), host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
