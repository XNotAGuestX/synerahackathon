"""Session answers for the Wayfinder UI. Facts come from BuildingMap, not from the model."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from .building_map import BuildingMap, MapError, RouteResult

DEV = Path(__file__).resolve().parents[1] / "data" / "dev"


def available_buildings() -> list[Path]:
    return sorted(path.parent for path in DEV.glob("*/building.json"))


class GuideSession:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.map = BuildingMap.load(directory)
        self.id = str(uuid.uuid4())
        self.here: str | None = None
        self.destination: str | None = None
        self.step_free = False
        self.revision = 1
        self.pending: dict | None = None
        self.routes: dict[str, dict] = {}
        self.last_route_id: str | None = None

    def building_summary(self) -> dict:
        info = self.map.data["building"]
        return {
            "id": info["id"],
            "name": info["name"],
            "floors": len(self.map.floors),
            "has_lift": any(item["kind"] == "lift" for item in self.map.connectors.values()),
            "has_step_free_entrance": any(item["step_free"] and "outside" in item["space_ids"] for item in self.map.openings.values()),
        }

    def floors(self) -> list[dict]:
        return [
            {
                "id": floor["id"],
                "level": floor["level"],
                "name": floor["name"],
                "elevation_m": floor.get("elevation_m", 0),
                "height_m": floor.get("height_m", 3),
                "space_count": sum(1 for space in self.map.spaces.values() if space["floor_id"] == floor["id"]),
            }
            for floor in sorted(self.map.floors.values(), key=lambda item: item["level"])
        ]

    def floor_plan(self, floor_id: str) -> dict:
        floor = self.map.floors[floor_id]
        spaces = [space for space in self.map.spaces.values() if space["floor_id"] == floor_id]
        openings = [item for item in self.map.openings.values() if item["floor_id"] == floor_id]
        assets = [item for item in self.map.assets.values() if item["floor_id"] == floor_id]
        connectors = [item for item in self.map.connectors.values() if floor_id in item["floor_ids"]]
        points = [point for space in spaces for point in space["polygon"]]
        points += [item["position"] for item in openings]
        xs = [point[0] for point in points] or [0]
        ys = [point[1] for point in points] or [0]
        return {
            "schema_version": 1,
            "floor": self.floors()[next(index for index, item in enumerate(self.floors()) if item["id"] == floor_id)],
            "spaces": spaces,
            "openings": openings,
            "assets": assets,
            "connectors": connectors,
            "closed_ids": sorted(self.map.closed),
            "bounds": {"min": [min(xs), min(ys)], "max": [max(xs), max(ys)]},
        }

    def search(self, query: str, page: int = 1, page_size: int = 15) -> dict:
        matches = self.map.search(re.sub(r"^the ", "", query.strip(), flags=re.IGNORECASE))
        start = max(page - 1, 0) * page_size
        items = [self._place(item) for item in matches[start:start + page_size]]
        return {"items": items, "page": page, "page_size": page_size, "total": len(matches)}

    def message(self, text: str) -> dict:
        stripped = text.strip()
        lowered = stripped.lower()
        if re.search(r"no stairs|without stairs|step-free|wheelchair", lowered):
            self.step_free = True
        if match := re.search(r"i am (?:now )?at (.+)", stripped, flags=re.IGNORECASE):
            return self._locate_or_ask(match.group(1), stripped, set_here=True)
        if match := re.search(r"now go to (.+?)(?: instead)?$", stripped, flags=re.IGNORECASE):
            return self._set_destination(match.group(1), stripped)
        if match := re.search(r"(?:where is|find|how do i reach|how do i get to) (.+?)(?:\?|$)", stripped, flags=re.IGNORECASE):
            return self._locate_or_ask(match.group(1), stripped, set_here=False)
        if match := re.search(r"reopen (.+)", stripped, flags=re.IGNORECASE):
            return self._pending(match.group(1), closed=False, text=stripped)
        if match := re.search(r"(?:close|closed) (.+)", stripped, flags=re.IGNORECASE):
            return self._pending(match.group(1), closed=True, text=stripped)
        if match := re.search(r"visit (.+?) then (.+)", stripped, flags=re.IGNORECASE):
            return self._tour(match.group(1), match.group(2), stripped)
        if re.fullmatch(r"no stairs|without stairs|step-free|wheelchair", lowered):
            return self._context_reply(stripped, "Step-free is on for later routes.")
        return self._not_found(stripped)

    def confirm(self) -> dict:
        if not self.pending:
            raise MapError("Action is no longer pending.")
        element = self.pending["element_id"]
        self.map.set_closed(element, self.pending["closed"])
        self.pending = None
        self.revision += 1
        route_reply = self._reroute_after_change()
        return {"summary": "The map now uses the confirmed closure.", "closed_ids": sorted(self.map.closed), "route": route_reply}

    def cancel(self) -> dict:
        self.pending = None
        return {"summary": "Change cancelled. The map is unchanged.", "closed_ids": sorted(self.map.closed)}

    def create_route(self, start: str, destination: str, step_free: bool, via: list[str] | None = None) -> dict:
        self.here = self.map.resolve_space(start)
        self.destination = self.map.resolve_space(destination)
        self.step_free = step_free
        return self._route(self.here, self.destination, via or [])

    def _locate_or_ask(self, query: str, text: str, set_here: bool) -> dict:
        found = self.map.search(re.sub(r"^the ", "", query.strip(), flags=re.IGNORECASE))
        if not found:
            return self._not_found(query)
        if len(found) > 1:
            options = [{"id": item["id"], "label": f"{item['name']} · {self.building_summary()['name']}"} for item in found[:4]]
            return self._reply(text, f"Which {query.strip()}?", effects=[{"type": "ask", "question": f"Which {query.strip()}?", "options": options}], intent="clarify", missing=["place"])
        chosen = found[0]
        space_id = chosen["id"] if chosen["kind"] == "space" else self.map.assets[chosen["id"]]["space_id"]
        if set_here:
            self.here = space_id
            return self._reply(text, f"You are at {self.map.spaces[space_id]['name']}.", effects=self._focus(space_id), intent="context", start=space_id)
        self.destination = chosen["id"]
        if not self.here:
            return self._reply(text, "Where are you now?", effects=[{"type": "ask", "question": "Where are you now?", "options": []}], intent="clarify", missing=["start"])
        route = self._route(self.here, space_id, [])
        if not route["reachable"]:
            return self._reply(text, "No route with the current closures and step-free preference.", effects=[{"type": "clear_route"}, {"type": "draw_route", "route_id": route["id"]}], routes=[route], intent="route", start=self.here, destination=space_id)
        return self._reply(
            text,
            f"Route is {route['length_m']} m. Follow the tape on the plan.",
            effects=[{"type": "draw_route", "route_id": route["id"]}, *self._focus(space_id)],
            routes=[route],
            intent="route",
            start=self.here,
            destination=space_id,
        )

    def _set_destination(self, query: str, text: str) -> dict:
        found = self.map.search(re.sub(r"^the ", "", query.strip(), flags=re.IGNORECASE))
        if not found:
            return self._not_found(query)
        if len(found) > 1:
            options = [{"id": item["id"], "label": f"{item['name']} · {self.building_summary()['name']}"} for item in found[:4]]
            return self._reply(text, "Which destination?", effects=[{"type": "ask", "question": "Which destination?", "options": options}], intent="clarify", missing=["place"])
        self.destination = found[0]["id"]
        start_name = self.map.spaces[self.here]["name"] if self.here else "an unknown start"
        return self._reply(text, f"Destination is now {found[0]['name']}. You are still at {start_name}.", effects=[{"type": "clear_route"}], intent="context", start=self.here, destination=self.destination)

    def _pending(self, query: str, closed: bool, text: str) -> dict:
        try:
            element = self.map.find_element(query)
        except MapError:
            return self._not_found(query)
        name = self.map.connectors.get(element, self.map.spaces.get(element, {"name": element})).get("name", element)
        self.pending = {"id": str(uuid.uuid4()), "element_id": element, "closed": closed, "summary": f"{'Close' if closed else 'Reopen'} {name}"}
        spaces = self.map.connectors[element]["space_ids"] if element in self.map.connectors else [element]
        return self._reply(
            text,
            f"I can {'close' if closed else 'reopen'} {name}. Confirm before I change the map.",
            effects=[{"type": "highlight_spaces", "space_ids": spaces, "reason": "preview"}],
            intent="close" if closed else "reopen",
            pending={"id": self.pending["id"], "status": "pending", "summary": self.pending["summary"], "proposal": {"kind": "set_closed", "element_ref": element, "closed": closed}},
        )

    def _tour(self, first: str, rest: str, text: str) -> dict:
        if not self.here:
            return self._reply(text, "Where are you now?", effects=[{"type": "ask", "question": "Where are you now?", "options": []}], intent="clarify", missing=["start"])
        stops = [self._one(part) for part in [first, *re.split(r"\s+then\s+", rest, flags=re.IGNORECASE)]]
        if any(item is None for item in stops):
            return self._not_found(text)
        resolved = [item for item in stops if item]
        via = resolved[:-1]
        destination = resolved[-1]
        route = self._route(self.here, destination, via)
        if not route["reachable"]:
            return self._reply(text, "No route for that stop order with the current closures.", effects=[{"type": "clear_route"}], intent="tour", missing=["route"])
        names = [self.map.spaces[item]["name"] if item in self.map.spaces else self.map.assets[item]["name"] for item in resolved]
        return self._reply(text, f"Order kept: {' → '.join(names)}. Total {route['length_m']} m.", effects=[{"type": "draw_route", "route_id": route["id"]}], routes=[route], intent="tour")

    def _one(self, query: str) -> str | None:
        found = self.map.search(re.sub(r"^the ", "", query.strip(" ."), flags=re.IGNORECASE))
        if len(found) != 1:
            return None
        return found[0]["id"] if found[0]["kind"] == "space" else self.map.assets[found[0]["id"]]["space_id"]

    def _route(self, start: str, destination: str, via: list[str]) -> dict:
        try:
            result = self.map.route(start, destination, step_free=self.step_free, via=via)
            payload = self._payload(result, via)
        except MapError:
            payload = self._unreachable(start, destination, via)
        self.routes[payload["id"]] = payload
        self.last_route_id = payload["id"]
        return payload

    def _reroute_after_change(self) -> dict | None:
        if not self.here or not self.destination:
            return None
        try:
            return self._route(self.here, self.destination, [])
        except MapError:
            return self.routes.get(self.last_route_id or "")

    def _payload(self, result: RouteResult, via: list[str]) -> dict:
        directions = []
        legs: dict[str, list[list[float]]] = {}
        for space_id in result.space_path:
            if space_id not in self.map.spaces:
                directions.append({"text": "Leave through the entrance.", "floor_id": self.map.spaces[result.start_space_id]["floor_id"], "at": list(self.map.anchor(result.start_space_id))})
                continue
            floor_id = self.map.spaces[space_id]["floor_id"]
            point = [round(value, 3) for value in self.map.anchor(space_id)]
            legs.setdefault(floor_id, []).append(point)
            directions.append({"text": f"Continue in {self.map.spaces[space_id]['name']} on {self.map.floor_name(floor_id)}.", "floor_id": floor_id, "at": point})
        return {
            "id": str(uuid.uuid4()),
            "reachable": True,
            "length_m": result.length_m,
            "step_free": result.step_free,
            "via": via,
            "closed_ids": result.closed,
            "start_space_id": result.start_space_id,
            "destination_space_id": result.destination_space_id,
            "space_path": result.space_path,
            "directions": directions,
            "legs": [{"floor_id": floor_id, "floor_level": self.map.floors[floor_id]["level"], "points": points} for floor_id, points in legs.items() if len(points) > 1],
        }

    def _unreachable(self, start: str, destination: str, via: list[str]) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "reachable": False,
            "length_m": None,
            "step_free": self.step_free,
            "via": via,
            "closed_ids": sorted(self.map.closed),
            "start_space_id": start,
            "destination_space_id": destination,
            "directions": [],
            "legs": [],
        }

    def _focus(self, space_id: str) -> list[dict]:
        space = self.map.spaces[space_id]
        floor = self.map.floors[space["floor_id"]]
        return [{"type": "focus", "floor_id": space["floor_id"], "floor_level": floor["level"], "point": list(self.map.anchor(space_id))}, {"type": "highlight_spaces", "space_ids": [space_id], "reason": "selected"}]

    def _place(self, item: dict) -> dict:
        if item["kind"] == "space":
            space = self.map.spaces[item["id"]]
            floor = self.map.floors[space["floor_id"]]
            return {"kind": "space", "id": space["id"], "name": space["name"], "floor_id": space["floor_id"], "floor_level": floor["level"], "floor_name": floor["name"], "space_id": space["id"], "room_type": space.get("room_type"), "asset_type": None, "position": list(self.map.anchor(space["id"]))}
        asset = self.map.assets[item["id"]]
        floor = self.map.floors[asset["floor_id"]]
        return {"kind": "asset", "id": asset["id"], "name": asset["name"], "floor_id": asset["floor_id"], "floor_level": floor["level"], "floor_name": floor["name"], "space_id": asset["space_id"], "room_type": None, "asset_type": asset["type"], "position": asset["position"]}

    def _not_found(self, text: str) -> dict:
        return self._reply(text, f"No place in this building matches “{text.strip()}”.", effects=[{"type": "clear_route"}], intent="clarify", missing=["place"])

    def _context_reply(self, text: str, guide: str) -> dict:
        return self._reply(text, guide, effects=[], intent="context", start=self.here, destination=self.destination)

    def _reply(self, text: str, guide: str, effects: list[dict], routes: list[dict] | None = None, intent: str = "clarify", missing: list[str] | None = None, start: str | None = None, destination: str | None = None, pending: dict | None = None) -> dict:
        return {
            "user_message": {"text": text},
            "guide_message": {
                "text": guide,
                "understood": {
                    "intent": intent,
                    "summary": guide,
                    "constraints": {"step_free": self.step_free, "via": [], "closed_ids": sorted(self.map.closed)},
                    "resolved": {"start_space_id": start, "destination_space_id": destination, "space_ids": [], "asset_ids": [], "count": None},
                    "missing": missing or [],
                },
                "effects": effects,
            },
            "routes": routes or [],
            "pending_action": pending,
        }


def validate_plan(plan: dict) -> list[str]:
    issues: list[str] = []
    spaces = plan.get("spaces")
    if not isinstance(spaces, list) or not spaces:
        return ["spaces must be a non-empty list."]
    seen: set[str] = set()
    for space in spaces:
        space_id = str(space.get("id", ""))
        if not space_id or space_id in seen:
            issues.append(f"Duplicate or missing space id {space_id}.")
        seen.add(space_id)
        polygon = space.get("polygon") or []
        if len(polygon) < 3:
            issues.append(f"{space_id} needs at least 3 points.")
        if any(len(point) < 2 or not all(isinstance(value, (int, float)) for value in point[:2]) for point in polygon):
            issues.append(f"{space_id} has a non-finite coordinate.")
    return issues
