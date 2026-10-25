"""Phrase catalogue for spoken guidance. The server fills every fact (distance, side, names); a narrator only picks ids."""

from dataclasses import dataclass

from .waypoints import Waypoint, spoken_distance


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
