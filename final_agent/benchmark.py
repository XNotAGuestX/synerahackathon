"""Project agent adapter for ``benchmark.evaluate --agent final_agent.benchmark:answer``."""

from pathlib import Path
from tempfile import TemporaryDirectory

from .agent import BuildingAgent
from .building_map import BuildingMap


def answer(building_directory: Path, question_text: str) -> str:
    """Answer one question with a fresh map, conversation and temporary outputs.

    Edits and closures affect only this question. Scratch images and snapshots
    are removed afterward; the benchmark runner retains the returned reply.
    """
    with TemporaryDirectory(prefix="final-agent-benchmark-") as temporary:
        agent = BuildingAgent(BuildingMap.load(building_directory), Path(temporary))
        return agent.ask(question_text)
