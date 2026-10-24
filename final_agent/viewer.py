"""Flat 2D floor plans: one renderer draws every display (route, located room/asset, landmarks).

The renderer only draws what BuildingMap already computed: the route's selected doors (route_polylines),
its stops and connectors, the explicit selection, closures and the landmark ids it is given.
"""

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.patches import Polygon as PolygonPatch

from .building_map import DOOR_PREFIX, OUTSIDE, BuildingMap, MapError, RouteResult, normalize_type

ROOM_COLOURS = {"hall": "#ece6d6", "corridor": "#faf8f2", "stair": "#dce6f2", "lift": "#dce6f2"}
ROOM_COLOUR = "#f3efe6"
CLOSED_COLOUR = "#f4cccc"
CLOSED_EDGE_COLOUR = "#b71c1c"
ROUTE_COLOUR = "#d32f2f"
START_COLOUR = "#2e7d32"
STOP_COLOUR = "#1565c0"
HANDOFF_COLOUR = "#00838f"
SELECTION_COLOUR = "#ef6c00"
SELECTION_FILL = "#ffe0a3"
LANDMARK_COLOUR = "#6a1b9a"
LANDMARK_FILL = "#ead7f2"
OUTLINE_COLOUR = "#666666"

FIGURE_INCHES = 9
DPI = 100
ROUTE_LINE_WIDTH = 2.5
MARGIN_FRACTION = 0.12
MARGIN_M = 4.0
MIN_EXTENT_M = 24.0
MAX_LABEL_CHARS = 30
ROOM_LABEL_SIZE = 6.5
LABEL_SIZE = 8

Candidate = tuple[float, float, int, int, str, str]  # data x, y, pixel offset dx, dy, horizontal/vertical alignment


def node_location(building_map: BuildingMap, node: str) -> tuple[str, tuple[float, float]] | None:
    """Floor id and plan position of a route node; None for 'outside', which has no place on any plan."""
    if node == OUTSIDE:
        return None
    if node.startswith(DOOR_PREFIX):
        opening = building_map.openings[node.removeprefix(DOOR_PREFIX)]
        return opening["floor_id"], tuple(opening["position"])
    return building_map.spaces[node]["floor_id"], building_map.anchor(node)


def route_polylines(
    building_map: BuildingMap, route: RouteResult
) -> list[tuple[str, list[tuple[float, float]]]]:
    """The route's recorded nodes (room anchors and the doors actually used) as one polyline per floor run.

    A new polyline starts at every floor change, outside transition or revisit of a floor, so no line is
    drawn across stairs, lifts or the outside.
    """
    polylines: list[tuple[str, list[tuple[float, float]]]] = []
    previous_floor = None
    for node in route.node_path:
        location = node_location(building_map, node)
        if location is None:
            previous_floor = None
            continue
        floor_id, point = location
        if floor_id != previous_floor:
            polylines.append((floor_id, []))
        polylines[-1][1].append(point)
        previous_floor = floor_id
    return polylines


def route_handoffs(building_map: BuildingMap, route: RouteResult) -> list[tuple[str, tuple[float, float], str]]:
    """(floor id, position, label) where the route changes floor by stairs/lift or passes through the outside."""
    handoffs = []
    nodes = route.node_path
    for index, element in enumerate(route.element_path):
        connector = building_map.connectors.get(element)
        if connector is None:
            continue
        before, after = nodes[index], nodes[index + 1]
        for here, other, template in ((before, after, "{name} → {floor}"), (after, before, "{name} from {floor}")):
            floor_id, point = node_location(building_map, here)
            other_floor = building_map.floor_name(building_map.spaces[other]["floor_id"])
            handoffs.append((floor_id, point, template.format(name=connector["name"], floor=other_floor)))
    for index, node in enumerate(nodes):
        if node != OUTSIDE:
            continue
        for neighbour, text in ((index - 1, "Out through entrance"), (index + 1, "In through entrance")):
            if 0 <= neighbour < len(nodes) and nodes[neighbour].startswith(DOOR_PREFIX):
                floor_id, point = node_location(building_map, nodes[neighbour])
                handoffs.append((floor_id, point, text))
    return handoffs


class Labeller:
    """Places text labels so they stay inside the view and avoid each other and the markers already drawn."""

    def __init__(self, axes: plt.Axes) -> None:
        self.axes = axes
        self.dpi = axes.figure.dpi
        self.view = axes.get_window_extent()
        self.boxes: list[tuple[float, float, float, float]] = []

    def pixel(self, x: float, y: float) -> tuple[float, float]:
        return tuple(self.axes.transData.transform((x, y)))

    def reserve(self, x: float, y: float, half_pixels: float = 10) -> None:
        px, py = self.pixel(x, y)
        self.boxes.append((px - half_pixels, py - half_pixels, px + half_pixels, py + half_pixels))

    def box(self, text: str, size: float, candidate: Candidate) -> tuple[float, float, float, float]:
        x, y, dx, dy, ha, va = candidate
        lines = text.split("\n")
        width = max(len(line) for line in lines) * 0.6 * size * self.dpi / 72 + 6
        height = len(lines) * 1.4 * size * self.dpi / 72 + 4
        px, py = self.pixel(x, y)
        left = px + dx - (0 if ha == "left" else width if ha == "right" else width / 2)
        bottom = py + dy - (0 if va == "bottom" else height if va == "top" else height / 2)
        return left, bottom, left + width, bottom + height

    def free(self, box: tuple[float, float, float, float], inside: bool) -> bool:
        if inside and not (
            box[0] >= self.view.x0 and box[1] >= self.view.y0 and box[2] <= self.view.x1 and box[3] <= self.view.y1
        ):
            return False
        return not any(
            box[0] < other[2] and other[0] < box[2] and box[1] < other[3] and other[1] < box[3]
            for other in self.boxes
        )

    def place(
        self, text: str, candidates: list[Candidate], size: float = LABEL_SIZE, optional: bool = False,
        max_width_pixels: float | None = None, **style: object,
    ) -> bool:
        """Draw text at the first candidate that fits; mandatory labels fall back to the first candidate."""
        chosen = None
        for inside in (True, False):
            for candidate in candidates:
                box = self.box(text, size, candidate)
                if max_width_pixels is not None and box[2] - box[0] > max_width_pixels:
                    continue
                if self.free(box, inside):
                    chosen = candidate
                    break
            if chosen or optional:
                break
        if chosen is None:
            if optional:
                return False
            chosen = candidates[0]
        x, y, dx, dy, ha, va = chosen
        self.boxes.append(self.box(text, size, chosen))
        style = {"bbox": {"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": 0.85}, **style}
        self.axes.annotate(
            text, (x, y), xytext=(dx * 72 / self.dpi, dy * 72 / self.dpi), textcoords="offset points",
            ha=ha, va=va, fontsize=size, zorder=12, annotation_clip=False, **style,
        )
        return True


def around(x: float, y: float, gap: int = 12) -> list[Candidate]:
    """Label positions around a point, nearest side first."""
    return [
        (x, y, gap, 0, "left", "center"), (x, y, -gap, 0, "right", "center"),
        (x, y, 0, gap, "center", "bottom"), (x, y, 0, -gap, "center", "top"),
        (x, y, gap, gap, "left", "bottom"), (x, y, -gap, gap, "right", "bottom"),
        (x, y, gap, -gap, "left", "top"), (x, y, -gap, -gap, "right", "top"),
    ]


def above_below(bounds: tuple[float, float, float, float]) -> list[Candidate]:
    """Label positions just outside the top, then the bottom edge of a room's bounding box."""
    min_x, min_y, max_x, max_y = bounds
    centre = (min_x + max_x) / 2
    return [(centre, max_y, 0, 3, "center", "bottom"), (centre, min_y, 0, -3, "center", "top")]


def short(text: str) -> str:
    return text if len(text) <= MAX_LABEL_CHARS else text[: MAX_LABEL_CHARS - 1] + "…"


def label_point(building_map: BuildingMap, space_id: str) -> tuple[float, float]:
    """A point inside the room, preferring its centroid, for room labels."""
    polygon = building_map.space_polygon(space_id)
    point = polygon.centroid if polygon.contains(polygon.centroid) else polygon.representative_point()
    return point.x, point.y


def bounds_union(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def fit_view(
    boxes: list[tuple[float, float, float, float]], floor_bounds: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """Focus bounds plus a margin, at least MIN_EXTENT_M wide and shifted back onto the floor where it fits."""
    focus = bounds_union(boxes)
    margin = MARGIN_M + MARGIN_FRACTION * max(focus[2] - focus[0], focus[3] - focus[1])
    view = []
    for low, high, floor_low, floor_high in (
        (focus[0], focus[2], floor_bounds[0], floor_bounds[2]), (focus[1], focus[3], floor_bounds[1], floor_bounds[3]),
    ):
        low, high = low - margin, high + margin
        if high - low < MIN_EXTENT_M:
            centre = (low + high) / 2
            low, high = centre - MIN_EXTENT_M / 2, centre + MIN_EXTENT_M / 2
        floor_low, floor_high = floor_low - MARGIN_M / 2, floor_high + MARGIN_M / 2
        if high - low <= floor_high - floor_low:
            shift = max(floor_low - low, 0) or min(floor_high - high, 0)
            low, high = low + shift, high + shift
        view.append((low, high))
    return view[0][0], view[1][0], view[0][1], view[1][1]


def landmark_targets(building_map: BuildingMap, landmark_ids: list[str]) -> list[tuple[str, str]]:
    """(kind, id) for each landmark id; unknown ids are an error, never silently skipped."""
    targets = []
    for landmark_id in landmark_ids:
        if landmark_id in building_map.spaces:
            targets.append(("space", landmark_id))
        elif landmark_id in building_map.assets:
            targets.append(("asset", landmark_id))
        else:
            raise MapError(f"Unknown landmark id '{landmark_id}': give a space or asset id.")
    return targets


def draw_floor(
    building_map: BuildingMap, floor_id: str, path: Path, route: RouteResult | None = None,
    selection: dict | None = None, landmark_ids: list[str] | None = None,
) -> Path:
    """Render one floor with the optional route, selection and landmarks; return the PNG path."""
    spaces = [space for space in building_map.spaces.values() if space["floor_id"] == floor_id]
    targets = [
        target for target in landmark_targets(building_map, landmark_ids or [])
        if (building_map.spaces[target[1]] if target[0] == "space" else building_map.assets[target[1]])["floor_id"]
        == floor_id
    ]
    selected_space = selection["space_id"] if selection and selection["floor_id"] == floor_id else None
    selected_asset = (
        building_map.assets[selection["id"]] if selected_space and selection["kind"] == "asset" else None
    )
    polylines = [
        points for run_floor, points in (route_polylines(building_map, route) if route else [])
        if run_floor == floor_id
    ]
    handoffs = [item for item in route_handoffs(building_map, route) if item[0] == floor_id] if route else []
    stops = list(enumerate(route.stops)) if route else []
    stops_here = [(index, space_id) for index, space_id in stops if building_map.spaces[space_id]["floor_id"] == floor_id]
    start_id, destination_id = (route.stops[0], route.stops[-1]) if route else (None, None)

    focus = [(x, y, x, y) for points in polylines for x, y in points]
    focus += [building_map.space_polygon(space_id).bounds for _, space_id in stops_here]
    if selected_space:
        focus.append(building_map.space_polygon(selected_space).bounds)
    for kind, target_id in targets:
        if kind == "space":
            focus.append(building_map.space_polygon(target_id).bounds)
        else:
            x, y = building_map.assets[target_id]["position"]
            focus.append((x, y, x, y))
    focus += [(point[0], point[1], point[0], point[1]) for _, point, _ in handoffs]
    floor_bounds = bounds_union([building_map.space_polygon(space["id"]).bounds for space in spaces] or [(0, 0, 1, 1)])
    view = fit_view(focus, floor_bounds) if focus else floor_bounds

    figure, axes = plt.subplots(figsize=(FIGURE_INCHES, FIGURE_INCHES), dpi=DPI)
    try:
        closed_connector_spaces = {
            space_id: connector for connector in building_map.connectors.values() if connector["id"] in building_map.closed
            for space_id in connector["space_ids"]
        }
        landmark_spaces = {target_id for kind, target_id in targets if kind == "space"}
        for space in spaces:
            space_id = space["id"]
            colour = ROOM_COLOURS.get(normalize_type(space.get("type") or ""), ROOM_COLOUR)
            edge, width, hatch = OUTLINE_COLOUR, 0.6, None
            if space_id in landmark_spaces:
                colour, edge, width = LANDMARK_FILL, LANDMARK_COLOUR, 2.8
            if space_id in building_map.closed:
                colour, hatch = CLOSED_COLOUR, "///"
            if space_id == selected_space:
                colour, edge, width = SELECTION_FILL, SELECTION_COLOUR, 3.0
            if route and space_id == destination_id:
                edge, width = ROUTE_COLOUR, 2.6
            elif route and space_id == start_id:
                edge, width = START_COLOUR, 2.6
            axes.add_patch(PolygonPatch(
                space["polygon"], facecolor=colour, edgecolor=edge, linewidth=width, hatch=hatch, zorder=1 + (width > 1),
            ))
        axes.set_xlim(view[0], view[2])
        axes.set_ylim(view[1], view[3])
        axes.set_aspect("equal", adjustable="box")
        axes.apply_aspect()
        axes.axis("off")
        labels = Labeller(axes)
        in_view = lambda x, y: view[0] <= x <= view[2] and view[1] <= y <= view[3]  # noqa: E731

        legend: list = []
        for points in polylines:
            xs, ys = zip(*points, strict=True)
            axes.plot(xs, ys, color="white", linewidth=ROUTE_LINE_WIDTH + 2.5, zorder=4, solid_capstyle="round")
            axes.plot(xs, ys, color=ROUTE_COLOUR, linewidth=ROUTE_LINE_WIDTH, zorder=5, solid_capstyle="round")
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                if math.dist((x0, y0), (x1, y1)) > 0.05 * (view[2] - view[0]):
                    axes.annotate("", (x0 + 0.58 * (x1 - x0), y0 + 0.58 * (y1 - y0)),
                                  (x0 + 0.46 * (x1 - x0), y0 + 0.46 * (y1 - y0)), zorder=6,
                                  arrowprops={"arrowstyle": "-|>", "color": ROUTE_COLOUR, "lw": 1.5, "mutation_scale": 14})
        if polylines:
            legend.append(Line2D([], [], color=ROUTE_COLOUR, linewidth=ROUTE_LINE_WIDTH, label="Route (selected doors)"))
        used_doors = [node.removeprefix(DOOR_PREFIX) for node in route.node_path if node.startswith(DOOR_PREFIX)] if route else []
        for opening_id in used_doors:
            opening = building_map.openings[opening_id]
            if opening["floor_id"] == floor_id:
                axes.plot(*opening["position"], "s", color="white", markeredgecolor=ROUTE_COLOUR, markersize=6, zorder=7)
        # Closed elements.
        closed_marked = False
        for opening_id in building_map.closed:
            opening = building_map.openings.get(opening_id)
            if opening and opening["floor_id"] == floor_id:
                axes.plot(*opening["position"], "X", color=CLOSED_EDGE_COLOUR, markeredgecolor="white", markersize=12, zorder=9)
                labels.reserve(*opening["position"])
                closed_marked = True
        for space_id, connector in closed_connector_spaces.items():
            if space_id in building_map.spaces and building_map.spaces[space_id]["floor_id"] == floor_id:
                x, y = building_map.anchor(space_id)
                axes.plot(x, y, "X", color=CLOSED_EDGE_COLOUR, markeredgecolor="white", markersize=14, zorder=9)
                labels.reserve(x, y)
                labels.place(f"{connector['name']} (closed)", around(x, y), color=CLOSED_EDGE_COLOUR, fontweight="bold")
                closed_marked = True
        if closed_marked:
            legend.append(Line2D([], [], marker="X", linestyle="", color=CLOSED_EDGE_COLOUR, markersize=10, label="Closed door / lift / stairs"))
        if any(space["id"] in building_map.closed for space in spaces):
            legend.append(Patch(facecolor=CLOSED_COLOUR, edgecolor=CLOSED_EDGE_COLOUR, hatch="///", label="Closed room"))
        # Start, destination and numbered stops.
        route_points = {space_id: building_map.anchor(space_id) for _, space_id in stops_here}
        if route and start_id in route_points:
            x, y = route_points[start_id]
            axes.plot(x, y, "o", color=START_COLOUR, markeredgecolor="white", markersize=10, zorder=11)
            labels.reserve(x, y)
            labels.place(f"Start: {short(building_map.spaces[start_id]['name'])}", around(x, y), color=START_COLOUR, fontweight="bold")
            legend.append(Line2D([], [], marker="o", linestyle="", color=START_COLOUR, markersize=10,
                                 label=f"Start: {short(building_map.spaces[start_id]['name'])}"))
        numbered = [(index, space_id) for index, space_id in stops_here if 0 < index < len(route.stops) - 1] if route else []
        grouped: dict[str, list[int]] = {}
        for index, space_id in numbered:
            grouped.setdefault(space_id, []).append(index)
        for space_id, numbers in grouped.items():
            x, y = route_points[space_id]
            text = ",".join(str(number) for number in numbers)
            axes.annotate(text, (x, y), ha="center", va="center", fontsize=9, fontweight="bold", color="white", zorder=11,
                          bbox={"boxstyle": "circle,pad=0.35", "fc": STOP_COLOUR, "ec": "white"})
            labels.reserve(x, y, 13)
            labels.place(short(building_map.spaces[space_id]["name"]), around(x, y, 16), color=STOP_COLOUR)
        for index, space_id in numbered:
            name = building_map.spaces[space_id]["name"].replace("$", r"\$")
            legend.append(Line2D([], [], marker=f"${index}$", linestyle="", color=STOP_COLOUR, markersize=9, label=short(name)))
        if route and destination_id in route_points:
            x, y = route_points[destination_id]
            axes.plot(x, y, "*", color=ROUTE_COLOUR, markeredgecolor="white", markersize=24, zorder=10)
            labels.reserve(x, y, 14)
            name = short(building_map.spaces[destination_id]["name"])
            labels.place(f"Destination: {name}", around(x, y, 16), color=ROUTE_COLOUR, fontweight="bold")
            legend.append(Line2D([], [], marker="*", linestyle="", color=ROUTE_COLOUR, markersize=13, label=f"Destination: {name}"))
        for _, point, text in handoffs:
            axes.plot(*point, "D", color=HANDOFF_COLOUR, markeredgecolor="white", markersize=9, zorder=10)
            labels.reserve(*point)
            labels.place(text, around(*point), color=HANDOFF_COLOUR, fontweight="bold")
        if handoffs:
            legend.append(Line2D([], [], marker="D", linestyle="", color=HANDOFF_COLOUR, markersize=8, label="Stairs / lift / entrance handoff"))
        # Selection.
        if selected_space:
            polygon_bounds = building_map.space_polygon(selected_space).bounds
            room_name = short(building_map.spaces[selected_space]["name"])
            if selected_asset:
                x, y = selected_asset["position"]
                axes.plot(x, y, "D", color=SELECTION_COLOUR, markeredgecolor="black", markersize=13, zorder=10)
                labels.reserve(x, y, 12)
                labels.place(short(f"{selected_asset['name']} ({selected_asset['type']})"), around(x, y, 14),
                             color="black", fontweight="bold")
                labels.place(f"in {room_name}", above_below(polygon_bounds), color=SELECTION_COLOUR, fontweight="bold")
                legend.append(Line2D([], [], marker="D", linestyle="", markerfacecolor=SELECTION_COLOUR, markeredgecolor="black",
                                     markersize=9, label="Selected asset"))
            else:
                labels.place(room_name, above_below(polygon_bounds), color=SELECTION_COLOUR, fontweight="bold")
            legend.append(Patch(facecolor=SELECTION_FILL, edgecolor=SELECTION_COLOUR, linewidth=2, label="Selected room"))
        # Landmarks and destination context.
        for kind, target_id in targets:
            if kind == "space":
                bounds = building_map.space_polygon(target_id).bounds
                name = short(building_map.spaces[target_id]["name"])
                centre = (*label_point(building_map, target_id), 0, 0, "center", "center")
                inside = labels.box(f"Landmark:\n{name}", LABEL_SIZE, centre)
                room_pixels = labels.pixel(bounds[2], bounds[3])[0] - labels.pixel(bounds[0], bounds[1])[0]
                if inside[2] - inside[0] <= room_pixels and labels.place(
                    f"Landmark:\n{name}", [centre], optional=True, color=LANDMARK_COLOUR, fontweight="bold"
                ):
                    continue
                labels.place(f"Landmark: {name}", above_below(bounds), color=LANDMARK_COLOUR, fontweight="bold")
            else:
                asset = building_map.assets[target_id]
                x, y = asset["position"]
                axes.plot(x, y, "P", color=LANDMARK_COLOUR, markeredgecolor="white", markersize=12, zorder=10)
                labels.reserve(x, y, 12)
                labels.place(f"Landmark: {short(asset['name'])}", around(x, y, 14), color=LANDMARK_COLOUR, fontweight="bold")
        if landmark_spaces:
            legend.append(Patch(facecolor=LANDMARK_FILL, edgecolor=LANDMARK_COLOUR, linewidth=2, label="Landmark / destination context room"))
        if any(kind == "asset" for kind, _ in targets):
            legend.append(Line2D([], [], marker="P", linestyle="", color=LANDMARK_COLOUR, markersize=9, label="Landmark object"))
        # Remaining room names, only where they fit.
        for space in sorted(spaces, key=lambda item: -building_map.space_area_m2(item["id"])):
            space_id = space["id"]
            x, y = label_point(building_map, space_id)
            if not in_view(x, y):
                continue
            bounds = building_map.space_polygon(space_id).bounds
            lower, upper = labels.pixel(bounds[0], bounds[1]), labels.pixel(bounds[2], bounds[3])
            name = space["name"] + (" (closed)" if space_id in building_map.closed else "")
            labels.place(short(name), [(x, y, 0, 0, "center", "center")], size=ROOM_LABEL_SIZE, optional=True,
                         max_width_pixels=abs(upper[0] - lower[0]), color="#444444",
                         bbox={"boxstyle": "round,pad=0.1", "fc": "white", "ec": "none", "alpha": 0.55})
        axes.set_title(f"{building_map.data['building']['name']} — {building_map.floor_name(floor_id)}")
        if legend:
            axes.legend(handles=legend, loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=2, fontsize=8, frameon=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(path, bbox_inches="tight")
    finally:
        plt.close(figure)
    return path


def route_floor_ids(building_map: BuildingMap, route: RouteResult) -> list[str]:
    """Floors the route visits, in order of first visit (a lone stair/lift node still counts)."""
    return list(dict.fromkeys(
        floor_id for floor_id, _ in route_polylines(building_map, route)
    ))


def draw_route(building_map: BuildingMap, output_directory: Path, landmark_ids: list[str] | None = None) -> list[Path]:
    """One PNG per floor of the active route, with stops, handoffs and the given landmarks."""
    route = building_map.last_route
    return [
        draw_floor(
            building_map, floor_id, output_directory / f"route_{building_map.floors[floor_id]['level']}.png",
            route=route, landmark_ids=landmark_ids,
        )
        for floor_id in route_floor_ids(building_map, route)
    ]


def draw_location(building_map: BuildingMap, output_directory: Path) -> Path:
    """The selected room or asset on its floor."""
    selection = building_map.selection
    level = building_map.floor_level(selection["floor_id"])
    return draw_floor(
        building_map, selection["floor_id"], output_directory / f"location_{level}.png", selection=selection
    )
