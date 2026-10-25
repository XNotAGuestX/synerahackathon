"""Entry-point checks for the hull without Claude: a scripted stand-in drives the real agent loop and tools."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import anthropic

from final_agent.agent import MISSING_CREDENTIALS_MESSAGE, BuildingAgent, MissingCredentialsError
from final_agent.benchmark import answer
from final_agent.building_map import BuildingMap, MapError
from final_agent.tools import ArgumentCheckedTool, make_tools
from anthropic.lib.tools import ToolError
from anthropic.lib.tools._beta_runner import BetaToolRunner


ROOT = Path(__file__).resolve().parents[1]
BUILDING = ROOT / "data" / "dev" / "proc-factory-dev-003"
P = "proc-factory-dev-003-"
CREDENTIAL_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
# Even if a stored `ant` profile still resolves credentials, no request can reach a paid endpoint.
UNREACHABLE_API = "http://127.0.0.1:9"


def without_credentials() -> dict:
    environment = {name: value for name, value in os.environ.items() if name not in CREDENTIAL_VARIABLES}
    return {**environment, "ANTHROPIC_BASE_URL": UNREACHABLE_API}


def credentials_resolve() -> bool:
    """Whether the SDK still finds credentials (e.g. an `ant auth login` profile) without the variables."""
    with patch.dict(os.environ, without_credentials(), clear=True):
        client = anthropic.Anthropic()
    return any(getattr(client, name, None) for name in ("api_key", "auth_token", "credentials", "_token_cache"))


def call(name: str, **arguments) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=f"toolu_{name}", name=name, input=arguments)


def say(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def reply(*blocks: SimpleNamespace) -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=10, output_tokens=5, cache_read_input_tokens=None, cache_creation_input_tokens=2
    )
    stop = "tool_use" if any(block.type == "tool_use" for block in blocks) else "end_turn"
    return SimpleNamespace(content=list(blocks), usage=usage, stop_reason=stop)


class ScriptedRunner:
    """Replays assistant messages and answers tool calls with the real tools, like the SDK's tool runner."""

    def __init__(self, script: list, tools: list, results: list) -> None:
        self.script = script
        self.tools = {tool.name: tool for tool in tools}
        self.results = results
        self.current = None

    def __iter__(self):
        for message in self.script:
            self.current = message
            yield message

    def generate_tool_call_response(self) -> dict | None:
        blocks = []
        for block in self.current.content:
            if block.type != "tool_use":
                continue
            try:
                content, is_error = self.tools[block.name].call(block.input), False
            except ToolError as error:
                content, is_error = str(error), True
            self.results.append((block.name, is_error, content))
            blocks.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error}
            )
        return {"role": "user", "content": blocks} if blocks else None


class ScriptedClient:
    """Stands in for anthropic.Anthropic: each tool_runner() call replays the next scripted turn."""

    def __init__(self, turns: list[list], parsed: list | None = None) -> None:
        self.turns = list(turns)
        self.parsed = list(parsed or [])  # scripted parse() outputs; an Exception instance is raised
        self.parse_requests: list[dict] = []
        self.results: list[tuple[str, bool, str]] = []
        self.history_lengths: list[int] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(tool_runner=self.tool_runner, parse=self.parse))

    def parse(self, **request) -> SimpleNamespace:
        """A scripted structuring request: the next queued output, else no schema-valid reply."""
        self.parse_requests.append(request)
        if self.parsed:
            output = self.parsed.pop(0)
            if isinstance(output, Exception):
                raise output
            return SimpleNamespace(parsed_output=output, stop_reason="end_turn", usage=reply().usage)
        return SimpleNamespace(parsed_output=None, stop_reason="end_turn", usage=reply().usage)

    def tool_runner(self, **request) -> ScriptedRunner:
        self.history_lengths.append(len(request["messages"]))
        return ScriptedRunner(self.turns.pop(0), request["tools"], self.results)


class ScriptedConversationTests(unittest.TestCase):
    def test_multi_turn_conversation_runs_real_tools_and_keeps_history(self):
        turns = [
            [
                reply(call("search_building", query="coordinate measuring machine")),
                reply(call("show_location", element=P + "A00117")),
                reply(say("The coordinate measuring machine is in Quality lab 0.21 on the ground floor.")),
            ],
            [
                reply(call("find_route", start=P + "F0-S023", destination=P + "F1-S008", step_free=True)),
                reply(call("show_route")),
                reply(say("Step-free route: 118.4 m via the lift.")),
            ],
            [
                reply(call("set_closed", element=P + "V02", closed=True)),
                reply(call("find_route", start=P + "F0-S023", destination=P + "F1-S008")),
                reply(say("With the lift closed the stairs route is 115.89 m.")),
            ],
            [
                reply(call("find_route", start=P + "F0-S023", destination=P + "F1-S008", step_free=True)),
                reply(say("No step-free route exists while the lift is closed.")),
            ],
            [
                reply(call("find_largest_room", room_type="office", floor_level=0)),
                reply(say("Office 0.30, 29.55 m2.\nAnswer: Office 0.30, 29.55")),
            ],
        ]
        client = ScriptedClient(turns)
        source_bytes = (BUILDING / "building.json").read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            agent = BuildingAgent(BuildingMap.load(BUILDING), output, client)
            replies = [
                agent.ask(text)
                for text in (
                    "Where is the coordinate measuring machine?",
                    "Step-free from Office 0.23 to Kitchen 1.08?",
                    "The office lift is closed; can I still get there?",
                    "And step-free?",
                    "Which office on the ground floor is largest?",
                )
            ]

            self.assertTrue(all(replies))
            self.assertIn("Quality lab 0.21", replies[0])
            self.assertTrue(replies[-1].endswith("Answer: Office 0.30, 29.55"))

            roles = [message["role"] for message in agent.messages]
            self.assertEqual(roles[0], "user")
            self.assertEqual(roles[-1], "assistant")
            self.assertTrue(all(first != second for first, second in zip(roles, roles[1:])))
            self.assertEqual(client.history_lengths, [1, 7, 13, 19, 23])

            self.assertEqual(agent.usage["input_tokens"], 10 * 13)
            self.assertEqual(agent.usage["output_tokens"], 5 * 13)
            self.assertEqual(agent.usage["cache_read_input_tokens"], 0)
            self.assertEqual(agent.usage["cache_creation_input_tokens"], 2 * 13)

            errors = [name for name, is_error, _ in client.results if is_error]
            self.assertEqual(errors, ["find_route"])
            unreachable = client.results[-2][2]
            self.assertIn("No route", unreachable)
            self.assertEqual(agent.map.closed, {P + "V02"})
            self.assertIn("active_route_error", client.results[4][2])

            self.assertTrue((output / "location_0.png").is_file())
            self.assertTrue((output / "route_0.png").is_file())
            self.assertTrue((output / "route_1.png").is_file())
            edited = BuildingMap.load(output / "building_edited.json")
            self.assertEqual(edited.closed, {P + "V02"})
        self.assertEqual((BUILDING / "building.json").read_bytes(), source_bytes)


class MissingCredentialsTests(unittest.TestCase):
    @unittest.skipIf(credentials_resolve(), "Anthropic credentials are configured on this machine")
    def test_sdk_authentication_type_error_becomes_missing_credentials_error(self):
        with patch.dict(os.environ, without_credentials(), clear=True):
            with tempfile.TemporaryDirectory() as temporary:
                agent = BuildingAgent(BuildingMap.load(BUILDING), Path(temporary), anthropic.Anthropic())
                with self.assertRaises(MissingCredentialsError) as caught:
                    agent.ask("where is the printer?")
        self.assertEqual(str(caught.exception), MISSING_CREDENTIALS_MESSAGE)
        self.assertEqual(agent.messages, [])

    def test_unrelated_type_error_is_not_swallowed(self):
        def broken_runner(**request):
            raise TypeError("a real bug")

        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(tool_runner=broken_runner)))
        with tempfile.TemporaryDirectory() as temporary:
            agent = BuildingAgent(BuildingMap.load(BUILDING), Path(temporary), client)
            with self.assertRaisesRegex(TypeError, "a real bug"):
                agent.ask("hello")

    @unittest.skipIf(credentials_resolve(), "Anthropic credentials are configured on this machine")
    def test_benchmark_answer_stops_the_run_without_credentials(self):
        # The committed run library would load the embedding model before the missing credentials surface.
        with patch.dict(os.environ, without_credentials(), clear=True), patch(
            "final_agent.benchmark.run_index", return_value=None
        ):
            with self.assertRaises(SystemExit) as caught:
                answer(BUILDING, "Where is the printer?")
        self.assertEqual(str(caught.exception), MISSING_CREDENTIALS_MESSAGE)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, building: Path, stdin: str = "") -> subprocess.CompletedProcess:
        env = {**without_credentials(), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
        return subprocess.run(
            [sys.executable, "-m", "final_agent", str(building)], cwd=ROOT, env=env, input=stdin,
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )

    def test_missing_building_prints_one_message_and_fails(self):
        result = self.run_cli(BUILDING.parent / "does-not-exist")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot load building", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_malformed_building_prints_one_message_and_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / "building.json").write_text("{not json", encoding="utf-8")
            result = self.run_cli(Path(temporary))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot load building", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    @unittest.skipIf(credentials_resolve(), "Anthropic credentials are configured on this machine")
    def test_chat_without_credentials_ends_with_clear_message(self):
        result = self.run_cli(BUILDING, "where is the printer?\nexit\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(MISSING_CREDENTIALS_MESSAGE, result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class BadToolArgumentTests(unittest.TestCase):
    """Bad model-sent arguments become readable is_error results, not logged tracebacks."""

    @classmethod
    def setUpClass(cls):
        cls.building = BuildingMap.load(BUILDING)
        cls.tools = {tool.name: tool for tool in make_tools(cls.building, Path(tempfile.gettempdir()))}

    def error_text(self, name: str, tool_input: object) -> str:
        with self.assertRaises(ToolError) as caught:
            self.tools[name].call(tool_input)
        return str(caught.exception)

    def test_bad_arguments_name_the_argument_and_reason(self):
        self.assertEqual(
            self.error_text("find_largest_room", {"room_type": "office", "floor_level": 5.5}),
            "Invalid arguments for find_largest_room: floor_level: Input should be a valid integer, "
            "got a number with a fractional part.",
        )
        self.assertIn("floor_level: Input should be a valid integer", self.error_text("find_largest_room", {"room_type": "office", "floor_level": "high"}))
        self.assertEqual(
            self.error_text("straight_line_distance_3d", {}),
            "Invalid arguments for straight_line_distance_3d: first: Missing required argument; "
            "second: Missing required argument.",
        )
        self.assertEqual(
            self.error_text("straight_line_distance_3d", ["a", "b"]),
            "Invalid arguments for straight_line_distance_3d: expected a JSON object of named arguments, got list.",
        )

    def test_other_exceptions_propagate_unchanged(self):
        def broken(item: str) -> str:
            """Broken tool."""
            raise ValueError("our own bug") if item == "value" else KeyError(item)

        tool = ArgumentCheckedTool(broken)
        with self.assertRaisesRegex(ValueError, "our own bug"):
            tool.call({"item": "value"})
        with self.assertRaises(KeyError):
            tool.call({"item": "key"})

    def test_schemas_unchanged_by_the_wrapper(self):
        self.assertEqual(len(self.tools), 25)
        for tool in self.tools.values():
            plain = anthropic.beta_tool(tool.func).to_dict()
            self.assertEqual(tool.to_dict(), plain)

    def test_sdk_runner_returns_error_result_without_logging(self):
        runner = BetaToolRunner.__new__(BetaToolRunner)
        tool_use = call("find_largest_room", room_type="office", floor_level=5.5)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertNoLogs("anthropic"):
            result = runner._run_tool(self.tools["find_largest_room"], tool_use)
        self.assertTrue(result["is_error"])
        self.assertIn("Invalid arguments for find_largest_room: floor_level:", str(result["content"]))
        self.assertEqual(stderr.getvalue(), "")

    def test_blank_place_reference_gets_direct_message(self):
        for blank in ("", "   "):
            with self.assertRaisesRegex(MapError, "Give a place"):
                self.building.resolve_space(blank)


if __name__ == "__main__":
    unittest.main()
