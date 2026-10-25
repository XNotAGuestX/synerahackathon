"""Phrase catalogue for spoken guidance. The server fills every fact (distance, side, names); a narrator only picks ids."""

import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from .building_map import MapError
from .waypoints import RouteWalk, Waypoint, spoken_distance

NARRATOR_TIMEOUT_S = 8.0


@dataclass(frozen=True)
class Phrase:
    id: str
    kinds: frozenset[str]  # waypoint kinds it may describe
    template: str  # str.format slots: distance, side, space, landmark, connector, direction, floor, destination
    needs_landmark: bool


def _phrase(phrase_id: str, kind: str, template: str) -> tuple[str, Phrase]:
    return phrase_id, Phrase(phrase_id, frozenset({kind}), template, "{landmark}" in template)


PHRASES: dict[str, Phrase] = dict([
    _phrase("turn_in", "turn", "In {distance}, turn {side}."),
    _phrase("turn_past", "turn", "Walk past {landmark}, then turn {side}."),
    _phrase("turn_at", "turn", "Turn {side} at {landmark}."),
    _phrase("door_walk", "door", "Walk {distance} to the door into {space}."),
    _phrase("door_then_turn", "door", "Go through the door into {space}, then turn {side}."),
    _phrase("door_by", "door", "Take the door next to {landmark} into {space}."),
    _phrase("connector_walk", "connector_entry", "Walk {distance} to the {connector}."),
    _phrase("connector_by", "connector_entry", "Head for the {connector} by {landmark}."),
    _phrase("connector_take", "connector_exit", "Take the {connector} {direction} to {floor}."),
    _phrase("stop_walk", "stop", "Walk {distance} into {space}."),
    _phrase("stop_past", "stop", "Walk past {landmark} into {space}."),
    _phrase("arrival_ahead", "arrival", "{destination} is {distance} ahead."),
    _phrase("arrival_past", "arrival", "{destination} is just past {landmark}."),
])

DEFAULT_PHRASE: dict[str, str] = {
    "turn": "turn_in", "door": "door_walk", "connector_entry": "connector_walk",
    "connector_exit": "connector_take", "stop": "stop_walk", "arrival": "arrival_ahead",
}

SIDE_WORDS = {"left": "left", "right": "right", "slight_left": "slightly left", "slight_right": "slightly right",
              "sharp_left": "sharp left", "sharp_right": "sharp right"}


def render(waypoint: Waypoint, phrase_id: str | None = None, landmark_name: str | None = None) -> str:
    phrase = PHRASES.get(phrase_id or "")
    if (phrase is None or waypoint.kind not in phrase.kinds or (phrase.needs_landmark and not landmark_name)
            or ("{side}" in phrase.template and waypoint.side not in SIDE_WORDS)):
        phrase = PHRASES[DEFAULT_PHRASE[waypoint.kind]]
    text = phrase.template.format(
        distance=spoken_distance(waypoint.distance_m), side=SIDE_WORDS.get(waypoint.side or "", ""),
        space=waypoint.name or "", landmark=landmark_name or "", connector=waypoint.connector_kind or "",
        direction=waypoint.direction or "", floor=waypoint.target_floor_name or "", destination=waypoint.name or "")
    return text[0].upper() + text[1:]


def arrived_text(destination_name: str) -> str:
    return f"You've arrived at {destination_name}."


def stop_reached_text(name: str) -> str:
    return f"You've reached {name}."


def wrong_way_text(target: Waypoint) -> str:
    goal = {"door": f"the door into {target.name}", "turn": "the next turn", "stop": target.name,
            "arrival": target.name, "connector_entry": f"the {target.connector_kind}",
            "connector_exit": f"the {target.connector_kind}"}[target.kind]
    return f"Looks like you're heading away from {goal}. Turn around when you can."


# AI narrator: picks phrase ids and landmark ids only. Every fact in the final text comes from render().

NARRATOR_PROMPT = """You choose how each step of a walking route is worded for a voice guide.
You receive the route waypoints, the landmark candidates near each waypoint, and the phrase catalogue.
For every waypoint pick one phrase_id valid for its kind. A phrase with a {landmark} slot needs a landmark_id
taken from that waypoint's own candidate list. Otherwise landmark_id is null.
- Mix distances and landmarks: use a landmark for roughly half of the waypoints when candidates exist.
- Vary the wording of consecutive steps; do not repeat the same phrase back to back when another fits.
- Use only the listed phrase ids and landmark ids. Never invent either. Never write the sentences yourself.
Return one choice per waypoint index."""


class NarrationChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    phrase_id: str
    landmark_id: str | None


class NarrationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choices: list[NarrationChoice]


def landmark_candidates(building_map, waypoint: Waypoint) -> list[dict]:
    """Up to three unambiguous assets near a waypoint, nearest first."""
    try:
        found = building_map.find_navigation_landmarks(
            waypoint.at[0], waypoint.at[1], building_map.floors[waypoint.floor_id]["level"],
            inner_radius=4.0, outer_radius=15.0, kind="asset")
    except MapError:
        return []
    unambiguous = [item for item in found["candidates"] if item["is_unambiguous"]]
    unambiguous.sort(key=lambda item: item["distance_m"])
    return [{"id": item["id"], "name": item["name"], "distance_m": item["distance_m"]} for item in unambiguous[:3]]


def _checked_text(waypoint: Waypoint, choice: NarrationChoice | None, candidates: list[dict]) -> str:
    phrase = PHRASES.get(choice.phrase_id) if choice else None
    if phrase is None or waypoint.kind not in phrase.kinds:
        return render(waypoint)
    name = next((item["name"] for item in candidates if item["id"] == choice.landmark_id), None)
    if phrase.needs_landmark and name is None:
        return render(waypoint)
    return render(waypoint, phrase.id, name if phrase.needs_landmark else None)


def narrate(client, model: str, walk: RouteWalk, candidates_by_index: dict[int, list[dict]]) -> dict[int, str]:
    """Texts for every waypoint index; invalid choices and any failure fall back to the default wording."""
    defaults = {w.index: render(w) for w in walk.waypoints}
    try:
        payload = {
            "waypoints": [{"index": w.index, "kind": w.kind, "side": w.side, "distance_m": round(w.distance_m),
                           "landmark_candidates": candidates_by_index.get(w.index, [])} for w in walk.waypoints],
            "phrases": [{"id": p.id, "kind": sorted(p.kinds)[0], "template": p.template} for p in PHRASES.values()],
        }
        # The main agent already sends output_config.effort to haiku 5.5 (agent.py EFFORT), so it is accepted here too.
        message = client.beta.messages.parse(
            model=model, max_tokens=1500, system=NARRATOR_PROMPT, timeout=NARRATOR_TIMEOUT_S,
            messages=[{"role": "user", "content": json.dumps(payload, separators=(",", ":"))}],
            output_format=NarrationPlan, output_config={"effort": "low"})
        plan = message.parsed_output
        if plan is None:
            return defaults
        chosen = {choice.index: choice for choice in plan.choices}
        return {w.index: _checked_text(w, chosen.get(w.index), candidates_by_index.get(w.index, [])) for w in walk.waypoints}
    except Exception:  # narration only enhances the wording; guidance must work without it
        return defaults
