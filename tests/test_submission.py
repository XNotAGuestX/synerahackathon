"""Public submission files are kept only when they can be graded."""

import tempfile
import unittest
from pathlib import Path

from benchmark.validate_submission import write_validated_submission


class SubmissionValidationTests(unittest.TestCase):
    def test_empty_answer_does_not_leave_a_csv(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "team_answers.csv"
            problems = write_validated_submission(path, [("q1", ""), ("q2", "Answer: 1")])
            self.assertTrue(problems)
            self.assertFalse(path.exists())

    def test_template_coverage_rejects_a_partial_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "submission_template.csv"
            template.write_text("question_id,answer\nq1,\nq2,\n", encoding="utf-8")
            target = root / "team_answers.csv"
            problems = write_validated_submission(target, [("q1", "Answer: 1")], template)
            self.assertTrue(any("Expected 2" in problem for problem in problems))
            self.assertFalse(target.exists())

    def test_complete_utf8_file_is_kept(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "submission_template.csv"
            template.write_text("question_id,answer\nq1,\nq2,\n", encoding="utf-8")
            target = root / "team_answers.csv"
            problems = write_validated_submission(
                target, [("q2", "Answer: 2"), ("q1", "Answer: 1")], template,
            )
            self.assertEqual(problems, [])
            text = target.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("question_id,answer"))
            self.assertLess(target.stat().st_size, 5 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
