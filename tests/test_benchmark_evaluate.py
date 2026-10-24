"""The actual benchmark entry point forwards public kind metadata into model messages, offline."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from itertools import product
from pathlib import Path
from unittest.mock import patch

from benchmark.evaluate import run
from final_agent.agent import MODEL
from test_hull import BUILDING, ScriptedClient, reply, say


class BenchmarkKindTests(unittest.TestCase):
    def test_actual_runs_allow_optional_kind_with_and_without_examples_and_labels(self):
        for adapter in (None, "final_agent.benchmark:answer_without_examples"):
            for labelled, kind in product((False, True), ("wide_delivery_count", None, "", "missing")):
                with self.subTest(adapter=adapter, labelled=labelled, kind=kind):
                    question = {
                        "id": "case-1", "building_id": "example",
                        "question": "How many rooms can the 1.0 m wide trolley reach?",
                    }
                    if kind != "missing":
                        question["kind"] = kind
                    if labelled:
                        question.update(
                            inputs={"start": "PRIVATE_SOURCE_ID"},
                            answer={"type": "number", "value": 7, "relative_tolerance": 0,
                                    "absolute_tolerance": 0},
                        )
                    client = ScriptedClient([[reply(say("Answer: 7"))]])
                    with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()), patch(
                        "benchmark.evaluate.load_questions", return_value=[(BUILDING, question)]
                    ), patch("benchmark.evaluate.RESULTS_DIRECTORY", Path(temporary)), patch(
                        "final_agent.benchmark.run_index", return_value=None
                    ), patch("final_agent.agent.anthropic.Anthropic", return_value=client), patch.object(
                        client.beta.messages, "tool_runner", wraps=client.beta.messages.tool_runner
                    ) as runner:
                        run(BUILDING.parent, 1, adapter, "kind-check", model=MODEL)
                        request = runner.call_args.kwargs
                        prompt = request["messages"][0]["content"]
                        if kind == "wide_delivery_count":
                            self.assertIn("Benchmark question kind: wide_delivery_count", prompt)
                            self.assertEqual(prompt.count("Benchmark question kind:"), 1)
                        else:
                            self.assertEqual(prompt, question["question"])
                        self.assertTrue(prompt.endswith(question["question"]))
                        self.assertNotIn("PRIVATE_SOURCE_ID", str(request))
                        self.assertNotIn('"answer"', prompt)
                        saved = json.loads((Path(temporary) / "kind-check.jsonl").read_text())
                        self.assertEqual(saved["question"], question["question"])
                        self.assertEqual(saved["kind"], question.get("kind") or None)
                        self.assertIs(saved["correct"], True if labelled else None)


if __name__ == "__main__":
    unittest.main()
