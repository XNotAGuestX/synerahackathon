"""JSON persistence and Cartesian spatial indexes for indoor building data."""

import json
import math
import os
import tempfile
from pathlib import Path

from shapely import STRtree
from shapely.geometry import Point, Polygon


class JsonBuildingStore:
    """Keep the dataset format, replacing a saved file only after writing succeeds."""

    @staticmethod
    def load(path: Path) -> dict:
        path = Path(path)
        if path.is_dir():
            path /= "building.json"
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def save(path: Path, building: dict) -> None:
        path = Path(path)
        if path.is_dir():
            path /= "building.json"
        contents = json.dumps(building, indent=1, ensure_ascii=False, allow_nan=False) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(contents)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


class BuildingSpatialIndex:
    """One immutable STRtree per floor and element kind, using local metres.

    Rooms use their polygons; assets and openings use their positions. Rebuild
    after geometry changes. Indexes are derived from JSON and stay in memory.
    """

    KINDS = {"space": "spaces", "asset": "assets", "opening": "openings"}

    def __init__(self, building: dict) -> None:
        self.levels = {floor["id"]: floor["level"] for floor in building["floors"]}
        self.indexes: dict[tuple[str, str], tuple[list[dict], STRtree]] = {}
        for kind, collection in self.KINDS.items():
            by_floor: dict[str, list[dict]] = {}
            for element in building[collection]:
                by_floor.setdefault(element["floor_id"], []).append(element)
            for floor_id, elements in by_floor.items():
                geometries = [
                    Polygon(element["polygon"]) if kind == "space" else Point(element["position"])
                    for element in elements
                ]
                self.indexes[(floor_id, kind)] = (elements, STRtree(geometries))

    def search(
        self, x_m: float, y_m: float, floor_level: int, radius_m: float = 0,
        kind: str = "all",
    ) -> list[dict]:
        """Return elements within radius, sorted by distance then kind and id.

        A radius of zero includes rooms containing or touching the point.
        Distances to rooms are measured to their polygon, not their centre.
        """
        if not all(math.isfinite(value) for value in (x_m, y_m, radius_m)) or radius_m < 0:
            raise ValueError("Coordinates and radius must be finite; radius must be non-negative.")
        if kind != "all" and kind not in self.KINDS:
            raise ValueError("kind must be all, space, asset or opening.")
        if floor_level not in self.levels.values():
            raise ValueError(f"Unknown floor level: {floor_level}.")
        point = Point(x_m, y_m)
        results = []
        for (floor_id, element_kind), (elements, tree) in self.indexes.items():
            if self.levels[floor_id] != floor_level or kind not in ("all", element_kind):
                continue
            for index in tree.query(point, predicate="dwithin", distance=radius_m):
                element = elements[index]
                results.append({
                    "kind": element_kind,
                    "id": element["id"],
                    "name": element.get("name", element["id"]),
                    "floor_level": floor_level,
                    "distance_m": float(point.distance(tree.geometries[index])),
                })
        return sorted(results, key=lambda item: (item["distance_m"], item["kind"], item["id"]))
