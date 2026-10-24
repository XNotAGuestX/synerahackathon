import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from final_agent.train_runs import confirm_full, make_run, pending_questions, require_labels
from test_run_library import sample_run

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

    def test_first_declaration_counts(self):
        calls = [recall("largest_room", "first"), AREA_CALL, recall("floor_area_total", "second")]
        run = make_run(QUESTION, calls, "Answer: 10.2")
        self.assertFalse(run.accepted)
        self.assertEqual((run.declared_kind, run.semantic_translation), ("largest_room", "first"))
        self.assertEqual(run.tool_calls, [AREA_CALL])


class BuildSelectionTests(unittest.TestCase):
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
