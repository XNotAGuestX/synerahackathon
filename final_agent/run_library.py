"""Benchmark runs: one record per question, kept as JSONL and searched by kind and similarity.

Only accepted runs are indexed, so only successful runs ever reach the agent as examples.
Stored runs never contain a question's expected ``answer`` or ``inputs``.
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .embedding import Embedder

logger = logging.getLogger(__name__)

ScoredKind = Literal[
    "largest_room", "floor_area_total", "straight_line_3d", "room_stacked",
    "shared_walls_count", "wide_delivery_count", "step_free_reachable_count",
    "errand", "what_if_door",
]

# Skill maps 1:1 to kind in the benchmark data, so a kind filter is also a skill filter.
SKILL_BY_KIND: dict[str, str] = {
    "largest_room": "room geometry: area",
    "floor_area_total": "room geometry: summed area",
    "straight_line_3d": "3D geometry: centroids and floor elevations",
    "room_stacked": "3D stacking: polygon overlap between floors",
    "shared_walls_count": "wall adjacency from polygons",
    "wide_delivery_count": "door widths + reachability",
    "step_free_reachable_count": "reachability under constraints",
    "errand": "chain nearest-item, area and routing",
    "what_if_door": "what-if edit with effects on another floor",
}


@dataclass
class Run:
    """One answered benchmark question; ``question_id`` from the data is the key.

    ``declared_kind`` and ``semantic_translation`` come from the agent's first
    ``recall_examples`` call. Tool calls hold names and inputs only, no results.
    """

    question_id: str
    building_id: str
    skill: str
    kind: ScoredKind
    declared_kind: ScoredKind | None
    semantic_translation: str
    question: str
    tool_calls: list[dict]
    reply: str
    accepted: bool


def load_runs(path: Path) -> list[Run]:
    """Read a JSONL run library; a missing file is an empty library."""
    path = Path(path)
    if not path.exists():
        return []
    runs = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            run = Run(**json.loads(line))
            if run.kind not in SKILL_BY_KIND:
                raise ValueError(f"unknown kind {run.kind!r}")
        except (ValueError, TypeError) as error:
            raise ValueError(f"{path}:{number}: {error}") from error
        runs.append(run)
    return runs


def save_runs(path: Path, runs: list[Run]) -> None:
    """Write UTF-8 JSONL sorted by question_id, replacing the file only after writing succeeds."""
    path = Path(path)
    ordered = sorted(runs, key=lambda run: run.question_id)
    contents = "".join(json.dumps(asdict(run), ensure_ascii=False) + "\n" for run in ordered)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(contents, encoding="utf-8")
    temporary.replace(path)


def example_json(run: Run) -> dict:
    """The part of a run shown to the agent as a worked example."""
    return {
        "kind": run.kind,
        "skill": run.skill,
        "semantic_translation": run.semantic_translation,
        "question": run.question,
        "tool_calls": run.tool_calls,
        "reply": run.reply,
    }


class RunIndex:
    """Accepted runs in an in-memory Qdrant collection, rebuilt from the JSONL per process.

    Vectors come from the ``Embedder`` adapter rather than Qdrant's FastEmbed
    integration, so either side can be replaced alone. Moving to a Qdrant server
    only changes the client constructor.
    """

    COLLECTION = "runs"

    def __init__(self, runs: list[Run], embedder: Embedder) -> None:
        self.runs = [run for run in runs if run.accepted]
        self.embedder = embedder
        self.client = None
        if not self.runs:
            # Nothing to search, so neither Qdrant nor the embedding model is loaded.
            return
        # Imported here: qdrant_client also imports FastEmbed, which chat never needs.
        from qdrant_client import QdrantClient, models

        self.client = QdrantClient(":memory:")
        self.client.create_collection(
            self.COLLECTION,
            vectors_config=models.VectorParams(size=embedder.dimension, distance=models.Distance.COSINE),
        )
        vectors = embedder.embed([run.semantic_translation for run in self.runs])
        # The point id is the run's position in self.runs.
        self.client.upsert(self.COLLECTION, points=[
            models.PointStruct(id=position, vector=vector, payload={"kind": run.kind})
            for position, (run, vector) in enumerate(zip(self.runs, vectors, strict=True))
        ])

    def similar(self, kind: str, semantic_translation: str, limit: int = 3) -> list[Run]:
        """Return accepted runs of this kind, most similar translation first."""
        if not self.runs:
            logger.debug("recall %s %r: the run library has no accepted runs", kind, semantic_translation)
            return []
        from qdrant_client import models

        [vector] = self.embedder.embed([semantic_translation])
        same_kind = models.Filter(
            must=[models.FieldCondition(key="kind", match=models.MatchValue(value=kind))]
        )
        response = self.client.query_points(
            self.COLLECTION, query=vector, query_filter=same_kind, limit=limit, with_payload=False,
        )
        logger.debug("recall %s %r: %d matched", kind, semantic_translation, len(response.points))
        for point in response.points:
            run = self.runs[point.id]
            logger.debug("  %.3f %s %r", point.score, run.question_id, run.semantic_translation)
            logger.debug("        %s", run.question)
        return [self.runs[point.id] for point in response.points]
