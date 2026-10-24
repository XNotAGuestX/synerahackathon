"""Project agent adapter for ``benchmark.evaluate --agent final_agent.benchmark:answer``.

``answer`` shows the agent worked examples from the run library; ``answer_without_examples``
is the same agent without them, the baseline for an A/B comparison.
"""

import logging
from collections import Counter
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory

from .agent import MODEL, BuildingAgent, MissingCredentialsError
from .building_map import BuildingMap
from .embedding import default_embedder
from .run_library import RunIndex, index_path, load_runs

RUN_LIBRARY_PATH = Path(__file__).with_name("run_library.jsonl")
logger = logging.getLogger(__name__)
# Tokens of every answer in this process, failed ones included; benchmark.evaluate reads
# it as ``answer.usage`` to show the running cost.
USAGE: Counter[str] = Counter()


@cache
def run_index() -> RunIndex:
    """The committed run library's index, saved beside it and opened on the first answer, never at import."""
    return RunIndex(load_runs(RUN_LIBRARY_PATH), default_embedder(), index_path(RUN_LIBRARY_PATH))


def answer(building_directory: Path, question_text: str, model: str = MODEL) -> str:
    """Answer one question with worked examples of similar accepted runs."""
    return _answer(building_directory, question_text, run_index(), model)


def answer_without_examples(building_directory: Path, question_text: str, model: str = MODEL) -> str:
    """Answer one question without the run library (A/B baseline)."""
    return _answer(building_directory, question_text, None, model)


def _answer(building_directory: Path, question_text: str, examples: RunIndex | None, model: str) -> str:
    """Answer one question with a fresh map, conversation and temporary outputs.

    Edits and closures affect only this question. Scratch images and snapshots
    are removed afterward; the benchmark runner retains the returned reply.
    """
    logger.debug("question: %s", question_text)
    with TemporaryDirectory(prefix="final-agent-benchmark-") as temporary:
        agent = BuildingAgent(
            BuildingMap.load(building_directory), Path(temporary), examples=examples, model=model
        )
        try:
            return agent.ask(question_text)
        except MissingCredentialsError as error:
            # Stop the whole run: every remaining question would fail the same way.
            raise SystemExit(str(error)) from error
        finally:
            USAGE.update(agent.usage)


answer.usage = USAGE
answer_without_examples.usage = USAGE
