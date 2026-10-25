"""Validated object and connection edits for the map editor, the chat tools and the HTTP API.

Every channel uses the same proposal dict (kinds in EDIT_KINDS). check_edit runs a proposal on a clone and
never changes the map; apply_edit changes the map atomically and records an undo entry. Walls and room
outlines never change. Object heights are catalog defaults unless BuildingMap.height_overrides has one.
"""

import copy
import functools
import json
import math
from collections.abc import Callable
from pathlib import Path

from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import nearest_points, unary_union

from . import stacking
from .building_map import OUTSIDE, BuildingMap, MapError, normalize_type
from .object_catalog import object_height, read_catalog

EDIT_KINDS = ("add_object", "update_object", "remove_object", "add_opening", "add_connector", "undo_edit")
CATALOG_PATH = Path(__file__).with_name("object_types.json")
# All 20 320 dev assets lie within their room grown by this much (thick walls, rounded footprints).
PLACEMENT_TOLERANCE_M = 0.15
SUPPORT_MIN_OVERLAP_M2 = 0.01
CONNECTOR_MIN_OVERLAP_M2 = 0.25
UNKNOWN_TYPE_SIZE_M = 0.5
FALLBACK_HEIGHT_M = 1.0  # only for categories the catalog does not know
POSITION_DECIMALS = 3
CENTRE_TOLERANCE_M = 1e-6
OPENING_KINDS = ("door", "opening")
OPENING_LABELS = {"door": "door", "opening": "passage", "entrance": "entrance"}
CONNECTOR_KINDS = ("stairs", "escalator", "lift")
STEP_FREE_CONNECTORS = ("lift",)
ASSET_FIELDS = (
    "name", "type", "category", "space", "floor_id", "position", "rotation_deg", "width_m", "depth_m",
    "height_m", "on_top_of",
)
OPENING_FIELDS = ("opening_kind", "width_m", "step_free")
CONNECTOR_FIELDS = ("name", "step_free")
FIELDS = {
    "add_object": ("type", "category", "name", "space", "floor_id", "position", "rotation_deg", "width_m",
                   "depth_m", "height_m", "on_top_of"),
    "update_object": ("object_ref", *ASSET_FIELDS, "step_free", "opening_kind"),
    "remove_object": ("object_ref",),
    "add_opening": ("opening_kind", "first_space", "second_space", "floor_id", "position", "width_m", "step_free"),
    "add_connector": ("connector_kind", "spaces", "name", "step_free"),
    "undo_edit": (),
}
LEGACY_DOOR_FIELDS = ("first_space", "second_space", "step_free")


# ---------- catalog ----------

@functools.cache
def _catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def load_catalog() -> dict:
    """The object catalog (object_types.json), read once; every caller gets its own copy."""
    return copy.deepcopy(_catalog())


def _group(group_id: str) -> dict:
    return next(group for group in _catalog()["groups"] if group["id"] == group_id)


@functools.cache
def _item_types() -> dict[str, list[tuple[str, dict]]]:
    """Catalog item entries by type id as (category, entry), most frequent category first."""
    found: dict[str, list[tuple[str, dict]]] = {}
    for category in _group("items")["categories"]:
        for entry in category["types"]:
            found.setdefault(entry["id"], []).append((category["id"], entry))
    return {type_id: sorted(entries, key=lambda item: -item[1]["count"]) for type_id, entries in found.items()}


def _category_heights() -> dict[str, float]:
    return {category["id"]: category["height_m"] for category in _group("items")["categories"]}


def _connection(type_id: str) -> dict:
    return next(
        entry for category in _group("connections")["categories"] for entry in category["types"]
        if entry["id"] == type_id
    )


def type_label(type_id: str) -> str:
    """Display label of a type id: underscores become spaces and the first letter is upper case."""
    text = type_id.replace("_", " ")
    return text[:1].upper() + text[1:]


def find_object_types(query: str | None = None) -> list[dict]:
    """Catalog types, flat, whose id, label, category or group contain every query word; all without a query."""
    words = normalize_type(query).split("_") if query and query.strip() else []
    rows = []
    for group in _catalog()["groups"]:
        for category in group["categories"]:
            for entry in category["types"]:
                text = f"{entry['id']} {entry['label']} {category['id']} {category['label']} {group['id']}"
                if all(word in text.lower().replace("_", " ") for word in words):
                    rows.append({
                        "group": group["id"], "category": category["id"], "type": entry["id"],
                        "label": entry["label"], "action": entry["action"], "width_m": entry["width_m"],
                        "depth_m": entry["depth_m"], "height_m": entry["height_m"], "count": entry["count"],
                    })
    return rows


# ---------- geometry and heights ----------

def footprint_polygon(asset: dict) -> Polygon:
    """The object's rectangle: width_m along x and depth_m along y, turned rotation_deg anticlockwise about position."""
    footprint = asset.get("footprint") or {}
    width, depth = footprint.get("width_m"), footprint.get("depth_m")
    if not all(isinstance(side, (int, float)) and not isinstance(side, bool) and side > 0 for side in (width, depth)):
        raise MapError(f"{asset['name']} has no usable footprint; give width_m and depth_m.",
                       reason="invalid_field", field="width_m")
    x, y = asset["position"]
    rectangle = box(x - width / 2, y - depth / 2, x + width / 2, y + depth / 2)
    return affinity.rotate(rectangle, footprint.get("rotation_deg") or 0.0, origin=(x, y))


@functools.cache
def _visual_catalog() -> dict:
    # A type registered later by a plan import gets the same estimate object_height computes for it.
    return read_catalog()


def default_height(asset: dict) -> float:
    """Height without a user override: the asset's own height_m, else the shared 3D catalog's type height.

    One table (final_agent/object_catalog.json) serves the editor, the stacking file and the 3D view.
    """
    return object_height(asset, _visual_catalog())


def effective_height(building_map: BuildingMap, asset_id: str) -> float:
    """The user's override height, else the catalog default."""
    if asset_id in building_map.height_overrides:
        return building_map.height_overrides[asset_id]
    return default_height(building_map.assets[asset_id])


def rounded(point: tuple[float, float] | list[float]) -> list[float]:
    return [round(value, POSITION_DECIMALS) + 0.0 for value in point]


def listing(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def objects_phrase(count: int) -> str:
    return f"{count} object" if count == 1 else f"{count} objects"


# ---------- proposal fields ----------

def invalid(field: str, message: str) -> MapError:
    return MapError(message, reason="invalid_field", field=field)


def number_field(proposal: dict, field: str, positive: bool = False) -> float | None:
    value = proposal.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise invalid(field, f"{field} must be a finite number, got {value!r}.")
    if positive and value <= 0:
        raise invalid(field, f"{field} must be greater than 0, got {value}.")
    return float(value)


def flag_field(proposal: dict, field: str) -> bool | None:
    value = proposal.get(field)
    if value is not None and not isinstance(value, bool):
        raise invalid(field, f"{field} must be true or false, got {value!r}.")
    return value


def text_field(proposal: dict, field: str) -> str | None:
    value = proposal.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise invalid(field, f"{field} must be non-empty text, got {value!r}.")
    return value.strip()


def position_field(proposal: dict, field: str = "position") -> list[float] | None:
    value = proposal.get(field)
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise invalid(field, f"{field} must be [x, y] in metres, got {value!r}.")
    return rounded([number_field({field: item}, field) for item in value])


def rotation_field(proposal: dict) -> float | None:
    value = number_field(proposal, "rotation_deg")
    return None if value is None else round(value % 360.0, 6) + 0.0


def floor_field(building_map: BuildingMap, proposal: dict) -> str | None:
    floor_id = text_field(proposal, "floor_id")
    if floor_id is not None and floor_id not in building_map.floors:
        raise invalid("floor_id", f"Unknown floor id {floor_id!r}. Floors: {sorted(building_map.floors)}.")
    return floor_id


def resolved(resolve: Callable[[str], str], reference: object, field: str) -> str:
    """Resolve a reference and name the proposal field in any error."""
    if not isinstance(reference, str) or not reference.strip():
        raise invalid(field, f"{field} must be a non-empty name or id, got {reference!r}.")
    try:
        return resolve(reference)
    except MapError as error:
        error.field = error.field or field
        raise


def space_field(building_map: BuildingMap, proposal: dict, field: str) -> str | None:
    value = proposal.get(field)
    return None if value is None else resolved(building_map.resolve_space, value, field)


def support_field(building_map: BuildingMap, proposal: dict, object_id: str | None) -> list[str] | None:
    """Rule 4: supports are existing assets other than the object and anything standing on it."""
    references = proposal.get("on_top_of")
    if references is None:
        return None
    if isinstance(references, str):
        references = [references]
    if not isinstance(references, (list, tuple)):
        raise invalid("on_top_of", f"on_top_of must be a list of objects, got {references!r}.")
    supports = sorted({resolved(building_map.resolve_object, reference, "on_top_of") for reference in references})
    for support in supports:
        if support not in building_map.assets:
            raise MapError(f"{support} is a door or connector, not an object that can carry things.",
                           reason="not_found", field="on_top_of")
    if object_id is not None:
        above = set(stacking.descendants(building_map.stacking, object_id))
        for support in supports:
            if support == object_id or support in above:
                raise MapError(
                    f"{building_map.assets[object_id]['name']} cannot stand on {building_map.assets[support]['name']}: "
                    "that object stands on it (or is it).", reason="support_cycle", field="on_top_of",
                )
    return supports


def item_category(type_id: str, category: str | None, keep: str | None = None) -> tuple[str, dict | None]:
    """The category for a type and its catalog entry (None for types the catalog does not list).

    Without a category the current one (keep) stays if the catalog lists the type there, else the
    type's most frequent category wins; an unlisted type then needs a category.
    """
    entries = _item_types().get(type_id, [])
    known = _category_heights()
    if category is not None:
        category = normalize_type(category)
        if category not in known:
            raise invalid("category", f"category must be one of {list(known)}, got {category!r}.")
        return category, next((entry for name, entry in entries if name == category), None)
    for name, entry in entries:
        if name == keep:
            return name, entry
    if entries:
        return entries[0]
    if keep is not None:
        return keep, None
    words = type_id.split("_")
    similar = sorted({row["type"] for row in find_object_types() if row["action"] == "add_object"
                      and any(word in row["type"].split("_") for word in words)})
    raise MapError(
        f"Unknown object type {type_id!r}. Similar types: {similar[:8] or 'none'}. Pick one from "
        "list_object_types or give a category (furniture, equipment, fixture, machine).",
        reason="unknown_type", field="type",
    )


# ---------- placement and stacking rules ----------

def locate(building_map: BuildingMap, asset: dict, space_id: str | None) -> str:
    """Rules 1–2: the space containing the centre (smallest if several, or the given one); footprint inside it."""
    point = Point(asset["position"])
    floor_name = building_map.floor_name(asset["floor_id"])
    if space_id is not None:
        if building_map.spaces[space_id]["floor_id"] != asset["floor_id"]:
            raise invalid("floor_id", f"{building_map.describe_space(space_id)} is not on {floor_name}.")
        if not building_map.valid_polygon(space_id).covers(point):
            raise MapError(
                f"{asset['name']} at ({point.x:.2f}, {point.y:.2f}) would be outside "
                f"{building_map.describe_space(space_id)}.", reason="outside_space", field="position",
            )
    else:
        containing = sorted(
            (building_map.valid_polygon(candidate).area, candidate)
            for candidate, space in building_map.spaces.items()
            if space["floor_id"] == asset["floor_id"] and building_map.valid_polygon(candidate).covers(point)
        )
        if not containing:
            raise MapError(f"{asset['name']} at ({point.x:.2f}, {point.y:.2f}) would not be in any room on "
                           f"{floor_name}.", reason="outside_space", field="position")
        space_id = containing[0][1]
    room = building_map.valid_polygon(space_id).buffer(PLACEMENT_TOLERANCE_M)
    if not room.covers(footprint_polygon(asset)):
        raise MapError(f"{asset['name']} would cross a wall of {building_map.describe_space(space_id)}.",
                       reason="crosses_wall", field="position")
    return space_id


def check_support_rooms(building_map: BuildingMap, supports: list[str], space_id: str | None) -> None:
    """Rule 5 up front when both a room and supports are given, so the error names the real conflict."""
    for support in supports:
        if space_id is not None and building_map.assets[support]["space_id"] != space_id:
            raise MapError(
                f"{building_map.assets[support]['name']} is not in {building_map.describe_space(space_id)}; "
                "an object can only stand on things in its own room.", reason="support_other_space", field="on_top_of",
            )


def supports_centre(building_map: BuildingMap, supports: list[str]) -> list[float]:
    """Rule 3: the centre of the supports' combined footprint."""
    centre = unary_union([footprint_polygon(building_map.assets[support]) for support in supports]).centroid
    return rounded((centre.x, centre.y))


def check_support(building_map: BuildingMap, object_id: str, target: bool) -> None:
    """Rules 5–6 for one stacked object; target is the edited object, others would be stranded by the edit."""
    supports = building_map.stacking.get(object_id)
    if not supports:
        return
    asset = building_map.assets[object_id]
    lead = "" if target else "This change would strand an object: "
    for support_id in supports:
        support = building_map.assets[support_id]
        if (support["floor_id"], support["space_id"]) != (asset["floor_id"], asset["space_id"]):
            raise MapError(f"{lead}{asset['name']} and {support['name']} are not in the same room.",
                           reason="support_other_space" if target else "would_strand", field="on_top_of")
    shape = footprint_polygon(asset)
    bases = {support_id: footprint_polygon(building_map.assets[support_id]) for support_id in supports}
    reason = "floating" if target else "would_strand"
    for support_id, base in bases.items():
        if shape.intersection(base).area < SUPPORT_MIN_OVERLAP_M2:
            raise MapError(f"{lead}{asset['name']} would float: it does not rest on "
                           f"{building_map.assets[support_id]['name']}.", reason=reason, field="on_top_of")
    if unary_union(list(bases.values())).distance(Point(asset["position"])) > CENTRE_TOLERANCE_M:
        raise MapError(f"{lead}{asset['name']} would tip over: its centre is not above what it stands on.",
                       reason=reason, field="on_top_of")


# ---------- map changes ----------

def new_id(building_map: BuildingMap, prefix: str, count: int) -> str:
    """The id schema of add_door: smallest free number from count + 1."""
    taken = {*building_map.assets, *building_map.openings, *building_map.connectors,
             *building_map.spaces, *building_map.floors}
    number = count + 1
    while f"{prefix}{number}" in taken:
        number += 1
    return f"{prefix}{number}"


def default_name(building_map: BuildingMap, label: str, space_id: str) -> str:
    """"<Label> <room number>", made unique with -2, -3, ... so the name can be used as a reference."""
    space = building_map.spaces[space_id]
    base = f"{label} {space.get('ref') or space['name']}"
    taken = {asset["name"].lower() for asset in building_map.assets.values()}
    taken |= {(connector.get("name") or "").lower() for connector in building_map.connectors.values()}
    name, number = base, 2
    while name.lower() in taken:
        name, number = f"{base}-{number}", number + 1
    return name


def insert(building_map: BuildingMap, collection: str, record: dict) -> None:
    building_map.data[collection].append(record)
    getattr(building_map, BuildingMap.EDITABLE_COLLECTIONS[collection])[record["id"]] = record


def drop(building_map: BuildingMap, collection: str, ids: set[str]) -> None:
    building_map.data[collection][:] = [record for record in building_map.data[collection] if record["id"] not in ids]
    index = getattr(building_map, BuildingMap.EDITABLE_COLLECTIONS[collection])
    for record_id in ids:
        index.pop(record_id, None)


def set_supports(building_map: BuildingMap, object_id: str, supports: list[str]) -> None:
    if supports:
        building_map.stacking[object_id] = list(supports)
    else:
        building_map.stacking.pop(object_id, None)


def outcome(kind: str, proposal: dict, summary: str, changed: list[str], removed: list[str],
            floor_ids, space_ids) -> dict:
    return {
        "kind": kind, "proposal": proposal, "summary": summary, "changed_ids": changed, "removed_ids": removed,
        "floor_ids": sorted(set(floor_ids)), "space_ids": sorted(set(space_ids)),
    }


def space_name(building_map: BuildingMap, space_id: str) -> str:
    return building_map.spaces[space_id]["name"] if space_id in building_map.spaces else space_id


def describe_opening(building_map: BuildingMap, opening: dict) -> str:
    sides = [space_name(building_map, space_id) for space_id in opening["space_ids"]]
    return f"the {OPENING_LABELS.get(opening['kind'], opening['kind'])} between {sides[0]} and {sides[1]}"


# ---------- edit kinds ----------

def add_object(building_map: BuildingMap, proposal: dict) -> dict:
    type_text = text_field(proposal, "type")
    if type_text is None:
        raise invalid("type", "type is required, e.g. desk or coffee_machine (see list_object_types).")
    type_id = normalize_type(type_text)
    category, entry = item_category(type_id, text_field(proposal, "category"))
    width = number_field(proposal, "width_m", positive=True) or (entry["width_m"] if entry else UNKNOWN_TYPE_SIZE_M)
    depth = number_field(proposal, "depth_m", positive=True) or (entry["depth_m"] if entry else UNKNOWN_TYPE_SIZE_M)
    rotation = rotation_field(proposal) or 0.0
    height = number_field(proposal, "height_m", positive=True)
    supports = support_field(building_map, proposal, None) or []
    space_id = space_field(building_map, proposal, "space")
    check_support_rooms(building_map, supports, space_id)
    floor_id = floor_field(building_map, proposal)
    position = position_field(proposal)
    if position is None:
        if supports:
            position = supports_centre(building_map, supports)
        elif space_id is not None:
            position = rounded(building_map.anchor(space_id))
        else:
            raise invalid("space", "Give a space, a position or the objects it stands on (on_top_of).")
    if space_id is not None:
        floor = building_map.spaces[space_id]["floor_id"]
    elif supports:
        floor = building_map.assets[supports[0]]["floor_id"]
    elif floor_id is not None:
        floor = floor_id
    else:
        raise invalid("floor_id", "Give floor_id (or a space) together with a position.")
    if floor_id is not None and floor_id != floor:
        raise invalid("floor_id", f"floor_id {floor_id} contradicts the space or supports on {floor}.")

    name = text_field(proposal, "name")
    label = entry["label"] if entry else type_label(type_id)
    asset = {
        "id": new_id(building_map, f"{floor}-A-new", len(building_map.assets)),
        "name": name or f"The new {label.lower()}",  # error messages only; replaced below
        "category": category, "type": type_id, "space_id": "", "floor_id": floor, "position": position,
        "footprint": {"width_m": width, "depth_m": depth, "rotation_deg": rotation},
        "source": "user_edit",
    }
    asset["space_id"] = locate(building_map, asset, space_id)
    asset["name"] = name or default_name(building_map, label, asset["space_id"])
    insert(building_map, "assets", asset)
    set_supports(building_map, asset["id"], supports)
    if height is not None:
        building_map.height_overrides[asset["id"]] = height
    check_support(building_map, asset["id"], target=True)

    normalized = {
        "kind": "add_object", "type": type_id, "category": category, "name": asset["name"],
        "space": asset["space_id"], "floor_id": floor, "position": position, "rotation_deg": rotation,
        "width_m": width, "depth_m": depth, "height_m": height, "on_top_of": supports,
    }
    if supports:
        summary = f"Add {asset['name']} on {listing([building_map.assets[s]['name'] for s in supports])}."
    else:
        summary = f"Add {asset['name']} in {space_name(building_map, asset['space_id'])}."
    return outcome("add_object", normalized, summary, [asset["id"]], [], [floor], [asset["space_id"]])


def update_object(building_map: BuildingMap, proposal: dict) -> dict:
    target = resolved(building_map.resolve_object, proposal.get("object_ref"), "object_ref")
    given = [field for field in FIELDS["update_object"][1:] if proposal.get(field) is not None]
    if target in building_map.openings:
        allowed, handler, what = OPENING_FIELDS, update_opening, "a door or passage"
    elif target in building_map.connectors:
        allowed, handler, what = CONNECTOR_FIELDS, update_connector, "stairs, escalators and lifts"
    else:
        allowed, handler, what = ASSET_FIELDS, update_asset, "an object"
    for field in given:
        if field not in allowed:
            raise invalid(field, f"{field} cannot be changed on {what}; it accepts {', '.join(allowed)}.")
    if not given:
        raise invalid("object_ref", f"Nothing to change: give at least one of {', '.join(allowed)}.")
    return handler(building_map, target, proposal)


def update_asset(building_map: BuildingMap, asset_id: str, proposal: dict) -> dict:
    asset = building_map.assets[asset_id]
    old = copy.deepcopy(asset)
    old_supports = list(building_map.stacking.get(asset_id, []))
    normalized: dict = {"kind": "update_object", "object_ref": asset_id}

    name = text_field(proposal, "name")
    type_text, category_text = text_field(proposal, "type"), text_field(proposal, "category")
    width = number_field(proposal, "width_m", positive=True)
    depth = number_field(proposal, "depth_m", positive=True)
    rotation = rotation_field(proposal)
    height = number_field(proposal, "height_m", positive=True)
    supports = support_field(building_map, proposal, asset_id)
    space_id = space_field(building_map, proposal, "space")
    check_support_rooms(building_map, supports or [], space_id)
    floor_id = floor_field(building_map, proposal)
    position = position_field(proposal)

    # Rules 3 and 7: where the object goes.
    floor = asset["floor_id"]
    if space_id is not None:
        floor = building_map.spaces[space_id]["floor_id"]
    elif supports:
        floor = building_map.assets[supports[0]]["floor_id"]
    elif floor_id is not None:
        floor = floor_id
    if floor_id is not None and floor_id != floor:
        raise invalid("floor_id", f"floor_id {floor_id} contradicts the space or supports on {floor}.")
    if position is None:
        if supports:
            position = supports_centre(building_map, supports)
        elif space_id is not None and space_id != asset["space_id"]:
            position = rounded(building_map.anchor(space_id))
        else:
            position = list(asset["position"])
    moved = position != list(asset["position"]) or floor != asset["floor_id"]
    resized = width is not None or depth is not None or rotation is not None

    if name is not None:
        asset["name"] = name
    if type_text is not None or category_text is not None:
        asset["type"] = normalize_type(type_text) if type_text is not None else asset["type"]
        asset["category"], _ = item_category(asset["type"], category_text, keep=asset.get("category"))
        normalized.update(type=asset["type"], category=asset["category"])
    if resized:
        footprint = dict(asset.get("footprint") or {})
        for key, value in (("width_m", width), ("depth_m", depth), ("rotation_deg", rotation)):
            if value is not None:
                footprint[key] = value
                normalized[key] = value
        asset["footprint"] = footprint
    shift = (position[0] - asset["position"][0], position[1] - asset["position"][1])
    asset["position"], asset["floor_id"] = position, floor
    if moved or resized or space_id is not None:
        asset["space_id"] = locate(building_map, asset, space_id)
    left_room = (asset["floor_id"], asset["space_id"]) != (old["floor_id"], old["space_id"])
    supports_given = supports is not None
    if supports is None and left_room and old_supports:
        supports = []  # rule 7: moved to another room without new supports, so it stands on the floor
    if supports is not None:
        set_supports(building_map, asset_id, supports)
        normalized["on_top_of"] = supports
    if height is not None:
        building_map.height_overrides[asset_id] = height
        normalized["height_m"] = height
    if name is not None:
        normalized["name"] = name
    if space_id is not None:
        normalized["space"] = asset["space_id"]
    if floor_id is not None or floor != old["floor_id"]:
        normalized["floor_id"] = floor
    if moved or proposal.get("position") is not None:
        normalized["position"] = position

    carried = stacking.descendants(building_map.stacking, asset_id)
    if moved:  # rule 8: everything on top moves rigidly and takes the floor and room
        for other_id in carried:
            other = building_map.assets[other_id]
            other["position"] = rounded((other["position"][0] + shift[0], other["position"][1] + shift[1]))
            other["floor_id"] = floor
            other["space_id"] = locate(building_map, other, asset["space_id"])
    check_support(building_map, asset_id, target=True)
    for other_id in carried:
        check_support(building_map, other_id, target=False)

    summary = asset_update_summary(
        building_map, old, asset, old_supports, building_map.stacking.get(asset_id, []), supports_given, height,
        len(carried) if moved else 0,
    )
    heights_changed = height is not None or "type" in normalized
    changed = [asset_id, *(carried if moved or heights_changed else [])]
    return outcome("update_object", normalized, summary, changed, [],
                   [old["floor_id"], floor], [old["space_id"], asset["space_id"]])


def asset_update_summary(
    building_map: BuildingMap, old: dict, new: dict, old_supports: list[str], supports: list[str],
    supports_given: bool, height: float | None, carried: int,
) -> str:
    """One sentence: a single change reads "Move X to Y.", several read "Update X: a, b, c."."""
    name = old["name"]
    names = lambda ids: listing([building_map.assets[item]["name"] for item in ids])  # noqa: E731
    changes: list[tuple[str, str]] = []  # (sentence without the full stop, fragment for a list)
    on_top = f" with {objects_phrase(carried)} on top" if carried else ""
    put_on = supports_given and supports and supports != old_supports
    if put_on:
        changes.append((f"Put {name} on {names(supports)}", f"put it on {names(supports)}"))
    elif supports_given and not supports and old_supports:
        changes.append((f"Take {name} off {names(old_supports)}", f"take it off {names(old_supports)}"))
    if (new["floor_id"], new["space_id"]) != (old["floor_id"], old["space_id"]) and not put_on:
        where = space_name(building_map, new["space_id"])
        if new["floor_id"] != old["floor_id"]:
            where += f" on {building_map.floor_name(new['floor_id'])}"
        floor_note = "" if supports else " (on the floor)"
        changes.append((f"Move {name} to {where}{on_top}{floor_note}", f"move to {where}{on_top}{floor_note}"))
    elif new["position"] != old["position"] and not put_on:
        where = space_name(building_map, new["space_id"])
        changes.append((f"Move {name} within {where}{on_top}", f"move within {where}{on_top}"))
    old_footprint, new_footprint = old.get("footprint") or {}, new.get("footprint") or {}
    if new_footprint.get("rotation_deg") != old_footprint.get("rotation_deg"):
        angle = f"{new_footprint['rotation_deg']:g}°"
        changes.append((f"Rotate {name} to {angle}", f"rotate to {angle}"))
    if (new_footprint.get("width_m"), new_footprint.get("depth_m")) != (old_footprint.get("width_m"), old_footprint.get("depth_m")):
        size = f"{new_footprint['width_m']:g} × {new_footprint['depth_m']:g} m"
        changes.append((f"Resize {name} to {size}", f"resize to {size}"))
    if height is not None:
        changes.append((f"Set the height of {name} to {height:g} m", f"height {height:g} m"))
    if new["name"] != old["name"]:
        changes.append((f"Rename {name} to {new['name']}", f"rename to {new['name']}"))
    if (new["type"], new.get("category")) != (old["type"], old.get("category")):
        kind = f"{type_label(new['type'])} ({new.get('category')})"
        changes.append((f"Change {name} to a {kind}", f"type {kind}"))
    if not changes:
        return f"Keep {name} unchanged."
    if len(changes) == 1:
        return changes[0][0] + "."
    return f"Update {name}: " + ", ".join(fragment for _, fragment in changes) + "."


def update_opening(building_map: BuildingMap, opening_id: str, proposal: dict) -> dict:
    opening = building_map.openings[opening_id]
    subject = describe_opening(building_map, opening)
    kind = text_field(proposal, "opening_kind")
    if kind is not None and kind not in OPENING_KINDS:
        raise invalid("opening_kind", f"opening_kind must be door or opening, got {kind!r}.")
    width = number_field(proposal, "width_m", positive=True)
    step_free = flag_field(proposal, "step_free")
    normalized: dict = {"kind": "update_object", "object_ref": opening_id}
    fragments = []
    if kind is not None:
        opening["kind"] = normalized["opening_kind"] = kind
        fragments.append(f"make it a {OPENING_LABELS[kind]}")
    if width is not None:
        opening["width_m"] = normalized["width_m"] = width
        fragments.append(f"{width:g} m wide")
    if step_free is not None:
        opening["step_free"] = normalized["step_free"] = step_free
        fragments.append("step-free" if step_free else "with a step")
    spaces = [space_id for space_id in opening["space_ids"] if space_id != OUTSIDE]
    summary = f"Update {subject}: {', '.join(fragments)}."
    return outcome("update_object", normalized, summary, [opening_id], [], [opening["floor_id"]], spaces)


def update_connector(building_map: BuildingMap, connector_id: str, proposal: dict) -> dict:
    connector = building_map.connectors[connector_id]
    old_name = connector.get("name") or connector_id
    name = text_field(proposal, "name")
    step_free = flag_field(proposal, "step_free")
    normalized: dict = {"kind": "update_object", "object_ref": connector_id}
    fragments = []
    if name is not None:
        if any((other.get("name") or "").lower() == name.lower() for other_id, other in building_map.connectors.items()
               if other_id != connector_id):
            raise invalid("name", f"Another connector is already called {name!r}.")
        connector["name"] = normalized["name"] = name
        fragments.append(f"rename to {name}")
    if step_free is not None:
        if step_free and connector["kind"] not in STEP_FREE_CONNECTORS:
            raise invalid("step_free", f"{old_name} is {connector['kind']}, which is never step-free.")
        connector["step_free"] = normalized["step_free"] = step_free
        fragments.append("step-free" if step_free else "not step-free")
    summary = f"Update {old_name}: {', '.join(fragments)}."
    return outcome("update_object", normalized, summary, [connector_id], [], connector["floor_ids"],
                   connector["space_ids"])


def remove_object(building_map: BuildingMap, proposal: dict) -> dict:
    target = resolved(building_map.resolve_object, proposal.get("object_ref"), "object_ref")
    normalized = {"kind": "remove_object", "object_ref": target}
    if target in building_map.assets:
        asset = building_map.assets[target]
        carried = stacking.descendants(building_map.stacking, target)
        removed = {target, *carried}
        drop(building_map, "assets", removed)
        for object_id in removed:  # rule 9c: heights and stacks of removed objects go too
            building_map.stacking.pop(object_id, None)
            building_map.height_overrides.pop(object_id, None)
        for object_id in list(building_map.stacking):
            set_supports(building_map, object_id, [s for s in building_map.stacking[object_id] if s not in removed])
        on_top = f" and {objects_phrase(len(carried))} on top" if carried else ""
        return outcome("remove_object", normalized, f"Remove {asset['name']}{on_top}.", [], sorted(removed),
                       [asset["floor_id"]], [asset["space_id"]])
    is_opening = target in building_map.openings
    record = building_map.openings[target] if is_opening else building_map.connectors[target]
    label = describe_opening(building_map, record) if is_opening else record.get("name") or target
    if not (record.get("synthetic") and "-new" in target):
        raise MapError(f"{label[:1].upper() + label[1:]} comes from the building data and cannot be removed; "
                       "close it instead.", reason="not_removable", field="object_ref")
    spaces = [space_id for space_id in record["space_ids"] if space_id in building_map.spaces]
    drop(building_map, "openings" if is_opening else "vertical_connectors", {target})
    if is_opening:
        building_map.mark_edited(spaces)
    floors = [record["floor_id"]] if is_opening else record["floor_ids"]
    return outcome("remove_object", normalized, f"Remove {label}.", [], [target], floors, spaces)


def add_opening(building_map: BuildingMap, proposal: dict) -> dict:
    kind = text_field(proposal, "opening_kind") or "door"
    if kind not in OPENING_KINDS:
        raise invalid("opening_kind", f"opening_kind must be door or opening, got {kind!r}.")
    first, second = proposal.get("first_space"), proposal.get("second_space")
    if (first is None) != (second is None):
        missing = "second_space" if second is None else "first_space"
        raise invalid(missing, "Give both first_space and second_space, or neither (then floor_id and position).")
    width = number_field(proposal, "width_m", positive=True) or _connection(kind)["width_m"]
    step_free = flag_field(proposal, "step_free")
    step_free = True if step_free is None else step_free
    floor_id = floor_field(building_map, proposal)
    position = position_field(proposal)
    if first is not None:
        first_id = resolved(building_map.resolve_space, first, "first_space")
        second_id = resolved(building_map.resolve_space, second, "second_space")
        if floor_id is not None and building_map.spaces[first_id]["floor_id"] != floor_id:
            raise invalid("floor_id", f"{building_map.describe_space(first_id)} is not on floor {floor_id}.")
    else:
        if floor_id is None or position is None:
            raise invalid("position" if floor_id else "floor_id",
                          "Give first_space and second_space, or floor_id and a position on the wall.")
        first_id, second_id = building_map.wall_at(floor_id, position)
        position = onto_wall(building_map, first_id, second_id, position)
    opening = building_map.add_door(first_id, second_id, step_free, width, position, kind)
    normalized = {
        "kind": "add_opening", "opening_kind": kind, "first_space": first_id, "second_space": second_id,
        "floor_id": opening["floor_id"], "position": opening["position"], "width_m": width, "step_free": step_free,
    }
    summary = (f"Add a {OPENING_LABELS[kind]} between {space_name(building_map, first_id)} "
               f"and {space_name(building_map, second_id)}.")
    return outcome("add_opening", normalized, summary, [opening["id"]], [], [opening["floor_id"]],
                   [first_id, second_id])


def onto_wall(building_map: BuildingMap, first_id: str, second_id: str, position: list[float]) -> list[float]:
    """Rule 10: like the shared_wall midpoint, the nearest point on the first outline, halfway to the second."""
    on_first = nearest_points(building_map.valid_polygon(first_id).boundary, Point(position))[0]
    on_second = nearest_points(building_map.valid_polygon(second_id), on_first)[0]
    return [(on_first.x + on_second.x) / 2, (on_first.y + on_second.y) / 2]


def add_connector(building_map: BuildingMap, proposal: dict) -> dict:
    kind = text_field(proposal, "connector_kind")
    if kind not in CONNECTOR_KINDS:
        raise invalid("connector_kind", f"connector_kind must be stairs, escalator or lift, got {kind!r}.")
    references = proposal.get("spaces")
    if not isinstance(references, (list, tuple)) or len(references) < 2:
        raise invalid("spaces", "spaces must list at least two rooms, one per floor.")
    space_ids = [resolved(building_map.resolve_space, reference, "spaces") for reference in references]
    floors = [building_map.spaces[space_id]["floor_id"] for space_id in space_ids]
    if len(set(floors)) != len(floors):
        raise MapError("Each stop of a connector must be on a different floor.", reason="same_floor", field="spaces")
    stops = sorted(zip(floors, space_ids), key=lambda stop: building_map.floor_level(stop[0]))
    for (_, lower), (_, upper) in zip(stops, stops[1:]):
        overlap = building_map.valid_polygon(lower).intersection(building_map.valid_polygon(upper)).area
        if overlap < CONNECTOR_MIN_OVERLAP_M2:
            raise MapError(
                f"{building_map.describe_space(lower)} and {building_map.describe_space(upper)} are not above each "
                f"other (overlap {overlap:.2f} m², at least {CONNECTOR_MIN_OVERLAP_M2:g} m² needed).",
                reason="not_stacked", field="spaces",
            )
    step_free = flag_field(proposal, "step_free")
    if kind not in STEP_FREE_CONNECTORS:
        if step_free:
            raise invalid("step_free", f"{type_label(kind)} are never step-free.")
        step_free = False
    elif step_free is None:
        step_free = True
    taken = {(connector.get("name") or "").lower() for connector in building_map.connectors.values()}
    name = text_field(proposal, "name")
    if name is not None and name.lower() in taken:
        raise invalid("name", f"A connector called {name!r} already exists.")
    if name is None:
        number = 1
        while f"{type_label(kind)} {number}".lower() in taken:
            number += 1
        name = f"{type_label(kind)} {number}"
    connector = {
        "id": new_id(building_map, f"{building_map.data['building']['id']}-V-new", len(building_map.connectors)),
        "kind": kind, "name": name,
        "floor_ids": [floor for floor, _ in stops], "space_ids": [space_id for _, space_id in stops],
        "step_free": step_free, "synthetic": True,
    }
    insert(building_map, "vertical_connectors", connector)
    normalized = {"kind": "add_connector", "connector_kind": kind, "spaces": connector["space_ids"],
                  "name": name, "step_free": step_free}
    floor_names = listing([building_map.floor_name(floor) for floor in connector["floor_ids"]])
    return outcome("add_connector", normalized, f"Add {name} between {floor_names}.", [connector["id"]], [],
                   connector["floor_ids"], connector["space_ids"])


def undo_edit(building_map: BuildingMap, proposal: dict) -> dict:
    before = element_records(building_map)
    before_stacking, before_heights = dict(building_map.stacking), dict(building_map.height_overrides)
    entry = building_map.undo()
    after = element_records(building_map)
    changed = sorted(
        element_id for element_id, record in after.items()
        if before.get(element_id) != record
        or before_stacking.get(element_id) != building_map.stacking.get(element_id)
        or before_heights.get(element_id) != building_map.height_overrides.get(element_id)
    )
    removed = sorted(element_id for element_id in before if element_id not in after)
    spaces = {
        space_id
        for records, ids in ((after, changed), (before, changed), (before, removed))
        for element_id in ids if element_id in records
        for space_id in element_spaces(records[element_id])
    }
    return outcome("undo_edit", {"kind": "undo_edit"}, f"Undo: {entry['summary']}", changed, removed,
                   entry["floor_ids"], [space_id for space_id in spaces if space_id in building_map.spaces])


def element_records(building_map: BuildingMap) -> dict[str, dict]:
    return {**building_map.assets, **building_map.openings, **building_map.connectors}


def element_spaces(record: dict) -> list[str]:
    return record["space_ids"] if "space_ids" in record else [record["space_id"]]


HANDLERS = {
    "add_object": add_object, "update_object": update_object, "remove_object": remove_object,
    "add_opening": add_opening, "add_connector": add_connector, "undo_edit": undo_edit,
}


# ---------- entry points ----------

def checked_proposal(proposal: dict) -> dict:
    """The proposal with a known kind and only that kind's fields; the legacy add_door becomes add_opening."""
    if not isinstance(proposal, dict):
        raise invalid("kind", "An edit must be an object with a kind.")
    kind = proposal.get("kind")
    fields = LEGACY_DOOR_FIELDS if kind == "add_door" else FIELDS.get(kind)
    if fields is None:
        raise invalid("kind", f"kind must be one of {', '.join(EDIT_KINDS)}, got {kind!r}.")
    for field in proposal:
        if field != "kind" and field not in fields:
            raise invalid(field, f"{kind} does not accept {field}; it accepts {', '.join(fields) or 'no fields'}.")
    if kind == "add_door":
        return {"kind": "add_opening", "opening_kind": "door",
                **{field: proposal.get(field) for field in LEGACY_DOOR_FIELDS}}
    return proposal


def perform(building_map: BuildingMap, proposal: dict) -> dict:
    """Run one edit on this map and describe it. Raises MapError and may then leave partial changes behind."""
    proposal = checked_proposal(proposal)
    result = HANDLERS[proposal["kind"]](building_map, proposal)
    building_map.forget_missing()
    building_map.mark_edited()
    return result


def element_lists(building_map: BuildingMap, ids: list[str]) -> dict[str, list[dict]]:
    """Copies of the changed assets, openings and connectors after an edit."""
    return {
        "assets": [copy.deepcopy(building_map.assets[i]) for i in ids if i in building_map.assets],
        "openings": [copy.deepcopy(building_map.openings[i]) for i in ids if i in building_map.openings],
        "connectors": [copy.deepcopy(building_map.connectors[i]) for i in ids if i in building_map.connectors],
    }


def check_edit(building_map: BuildingMap, proposal: dict) -> dict:
    """Validate a proposal on a clone: normalized proposal, one-sentence summary and the state after it.

    preview lists every new or changed element after the edit (including carried stacks), the removed
    ids, the floors to redraw and the spaces to highlight. The map itself never changes.
    """
    trial = building_map.clone()
    result = perform(trial, proposal)
    return {
        "proposal": result["proposal"],
        "summary": result["summary"],
        "preview": {
            "floor_ids": result["floor_ids"], **element_lists(trial, result["changed_ids"]),
            "removed_ids": result["removed_ids"], "space_ids": result["space_ids"],
        },
    }


def apply_edit(building_map: BuildingMap, proposal: dict) -> dict:
    """Apply a proposal atomically and record it for undo_edit; returns the EditResult.

    EditResult: kind, summary, changed_ids, removed_ids, floor_ids (to redraw) and copies of the changed
    assets, openings and connectors. On any error the map is left exactly as it was.
    """
    with building_map.transaction() as before:
        result = perform(building_map, proposal)
        if result["kind"] != "undo_edit":
            building_map.push_undo(before, result["summary"], result["floor_ids"])
    return {
        "kind": result["kind"], "summary": result["summary"], "changed_ids": result["changed_ids"],
        "removed_ids": result["removed_ids"], "floor_ids": result["floor_ids"],
        **element_lists(building_map, result["changed_ids"]),
    }
