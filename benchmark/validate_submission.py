"""Read-only checks for a public question_id,answer submission.

The writer keeps a file only when these checks pass. An empty answer or a partial
test-set file is not left behind as a successful submission.
"""

import csv
import io
from pathlib import Path

MAX_SUBMISSION_BYTES = 5 * 1024 * 1024
HEADER = ("question_id", "answer")


def template_ids(path: Path | None) -> list[str] | None:
    """IDs from data/test/submission_template.csv. None when this run is not that submission."""
    if path is None:
        return None
    with path.open(encoding="utf-8", newline="") as handle:
        return [row["question_id"] for row in csv.DictReader(handle)]


def reply_problems(replies: list[tuple[str, str]], expected_ids: list[str] | None) -> list[str]:
    """Problems visible before a file is written."""
    problems: list[str] = []
    ids = [question_id for question_id, _ in replies]
    empty = [question_id for question_id, answer in replies if not str(answer).strip()]
    if empty:
        shown = ", ".join(empty[:5])
        problems.append(f"{len(empty)} empty answer(s), including {shown}.")
    if len(ids) != len(set(ids)):
        problems.append("Duplicate question ids.")
    if expected_ids is not None and (len(ids) != len(expected_ids) or set(ids) != set(expected_ids)):
        missing = len(set(expected_ids) - set(ids))
        extra = len(set(ids) - set(expected_ids))
        problems.append(
            f"Expected {len(expected_ids)} unique test ids; missing {missing}, extra {extra}."
        )
    return problems


def file_problems(path: Path, expected_ids: list[str] | None) -> list[str]:
    """Problems in a written CSV: encoding, header, size and the same id rules."""
    problems: list[str] = []
    size = path.stat().st_size
    if size > MAX_SUBMISSION_BYTES:
        problems.append(f"Submission is {size} bytes; the limit is 5 MB.")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return problems + ["Submission is not UTF-8."]
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != HEADER:
        problems.append(f"Header must be question_id,answer; got {reader.fieldnames}.")
        return problems
    rows = [(row.get("question_id") or "", row.get("answer") or "") for row in reader]
    problems.extend(reply_problems(rows, expected_ids))
    return problems


def write_validated_submission(
    path: Path, replies: list[tuple[str, str]], template: Path | None = None,
) -> list[str]:
    """Write the CSV only when it satisfies the public submission rules. Return any problems."""
    expected = template_ids(template)
    problems = reply_problems(replies, expected)
    if problems:
        return problems
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(replies)
    problems = file_problems(path, expected)
    if problems:
        path.unlink(missing_ok=True)
    return problems
