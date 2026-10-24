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
_ROOM_NOTE_SELECT = """
    SELECT room_notes.*,
           (SELECT COUNT(*) FROM room_note_confirmations
            WHERE room_note_confirmations.note_id = room_notes.note_id) AS confirmation_count
    FROM room_notes
"""


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
            self._ensure_schema(connection)
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(room_notes)")}
        confirmations = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'room_note_confirmations'"
        ).fetchone()
        if "category" in columns and confirmations is not None:
            return
        # Recheck under the write lock: two chats may open an old database together.
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS room_notes (
                    note_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    facility_number TEXT NOT NULL,
                    space_id TEXT NOT NULL,
                    room_number TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    resolved_at TEXT,
                    category TEXT NOT NULL DEFAULT 'legacy'
                        CHECK (category IN ('general', 'safety', 'legacy'))
                )
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(room_notes)")}
            if "category" not in columns:
                connection.execute("ALTER TABLE room_notes ADD COLUMN category TEXT NOT NULL DEFAULT 'legacy'")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS room_note_confirmations (
                    note_id INTEGER NOT NULL REFERENCES room_notes(note_id),
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    PRIMARY KEY (note_id, session_id)
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS room_notes_room
                ON room_notes (facility_number, space_id, resolved_at)
            """)

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        # Each report operation commits on its own, so a long model turn never holds the
        # write lock while another chat reports or confirms. A failed operation rolls back whole.
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    @staticmethod
    def _record(row: sqlite3.Row) -> dict:
        note = dict(row)
        if note["resolved_at"] is not None:
            note["status"] = "resolved"
        elif note["category"] == "general" and note["confirmation_count"] < 2:
            note["status"] = "pending"
        else:
            note["status"] = "active"
        return note

    @staticmethod
    def _check_session(session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("Give a non-empty report session id.")

    @staticmethod
    def _check_note_id(note_id: int) -> None:
        if type(note_id) is not int or note_id <= 0:
            raise ValueError("Give a positive integer report id returned by get_room_notes.")

    def add(
        self, facility_number: str, space_id: str, room_number: str, text: str, *,
        session_id: str, category: str = "general",
    ) -> dict:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Give a non-empty room report.")
        text = text.strip()
        if len(text) > MAX_ROOM_NOTE_LENGTH:
            raise ValueError(f"Room reports must be at most {MAX_ROOM_NOTE_LENGTH} characters.")
        if category not in ("general", "safety"):
            raise ValueError("Report category must be general or safety.")
        self._check_session(session_id)
        with self._write() as connection:
            # Exact repeats also merge when a caller forgets to use confirm. Semantic
            # matching (same device and issue, different wording) belongs to the agent.
            existing = connection.execute(
                "SELECT note_id FROM room_notes WHERE facility_number = ? AND space_id = ? "
                "AND text = ? AND category = ? AND resolved_at IS NULL ORDER BY note_id LIMIT 1",
                (facility_number, space_id, text, category),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    "INSERT INTO room_notes (facility_number, space_id, room_number, text, category) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (facility_number, space_id, room_number, text, category),
                )
                note_id = cursor.lastrowid
            else:
                note_id = existing["note_id"]
            connection.execute(
                "INSERT INTO room_note_confirmations (note_id, session_id) VALUES (?, ?) "
                "ON CONFLICT (note_id, session_id) DO NOTHING",
                (note_id, session_id),
            )
            note = connection.execute(_ROOM_NOTE_SELECT + " WHERE note_id = ?", (note_id,)).fetchone()
        return self._record(note)

    def active(
        self, facility_number: str, space_ids: list[str], *, include_pending: bool = False,
        reporting_session_id: str | None = None,
    ) -> list[dict]:
        """Return active reports and, optionally, pending reports created by this chat."""
        if reporting_session_id is not None:
            self._check_session(reporting_session_id)
        space_ids = list(dict.fromkeys(space_ids))
        if not space_ids or not self.path.exists():
            return []
        placeholders = ",".join("?" for _ in space_ids)
        eligibility = ""
        parameters: list[str] = [facility_number, *space_ids]
        if not include_pending:
            eligibility = " AND (category IN ('safety', 'legacy') OR confirmation_count >= 2"
            if reporting_session_id is not None:
                eligibility += (
                    " OR EXISTS (SELECT 1 FROM room_note_confirmations AS viewer_confirmation "
                    "WHERE viewer_confirmation.note_id = note_view.note_id AND viewer_confirmation.session_id = ?)"
                )
                parameters.append(reporting_session_id)
            eligibility += ")"
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM ({_ROOM_NOTE_SELECT}) AS note_view WHERE facility_number = ? "
                f"AND space_id IN ({placeholders}) AND resolved_at IS NULL{eligibility} ORDER BY note_id",
                parameters,
            ).fetchall()
        return [self._record(row) for row in rows]

    def confirm(self, facility_number: str, space_id: str, note_id: int, *, session_id: str) -> dict:
        self._check_note_id(note_id)
        self._check_session(session_id)
        if not self.path.exists():
            raise ValueError("No reports saved yet. Use get_room_notes with include_pending=true first.")
        with self._write() as connection:
            connection.execute(
                "INSERT INTO room_note_confirmations (note_id, session_id) "
                "SELECT note_id, ? FROM room_notes "
                "WHERE facility_number = ? AND space_id = ? AND note_id = ? AND resolved_at IS NULL "
                "ON CONFLICT (note_id, session_id) DO NOTHING",
                (session_id, facility_number, space_id, note_id),
            )
            note = connection.execute(
                _ROOM_NOTE_SELECT + " WHERE facility_number = ? AND space_id = ? AND note_id = ? AND resolved_at IS NULL",
                (facility_number, space_id, note_id),
            ).fetchone()
            if note is None:
                raise ValueError("No unresolved report with that id in this facility and room.")
        return self._record(note)

    def resolve(self, facility_number: str, space_id: str, note_id: int) -> dict:
        self._check_note_id(note_id)
        if not self.path.exists():
            raise ValueError("No reports saved yet. Use get_room_notes to find an active report.")
        with self._write() as connection:
            cursor = connection.execute(
                "UPDATE room_notes SET resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE facility_number = ? AND space_id = ? AND note_id = ? AND resolved_at IS NULL",
                (facility_number, space_id, note_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("No unresolved report with that id in this facility and room. Use get_room_notes first.")
            note = connection.execute(_ROOM_NOTE_SELECT + " WHERE note_id = ?", (note_id,)).fetchone()
        return self._record(note)


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
