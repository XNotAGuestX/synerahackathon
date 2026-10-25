"""Stacking and object heights as stored in stacking_adapter.json, without geometry.

`supports` maps an object id to the ids it stands on; objects on the floor have no entry. Layers and
elevations are always derived: when a document is read, only object ids, supports and override heights
count. Problems raise ValueError with a clear message; BuildingMap.load turns them into MapError.
"""

import json
import math
import os
import tempfile
from pathlib import Path

STACKING_FILE = "stacking_adapter.json"
SCHEMA_VERSION = 1
HEIGHT_SOURCES = ("override", "catalog")
DECIMALS = 3


def layers(supports: dict[str, list[str]]) -> dict[str, int]:
    """Layer of every object that stands on or carries another: 0 on the floor, else one above its highest support."""
    found: dict[str, int] = {}
    visiting: set[str] = set()

    def layer(object_id: str) -> int:
        if object_id in found:
            return found[object_id]
        if object_id in visiting:
            raise ValueError(f"The supports form a cycle through {object_id}.")
        visiting.add(object_id)
        below = supports.get(object_id, [])
        found[object_id] = 1 + max(layer(support) for support in below) if below else 0
        visiting.discard(object_id)
        return found[object_id]

    for object_id in sorted({*supports, *(support for below in supports.values() for support in below)}):
        layer(object_id)
    return found


def elevations(supports: dict[str, list[str]], heights: dict[str, float]) -> dict[str, float]:
    """Underside of every involved object above its floor: the highest top (elevation + height) of its supports."""
    levels = layers(supports)
    found: dict[str, float] = {}
    for object_id in sorted(levels, key=lambda item: (levels[item], item)):
        below = supports.get(object_id, [])
        found[object_id] = max(found[support] + heights[support] for support in below) if below else 0.0
    return found


def descendants(supports: dict[str, list[str]], object_id: str) -> list[str]:
    """Everything standing on the object, directly or indirectly, sorted by id."""
    found: set[str] = set()
    frontier = [object_id]
    while frontier:
        current = frontier.pop()
        for other, below in supports.items():
            if current in below and other not in found and other != object_id:
                found.add(other)
                frontier.append(other)
    return sorted(found)


def to_document(
    building_id: str, supports: dict[str, list[str]], overrides: dict[str, float], heights: dict[str, float]
) -> dict:
    """The stacking_adapter.json document; heights are the effective heights of every listed object.

    Listed are all objects that stand on something, carry something or have a height override.
    """
    listed = layers(supports)
    for object_id in overrides:
        listed.setdefault(object_id, 0)
    lifts = elevations(supports, heights)
    by_layer: dict[int, list[dict]] = {}
    for object_id in sorted(listed):
        by_layer.setdefault(listed[object_id], []).append({
            "object_id": object_id,
            "on_top_of": sorted(supports.get(object_id, [])),
            "height_m": round(heights[object_id], DECIMALS),
            "height_source": "override" if object_id in overrides else "catalog",
            "elevation_m": round(lifts.get(object_id, 0.0), DECIMALS) + 0.0,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "building_id": building_id,
        "layers": [{"layer": layer, "objects": by_layer[layer]} for layer in sorted(by_layer)],
    }


def from_document(
    document: dict, building_id: str, asset_ids: set[str]
) -> tuple[dict[str, list[str]], dict[str, float]]:
    """Supports and override heights from a document; written layers, elevations and catalog heights are ignored."""
    if not isinstance(document, dict):
        raise ValueError("The stacking document must be a JSON object.")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}, got {document.get('schema_version')!r}.")
    if document.get("building_id") != building_id:
        raise ValueError(f"It belongs to building {document.get('building_id')!r}, not {building_id!r}.")
    groups = document.get("layers")
    if not isinstance(groups, list):
        raise ValueError("layers must be a list.")
    supports: dict[str, list[str]] = {}
    overrides: dict[str, float] = {}
    seen: set[str] = set()
    for group in groups:
        entries = group.get("objects") if isinstance(group, dict) else None
        if not isinstance(entries, list):
            raise ValueError("Every layer needs an objects list.")
        for entry in entries:
            object_id = entry.get("object_id") if isinstance(entry, dict) else None
            if not isinstance(object_id, str) or object_id not in asset_ids:
                raise ValueError(f"Unknown object id {object_id!r}.")
            if object_id in seen:
                raise ValueError(f"Object {object_id} is listed twice.")
            seen.add(object_id)
            below = entry.get("on_top_of", [])
            if not isinstance(below, list) or any(not isinstance(item, str) or item not in asset_ids for item in below):
                raise ValueError(f"on_top_of of {object_id} must list known object ids, got {below!r}.")
            if object_id in below:
                raise ValueError(f"Object {object_id} cannot stand on itself.")
            if below:
                supports[object_id] = sorted(set(below))
            source = entry.get("height_source", "catalog")
            if source not in HEIGHT_SOURCES:
                raise ValueError(f"height_source of {object_id} must be override or catalog, got {source!r}.")
            if source == "override":
                height = entry.get("height_m")
                if isinstance(height, bool) or not isinstance(height, (int, float)) or not math.isfinite(height) or height <= 0:
                    raise ValueError(f"The override height_m of {object_id} must be a number above 0, got {height!r}.")
                overrides[object_id] = float(height)
    layers(supports)  # rejects cycles
    return supports, overrides


def load(path: Path, building_id: str, asset_ids: set[str]) -> tuple[dict[str, list[str]], dict[str, float]]:
    """Supports and overrides from the file; a missing file means no stacks and no overrides."""
    path = Path(path)
    if not path.exists():
        return {}, {}
    return from_document(json.loads(path.read_text(encoding="utf-8")), building_id, asset_ids)


def save(path: Path, document: dict) -> None:
    """Replace the file atomically: UTF-8, two-space indent, LF and a final newline."""
    path = Path(path)
    contents = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
