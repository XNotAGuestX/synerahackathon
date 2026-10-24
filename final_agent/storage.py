"""Local JSON/SQLite persistence and Cartesian spatial indexes for indoor building data."""

from contextlib import contextmanager
import json
import math
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path

from shapely import STRtree
from shapely.geometry import Point, Polygon


MAX_ROOM_NOTE_LENGTH = 4000


class RoomNoteStore:
    """User reports scoped to a facility and stable room id, shared across sessions.

    Room numbers are display labels (kept as text, including leading zeroes).
    Stable space ids distinguish repeated room numbers on different floors.
    The database is created on the first write; reads never create an empty file.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS room_notes (
                        note_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        facility_number TEXT NOT NULL,
                        space_id TEXT NOT NULL,
                        room_number TEXT NOT NULL,
                        text TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                        resolved_at TEXT
                    )
                """)
                connection.execute("""
                    CREATE INDEX IF NOT EXISTS room_notes_room
                    ON room_notes (facility_number, space_id, resolved_at)
                """)
                yield connection
        finally:
            connection.close()

    def add(self, facility_number: str, space_id: str, room_number: str, text: str) -> dict:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Give a non-empty room report.")
        text = text.strip()
        if len(text) > MAX_ROOM_NOTE_LENGTH:
            raise ValueError(f"Room reports must be at most {MAX_ROOM_NOTE_LENGTH} characters.")
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO room_notes (facility_number, space_id, room_number, text) VALUES (?, ?, ?, ?)",
                (facility_number, space_id, room_number, text),
            )
            note = connection.execute("SELECT * FROM room_notes WHERE note_id = ?", (cursor.lastrowid,)).fetchone()
        return dict(note)

    def active(self, facility_number: str, space_ids: list[str]) -> list[dict]:
        space_ids = list(dict.fromkeys(space_ids))
        if not space_ids or not self.path.exists():
            return []
        placeholders = ",".join("?" for _ in space_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM room_notes WHERE facility_number = ? AND space_id IN ({placeholders}) "
                "AND resolved_at IS NULL ORDER BY note_id",
                [facility_number, *space_ids],
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve(self, facility_number: str, space_id: str, note_id: int) -> dict:
        if not self.path.exists():
            raise ValueError("No reports saved yet. Use get_room_notes to find an active report.")
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE room_notes SET resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE facility_number = ? AND space_id = ? AND note_id = ? AND resolved_at IS NULL",
                (facility_number, space_id, note_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("No active report with that id in this facility and room. Use get_room_notes first.")
            note = connection.execute("SELECT * FROM room_notes WHERE note_id = ?", (note_id,)).fetchone()
        return dict(note)


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
