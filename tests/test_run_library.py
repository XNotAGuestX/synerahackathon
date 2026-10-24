import gc
import json
import tempfile
import unittest
import warnings
import zlib
from dataclasses import fields
from pathlib import Path
from typing import get_args

from final_agent.run_library import (
    SKILL_BY_KIND, Run, RunIndex, ScoredKind, load_runs, save_runs,
)


class FakeEmbedder:
    """Offline stand-in for FastEmbed (hashed bag of words); proves the adapter is swappable."""

    model_name = "fake-hashed-words"
    dimension = 64

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimension
            for word in text.lower().split():
                vector[zlib.crc32(word.encode()) % self.dimension] += 1.0
            vectors.append(vector)
        return vectors


def sample_run(
    question_id: str, building: str = "b1", kind: str = "errand",
    text: str = "nearest <asset> then largest <room_type> other floor step free",
    accepted: bool = True,
) -> Run:
    return Run(
        question_id=question_id, building_id=building, skill=SKILL_BY_KIND[kind], kind=kind,
        declared_kind=kind, semantic_translation=text, question=f"question {question_id}",
        tool_calls=[], reply="Answer: 1", accepted=accepted,
    )


class RunLibraryTests(unittest.TestCase):
    def test_jsonl_round_trip_is_sorted_and_stores_no_labels(self):
        later = sample_run("q2")
        later.tool_calls = [{"name": "route", "input": {"from": "Küche", "to": "Lager"}}]
        earlier = sample_run("q1", kind="largest_room", accepted=False)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runs.jsonl"
            save_runs(path, [later, earlier])
            self.assertEqual(load_runs(path), [earlier, later])
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([record["question_id"] for record in records], ["q1", "q2"])
        for record in records:
            self.assertEqual(list(record), [field.name for field in fields(Run)])
            self.assertNotIn("answer", record)
            self.assertNotIn("inputs", record)

    def test_missing_file_is_an_empty_library(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(load_runs(Path(temporary) / "runs.jsonl"), [])

    def test_bad_line_names_path_and_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runs.jsonl"
            path.write_text("not json\n", encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                load_runs(path)
        self.assertTrue(str(caught.exception).startswith(f"{path}:1: "), str(caught.exception))
        self.assertIn("runs.jsonl:1: ", str(caught.exception))

    def test_index_returns_accepted_runs_of_the_kind_nearest_first(self):
        query = "nearest <asset> then largest <room_type> other floor step free"
        runs = [
            sample_run("far", text="largest <room_type> on <floor>"),
            sample_run("rejected", text=query, accepted=False),
            sample_run("other-kind", kind="largest_room", text=query),
            sample_run("near", text="nearest <asset> then largest <room_type> other floor"),
        ]
        index = RunIndex(runs, FakeEmbedder())
        self.assertEqual([run.question_id for run in index.similar("errand", query)], ["near", "far"])
        self.assertEqual(index.similar("what_if_door", query), [])
        self.assertEqual(RunIndex([runs[1]], FakeEmbedder()).similar("errand", query), [])

    def test_saved_index_is_reused_until_the_accepted_runs_change(self):
        query = "largest <room_type> on <floor>"
        runs = [sample_run("q1"), sample_run("q2", text=query)]
        embedder = FakeEmbedder()
        # qdrant-client's local storage leaves some SQLite and lock handles to the collector.
        with tempfile.TemporaryDirectory() as temporary, warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            path = Path(temporary) / "runs.qdrant"
            RunIndex(runs, embedder, path).client.close()
            reused = RunIndex(runs, embedder, path)
            self.assertEqual(embedder.calls, 1)  # the second process embedded nothing
            self.assertEqual([run.question_id for run in reused.similar("errand", query)], ["q2", "q1"])
            # While the folder is held, another index works from memory instead of failing.
            with self.assertLogs("final_agent.run_library", "WARNING"):
                self.assertEqual(len(RunIndex(runs, embedder, path).similar("errand", query)), 2)
            reused.client.close()
            changed = RunIndex(runs[:1], embedder, path)
            self.assertEqual([run.question_id for run in changed.similar("errand", query)], ["q1"])
            self.assertEqual([c.name for c in changed.client.get_collections().collections], [changed.collection])
            changed.client.close()
            gc.collect()

    def test_kinds_literal_matches_skills(self):
        self.assertEqual(set(get_args(ScoredKind)), set(SKILL_BY_KIND))


if __name__ == "__main__":
    unittest.main()
