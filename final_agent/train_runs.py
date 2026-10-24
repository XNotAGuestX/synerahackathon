"""Build the run library by answering labelled benchmark questions with the agent.

  uv run python -m final_agent.train_runs                  # 1 train question per kind
  uv run python -m final_agent.train_runs --full           # every pending question (asks first)
  uv run python -m final_agent.train_runs --all            # add data/dev to data/train

This module reads train/dev answer labels only to accept runs. The answer path
(final_agent.benchmark, BuildingAgent, recall_examples) never imports it.
"""

import argparse
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

import anthropic

from benchmark.evaluate import cost_dollars, load_questions, sample_per_kind, spent
from benchmark.score import score_reply

from .agent import MODELS, BuildingAgent, MissingCredentialsError, add_model_argument
from .benchmark import RUN_LIBRARY_PATH, question_with_kind
from .building_map import BuildingMap
from .embedding import default_embedder
from .run_library import SKILL_BY_KIND, Run, RunIndex, ScoredKind, index_path, load_runs, save_runs

DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data"
TRAIN_DIRECTORY = DATA_DIRECTORY / "train"
DEV_DIRECTORY = DATA_DIRECTORY / "dev"
RECALL_TOOL = "recall_examples"
SMALL_PER_KIND = 1

Question = tuple[Path, dict]


def make_run(question: dict, tool_calls: list[dict], reply: str) -> Run | None:
    """Use the supplied kind, or the first recall's kind if omitted; unclassified runs cannot be indexed."""
    declarations = [call["input"] for call in tool_calls if call["name"] == RECALL_TOOL]
    declaration = declarations[0] if declarations else {}
    declared_kind = declaration.get("kind")
    kind = question.get("kind") or declared_kind
    if kind not in SKILL_BY_KIND:
        return None
    # A blank translation (e.g. from a rejected recall call) would be an unretrievable example.
    translation = str(declaration.get("semantic_translation", "")).strip()
    return Run(
        question_id=question["id"],
        building_id=question["building_id"],
        skill=SKILL_BY_KIND[kind],
        kind=kind,
        declared_kind=declared_kind,
        semantic_translation=translation,
        question=question["question"],
        # Examples replay the building work; the recall call itself is not part of it.
        tool_calls=[call for call in tool_calls if call["name"] != RECALL_TOOL],
        reply=reply,
        accepted=bool(translation) and declared_kind == kind and score_reply(question["answer"], reply),
    )


def require_labels(questions: list[Question]) -> None:
    """Runs can only be accepted against answer labels; the public test set has none."""
    unlabelled = [question["id"] for _, question in questions if "answer" not in question]
    if unlabelled:
        raise SystemExit(
            f"{len(unlabelled)} questions have no answer label (first: {unlabelled[0]}); "
            "build the run library from train/dev only."
        )


def pending_questions(questions: list[Question], runs: list[Run]) -> list[Question]:
    """Questions without an accepted run; rejected runs are retried."""
    accepted = {run.question_id for run in runs if run.accepted}
    return [item for item in questions if item[1]["id"] not in accepted]


def confirm_full(count: int, model: str, read: Callable[[str], str] = input) -> bool:
    """Ask before a paid full build; only the exact answer 'yes' proceeds."""
    print(f"Full build: {count} questions, each a paid conversation with {model}.")
    try:
        return read("Type 'yes' to continue: ") == "yes"
    except EOFError:
        return False


def ask_agent(
    building_directory: Path, question_text: str, index: RunIndex, model: str, usage: Counter[str],
    *, kind: ScoredKind | None = None,
) -> tuple[list[dict], str]:
    """Answer with a fresh map and conversation so edits never leak between questions."""
    with TemporaryDirectory(prefix="final-agent-train-") as temporary:
        agent = BuildingAgent(
            BuildingMap.load(building_directory), Path(temporary), examples=index, model=model
        )
        try:
            reply = agent.ask(question_with_kind(question_text, kind))
        finally:
            usage.update(agent.usage)
        return agent.tool_calls(), reply


def build(selected: list[Question], library: Path, model: str, full: bool) -> None:
    runs = {run.question_id: run for run in load_runs(library)}
    pending = pending_questions(selected, list(runs.values()))
    print(f"model: {model}")
    print(f"{len(pending)} pending of {len(selected)} selected")
    if not pending:
        return
    if full and not confirm_full(len(pending), model):
        raise SystemExit("Aborted: the full build only starts after typing 'yes'.")
    # Built once, so runs accepted during this build become examples from the next build on.
    index = RunIndex(list(runs.values()), default_embedder(), index_path(library))
    usage: Counter[str] = Counter()
    results: Counter[tuple[str, bool]] = Counter()
    for building_directory, question in pending:
        kind = question.get("kind") or None
        try:
            tool_calls, reply = ask_agent(
                building_directory, question["question"], index, model, usage, kind=kind
            )
        except anthropic.APIError as error:
            print(f"{question['id']:34s} {kind or 'unknown':26s} skipped  {spent(usage, model)}  API error: {error}")
            continue
        except MissingCredentialsError as error:
            raise SystemExit(str(error)) from error
        run = make_run(question, tool_calls, reply)
        if run is None:
            print(f"{question['id']:34s} skipped: no valid kind was supplied or declared for the run library")
            continue
        runs[run.question_id] = run
        # Saved after every question so an interrupted build keeps its finished runs.
        save_runs(library, list(runs.values()))
        results[(run.kind, run.accepted)] += 1
        outcome = "ACCEPTED" if run.accepted else "rejected"
        print(f"{run.question_id:34s} {run.kind:26s} {outcome:8s} {spent(usage, model)}  declared {run.declared_kind}")
    print_summary(results, usage, model)


def print_summary(results: Counter[tuple[str, bool]], usage: Counter[str], model: str) -> None:
    print(f"\n{'kind':28s} accepted / total")
    for kind in sorted({kind for kind, _ in results}):
        accepted = results[(kind, True)]
        print(f"  {kind:26s} {accepted:8d} / {accepted + results[(kind, False)]}")
    print(f"tokens: {dict(usage)}  cost: ${cost_dollars(usage, model):.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="final_agent.train_runs", description="Answer labelled questions and record accepted runs."
    )
    parser.add_argument("--full", action="store_true", help="every pending question, after a typed 'yes'")
    parser.add_argument("--all", action="store_true", help="add data/dev to data/train")
    add_model_argument(parser)
    parser.add_argument(
        "--library", type=Path, default=RUN_LIBRARY_PATH, help=f"run library JSONL (default: {RUN_LIBRARY_PATH})"
    )
    arguments = parser.parse_args()
    directories = [TRAIN_DIRECTORY, DEV_DIRECTORY] if arguments.all else [TRAIN_DIRECTORY]
    questions = [item for directory in directories for item in load_questions(directory)]
    if not questions:
        raise SystemExit(f"No questions found under {', '.join(map(str, directories))}.")
    require_labels(questions)
    selected = questions if arguments.full else sample_per_kind(questions, SMALL_PER_KIND)
    build(selected, arguments.library, MODELS[arguments.model], arguments.full)


if __name__ == "__main__":
    main()
