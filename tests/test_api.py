"""HTTP contract and state transitions against the supplied OpenAPI, without paid calls."""

import copy
import csv
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import anthropic
import httpx2
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from final_agent.api import create_app, load_contract
from final_agent.agent import BuildingAgent, MODELS
from final_agent.api_session import ApiReply
from final_agent.building_map import BuildingMap
from final_agent.storage import RoomNoteStore
from test_hull import ScriptedClient, ScriptedRunner, call, reply, say
from test_storage import example_building


def api_building() -> dict:
    data = example_building()
    data["building"].update(source="test", split="dev", license="CC0-1.0", attribution="Test fixture")
    for floor in data["floors"]:
        floor["height_m"] = 3.0
    for index, space in enumerate(data["spaces"]):
        space.update(type="room", ref=f"00{index}", synthetic=False)
    for asset in data["assets"]:
        asset.update(category="equipment", source="test", footprint={"width_m": 1, "depth_m": 1, "rotation_deg": 0})
    data["vertical_connectors"] = [{
        "id": "lift", "name": "Test lift", "kind": "lift", "floor_ids": ["F0", "F1"],
        "space_ids": ["left", "upstairs"], "step_free": True, "synthetic": False,
    }]
    return data


def answer(text="Done.", intent="unknown", **values):
    return say(json.dumps({"text": text, "intent": intent, "summary": text,
                           "missing": [], "question": None, "options": [], **values}))


class ApiTests(unittest.TestCase):
    def test_structured_reply_keeps_selected_model_fallback_policy_and_timeout(self):
        class RecordingClient(ScriptedClient):
            def __init__(self):
                super().__init__([[reply(say("Done."))]])
                self.requests = []

            def tool_runner(self, **request):
                self.requests.append(request)
                return super().tool_runner(**request)

            def parse(self, **request):
                self.requests.append(request)
                return SimpleNamespace(parsed_output=ApiReply.model_validate_json(answer().text), usage=reply().usage)

        for name, model in MODELS.items():
            with self.subTest(model=name):
                client = RecordingClient()
                agent = BuildingAgent(BuildingMap(api_building()), self.root, client=client, model=model,
                                      response_format=ApiReply, request_timeout=3)
                self.assertEqual(json.loads(agent.ask("Hello."))["text"], "Done.")
                self.assertEqual(len(client.requests), 2)
                for request in client.requests:
                    self.assertEqual(request["model"], model)
                    self.assertEqual(request["timeout"], 3)
                    self.assertEqual(request.get("fallbacks"), None if name == "haiku" else "default")
                self.assertEqual(client.requests[1]["tool_choice"], {"type": "none"})

    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "data"
        source = self.data / "dev" / "test" / "building.json"
        source.parent.mkdir(parents=True)
        source.write_text(json.dumps(api_building()))
        self.original = source.read_bytes()
        row = {
            "building_id": "test", "name": "Test building", "source": "test", "split": "dev", "license": "CC0-1.0",
            "floors": 2, "levels": "0;1", "spaces": 3, "assets": 2, "has_stairs": "False", "has_lift": "True",
            "has_step_free_entrance": "False", "path": "dev/test",
        }
        with (self.data / "manifest.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        self.now = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
        self.model = ScriptedClient([])
        self.app = self.make_app()
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.base = "/api/v1"

    def make_app(self, **options):
        return create_app(self.data, self.root / "output", notes_database=self.root / "notes.sqlite3",
                          client_factory=lambda: self.model, clock=lambda: self.now, api_token="", **options)

    def validate(self, response, schema):
        self.assertEqual(response.headers["X-API-Version"], "1")
        self.assertEqual(response.headers["X-Schema-Version"], "1")
        self.assertTrue(response.headers["X-Request-Id"])
        validator = Draft202012Validator({"$ref": f"#/components/schemas/{schema}", "components": self.contract["components"]}, format_checker=FormatChecker())
        validator.validate(response.json())
        return response.json()

    def post(self, path, body=None, *, key=None, headers=None, status=201, schema=None):
        response = self.client.post(path, **({"json": body} if body is not None else {}),
                                    headers={"Idempotency-Key": key or str(uuid4()), **(headers or {})})
        self.assertEqual(response.status_code, status, response.text)
        if schema:
            self.validate(response, schema)
        return response

    def session(self, **values):
        return self.post(self.base + "/sessions", {"building_id": "test", **values}, schema="Session").json()

    def path(self, session):
        return self.base + "/sessions/" + session["id"]

    def proposal(self, session, **values):
        return self.post(self.path(session) + "/actions", {"kind": "add_door", "first_space": "left", "second_space": "right", **values}, schema="Action").json()

    def test_health_buildings_detail_plans_and_search_match_contract(self):
        defined = {operation["operationId"] for methods in self.contract["paths"].values() for operation in methods.values()}
        implemented = {getattr(route, "operation_id", None) for route in self.app.routes}
        self.assertEqual(len(defined), 18)
        self.assertTrue(defined <= implemented)
        health = self.client.get(self.base + "/health", headers={"X-Request-Id": "from-frontend"})
        self.validate(health, "Health")
        self.assertEqual(health.headers["X-Request-Id"], "from-frontend")
        self.validate(self.client.get(self.base + "/buildings?split=dev&limit=1"), "BuildingPage")
        self.validate(self.client.get(self.base + "/buildings/test"), "BuildingDetail")
        session = self.session()
        path = self.path(session)
        self.validate(self.client.get(path), "Session")
        self.validate(self.client.get(path + "/floors"), "FloorIndex")
        plan = self.validate(self.client.get(path + "/floors/F0/plan?include=spaces,connectors"), "FloorPlan")
        self.assertEqual(plan["included"], ["spaces", "connectors"])
        self.assertEqual(plan["assets"], [])
        self.assertEqual(plan["openings"], [])
        self.assertEqual(plan["connectors"][0]["space_ids"], ["left", "upstairs"])
        empty_plan = self.validate(self.client.get(path + "/floors/F0/plan?include="), "FloorPlan")
        self.assertEqual(empty_plan["included"], [])
        self.assertTrue(all(empty_plan[name] == [] for name in ("spaces", "openings", "assets", "connectors")))
        places = self.validate(self.client.get(path + "/places?q=office&kind=space&limit=1"), "PlacePage")
        self.assertTrue(places["has_more"])
        second = self.client.get(path + "/places", params={"q": "office", "kind": "space", "limit": 1, "cursor": places["next_cursor"]})
        self.validate(second, "PlacePage")
        self.assertNotEqual(second.json()["items"][0]["id"], places["items"][0]["id"])
        empty = self.client.get(path + "/places?q=nonexistent")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["items"], [])

    def test_measured_asset_height_survives_floor_plan_projection(self):
        source = self.data / "dev/test/building.json"
        building = json.loads(source.read_text())
        building["assets"][0]["height_m"] = 0.42
        source.write_text(json.dumps(building))
        session = self.session()
        plan = self.validate(self.client.get(self.path(session) + "/floors/F0/plan?include=assets"), "FloorPlan")
        self.assertEqual(plan["assets"][0]["height_m"], 0.42)

    def test_route_unreachable_then_door_confirmation_and_reload(self):
        session = self.session()
        path = self.path(session)
        no_route = self.post(path + "/routes", {"start": "left", "destination": "right"}, schema="Route").json()
        self.assertFalse(no_route["reachable"])
        self.assertIsNone(no_route["length_m"])
        self.assertEqual(no_route["legs"], [])
        action = self.proposal(session)
        self.assertEqual(action["status"], "pending")
        self.assertEqual(self.client.get(path + "/floors/F0/plan").json()["openings"], [])
        self.validate(self.client.get(path + "/actions/" + action["id"]), "Action")
        confirmed = self.post(path + "/actions/" + action["id"] + "/confirmations", status=200, schema="Action").json()
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(self.client.get(path).json()["last_route_id"], None)
        plan = self.validate(self.client.get(path + "/floors/F0/plan"), "FloorPlan")
        self.assertEqual(plan["openings"], [confirmed["result"]["opening"]])
        route = self.post(path + "/routes", {"start": "000", "destination": "001"}, schema="Route").json()
        self.assertTrue(route["reachable"])
        self.assertEqual(route["space_path"], ["left", "right"])
        self.assertTrue(route["legs"])
        self.assertEqual(self.client.get(path).json()["last_route_id"], route["id"])
        self.assertEqual(self.validate(self.client.get(path + "/routes/" + no_route["id"]), "Route"), no_route)

    def test_preferences_defaults_multifloor_and_stable_route_snapshots(self):
        session = self.session(preferences={"step_free": True})
        path = self.path(session)
        route = self.post(path + "/routes", {"start": "printer", "destination": "upstairs"}, schema="Route").json()
        self.assertEqual(route["length_m"], 18)
        self.assertTrue(route["step_free"])
        response = self.client.put(path + "/preferences", json={"step_free": False})
        self.validate(response, "Session")
        repeat = self.client.put(path + "/preferences", json={"step_free": False})
        self.assertEqual(response.json()["revision"], repeat.json()["revision"])
        explicit = self.post(path + "/routes", {"start": "left", "destination": "upstairs", "step_free": True}).json()
        self.assertTrue(explicit["step_free"])
        self.assertEqual(self.client.get(path + "/routes/" + route["id"]).json(), route)

    def test_session_isolation_closures_and_source_preservation(self):
        first, other = self.session(), self.session()
        path = self.path(first)
        action = self.post(path + "/actions", {"kind": "set_closed", "element_ref": "lift", "closed": True}, schema="Action").json()
        self.assertEqual(self.client.get(path).json()["closed_ids"], [])
        self.post(path + "/actions/" + action["id"] + "/confirmations", status=200, schema="Action")
        self.assertEqual(self.client.get(path).json()["closed_ids"], ["lift"])
        self.assertEqual(self.client.get(self.path(other)).json()["closed_ids"], [])
        self.assertEqual((self.data / "dev/test/building.json").read_bytes(), self.original)
        self.assertEqual(self.client.get(path + "/floors/F0/plan").json()["closed_ids"], ["lift"])

    def test_actions_conflicts_expiration_cancellation_and_existing_door(self):
        session = self.session()
        path = self.path(session)
        first = self.proposal(session)
        conflict = self.post(path + "/actions", first["proposal"], status=409, schema="Error")
        self.assertEqual(conflict.json()["code"], "30010_action_conflict")
        url = path + "/actions/" + first["id"]
        cancelled = self.post(url + "/cancellations", status=200, schema="Action").json()
        self.assertEqual(cancelled, self.post(url + "/cancellations", status=200).json())
        self.assertEqual(self.post(url + "/confirmations", status=409).json()["code"], "30010_action_conflict")
        action = self.proposal(session)
        self.now += timedelta(minutes=15)
        self.assertEqual(self.post(path + "/actions/" + action["id"] + "/confirmations", status=409).json()["code"], "30009_action_expired")
        self.assertEqual(self.client.get(path + "/actions/" + action["id"]).json()["status"], "expired")
        self.assertIsNone(self.client.get(path).json()["pending_action_id"])
        action = self.proposal(session)
        url = path + "/actions/" + action["id"] + "/confirmations"
        result = self.post(url, key="confirmed-once", status=200).json()
        self.assertEqual(result, self.post(url, key="confirmed-once", headers={"If-Match": '"1"'}, status=200).json())
        self.assertEqual(result, self.post(url, status=200).json())
        next_action = self.proposal(session)
        existing = self.post(path + "/actions/" + next_action["id"] + "/confirmations", status=200).json()
        self.assertEqual(existing["result"]["opening"]["id"], result["result"]["opening"]["id"])
        self.assertEqual(len(self.client.get(path + "/floors/F0/plan").json()["openings"]), 1)

    def test_missing_and_ambiguous_references_have_stable_errors(self):
        session = self.session()
        path = self.path(session)
        self.post(path + "/actions", {"kind": "add_door", "first_space": "left", "second_space": "upstairs"}, status=409, schema="Error")
        self.assertIsNone(self.client.get(path).json()["pending_action_id"])
        self.post(path + "/routes", {"start": "missing", "destination": "right"}, status=404, schema="Error")
        state = self.app.state.service.get(session["id"])
        state.map.spaces["left"]["name"] = state.map.spaces["right"]["name"] = "Duplicated"
        ambiguous = self.post(path + "/routes", {"start": "Duplicated", "destination": "upstairs"}, status=409, schema="Error").json()
        self.assertEqual(ambiguous["code"], "30005_place_ambiguous")
        self.assertEqual({item["message"] for item in ambiguous["details"]}, {"left", "right"})
        self.assertEqual(state.routes, {})
        self.assertEqual(self.client.get(path + "/floors/missing/plan").status_code, 404)
        self.assertEqual(self.client.get(path + "/actions/" + str(uuid4())).status_code, 404)

    def test_idempotence_cached_errors_mismatch_revisions_and_ttl(self):
        url = self.base + "/sessions"
        first = self.post(url, {"building_id": "test"}, key="same-key")
        repeated = self.post(url, {"building_id": "test"}, key="same-key")
        self.assertEqual(first.json(), repeated.json())
        self.assertEqual(first.headers["Location"], repeated.headers["Location"])
        self.post(url, {"building_id": "missing"}, key="same-key", status=409, schema="Error")
        self.assertEqual(first.json(), self.post(url, {"building_id": "test"}, key="same-key").json())
        invalid = self.post(url, {"building_id": "missing"}, key="cached-404", status=404, schema="Error")
        again = self.post(url, {"building_id": "missing"}, key="cached-404", status=404, schema="Error")
        self.assertEqual(invalid.json()["code"], again.json()["code"])
        self.assertEqual(again.json()["trace_id"], again.headers["X-Request-Id"])
        path = self.path(first.json())
        self.post(path + "/routes", {"start": "left", "destination": "upstairs"}, key="retry-revision", headers={"If-Match": '"999"'}, status=409)
        self.post(path + "/routes", {"start": "left", "destination": "upstairs"}, key="retry-revision", headers={"If-Match": '"1"'})
        self.now += timedelta(hours=24)
        fresh = self.post(url, {"building_id": "test"}, key="same-key")
        self.assertNotEqual(fresh.json()["id"], first.json()["id"])

    def test_auth_cors_validation_limits_and_repeated_delete(self):
        protected = create_app(self.data, self.root / "auth", api_token="example-token", cors_origins=["http://localhost:5173"])
        with TestClient(protected) as client:
            self.assertEqual(client.get(self.base + "/health").status_code, 200)
            unauth = client.get(self.base + "/buildings", headers={"Origin": "http://localhost:5173"})
            self.validate(unauth, "Error")
            self.assertEqual(unauth.status_code, 401)
            self.assertEqual(unauth.headers["Access-Control-Allow-Origin"], "http://localhost:5173")
            self.assertEqual(client.get(self.base + "/buildings", headers={"Authorization": "Bearer example-token"}).status_code, 200)
            preflight = client.options(self.base + "/sessions", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "idempotency-key,authorization,if-match"})
            self.assertEqual(preflight.status_code, 200)
            self.assertEqual(preflight.headers["X-API-Version"], "1")
        missing_key = self.client.post(self.base + "/sessions", json={"building_id": "test"})
        self.assertEqual(missing_key.json()["code"], "20010_idempotency_key_required")
        invalid = self.post(self.base + "/sessions", {"building_id": "test", "unknown": True}, status=400, schema="Error")
        self.assertEqual(invalid.json()["details"][0]["code"], "unknown_field")
        self.assertEqual(self.client.get(self.base + "/buildings?unknown=yes").status_code, 400)
        too_large = self.client.post(self.base + "/sessions", content=b" " * 65537, headers={"Idempotency-Key": "large"})
        self.assertEqual(too_large.status_code, 413)
        self.validate(too_large, "Error")
        session = self.session()
        path = self.path(session)
        self.assertEqual(self.client.delete(path).status_code, 204)
        self.assertEqual(self.client.delete(path).status_code, 204)
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_chat_uses_real_tools_json_effects_and_turn_preference(self):
        self.model.turns = [
            [reply(call("show_location", element="printer")), reply(answer("Printer is in Left.", "locate"))],
            [reply(call("find_route", start="left", destination="upstairs")), reply(answer("Take the lift.", "route"))],
            [reply(answer("Where are you starting?", "clarify", missing=["start"], question="Where are you starting?", options=[{"id": "left", "label": "Left", "place_id": "left"}]))],
        ]
        session = self.session()
        path = self.path(session)
        locate = self.post(path + "/messages", {"text": "Where is the printer?"}, schema="MessageAccepted").json()
        self.assertEqual(locate["session"]["revision"], 1)
        self.assertIn("highlight_assets", [effect["type"] for effect in locate["guide_message"]["effects"]])
        self.assertEqual(locate["guide_message"]["understood"]["resolved"]["asset_ids"], ["printer"])
        routed = self.post(path + "/messages", {"text": "Take me upstairs.", "input_mode": "transcript", "client_context": {"preferences": {"step_free": True}}}, schema="MessageAccepted").json()
        self.assertTrue(routed["routes"][0]["step_free"])
        self.assertFalse(routed["session"]["preferences"]["step_free"])
        self.assertEqual(routed["guide_message"]["effects"][-1]["route_id"], routed["routes"][0]["id"])
        clarification = self.post(path + "/messages", {"text": "Take me there."}, schema="MessageAccepted").json()
        self.assertEqual(clarification["guide_message"]["understood"]["intent"], "clarify")
        self.assertEqual(clarification["guide_message"]["effects"][0]["type"], "ask")
        messages = self.validate(self.client.get(path + "/messages?limit=2"), "MessagePage")
        self.assertEqual([message["role"] for message in messages["items"]], ["user", "guide"])
        self.assertTrue(messages["has_more"])
        next_page = self.client.get(path + "/messages", params={"limit": 2, "cursor": messages["next_cursor"]})
        self.assertEqual(next_page.json()["items"][0]["text"], "Take me upstairs.")
        self.assertEqual(list((self.root / "output").rglob("*.png")), [])

    def test_chat_proposes_before_edit_and_preserves_persistent_reports(self):
        self.model.turns = [
            [reply(call("set_closed", element="lift", closed=True)), reply(answer("Please confirm the lift closure.", "close"))],
            [reply(call("add_room_note", space="left", text="Wet floor.", category="safety")), reply(answer("Report saved."))],
            [reply(call("get_room_notes", spaces=["left"])), reply(answer("A wet floor was reported."))],
        ]
        first = self.session()
        path = self.path(first)
        result = self.post(path + "/messages", {"text": "Close the lift."}, schema="MessageAccepted").json()
        self.assertEqual(result["session"]["closed_ids"], [])
        self.assertEqual(result["pending_action"]["status"], "pending")
        self.post(path + "/messages", {"text": "The floor in Left is wet."}, schema="MessageAccepted")
        self.assertEqual(len(RoomNoteStore(self.root / "notes.sqlite3").active("test", ["left"])), 1)
        second = self.session()
        self.post(self.path(second) + "/messages", {"text": "Any reports for Left?"}, schema="MessageAccepted")
        report_results = [json.loads(result) for name, error, result in self.model.results if name == "get_room_notes" and not error]
        self.assertEqual(report_results[0]["room_notes"][0]["notes"][0]["text"], "Wet floor.")

    def test_model_errors_leave_no_actions_or_dialog_and_can_retry_key(self):
        session = self.session()
        path = self.path(session)
        self.model.turns = [[reply(call("add_room_note", space="left", text="Saved before failure.", category="safety"), call("set_closed", element="lift", closed=True)), reply(say("not valid structured JSON"))]]
        response = self.post(path + "/messages", {"text": "Remember a problem and close the lift."}, key="retry-model", status=503, schema="Error")
        self.assertEqual(response.json()["code"], "40001_model_unavailable")
        self.assertIsNone(self.client.get(path).json()["pending_action_id"])
        self.assertEqual(self.client.get(path).json()["closed_ids"], [])
        self.assertEqual(self.client.get(path + "/messages").json()["items"], [])
        # Reports commit per tool call; only session state and map edits are discarded.
        self.assertEqual(len(RoomNoteStore(self.root / "notes.sqlite3").active("test", ["left"])), 1)
        self.model.turns = [[reply(answer("Done."))]]
        self.post(path + "/messages", {"text": "Remember a problem and close the lift."}, key="retry-model", schema="MessageAccepted")

    def test_model_timeout_and_rate_limit_have_contract_errors(self):
        session = self.session()
        service = self.app.state.service
        request = httpx2.Request("POST", "https://example.invalid/messages")
        errors = [
            (anthropic.APITimeoutError(request=request), 504, "40003_model_timeout"),
            (anthropic.RateLimitError("limited", response=httpx2.Response(429, request=request), body=None), 429, "40002_model_rate_limited"),
        ]
        for error, status, code in errors:
            def unavailable(error=error):
                raise error
            service.client_factory = unavailable
            response = self.post(self.path(session) + "/messages", {"text": "Hello"}, key="retry-all-errors", status=status, schema="Error")
            self.assertEqual(response.json()["code"], code)
        self.assertEqual(self.client.get(self.path(session) + "/messages").json()["items"], [])
        self.assertEqual(self.client.get(self.path(session) + "/floors").status_code, 200)

    def test_actual_sdk_runner_structures_reply_after_tool_loop_with_deferred_edit_tools(self):
        requests = []

        def transport(request):
            requests.append(json.loads(request.content))
            blocks = [[{"type": "tool_use", "id": "toolu_close", "name": "set_closed", "input": {"element": "lift", "closed": True}}],
                      [{"type": "text", "text": "Please confirm the closure."}],
                      [{"type": "text", "text": answer("Please confirm the closure.", "close").text}]][len(requests) - 1]
            return httpx2.Response(200, json={
                "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
                "content": blocks, "stop_reason": "tool_use" if len(requests) == 1 else "end_turn",
                "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5},
            })

        self.app.state.service.client_factory = lambda: anthropic.Anthropic(
            api_key="test-only", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(transport)),
        )
        session = self.session()
        result = self.post(self.path(session) + "/messages", {"text": "Close the lift."}, schema="MessageAccepted").json()
        # Tool use runs without the response format; one tool-free request then structures the reply.
        self.assertEqual(len(requests), 3)
        self.assertNotIn("format", requests[0]["output_config"])
        self.assertEqual(requests[2]["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(requests[2]["tool_choice"], {"type": "none"})
        spec = next(tool for tool in requests[0]["tools"] if tool["name"] == "set_closed")
        self.assertIn("PROPOSE", spec["description"].upper())
        self.assertEqual(result["pending_action"]["proposal"]["element_ref"], "lift")
        self.assertEqual(result["session"]["closed_ids"], [])

    def test_concurrent_identical_post_creates_one_session(self):
        def create(_):
            return self.client.post(self.base + "/sessions", json={"building_id": "test"}, headers={"Idempotency-Key": "concurrent-key"})
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(create, range(4)))
        self.assertEqual({response.status_code for response in responses}, {201})
        self.assertEqual(len({response.json()["id"] for response in responses}), 1)
        self.assertEqual(len(self.app.state.service.sessions), 1)

    def test_dev_fixtures_are_reproducible_and_validate_against_contract(self):
        from scripts.generate_api_fixtures import generate
        from scripts.validate_api_fixtures import validate

        data = Path(__file__).resolve().parents[1] / "data"
        first, second = self.root / "fixtures1", self.root / "fixtures2"
        entries = generate(data, first)
        generate(data, second)
        self.assertEqual(validate(first), len(entries))
        self.assertEqual({path.name: path.read_bytes() for path in first.iterdir()},
                         {path.name: path.read_bytes() for path in second.iterdir()})

    def test_model_does_not_block_reads_and_cannot_overwrite_concurrent_route(self):
        entered, release = threading.Event(), threading.Event()

        class BlockingRunner(ScriptedRunner):
            def __iter__(self):
                for index, message in enumerate(super().__iter__()):
                    if index == 1:
                        entered.set()
                        if not release.wait(5):
                            raise TimeoutError("Test release was not signalled")
                    yield message

        class BlockingClient(ScriptedClient):
            def tool_runner(self, **kwargs):
                return BlockingRunner(self.turns.pop(0), kwargs["tools"], self.results)

        model = BlockingClient([[reply(call("add_room_note", space="left", text="Saved before failure.", category="safety"), call("set_closed", element="lift", closed=True)), reply(answer("Please confirm.", "close"))]])
        self.app.state.service.client_factory = lambda: model
        session = self.session()
        path = self.path(session)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: self.client.post(path + "/messages", json={"text": "Close the lift and remember the floor."}, headers={"Idempotency-Key": "slow-model"}))
            self.assertTrue(entered.wait(5))
            try:
                self.assertEqual(self.client.get(path + "/floors").status_code, 200)
                self.post(path + "/routes", {"start": "left", "destination": "upstairs"})
            finally:
                release.set()
            response = future.result(timeout=5)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], "30012_revision_conflict")
        self.assertIsNone(self.client.get(path).json()["pending_action_id"])
        # Reports commit per tool call; only session state and map edits are discarded.
        self.assertEqual(len(RoomNoteStore(self.root / "notes.sqlite3").active("test", ["left"])), 1)


if __name__ == "__main__":
    unittest.main()
