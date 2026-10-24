"""Project agent adapter for ``benchmark.evaluate --agent final_agent.benchmark:answer``.

Also checks a finished submission file:  python -m final_agent.benchmark --check agent_output/submission.csv
"""

import argparse
import csv
import io
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmark.score import committed_answer

from .agent import BuildingAgent
from .building_map import BuildingMap

SUBMISSION_HEADER = ["question_id", "answer"]
MAX_SUBMISSION_BYTES = 5_000_000
DEFAULT_TEMPLATE = Path("data/test/submission_template.csv")
LISTED_IDS = 5


def answer(building_directory: Path, question_text: str) -> str:
    """Answer one question with a fresh map, conversation and temporary outputs.

    Edits and closures affect only this question. Scratch images and snapshots
    are removed afterward; the benchmark runner retains the returned reply.
    """
    with TemporaryDirectory(prefix="final-agent-benchmark-") as temporary:
        agent = BuildingAgent(BuildingMap.load(building_directory), Path(temporary))
        return agent.ask(question_text)


def listed(ids: list[str]) -> str:
    shown = ", ".join(ids[:LISTED_IDS])
    return shown + (f" and {len(ids) - LISTED_IDS} more" if len(ids) > LISTED_IDS else "")


def template_ids(template_path: Path) -> list[str]:
    with template_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    return [row[0] for row in rows[1:] if row]


def validate_submission(csv_path: Path, template_path: Path = DEFAULT_TEMPLATE) -> list[str]:
    """Return the problems that would cost points or get the file rejected; empty means valid."""
    raw = csv_path.read_bytes()
    problems = []
    if len(raw) > MAX_SUBMISSION_BYTES:
        problems.append(f"file is {len(raw)} bytes; the limit is {MAX_SUBMISSION_BYTES}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        return problems + [f"not valid UTF-8: {error}"]
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as error:
        return problems + [f"CSV quoting is malformed: {error}"]
    if not rows or rows[0] != SUBMISSION_HEADER:
        found = rows[0] if rows else "an empty file"
        return problems + [f"header must be exactly {','.join(SUBMISSION_HEADER)} (no BOM); found {found}"]

    malformed = [index for index, row in enumerate(rows[1:], start=2) if len(row) != 2]
    if malformed:
        problems.append(f"rows with other than 2 columns (CSV row numbers): {listed([str(i) for i in malformed])}")
    replies: dict[str, list[str]] = {}
    for row in rows[1:]:
        if len(row) == 2:
            replies.setdefault(row[0], []).append(row[1])

    expected = template_ids(template_path)
    if len(set(expected)) != len(expected):
        problems.append(f"template {template_path} lists duplicate ids")
    missing = [question_id for question_id in expected if question_id not in replies]
    extra = sorted(set(replies) - set(expected))
    duplicates = sorted(question_id for question_id, found in replies.items() if len(found) > 1)
    empty = [question_id for question_id, found in replies.items() if not found[0].strip()]
    no_answer_line = [
        question_id for question_id, found in replies.items() if found[0].strip() and committed_answer(found[0]) is None
    ]
    for label, ids in (
        (f"missing from the {len(expected)} template ids", missing),
        ("ids not in the template", extra),
        ("duplicate ids", duplicates),
        ("empty replies", empty),
        ("replies without an 'Answer:' line", no_answer_line),
    ):
        if ids:
            problems.append(f"{len(ids)} {label}: {listed(ids)}")

    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(rows)
    if list(csv.reader(io.StringIO(buffer.getvalue(), newline=""))) != rows:
        problems.append("rows do not survive a normal CSV write/read round trip")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(prog="final_agent.benchmark", description="Check a submission CSV.")
    parser.add_argument("--check", type=Path, required=True, metavar="CSV", help="submission file to validate")
    parser.add_argument(
        "--template", type=Path, default=DEFAULT_TEMPLATE, help="submission_template.csv listing the expected ids"
    )
    arguments = parser.parse_args()
    try:
        problems = validate_submission(arguments.check, arguments.template)
    except OSError as error:
        print(f"INVALID: cannot read file: {error}")
        return 1
    if problems:
        print(f"INVALID: {arguments.check}")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"OK: {arguments.check} has every id of {arguments.template}, each with an Answer: line.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
