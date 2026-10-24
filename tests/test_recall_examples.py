"""recall_examples, its agent wiring and the benchmark adapters, offline with a fake embedder."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anthropic.lib.tools import ToolError

from final_agent import benchmark
from final_agent.agent import BuildingAgent
from final_agent.building_map import BuildingMap
from final_agent.run_library import SKILL_BY_KIND, RunIndex
from final_agent.tools import NO_EXAMPLES_NOTE, make_recall_tool
from test_hull import BUILDING, ScriptedClient, call, reply, say
from test_run_library import FakeEmbedder, sample_run

TRANSLATION = "largest <room_type> on <floor>; answer room name and area"


def make_index() -> RunIndex:
    return RunIndex(
        [sample_run("q1", kind="largest_room", text=TRANSLATION), sample_run("q2", accepted=False)],
        FakeEmbedder(),
    )


class RecallToolTests(unittest.TestCase):
    def setUp(self):
        self.tool = make_recall_tool(make_index())

    def recall(self, kind: str, translation: str = TRANSLATION) -> dict:
        return json.loads(self.tool.call({"kind": kind, "semantic_translation": translation}))

    def test_returns_accepted_examples_of_the_kind(self):
        result = self.recall("largest_room")
        self.assertEqual((result["kind"], result["skill"]), ("largest_room", SKILL_BY_KIND["largest_room"]))
        self.assertEqual([example["question"] for example in result["examples"]], ["question q1"])
        self.assertNotIn("note", result)

    def test_kind_without_accepted_runs_gives_empty_list_and_note(self):
        result = self.recall("errand")
        self.assertEqual(result["examples"], [])
        self.assertEqual(result["note"], NO_EXAMPLES_NOTE)

    def test_unknown_kind_and_blank_translation_are_tool_errors(self):
        with self.assertRaisesRegex(ToolError, "kind"):
            self.recall("teleport")
        with self.assertRaisesRegex(ToolError, "semantic_translation"):
            self.recall("largest_room", "   ")


class AgentWiringTests(unittest.TestCase):
    def make_agent(self, client: object, examples: RunIndex | None) -> BuildingAgent:
        output = tempfile.TemporaryDirectory()
        self.addCleanup(output.cleanup)
        return BuildingAgent(BuildingMap.load(BUILDING), Path(output.name), client, examples=examples)

    def test_without_index_there_is_no_recall_tool_or_examples_prompt(self):
        agent = self.make_agent(object(), None)
        self.assertNotIn("recall_examples", [tool.name for tool in agent.tools])
        self.assertNotIn("# Worked examples", agent.system[0]["text"])

    def test_with_index_the_declaration_and_next_call_are_recorded(self):
        declaration = {"kind": "largest_room", "semantic_translation": TRANSLATION}
        client = ScriptedClient([[
            reply(call("recall_examples", **declaration)),
            reply(call("find_largest_room", room_type="office", floor_level=0)),
            reply(say("Office 0.30, 29.55 m2.\nAnswer: Office 0.30, 29.55")),
        ]])
        agent = self.make_agent(client, make_index())
        self.assertIn("# Worked examples", agent.system[0]["text"])
        text = agent.ask("Which office on the ground floor is largest?")
        self.assertTrue(text.endswith("Answer: Office 0.30, 29.55"))
        self.assertEqual([is_error for _, is_error, _ in client.results], [False, False])
        self.assertEqual(agent.tool_calls(), [
            {"name": "recall_examples", "input": declaration},
            {"name": "find_largest_room", "input": {"room_type": "office", "floor_level": 0}},
        ])


class BenchmarkAdapterTests(unittest.TestCase):
    def test_answer_passes_the_index_and_baseline_passes_none(self):
        index = object()
        with patch("final_agent.benchmark.run_index", return_value=index) as run_index, patch(
            "final_agent.benchmark.BuildingAgent"
        ) as agent_class:
            agent_class.return_value.ask.return_value = "Answer: 1"
            self.assertEqual(benchmark.answer(BUILDING, "question"), "Answer: 1")
            self.assertIs(agent_class.call_args.kwargs["examples"], index)
            self.assertEqual(benchmark.answer_without_examples(BUILDING, "question"), "Answer: 1")
            self.assertIsNone(agent_class.call_args.kwargs["examples"])
        self.assertEqual(run_index.call_count, 1)


if __name__ == "__main__":
    unittest.main()
