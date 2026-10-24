"""Validate generated examples against the authoritative OpenAPI 3.1 schemas."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jsonschema import Draft202012Validator, FormatChecker

from final_agent.api import load_contract


def validate(directory: Path) -> int:
    contract = load_contract()
    entries = json.loads((directory / "index.json").read_text())
    for entry in entries:
        path = (directory / entry["file"]).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("Fixture index points outside its directory.")
        schema = {"$ref": f"#/components/schemas/{entry['schema']}", "components": contract["components"]}
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(json.loads(path.read_text()))
    return len(entries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("docs/api/examples"))
    args = parser.parse_args()
    print(f"Validated {validate(args.directory)} examples against OpenAPI.")


if __name__ == "__main__":
    main()
