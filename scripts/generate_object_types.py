"""Generate final_agent/object_types.json from the train and dev buildings; deterministic, no model calls.

Run: uv run python scripts/generate_object_types.py
"""

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from final_agent.building_map import NEW_DOOR_WIDTH_M  # noqa: E402
from final_agent.object_catalog import object_height, read_catalog  # noqa: E402
from final_agent.object_edits import CATALOG_PATH, type_label  # noqa: E402

CATEGORIES = ("furniture", "equipment", "fixture", "machine")
STEP_M = 0.05
# Heights come from the shared 3D object catalog (final_agent/object_catalog.json), so the editor,
# the stacking file and the 3D view agree on one height per type.
CATEGORY_HEIGHTS_M = read_catalog()["defaults"]["category_heights_m"]
CONNECTIONS = (
    ("same_floor", "Same floor", "add_opening", (("door", "Door"), ("opening", "Passage"))),
    ("between_floors", "Between floors", "add_connector", (("stairs", "Stairs"), ("escalator", "Escalator"), ("lift", "Lift"))),
)


def rounded(value: float) -> float:
    """A dataset median on the 5 cm grid, at least 5 cm."""
    return max(STEP_M, round(round(value / STEP_M) * STEP_M, 2))


def collect(data: Path) -> tuple[dict, dict, dict]:
    """Footprints by (category, type), opening widths by kind and connector counts by kind."""
    sizes: dict[tuple[str, str], list[tuple[float, float]]] = {}
    widths: dict[str, list[float]] = {}
    connectors: dict[str, int] = {}
    paths = sorted(data.glob("train/*/building.json")) + sorted(data.glob("dev/*/building.json"))
    for path in paths:
        building = json.loads(path.read_text(encoding="utf-8"))
        for asset in building["assets"]:
            if asset["category"] not in CATEGORIES:
                raise ValueError(f"{path}: unknown asset category {asset['category']!r}.")
            footprint = asset["footprint"]
            sizes.setdefault((asset["category"], asset["type"]), []).append(
                (footprint["width_m"], footprint["depth_m"])
            )
        for opening in building["openings"]:
            widths.setdefault(opening["kind"], []).append(opening["width_m"])
        for connector in building["vertical_connectors"]:
            connectors[connector["kind"]] = connectors.get(connector["kind"], 0) + 1
    return sizes, widths, connectors


def catalog(data: Path) -> dict:
    sizes, widths, connectors = collect(data)
    items = []
    for category in CATEGORIES:
        types = [
            {
                "id": type_id, "label": type_label(type_id), "action": "add_object",
                "width_m": rounded(statistics.median(width for width, _ in footprints)),
                "depth_m": rounded(statistics.median(depth for _, depth in footprints)),
                "height_m": object_height({"type": type_id, "category": category}),
                "count": len(footprints),
            }
            for (item_category, type_id), footprints in sizes.items() if item_category == category
        ]
        items.append({
            "id": category, "label": type_label(category), "height_m": CATEGORY_HEIGHTS_M[category],
            "types": sorted(types, key=lambda item: (item["label"], item["id"])),
        })
    connection_widths = {"door": NEW_DOOR_WIDTH_M, "opening": rounded(statistics.median(widths["opening"]))}
    counts = {kind: len(values) for kind, values in widths.items()} | connectors
    connections = [
        {
            "id": category_id, "label": label, "height_m": None,
            "types": [
                {"id": type_id, "label": type_name, "action": action, "width_m": connection_widths.get(type_id),
                 "depth_m": None, "height_m": None, "count": counts.get(type_id, 0)}
                for type_id, type_name in types
            ],
        }
        for category_id, label, action, types in CONNECTIONS
    ]
    return {
        "schema_version": 1,
        "groups": [
            {"id": "items", "label": "Items", "categories": items},
            {"id": "connections", "label": "Connections", "categories": connections},
        ],
    }


def main() -> None:
    contents = json.dumps(catalog(ROOT / "data"), indent=2, ensure_ascii=False) + "\n"
    with open(CATALOG_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(contents)
    print(f"Wrote {CATALOG_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
