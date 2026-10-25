import unittest
from pathlib import Path

from benchmark.sunday import explain, main


class SundayShellTests(unittest.TestCase):
    def test_missing_input_and_unannounced_schema_both_fail(self):
        self.assertIn("No schema has been announced", explain(None))
        self.assertIn("not found", explain(Path("missing-sunday-input.json")))
        self.assertEqual(main([]), 1)
        self.assertEqual(main(["docs/TODOLIST-2026-10-25.md"]), 1)
        self.assertIn("has not been recorded", explain(Path("docs/TODOLIST-2026-10-25.md")))


if __name__ == "__main__":
    unittest.main()
