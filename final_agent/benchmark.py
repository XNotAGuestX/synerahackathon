"""Project agent adapter for ``benchmark.evaluate --agent final_agent.benchmark:answer``.

``answer`` shows the agent worked examples from the run library; ``answer_without_examples``
is the same agent without them, the baseline for an A/B comparison.
"""

from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory

from .agent import BuildingAgent, MissingCredentialsError
from .building_map import BuildingMap
from .embedding import default_embedder
from .run_library import RunIndex, load_runs

RUN_LIBRARY_PATH = Path(__file__).with_name("run_library.jsonl")


@cache
def run_index() -> RunIndex:
    """The committed run library, indexed once per process on the first answer, never at import."""
    return RunIndex(load_runs(RUN_LIBRARY_PATH), default_embedder())


def answer(building_directory: Path, question_text: str) -> str:
    """Answer one question with worked examples of similar accepted runs."""
    return _answer(building_directory, question_text, run_index())


def answer_without_examples(building_directory: Path, question_text: str) -> str:
    """Answer one question without the run library (A/B baseline)."""
    return _answer(building_directory, question_text, None)


def _answer(building_directory: Path, question_text: str, examples: RunIndex | None) -> str:
    """Answer one question with a fresh map, conversation and temporary outputs.

    Edits and closures affect only this question. Scratch images and snapshots
    are removed afterward; the benchmark runner retains the returned reply.
    """
    with TemporaryDirectory(prefix="final-agent-benchmark-") as temporary:
        agent = BuildingAgent(BuildingMap.load(building_directory), Path(temporary), examples=examples)
        try:
            return agent.ask(question_text)
        except MissingCredentialsError as error:
            # Stop the whole run: every remaining question would fail the same way.
            raise SystemExit(str(error)) from error
