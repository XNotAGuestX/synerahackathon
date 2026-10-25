"""Small file-backed registry and constrained router for multiple buildings."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

import networkx as nx

from .building_map import DOOR_PREFIX, BuildingMap, MapError, door_landing, outline, require_navigation_records, walking_path
from .storage import JsonBuildingStore


class Campus:
    """Own isolated BuildingMaps and measured, explicitly connected walkway links."""

    def __init__(self, manifest: str | Path):
        self.path = Path(manifest)
        self.buildings: dict[str, dict] = {}
        self.walkways: dict[str, dict] = {}
        self.selected_building_id: str | None = None
        self.revision = 0
        self.active_request: dict | None = None
        self.last_route: dict | None = None
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.revision = int(data.get("revision", 0))
            self.selected_building_id = data.get("selected_building_id")
            self.walkways = {w["id"]: w for w in data.get("walkways", [])}
            for item in data.get("buildings", []):
                self._register(item["building_id"], item["name"], item["path"], item.get("revision", 1))
                self.buildings[item["building_id"]]["map"].closed = set(item.get("closed", []))
            self.active_request = data.get("active_request")
            if self.active_request:
                try: self.last_route = self._route(**self.active_request)
                except MapError as error: self.last_route = {"reachable": False, "reason": str(error), "route_id": None}

    def _register(self, building_id: str, name: str, path: str | Path, revision: int = 1):
        source = Path(path).resolve()
        data = JsonBuildingStore.load(source)
        require_navigation_records(data)
        building = data.get("building", data)
        if building.get("id") != building_id:
            raise MapError(f"Building id {building_id!r} does not match source id {building.get('id')!r}.")
        for collection in ("floors", "spaces", "assets", "openings", "vertical_connectors"):
            records = data.get(collection)
            if not isinstance(records, list) or any(not isinstance(record, dict) or not isinstance(record.get("id"), str) for record in records):
                raise MapError(f"Building {building_id}: {collection} must contain records with string IDs.")
            identifiers = [record["id"] for record in records]
            if len(set(identifiers)) != len(identifiers):
                raise MapError(f"Building {building_id}: duplicate IDs in {collection}; correct them before loading.")
        floors = {floor["id"] for floor in data["floors"]}
        spaces = {space["id"]: space for space in data["spaces"]}
        for space in spaces.values():
            if space.get("floor_id") not in floors:
                raise MapError(f"Space {space['id']} references an unknown floor.")
        for opening in data["openings"]:
            refs = opening.get("space_ids", [])
            if len(refs) != 2 or refs[0] == refs[1] or all(ref == "outside" for ref in refs):
                raise MapError(f"Opening {opening['id']} must join two distinct spaces or a room and outside.")
            if any(ref != "outside" and (ref not in spaces or spaces[ref]["floor_id"] != opening.get("floor_id")) for ref in refs):
                raise MapError(f"Opening {opening['id']} has an invalid or cross-floor room reference.")
        self.buildings[building_id] = {"building_id": building_id, "name": name or building.get("name", building_id),
                                       "path": str(source), "map": BuildingMap(data), "revision": revision}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"revision": self.revision, "selected_building_id": self.selected_building_id,
                   "active_request": self.active_request,
                   "buildings": [{**{k: b[k] for k in ("building_id", "name", "path", "revision")},
                                  "closed": sorted(b["map"].closed)} for b in self.buildings.values()],
                   "walkways": list(self.walkways.values())}
        temp = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as f:
                temp = Path(f.name); json.dump(payload, f, ensure_ascii=False, allow_nan=False, indent=2); f.write("\n")
                f.flush(); os.fsync(f.fileno())
            os.replace(temp, self.path)
        finally:
            if temp: temp.unlink(missing_ok=True)

    def register_building(self, building_id: str, path: str | Path, name: str | None = None):
        if building_id in self.buildings: raise MapError(f"Building {building_id!r} is already registered.")
        old_revision = self.revision
        self._register(building_id, name or building_id, path)
        self.revision += 1
        try: self._save()
        except Exception: del self.buildings[building_id]; self.revision = old_revision; raise
        return self.list_buildings()

    def replace_building(self, building_id: str, path: str | Path):
        old = self.buildings.get(building_id)
        if old is None: raise MapError(f"Unknown building {building_id!r}.")
        old_map = old["map"]
        self._register(building_id, old["name"], path, old["revision"] + 1)
        new_map = self.buildings[building_id]["map"]
        new_map.active_request = copy.deepcopy(old_map.active_request)
        selection = old_map.selection
        if selection:
            selected_id = selection.get("id") or selection.get("element_id")
            selected_space = selection.get("space_id")
            if ((selected_id in new_map.spaces or selected_id in new_map.assets or selected_id in new_map.openings)
                    and (selected_space is None or selected_space in new_map.spaces)):
                new_map.select(selected_id)
        old_revision = self.revision; self.revision += 1
        try: self._save()
        except Exception:
            self.buildings[building_id] = old
            self.revision = old_revision
            raise
        self._invalidate()
        local_update = None
        if new_map.active_request:
            try: local_update = {"reachable": True, "route": asdict(new_map.recompute_active_route())}
            except MapError as error: local_update = {"reachable": False, "reason": str(error)}
        campus_update = self._recompute()
        return {"campus_route": campus_update, "local_route": local_update}

    def list_buildings(self):
        return [{"building_id": k, "name": b["name"], "revision": b["revision"],
                 "floors": copy.deepcopy(b["map"].data["floors"]), "selected": k == self.selected_building_id}
                for k, b in self.buildings.items()]

    def walkway_status(self):
        status = []
        for link in self.walkways.values():
            errors = []
            for endpoint in link["endpoints"]:
                try: self._entrance(endpoint)
                except MapError as error: errors.append(str(error))
            status.append({"walkway_id": link["id"], "usable": not errors and not link["closed"],
                           "closed": link["closed"], "repair_reasons": errors})
        return status

    def select_building(self, building_id: str):
        self._building(building_id); old = self.selected_building_id; self.selected_building_id = building_id
        try: self._save()
        except Exception: self.selected_building_id = old; raise
        return {"selected_building_id": building_id}

    @property
    def selected_map(self):
        return self._building(self.selected_building_id)["map"] if self.selected_building_id else None

    def save(self):
        self._save()

    def add_walkway(self, walkway_id: str, name: str, endpoint_a: dict, endpoint_b: dict,
                    length_m: float, width_m: float, step_free: bool):
        if walkway_id in self.walkways: raise MapError(f"Walkway {walkway_id!r} already exists.")
        for label, value in (("length_m", length_m), ("width_m", width_m)):
            if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or value <= 0:
                raise MapError(f"{label} must be a finite positive number.")
        if not isinstance(step_free, bool): raise MapError("step_free must be a boolean.")
        if endpoint_a == endpoint_b: raise MapError("A walkway must join two distinct entrances.")
        for endpoint in (endpoint_a, endpoint_b): self._entrance(endpoint)
        link = {"id": walkway_id, "name": name, "endpoints": [dict(endpoint_a), dict(endpoint_b)],
                "length_m": float(length_m), "width_m": float(width_m), "step_free": step_free,
                "closed": False, "revision": 1}
        self.walkways[walkway_id] = link; old_revision = self.revision; self.revision += 1
        try: self._save()
        except Exception: del self.walkways[walkway_id]; self.revision = old_revision; raise
        self._invalidate()
        return link

    def _building(self, building_id):
        try: return self.buildings[building_id]
        except KeyError as e: raise MapError(f"Unknown building {building_id!r}.") from e

    def _entrance(self, ref):
        b = self._building(ref.get("building_id")); opening_id = ref.get("opening_id")
        opening = b["map"].openings.get(opening_id)
        refs = opening.get("space_ids", []) if opening else []
        indoor = [s for s in refs if s != "outside"]
        if (opening is None or len(refs) != 2 or
                refs.count("outside") != 1 or len(indoor) != 1 or indoor[0] not in b["map"].spaces or
                b["map"].spaces[indoor[0]]["floor_id"] != opening.get("floor_id")):
            raise MapError(f"{opening_id!r} is not a registered entrance in {ref.get('building_id')!r}.")
        return opening

    def close(self, target_id: str | dict, closed: bool = True):
        if not isinstance(closed, bool): raise MapError("closed must be a boolean.")
        scoped_building = target_id.get("building_id") if isinstance(target_id, dict) else None
        target_id = target_id.get("element_id", target_id.get("id")) if isinstance(target_id, dict) else target_id
        walk_change = scoped_building is None and target_id in self.walkways
        old_revision = self.revision
        if walk_change:
            old_link = copy.deepcopy(self.walkways[target_id])
            self.walkways[target_id]["closed"] = closed; self.walkways[target_id]["revision"] += 1
        else:
            matches = [(bid, b) for bid, b in self.buildings.items() if (scoped_building is None or bid == scoped_building) and (target_id in b["map"].openings or target_id in b["map"].connectors or target_id in b["map"].spaces)]
            if len(matches) != 1: raise MapError(f"Element {target_id!r} is unknown or ambiguous; use a unique walkway id or a scoped building closure.")
            bid, b = matches[0]
            old_closed = set(b["map"].closed); old_building_revision = b["revision"]
            old_map_route = b["map"].last_route
            b["map"].set_closed(target_id, closed)
            b["revision"] += 1
        self.revision += 1
        try: self._save()
        except Exception:
            if walk_change: self.walkways[target_id] = old_link
            else:
                b["map"].closed = old_closed; b["revision"] = old_building_revision
                b["map"].last_route = old_map_route
            self.revision = old_revision
            raise
        self._invalidate()
        update = self._recompute()
        if not walk_change and b["map"].active_request:
            try: local_update = {"reachable": True, "route": asdict(b["map"].recompute_active_route())}
            except MapError as error: local_update = {"reachable": False, "reason": str(error)}
            if update is None: update = {}
            if isinstance(update, dict): update["local_route_update"] = local_update
        return update

    def _invalidate(self): self.last_route = None

    def _resolve(self, ref):
        if not isinstance(ref, dict) or not ref.get("building_id"): raise MapError("Each endpoint needs building_id and element_id.")
        bid = ref["building_id"]; b = self._building(bid); kind = ref.get("kind", "space"); eid = ref.get("element_id", ref.get("id"))
        if kind == "asset":
            asset = b["map"].assets.get(eid)
            if asset is None: raise MapError(f"Unknown asset {eid!r} in {bid!r}.")
            eid = asset["space_id"]
        elif kind != "space": raise MapError("Campus endpoints support space or asset references.")
        if eid not in b["map"].spaces: raise MapError(f"Unknown space {eid!r} in {bid!r}.")
        return bid, eid

    def find_route(self, start: dict, destination: dict, via: list[dict] | None = None,
                   step_free: bool = False, min_width_m: float = 0.0):
        if not isinstance(step_free, bool): raise MapError("step_free must be a boolean.")
        if via is not None and (not isinstance(via, list) or any(not isinstance(ref, dict) for ref in via)):
            raise MapError("via must be a list of scoped endpoint references.")
        request = {"start": start, "destination": destination, "via": via or [], "step_free": step_free, "min_width_m": min_width_m}
        old_request = self.active_request
        self.active_request = request
        try: self._save()
        except Exception:
            self.active_request = old_request
            raise
        try: self.last_route = self._route(**request)
        except MapError as e: self.last_route = {"reachable": False, "reason": str(e), "route_id": None}
        return self.last_route

    def _route(self, start, destination, via, step_free, min_width_m):
        if isinstance(min_width_m, bool) or not isinstance(min_width_m, (int, float)) or not math.isfinite(min_width_m) or min_width_m < 0:
            raise MapError("min_width_m must be a finite non-negative number.")
        stops = [self._resolve(ref) for ref in [start, *via, destination]]
        graph = nx.MultiGraph()
        for bid, building in self.buildings.items():
            local = building["map"].graph(step_free, min_width_m)
            graph.add_nodes_from(((bid, n), attrs) for n, attrs in local.nodes(data=True))
            for a, b, key, attrs in local.edges(keys=True, data=True):
                graph.add_edge((bid, a), (bid, b), key=f"{bid}:{key}", **attrs)
        for link in self.walkways.values():
            if link["closed"] or link["width_m"] < min_width_m or (step_free and not link["step_free"]):
                continue
            try:
                oa, ob = [self._entrance(ep) for ep in link["endpoints"]]
            except MapError:
                continue  # dangling replacement link remains visible in manifest, but unusable
            endpoints = link["endpoints"]
            if any(o["id"] in self._building(ep["building_id"])["map"].closed or
                   (step_free and not o.get("step_free", False)) or o.get("width_m", 0) < min_width_m
                   for ep, o in zip(endpoints, (oa, ob))):
                continue
            ba = endpoints[0]["building_id"]
            bb = endpoints[1]["building_id"]
            na, nb = (ba, "door:" + oa["id"]), (bb, "door:" + ob["id"])
            if na in graph and nb in graph:
                graph.add_edge(na, nb, key="walkway:" + link["id"], weight=link["length_m"], walkway_id=link["id"])
        route_legs, full_nodes, total = [], [], 0.0
        for (ba, sa), (bb, sb) in zip(stops, stops[1:]):
            try:
                distance, nodes = nx.single_source_dijkstra(graph, (ba, sa), (bb, sb), weight="weight")
            except (nx.NetworkXNoPath, nx.NodeNotFound) as error:
                raise MapError(f"No permitted campus route from {sa} in {ba} to {sb} in {bb}.") from error
            selected = []
            for a, b in zip(nodes, nodes[1:]):
                candidates = graph.get_edge_data(a, b)
                key, attrs = min(candidates.items(), key=lambda item: (item[1]["weight"], str(item[0])))
                selected.append((key, attrs))
            current = None
            for i, (key, attrs) in enumerate(selected):
                a, b = nodes[i], nodes[i + 1]
                if attrs.get("walkway_id"):
                    current = None
                    link = self.walkways[attrs["walkway_id"]]
                    route_legs.append({"kind": "walkway", "walkway_id": link["id"], "name": link["name"],
                                       "from": {"building_id": a[0], "opening_id": a[1].removeprefix("door:")},
                                       "to": {"building_id": b[0], "opening_id": b[1].removeprefix("door:")}, "length_m": attrs["weight"]})
                    continue
                bid = a[0]
                if current is None or current["building_id"] != bid:
                    current = {"kind": "indoor", "building_id": bid, "from_node": a[1], "to_node": b[1],
                               "length_m": 0.0, "edge_ids": [], "node_path": [a[1]], "edge_lengths_m": [],
                               "space_path": [a[1]] if a[1] in self._building(bid)["map"].spaces else [],
                               "element_path": [], "geometry_complete": True}
                    if a[1].startswith(DOOR_PREFIX):
                        current["element_path"].append(a[1].removeprefix(DOOR_PREFIX))
                    route_legs.append(current)
                current["to_node"] = b[1]; current["node_path"].append(b[1])
                current["length_m"] += attrs["weight"]
                edge_id = attrs.get("via", attrs.get("space", str(key)))
                current["edge_ids"].append(edge_id); current["edge_lengths_m"].append(attrs["weight"])
                if "via" in attrs:
                    current["element_path"].append(attrs["via"])
                elif b[1].startswith(DOOR_PREFIX):
                    current["element_path"].append(b[1].removeprefix(DOOR_PREFIX))
                if attrs.get("space") and (not current["space_path"] or current["space_path"][-1] != attrs["space"]):
                    current["space_path"].append(attrs["space"])
                if b[1] in self._building(bid)["map"].spaces and (not current["space_path"] or current["space_path"][-1] != b[1]):
                    current["space_path"].append(b[1])
                if attrs.get("space") and not self._walk_is_verified(self._building(bid)["map"], a[1], b[1], attrs["space"]):
                    current["geometry_complete"] = False
            full_nodes.extend(nodes if not full_nodes else nodes[1:]); total += distance
        elapsed = 0.0
        for leg in route_legs:
            leg["cumulative_start_m"] = elapsed
            elapsed += leg["length_m"]
            leg["cumulative_end_m"] = elapsed
            if leg["kind"] == "indoor":
                local = self._building(leg["building_id"])["map"]
                if leg["node_path"][0] in local.spaces and leg["node_path"][-1] in local.spaces:
                    leg["steps"] = local.directions(leg["node_path"], list(zip(leg["edge_ids"], leg["edge_lengths_m"], strict=True)))
                else:
                    leg["steps"] = self._portal_directions(local, leg)
                leg["floor_segments"] = local.floor_segments(leg["space_path"])
                if not leg["geometry_complete"]:
                    leg["geometry_warning"] = "A kit distance uses its disconnected-geometry fallback; the walking line is unverified."
                else:
                    leg["geometry_warning"] = None
        identity = (tuple(full_nodes), self.revision, tuple(sorted((k, b["revision"]) for k, b in self.buildings.items())),
                    tuple(sorted((k, w["revision"]) for k, w in self.walkways.items())))
        return {"reachable": True, "route_id": "campus-" + hashlib.sha1(repr(identity).encode()).hexdigest()[:12],
                "cost_model": "campus-explicit-walkways; indoor legs kit-1.1.0", "total_m": total,
                "legs": route_legs, "node_path": [{"building_id": bid, "node_id": node} for bid, node in full_nodes],
                "space_path": [{"building_id": leg["building_id"], "space_id": space}
                               for leg in route_legs if leg["kind"] == "indoor" for space in leg["space_path"]],
                "element_path": [({"building_id": leg["building_id"], "element_id": element} if leg["kind"] == "indoor"
                                  else {"walkway_id": leg["walkway_id"]}) for leg in route_legs for element in (leg["element_path"] if leg["kind"] == "indoor" else [None])],
                "step_free": step_free, "min_width_m": float(min_width_m), "campus_revision": self.revision,
                "building_revisions": {bid: b["revision"] for bid, b in self.buildings.items()},
                "walkway_revisions": {wid: w["revision"] for wid, w in self.walkways.items()}}

    @staticmethod
    def _walk_is_verified(building: BuildingMap, first: str, second: str, space_id: str) -> bool:
        polygon = outline(building.spaces[space_id]["polygon"])
        def point(node):
            if node == space_id: return building.anchor(space_id)
            if not node.startswith(DOOR_PREFIX): return None
            opening = building.openings.get(node.removeprefix(DOOR_PREFIX))
            if opening is None: return None
            position = opening["position"]
            return door_landing(polygon, (position[0], position[1]))
        a, b = point(first), point(second)
        return a is not None and b is not None and bool(walking_path(polygon, a, b))

    @staticmethod
    def _portal_directions(building: BuildingMap, leg: dict) -> list[str]:
        nodes = leg["node_path"]
        edges = list(zip(leg["edge_ids"], leg["edge_lengths_m"], strict=True))
        prefix, suffix = [], []
        space_positions = [i for i, node in enumerate(nodes) if node in building.spaces]
        if not space_positions:
            return [f"Use the selected indoor portals in order; total indoor distance {leg['length_m']:.1f} m."]
        first, last = space_positions[0], space_positions[-1]
        if first:
            portal = next((n.removeprefix(DOOR_PREFIX) for n in nodes[:first] if n.startswith(DOOR_PREFIX)), None)
            if portal: prefix.append(f"Enter {building.spaces[nodes[first]]['name']} through entrance {portal}.")
        if last < len(nodes) - 1:
            portal = next((n.removeprefix(DOOR_PREFIX) for n in nodes[last + 1:] if n.startswith(DOOR_PREFIX)), None)
            if portal: suffix.append(f"From {building.spaces[nodes[last]]['name']}, continue through entrance {portal}.")
        directions = building.directions(nodes[first:last + 1], edges[first:last])
        return prefix + directions + suffix

    def _recompute(self):
        if self.active_request is None: return None
        return self.find_route(**self.active_request)
