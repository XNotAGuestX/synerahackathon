"""Follows a RouteWalk from live position fixes: decides when a waypoint is reached, what to say next, and wrong-way."""

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .narration import arrived_text, render, stop_reached_text, wrong_way_text
from .waypoints import Point2, RouteWalk

STALE_S = 15.0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Fix:
    floor_id: str
    point: Point2
    measured_at: datetime
    received_at: datetime
    source: str  # "simulated" | "wifi" | "manual"
    space_id: str | None  # resolved by space_containing
    accuracy_m: float | None = None


@dataclass(frozen=True)
class NavEvent:
    kind: str  # "instruction" | "wrong_way" | "arrived"
    text: str
    waypoint_index: int | None


class Navigator:
    REACH_RADIUS_M = 3.0
    LOOKAHEAD = 3
    WRONG_WAY_MARGIN_M = 3.0
    JUMP_M = 5.0

    def __init__(self, walk: RouteWalk, destination_name: str, texts: dict[int, str] | None = None,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self.walk = walk
        self.destination_name = destination_name
        self.texts = dict(texts or {})
        self.clock = clock
        self.target = 0
        self._finished = False
        self._warned = False
        self._best = math.inf  # smallest remaining distance to the current target so far
        self._bad = 0  # consecutive fixes farther than best + margin
        self._progress = 0.0
        self._last: Fix | None = None

    def set_texts(self, texts: dict[int, str]) -> None:
        self.texts.update(texts)

    def text_for(self, index: int) -> str:
        return self.texts.get(index) or render(self.walk.waypoints[index])

    @property
    def finished(self) -> bool:
        return self._finished

    def start(self) -> list[NavEvent]:
        return [NavEvent("instruction", self.text_for(0), 0)]

    def status(self) -> dict:
        remaining = 0.0 if self._finished else max(0.0, self.walk.total_m - self._progress)
        return {"target_index": self.target, "remaining_m": round(remaining, 1), "finished": self._finished,
                "warned": self._warned}

    def _window(self, index: int) -> tuple[float, float]:
        waypoints = self.walk.waypoints
        return (waypoints[index - 1].arc_m if index else 0.0) - 2.0, waypoints[index].arc_m + 6.0

    def _reached(self, index: int, fix: Fix) -> bool:
        waypoint = self.walk.waypoints[index]
        if fix.floor_id != waypoint.floor_id:
            return False
        if waypoint.kind == "connector_exit":
            return True  # any position on the new floor counts
        ahead = index > self.target  # a skipped-to door or stop needs its own rule, not just closeness
        if fix.space_id is not None and fix.space_id == waypoint.next_space_id:
            if waypoint.kind in ("door", "stop") or (waypoint.kind == "arrival" and not ahead):
                return True
        on_route = fix.space_id is None or fix.space_id in self.walk.space_ids
        if on_route and math.dist(fix.point, waypoint.at) <= self.REACH_RADIUS_M:
            if not (ahead and waypoint.kind in ("door", "stop")):
                return True
        if waypoint.kind == "turn":
            progress = self.walk.project(fix.floor_id, fix.point, *self._window(index))
            return progress is not None and progress[0] >= waypoint.arc_m and progress[1] <= 4.0
        return False

    def on_fix(self, fix: Fix) -> list[NavEvent]:
        if self._finished:
            return []
        last = self._last
        if (last is not None and fix.measured_at <= last.measured_at) or \
                (self.clock() - fix.measured_at).total_seconds() > STALE_S:
            return []
        self._last = fix
        waypoints = self.walk.waypoints
        reached = [index for index in range(self.target, min(self.target + self.LOOKAHEAD + 1, len(waypoints)))
                   if self._reached(index, fix)]
        if reached:
            return self._advance(reached, waypoints)
        projected = self.walk.project(fix.floor_id, fix.point, *self._window(self.target))
        if projected is None:
            return []  # neither progress nor wrong way
        self._progress = projected[0]
        remaining = waypoints[self.target].arc_m - projected[0]
        if last is not None and (fix.source == "manual" or fix.floor_id != last.floor_id
                                 or math.dist(fix.point, last.point) > self.JUMP_M):
            self._best, self._bad = remaining, 0
            return []
        self._best = min(self._best, remaining)
        self._bad = self._bad + 1 if remaining >= self._best + self.WRONG_WAY_MARGIN_M else 0
        if self._bad >= 2 and not self._warned:
            self._warned = True
            return [NavEvent("wrong_way", wrong_way_text(waypoints[self.target]), self.target)]
        return []

    def _advance(self, reached: list[int], waypoints) -> list[NavEvent]:
        index = reached[-1]  # furthest reached; skipped instructions are never repeated
        self._progress = max(self._progress, waypoints[index].arc_m)
        if waypoints[index].kind == "arrival":
            self._finished = True
            self.target = index
            return [NavEvent("arrived", arrived_text(self.destination_name), index)]
        # A new target re-arms the wrong-way warning.
        self.target, self._warned, self._best, self._bad = index + 1, False, math.inf, 0
        text = self.text_for(index + 1)
        stop = next((waypoints[i] for i in reversed(reached) if waypoints[i].kind == "stop"), None)
        if stop is not None:
            text = f"{stop_reached_text(stop.name or 'the stop')} {text}"
        return [NavEvent("instruction", text, index + 1)]
