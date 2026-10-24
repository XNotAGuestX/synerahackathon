"""Prüft die erzeugten Beispiele gegen die OpenAPI-Schemas.

    uv run --with pyyaml --with jsonschema --with referencing python scripts/validate_api_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs" / "api" / "openapi.yaml"
EXAMPLES = ROOT / "docs" / "api" / "examples"
MAPPING = {
    "buildings-page.json": "BuildingPage",
    "buildings-page-2.json": "BuildingPage",
    "building-detail.json": "BuildingDetail",
    "session.json": "Session",
    "floor-index.json": "FloorIndex",
    "floor-plan.json": "FloorPlan",
    "floor-plan-closed.json": "FloorPlan",
    "places-page.json": "PlacePage",
    "route.json": "Route",
    "route-unreachable.json": "Route",
    "message-accepted.json": "MessageAccepted",
    "message-clarify.json": "MessageAccepted",
    "message-pending-action.json": "MessageAccepted",
    "message-page.json": "MessagePage",
    "action-pending.json": "Action",
    "action-confirmed.json": "Action",
    "error-validation.json": "Error",
    "error-ambiguous.json": "Error",
    "health.json": "Health",
}


def main() -> int:
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    registry = Registry().with_resource(uri="urn:openapi", resource=resource)
    failed = 0
    for name, schema_name in MAPPING.items():
        path = EXAMPLES / name
        if not path.exists():
            failed += 1
            print(f"MISSING {name}")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        schema = {"$ref": f"urn:openapi#/components/schemas/{schema_name}"}
        validator = Draft202012Validator(schema, registry=registry)
        errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
        if not errors:
            print(f"OK   {name}")
            continue
        failed += 1
        print(f"FAIL {name} -> {schema_name} ({len(errors)})")
        for err in errors[:12]:
            loc = "/".join(str(part) for part in err.path) or "<root>"
            print(f"  {loc}: {err.message}")
    print(f"failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
