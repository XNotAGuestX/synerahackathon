"""Project agent adapter for ``benchmark.evaluate --agent final_agent.benchmark:answer``."""

from pathlib import Path
from tempfile import TemporaryDirectory

from .agent import BuildingAgent
from .building_map import BuildingMap
from .scored import answer_line


def answer(building_directory: Path, question_text: str) -> str:
    """Answer one question with a fresh map, conversation and temporary outputs.

    The nine scored kinds are answered by deterministic tools. Other questions
    go to the conversational agent. Edits stay inside this call.
    """
    building = BuildingMap.load(building_directory)
    scored = answer_line(building, question_text)
    if scored:
        return scored
    with TemporaryDirectory(prefix="final-agent-benchmark-") as temporary:
        agent = BuildingAgent(building, Path(temporary))
        return agent.ask(question_text)
