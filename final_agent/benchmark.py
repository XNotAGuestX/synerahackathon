"""Project agent adapter for ``benchmark.evaluate --agent final_agent.benchmark:answer``."""

from pathlib import Path
from tempfile import TemporaryDirectory

from .agent import BuildingAgent, MissingCredentialsError
from .building_map import BuildingMap


def answer(building_directory: Path, question_text: str) -> str:
    """Answer one question with a fresh map, conversation and temporary outputs.

    Edits and closures affect only this question. Scratch images and snapshots
    are removed afterward; the benchmark runner retains the returned reply.
    """
    with TemporaryDirectory(prefix="final-agent-benchmark-") as temporary:
        agent = BuildingAgent(BuildingMap.load(building_directory), Path(temporary))
        try:
            return agent.ask(question_text)
        except MissingCredentialsError as error:
            # Stop the whole run: every remaining question would fail the same way.
            raise SystemExit(str(error)) from error
