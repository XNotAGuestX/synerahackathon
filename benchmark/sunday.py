"""Fail closed until the organizers announce the Sunday input schema.

Do not invent question fields, route fields, or an answers file.
"""

import sys
from pathlib import Path


def explain(path: Path | None) -> str:
    """The reason this command will not write Sunday answers."""
    if path is None:
        return "Pass the Sunday input path. No schema has been announced, so no answers file was written."
    if not path.exists():
        return f"Sunday input was not found: {path}. No answers file was written."
    return (
        f"Sunday input exists at {path}, but the announced field schema has not been recorded. "
        "Refusing to guess question, route, or answer fields. No answers file was written."
    )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    path = Path(arguments[0]) if arguments else None
    print(explain(path))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
