"""Turn a scored question into an Answer line using deterministic tools.

The question text is the only input. Expected answers are not read here.
"""

from __future__ import annotations

import re

from .building_map import BuildingMap, MapError


def floor_reference(phrase: str) -> str:
    text = phrase.strip().lower()
    if "ground" in text:
        return "0"
    basement = re.search(r"basement\s*(\d+)", text)
    if basement:
        return f"-{int(basement.group(1))}"
    floor = re.search(r"floor\s*(-?\d+)", text)
    if floor:
        return floor.group(1)
    return phrase.strip()


def room_type_of(phrase: str) -> str:
    return phrase.strip().lower().replace(" ", "_")


def named_space(building: BuildingMap, name: str, floor_phrase: str) -> str:
    floor_id = building.resolve_floor(floor_reference(floor_phrase))
    lowered = name.strip().lower()
    matches = [
        space["id"]
        for space in building.spaces.values()
        if space["floor_id"] == floor_id
        and (space["name"].lower() == lowered or str(space.get("ref") or "").lower() == lowered)
    ]
    if len(matches) == 1:
        return matches[0]
    return building.resolve_space(name)


def answer_line(building: BuildingMap, question: str) -> str | None:
    try:
        return _answer_line(building, question)
    except MapError:
        return None


def _answer_line(building: BuildingMap, question: str) -> str | None:
    text = question.strip()
    largest = re.search(r"Which is the largest (.+?) on the (.+?), and how big", text, flags=re.IGNORECASE)
    if largest:
        room = building.largest_room(floor_reference(largest.group(2)), room_type_of(largest.group(1)))
        return f"Answer: {room['name']}, {room['area_m2']}"
    total = re.search(r"total floor area of every (.+?) on the (.+?) added", text, flags=re.IGNORECASE)
    if total:
        area = building.floor_area_total(floor_reference(total.group(2)), room_type_of(total.group(1)))
        return f"Answer: {area['area_m2']}"
    distance = re.search(
        r"between (.+) \(([^()]+)\) and (.+) \(([^()]+)\)\.",
        text,
        flags=re.IGNORECASE,
    )
    if "straight-line distance" in text.lower() and distance:
        first = named_space(building, distance.group(1), distance.group(2))
        second = named_space(building, distance.group(3), distance.group(4))
        return f"Answer: {building.straight_line_3d(first, second)['distance_m']}"
    stacked = re.search(r"(?:floor of|ceiling in) (.+) \(([^()]+)\)", text, flags=re.IGNORECASE)
    if stacked and ("directly below" in text.lower() or "directly above" in text.lower()):
        direction = "below" if "directly below" in text.lower() else "above"
        room = building.room_stacked(named_space(building, stacked.group(1), stacked.group(2)), direction)
        return f"Answer: {room['name']}"
    walls = re.search(r"soundproofing (.+) \(([^()]+)\)", text, flags=re.IGNORECASE)
    if walls:
        count = building.shared_walls_count(named_space(building, walls.group(1), walls.group(2)))
        return f"Answer: {count['count']}"
    width = re.search(r"at least ([0-9.]+) m wide", text, flags=re.IGNORECASE)
    arrival = re.search(r"entrance into (.+) \(([^()]+)\)", text, flags=re.IGNORECASE)
    target_floor = re.search(r"rooms on the (.+?)(?: can|\?)", text, flags=re.IGNORECASE)
    if width and arrival and target_floor:
        count = building.wide_delivery_count(
            named_space(building, arrival.group(1), arrival.group(2)),
            floor_reference(target_floor.group(1)),
            float(width.group(1)),
        )
        return f"Answer: {count['count']}"
    if "out of service" in text.lower() and arrival and target_floor:
        closed = re.match(r"(.+?) is out of service", text, flags=re.IGNORECASE)
        count = building.step_free_reachable_count(
            named_space(building, arrival.group(1), arrival.group(2)),
            floor_reference(target_floor.group(1)),
            closed.group(1) if closed else None,
        )
        return f"Answer: {count['count']}"
    errand = re.search(
        r"I'm in (.+) \(([^()]+)\)\. I need to grab a(?:n)? (.+?) from the room.*?largest (.+?) on the (.+?)\.",
        text,
        flags=re.IGNORECASE,
    )
    if errand:
        result = building.errand(
            named_space(building, errand.group(1), errand.group(2)),
            room_type_of(errand.group(3)),
            floor_reference(errand.group(5)),
            room_type_of(errand.group(4)),
            step_free="can't" in text.lower() or "cannot" in text.lower(),
        )
        return f"Answer: {result['length_m']}"
    door = re.search(
        r"door between (.+) \(([^()]+)\) and (.+) \(([^()]+)\).*?rooms on the (.+?) would",
        text,
        flags=re.IGNORECASE,
    )
    if door:
        count = building.what_if_door(
            named_space(building, door.group(1), door.group(2)),
            named_space(building, door.group(3), door.group(4)),
            floor_reference(door.group(5)),
        )
        return f"Answer: {count['count']}"
    return None
