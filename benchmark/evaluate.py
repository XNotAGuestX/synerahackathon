"""Run an agent on the benchmark questions (questions.jsonl) and score its replies.

  uv run --env-file .env python -m benchmark.evaluate data/dev --per-kind 4

By default it runs the project agent (final_agent.benchmark:answer). Pass --agent module:function to evaluate
another one; the function gets (building_directory: Path, question_text: str) and returns the reply text.
The question text includes the supplied benchmark kind. With --model it is also
called with model=<API model ID>."""

import argparse
import csv
import importlib
import json
import logging
import random
import sys
from collections import Counter
from collections.abc import Callable
from functools import partial
from pathlib import Path

import anthropic

from benchmark.score import score_reply
from final_agent.agent import DEFAULT_MODEL, MODEL, MODELS
from final_agent.benchmark import question_with_kind

QUESTIONS_FILENAME = "questions.jsonl"
SUBMISSION_COLUMNS = ("question_id", "answer")
RESULTS_DIRECTORY = Path("agent_output") / "benchmark"
SAMPLE_SEED = 7
DEFAULT_AGENT = "final_agent.benchmark:answer"
# Dollars per million tokens; cache writes are the 5-minute cache. Haiku's rates apply to prompts up to 100K tokens.
PRICE_PER_MILLION = {
    "claude-opus-5-5": {
        "input_tokens": 4.00, "output_tokens": 20.00,
        "cache_read_input_tokens": 0.20, "cache_creation_input_tokens": 5.00,
    },
    "claude-sonnet-5-5": {
        "input_tokens": 2.00, "output_tokens": 10.00,
        "cache_read_input_tokens": 0.20, "cache_creation_input_tokens": 2.50,
    },
    "claude-haiku-5-5": {
        "input_tokens": 0.10, "output_tokens": 0.50,
        "cache_read_input_tokens": 0.01, "cache_creation_input_tokens": 0.125,
    },
}

AgentFunction = Callable[[Path, str], str]


def load_questions(directory: Path) -> list[tuple[Path, dict]]:
    questions = []
    for path in sorted(directory.glob(f"*/{QUESTIONS_FILENAME}")):
        with path.open(encoding="utf-8") as handle:
            questions += [(path.parent, json.loads(line)) for line in handle if line.strip()]
    return questions


def sample_per_kind(questions: list[tuple[Path, dict]], per_kind: int | None) -> list[tuple[Path, dict]]:
    if per_kind is None:
        return questions
    rng = random.Random(SAMPLE_SEED)
    by_kind: dict[str, list[tuple[Path, dict]]] = {}
    for item in questions:
        by_kind.setdefault(item[1].get("kind") or "unknown", []).append(item)
    sampled = []
    for kind in sorted(by_kind):
        members = by_kind[kind]
        sampled += rng.sample(members, min(per_kind, len(members)))
    return sampled


def load_agent(reference: str | None) -> AgentFunction:
    module_name, function_name = (reference or DEFAULT_AGENT).split(":")
    return getattr(importlib.import_module(module_name), function_name)


def enable_debug_log(agent_reference: str | None) -> None:
    """Print the agent package's debug log, e.g. the run-library questions matched for each answer.

    Only that package logs at DEBUG, so SDK, HTTP and Qdrant logs stay quiet. It goes to stdout
    to stay in order with the per-question result lines.
    """
    module_name = (agent_reference or DEFAULT_AGENT).split(":")[0]
    logging.basicConfig(stream=sys.stdout, format="[debug] %(message)s")
    logging.getLogger(module_name.partition(".")[0]).setLevel(logging.DEBUG)


def cost_dollars(usage: Counter[str], model: str) -> float:
    return sum(usage[key] * price / 1_000_000 for key, price in PRICE_PER_MILLION[model].items())


def spent(usage: Counter[str], model: str) -> str:
    """Running cost estimate for per-question progress lines, at list prices."""
    return f"${cost_dollars(usage, model):.3f} so far"


def submission_template(directory: Path) -> Path | None:
    """The public test template, when this run is the 145-question submission."""
    path = directory / "submission_template.csv"
    return path if path.is_file() else None


def write_submission_csv(path: Path, replies: list[tuple[str, str]]) -> None:
    """question_id,answer with the full replies: the file the judge app grades."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(SUBMISSION_COLUMNS)
        writer.writerows(replies)


def run(
    directory: Path,
    per_kind: int | None,
    agent_reference: str | None,
    results_name: str,
    submission_csv: Path | None = None,
    kinds: list[str] | None = None,
    model: str | None = None,
) -> int:
    answer = load_agent(agent_reference)
    # Without a model the agent uses its own default (MODEL for the project agent).
    agent = partial(answer, model=model) if model else answer
    # An agent may expose its accumulated token usage; it is then priced after every question.
    usage = getattr(answer, "usage", None)
    results: Counter[tuple[str, bool]] = Counter()
    replies: list[tuple[str, str]] = []
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    results_path = RESULTS_DIRECTORY / f"{results_name}.jsonl"
    with results_path.open("w", encoding="utf-8") as log:
        questions = [item for item in load_questions(directory) if not kinds or item[1].get("kind") in kinds]
        for building_directory, question in sample_per_kind(questions, per_kind):
            kind = question.get("kind") or None
            try:
                reply = agent(building_directory, question_with_kind(question["question"], kind))
            except anthropic.APIError as error:
                print(f"[benchmark] {question['id']}: API error {error}")
                reply = ""
            replies.append((question["id"], reply))
            # The public test set has no answers: then replies are only saved, for the judge to grade.
            correct = score_reply(question["answer"], reply) if "answer" in question else None
            if correct is not None:
                results[(kind or "unknown", correct)] += 1
            log.write(
                json.dumps(
                    {
                        "id": question["id"],
                        "kind": kind,
                        "correct": correct,
                        "question": question["question"],
                        "answer": question.get("answer"),
                        "reply": reply,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            outcome = {True: "OK ", False: "BAD", None: "saved"}[correct]
            progress = f"  {spent(usage, model or MODEL)}" if usage is not None else ""
            print(f"[benchmark] {question['id']:34s} {kind or 'unknown':20s} {outcome}{progress}")
    if results:
        report(results)
    exit_code = 0
    if submission_csv is not None:
        from benchmark.validate_submission import write_validated_submission
        template = submission_template(directory)
        problems = write_validated_submission(submission_csv, replies, template)
        if problems:
            exit_code = 1
            print("submission CSV was not kept:")
            for problem in problems:
                print(f"  {problem}")
        else:
            print(f"submission CSV with {len(replies)} answers saved to {submission_csv}")
    if usage:
        print(f"tokens: {dict(usage)}  cost: ${cost_dollars(usage, model or MODEL):.2f}")
    print(f"replies saved to {results_path}")
    return exit_code


def report(results: Counter[tuple[str, bool]]) -> None:
    print("\nkind                  correct / total")
    for kind in sorted({kind for kind, _ in results}):
        correct, wrong = results[(kind, True)], results[(kind, False)]
        print(f"  {kind:20s} {correct:4d} / {correct + wrong}")
    total_correct = sum(count for (_, correct), count in results.items() if correct)
    total = sum(results.values())
    print(f"  {'all':20s} {total_correct:4d} / {total}  ({total_correct / max(total, 1):.0%})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="benchmark.evaluate")
    parser.add_argument("directory", type=Path, help="a split directory such as data/dev")
    parser.add_argument("--per-kind", type=int, default=None, help="sample this many questions per kind")
    parser.add_argument("--kinds", nargs="+", default=None, help="only these question kinds")
    parser.add_argument(
        "--agent", default=None, help=f"module:function of the agent (default: {DEFAULT_AGENT})"
    )
    parser.add_argument("--name", default="results", help="file name for the saved replies")
    parser.add_argument(
        "--submission-csv", type=Path, default=None, help="also write question_id,answer for the judge app"
    )
    parser.add_argument(
        "--debug", action="store_true", help="print each question and the run-library questions it matched"
    )
    parser.add_argument(
        "--model", choices=MODELS, default=None,
        help=f"Claude model (default: the agent's own; final_agent: {DEFAULT_MODEL})",
    )
    arguments = parser.parse_args()
    if arguments.debug:
        enable_debug_log(arguments.agent)
    raise SystemExit(run(
        arguments.directory,
        arguments.per_kind,
        arguments.agent,
        arguments.name,
        arguments.submission_csv,
        arguments.kinds,
        MODELS[arguments.model] if arguments.model else None,
    ))


if __name__ == "__main__":
    main()
