"""Per-session live position and spoken guidance state. Never touches session revision or history."""

import threading
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Callable

from .building_map import DOOR_PREFIX, BuildingMap
from .narration import render
from .navigator import Fix, NavEvent, Navigator
from .waypoints import RouteWalk, route_walk, space_containing

EVENT_RING = 100
CLIP_LIMIT = 200
MAX_WAIT_S = 25.0


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class LiveState:
    STALE_S = 15.0

    def __init__(self, clock: Callable[[], datetime], new_id: Callable[[], str], *,
                 narrate: Callable[[BuildingMap, RouteWalk], dict[int, str]] | None = None,
                 prewarm: Callable[[list[str]], None] | None = None, first_wait_s: float = 2.5) -> None:
        self.clock, self.new_id = clock, new_id
        self._narrate, self._prewarm, self._first_wait_s = narrate, prewarm, first_wait_s
        self._nav_gen = 0
        self._gen = 0  # bumped by start/stop/close so a late narration result is discarded
        self._texts: dict[int, str] = {}
        self._narrated = threading.Event()
        self._cond = threading.Condition(threading.Lock())
        self._fix: Fix | None = None
        self._events: deque[dict] = deque(maxlen=EVENT_RING)
        self._seq = 0
        self._clips: OrderedDict[str, str] = OrderedDict()
        self._closed = False
        self._status = "idle"
        self._route_id: str | None = None
        self._destination_id: str | None = None
        self._destination_name: str | None = None
        self._nav: Navigator | None = None
        self._walk: RouteWalk | None = None
        self._elements: frozenset[str] = frozenset()
        self.spoken = False

    # Fixes

    def apply_fix(self, building_map: BuildingMap, body: dict) -> dict:
        from .api_session import ApiError  # api_session imports this module

        floor_id = body["floor_id"]
        if floor_id not in building_map.floors:
            raise ApiError("20001_validation_failed", [{"field": "floor_id", "code": "unknown"}])
        point = (float(body["x_m"]), float(body["y_m"]))
        measured = body["measured_at"]
        if isinstance(measured, str):
            measured = datetime.fromisoformat(measured.replace("Z", "+00:00"))
        with self._cond:
            active = self._status == "active" and self._nav is not None
            prefer = self._walk.space_ids if active else ()
            fix = Fix(floor_id, point, measured, self.clock(), body["source"],
                      space_containing(building_map, floor_id, point, prefer), body.get("accuracy_m"))
            applied = self._fix is None or fix.measured_at > self._fix.measured_at
            if applied:
                self._fix = fix
                if active:
                    for event in self._nav.on_fix(fix):
                        self._emit(event.kind, event.text, event.waypoint_index)
                    if self._nav.finished:
                        self._status = "arrived"
            return {"position": self._position(), "applied": applied, "guidance": self._summary()}

    def _tracking(self) -> str:
        if self._fix is None:
            return "none"
        return "live" if (self.clock() - self._fix.measured_at).total_seconds() <= self.STALE_S else "stale"

    def _position(self) -> dict | None:
        fix = self._fix
        if fix is None:
            return None
        return {"floor_id": fix.floor_id, "x_m": fix.point[0], "y_m": fix.point[1], "accuracy_m": fix.accuracy_m,
                "space_id": fix.space_id, "measured_at": iso(fix.measured_at), "received_at": iso(fix.received_at),
                "source": fix.source, "tracking": self._tracking()}

    def position_view(self) -> dict | None:
        with self._cond:
            return self._position()

    def last_fix(self) -> Fix | None:
        """The latest applied fix, for emergency mode; None before the first one."""
        with self._cond:
            return self._fix

    # Guidance

    def start(self, building_map: BuildingMap, route_id: str, route_record: dict, route_result, spoken: bool) -> threading.Event:
        """Activate guidance without blocking; returns an event set once the first instruction is emitted.

        Callers may hold the session lock, so the wait for the narrator happens on a helper thread.
        """
        first_emitted = threading.Event()
        with self._cond:
            fix = self._fix
            fresh = fix is not None and (self.clock() - fix.measured_at).total_seconds() <= self.STALE_S
            start_point = fix.point if fresh and fix.space_id == route_result.start_space_id else None
            walk = route_walk(building_map, route_result, start_point)
            self._gen += 1
            gen = self._gen
            self._texts, self._narrated = {}, threading.Event()
            narrated = self._narrated
            self._walk = walk
            self._route_id = route_id
            self._destination_id = route_record["destination_space_id"]
            self._destination_name = building_map.spaces[self._destination_id]["name"]
            self._elements = frozenset(
                {node[len(DOOR_PREFIX):] for node in route_result.node_path if node.startswith(DOOR_PREFIX)}
                | set(route_result.edge_path) | set(route_result.space_path))
            self.spoken = spoken
            self._status = "active"
            self._nav_gen = gen
            self._nav = Navigator(walk, self._destination_name, texts=self._texts, clock=self.clock)
            first = self._nav.start()  # initialises progress now; the first instruction may wait for the narrator
            if self._narrate is None:
                self._emit_first(gen, first, first_emitted)
                return first_emitted
        threading.Thread(target=self._narrate_walk, args=(gen, building_map, walk, spoken), daemon=True).start()
        threading.Thread(target=self._emit_first_after_narration, args=(gen, narrated, first, first_emitted), daemon=True).start()
        return first_emitted

    def _emit_first_after_narration(self, gen: int, narrated: threading.Event, first: list, done: threading.Event) -> None:
        narrated.wait(self._first_wait_s)
        with self._cond:
            self._emit_first(gen, first, done)

    def _emit_first(self, gen: int, first: list, done: threading.Event) -> None:
        """Emit the navigator's start events with the latest (possibly narrated) text. Caller holds self._cond."""
        if self._gen == gen and self._nav is not None:
            for event in first:
                indexed = event.kind == "instruction" and event.waypoint_index is not None
                self._emit(event.kind, self._nav.text_for(event.waypoint_index) if indexed else event.text, event.waypoint_index)
        done.set()

    def _narrate_walk(self, gen: int, building_map: BuildingMap, walk: RouteWalk, spoken: bool) -> None:
        try:
            texts = self._narrate(building_map, walk)
        except Exception:
            texts = {}
        with self._cond:
            if self._gen != gen:
                return
            self._texts = dict(texts)
            if self._nav is not None and self._nav_gen == gen:
                self._nav.set_texts(texts)
            self._narrated.set()
        if spoken and self._prewarm is not None:
            try:
                self._prewarm([texts.get(w.index) or render(w) for w in walk.waypoints])
            except Exception:
                pass  # pre-warming is best effort

    def stop(self, reason: str, text: str | None = None) -> None:
        with self._cond:
            if reason == "cancelled" or self._status == "active":
                self._gen += 1
            if reason == "cancelled":
                self._status, self._route_id, self._walk, self._nav = "idle", None, None, None
                self._destination_id = self._destination_name = None
                self._elements = frozenset()
            elif self._status == "active":
                self._status = "stopped"
            else:
                return
            if text:
                self._emit("stopped", text, None)
            self._cond.notify_all()

    def close(self) -> None:
        with self._cond:
            self._gen += 1
            self._closed = True
            self._cond.notify_all()
        self.stop("closed")

    def blocked_by(self, closed_ids: set[str]) -> bool:
        with self._cond:
            return self._status == "active" and bool(self._elements & set(closed_ids))

    def _summary(self) -> dict:
        status = self._nav.status() if self._nav is not None and self._status != "stopped" else None
        return {"status": self._status, "target_index": status["target_index"] if status else None,
                "remaining_m": status["remaining_m"] if status else None, "cursor": self._seq}

    def guidance_view(self) -> dict:
        with self._cond:
            nav, walk = self._nav, self._walk
            status = nav.status() if nav is not None and self._status != "stopped" else None
            waypoints = []
            if walk is not None:
                waypoints = [{"index": w.index, "kind": w.kind, "floor_id": w.floor_id, "at": list(w.at),
                              "text": nav.text_for(w.index)} for w in walk.waypoints]
            return {"status": self._status, "route_id": self._route_id, "destination_space_id": self._destination_id,
                    "destination_name": self._destination_name,
                    "target_index": status["target_index"] if status else None, "waypoints": waypoints,
                    "remaining_m": status["remaining_m"] if status else None, "tracking": self._tracking()}

    # Events and clips

    def _emit(self, kind: str, text: str, waypoint_index: int | None) -> None:
        self._seq += 1
        self._events.append({"seq": self._seq, "kind": kind, "text": text, "route_id": self._route_id,
                             "waypoint_index": waypoint_index, "speech_clip_id": self._clip(text),
                             "created_at": iso(self.clock())})
        self._cond.notify_all()

    def events_after(self, after: int, wait_s: float) -> tuple[list[dict], int]:
        deadline = min(max(wait_s, 0.0), MAX_WAIT_S)
        with self._cond:
            self._cond.wait_for(lambda: self._closed or self._seq > after, timeout=deadline)
            return [dict(event) for event in self._events if event["seq"] > after], self._seq

    def _clip(self, text: str) -> str:
        clip_id = self.new_id()
        self._clips[clip_id] = text
        while len(self._clips) > CLIP_LIMIT:
            self._clips.popitem(last=False)
        return clip_id

    def clip(self, text: str) -> str:
        with self._cond:
            return self._clip(text)

    def clip_text(self, clip_id: str) -> str | None:
        with self._cond:
            return self._clips.get(clip_id)
