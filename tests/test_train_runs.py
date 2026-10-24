import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from final_agent.agent import MODEL
from final_agent.train_runs import build, confirm_full, make_run, pending_questions, require_labels
from test_hull import BUILDING, ScriptedClient, call, reply, say
from test_run_library import FakeEmbedder, sample_run

QUESTION = {
    "id": "b1-H01",
    "building_id": "b1",
    "kind": "floor_area_total",
    "skill": "room geometry: summed area",
    "question": "Total area of every office on the ground floor? Finish with a line 'Answer: <number>'.",
    "answer": {"type": "number", "value": 10.0, "unit": "m2", "relative_tolerance": 0.05, "absolute_tolerance": 0.0},
}
TRANSLATION = "total area of every <room_type> on <floor>; answer square metres"
AREA_CALL = {"name": "floor_area", "input": {"floor": "b1-F0", "room_type": "office"}}


def recall(kind: str, translation: str = TRANSLATION) -> dict:
    return {"name": "recall_examples", "input": {"kind": kind, "semantic_translation": translation}}


class MakeRunTests(unittest.TestCase):
    def test_missing_kind_uses_the_agents_declaration(self):
        question = {key: value for key, value in QUESTION.items() if key != "kind"}
        run = make_run(question, [recall("floor_area_total"), AREA_CALL], "Answer: 10.2")
        self.assertEqual(run.kind, "floor_area_total")
        self.assertTrue(run.accepted)

    def test_missing_kind_and_declaration_does_not_throw(self):
        question = {key: value for key, value in QUESTION.items() if key != "kind"}
        self.assertIsNone(make_run(question, [AREA_CALL], "Answer: 10.2"))

    def test_correct_reply_with_matching_declaration_is_accepted(self):
        run = make_run(QUESTION, [recall("floor_area_total"), AREA_CALL], "Answer: 10.2")
        self.assertTrue(run.accepted)
        self.assertEqual((run.declared_kind, run.semantic_translation), ("floor_area_total", TRANSLATION))
        self.assertEqual(run.tool_calls, [AREA_CALL])
        self.assertEqual(run.skill, "room geometry: summed area")

    def test_wrong_number_is_rejected(self):
        self.assertFalse(make_run(QUESTION, [recall("floor_area_total"), AREA_CALL], "Answer: 20").accepted)

    def test_wrong_declared_kind_is_rejected(self):
        run = make_run(QUESTION, [recall("largest_room"), AREA_CALL], "Answer: 10.2")
        self.assertFalse(run.accepted)
        self.assertEqual(run.declared_kind, "largest_room")

    def test_missing_declaration_is_rejected(self):
        run = make_run(QUESTION, [AREA_CALL], "Answer: 10.2")
        self.assertFalse(run.accepted)
        self.assertEqual((run.declared_kind, run.semantic_translation), (None, ""))

    def test_blank_translation_is_rejected(self):
        run = make_run(QUESTION, [recall("floor_area_total", "  "), AREA_CALL], "Answer: 10.2")
        self.assertFalse(run.accepted)
        self.assertEqual(run.semantic_translation, "")

    def test_first_declaration_counts(self):
        calls = [recall("largest_room", "first"), AREA_CALL, recall("floor_area_total", "second")]
        run = make_run(QUESTION, calls, "Answer: 10.2")
        self.assertFalse(run.accepted)
        self.assertEqual((run.declared_kind, run.semantic_translation), ("largest_room", "first"))
        self.assertEqual(run.tool_calls, [AREA_CALL])


class BuildSelectionTests(unittest.TestCase):
    def test_training_without_kind_infers_it_from_recall(self):
        question = {key: value for key, value in QUESTION.items() if key != "kind"}
        client = ScriptedClient([[
            reply(call("recall_examples", kind="floor_area_total", semantic_translation=TRANSLATION)),
            reply(say("Answer: 10.2")),
        ]])
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()), patch(
            "final_agent.agent.anthropic.Anthropic", return_value=client
        ), patch("final_agent.train_runs.default_embedder", return_value=FakeEmbedder()), patch.object(
            client.beta.messages, "tool_runner", wraps=client.beta.messages.tool_runner
        ) as runner:
            library = Path(temporary) / "runs.jsonl"
            build([(BUILDING, question)], library, MODEL, full=False)
            self.assertEqual(runner.call_args.kwargs["messages"][0]["content"], question["question"])
            saved = json.loads(library.read_text())
            self.assertEqual(saved["kind"], "floor_area_total")
            self.assertTrue(saved["accepted"])

    def test_training_build_supplies_kind_without_exposing_labelled_inputs_or_answer(self):
        question = {**QUESTION, "inputs": {"start": "PRIVATE_SOURCE_ID"}}
        client = ScriptedClient([[
            reply(call("recall_examples", kind=question["kind"], semantic_translation=TRANSLATION)),
            reply(say("Answer: 10.2")),
        ]])
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()), patch(
            "final_agent.agent.anthropic.Anthropic", return_value=client
        ), patch("final_agent.train_runs.default_embedder", return_value=FakeEmbedder()), patch.object(
            client.beta.messages, "tool_runner", wraps=client.beta.messages.tool_runner
        ) as runner:
            library = Path(temporary) / "runs.jsonl"
            build([(BUILDING, question)], library, MODEL, full=False)
            request = runner.call_args.kwargs
            prompt = request["messages"][0]["content"]
            self.assertIn("Benchmark question kind: floor_area_total", prompt)
            self.assertTrue(prompt.endswith(question["question"]))
            self.assertNotIn("PRIVATE_SOURCE_ID", str(request))
            self.assertNotIn(str(question["answer"]), prompt)
            saved = json.loads(library.read_text())
            self.assertEqual(saved["question"], question["question"])
            self.assertEqual(saved["declared_kind"], question["kind"])
            self.assertTrue(saved["accepted"])

    def test_require_labels_exits_on_unlabelled_question(self):
        unlabelled = {key: value for key, value in QUESTION.items() if key != "answer"}
        require_labels([(Path("b1"), QUESTION)])
        with self.assertRaises(SystemExit):
            require_labels([(Path("b1"), QUESTION), (Path("b1"), unlabelled)])

    def test_pending_questions_skips_accepted_runs_only(self):
        questions = [(Path("b1"), {**QUESTION, "id": question_id}) for question_id in ("q1", "q2", "q3")]
        runs = [sample_run("q1"), sample_run("q2", accepted=False)]
        pending = pending_questions(questions, runs)
        self.assertEqual([question["id"] for _, question in pending], ["q2", "q3"])

    def test_confirm_full_accepts_only_exact_yes(self):
        for typed, expected in [("yes", True), ("y", False), ("no", False), ("", False)]:
            printed = io.StringIO()
            with self.subTest(typed=typed), redirect_stdout(printed):
                self.assertEqual(confirm_full(12, "claude-test", read=lambda prompt: typed), expected)
            self.assertIn("12", printed.getvalue())
            self.assertIn("claude-test", printed.getvalue())


if __name__ == "__main__":
    unittest.main()
