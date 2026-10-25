"""Local multi-building session and reviewed plan creation, used by chat and CLI.

Run ``python -m final_agent.workspace --building data/dev/<id>``. Every new run
gets its own directory; ``--resume <directory>`` opens that exact saved session.
"""

import argparse
import copy
import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

from anthropic.lib.tools import ToolError

from .building_map import BuildingMap, MapError, require_navigation_records
from .campus import Campus
from .plan_build import Calibration, PlanDraft, PlanError, extract_plan, observations_to_building
from .storage import JsonBuildingStore
from .tools import ArgumentCheckedTool, as_json, make_emergency_tools, make_tools, route_json
from .viewer import draw_campus_route, draw_plan_preview


def safe_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise MapError("IDs must use letters, digits, dots, underscores or hyphens and start with a letter/digit.")
    return value


class Workspace:
    """One explicit local session, retaining current maps and reviewed draft state."""

    def __init__(
        self, directory: Path, client=None, model: str | None = None, *, notes_database: Path | None = None,
    ):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.campus = Campus(self.directory / "campus.json")
        self.client, self.model = client, model
        self.notes_database = Path(notes_database if notes_database is not None else self.directory / "room_notes.sqlite3").resolve()
        self.report_session_id = uuid.uuid4().hex
        self.facility_numbers: dict[str, str] = {}
        self.draft: PlanDraft | None = None
        self.draft_id: str | None = None
        self.current_location: dict | None = None
        self.preferences: dict = {}
        self.pending_plan: dict | None = None
        # Mock emergencies last only for this process and are isolated by building/map instance.
        self.emergency_tools: dict[str, tuple[BuildingMap, dict]] = {}
        state = self.directory / "session.json"
        if state.exists():
            data = JsonBuildingStore.load(state)
            self.report_session_id = data.get("report_session_id", self.report_session_id)
            if notes_database is None and data.get("notes_database"):
                self.notes_database = Path(data["notes_database"])
            self.facility_numbers = data.get("facility_numbers", {})
            self.current_location = data.get("current_location")
            self.preferences = data.get("preferences", {})
            self.pending_plan = data.get("pending_plan")
            for bid, local in data.get("local_state", {}).items():
                if bid not in self.campus.buildings:
                    continue
                building = self.campus.buildings[bid]["map"]
                building.selection = local.get("selection")
                building.active_request = local.get("active_request")
                if building.active_request:
                    try:
                        building.recompute_active_route()
                    except MapError:
                        pass  # Keep the request and clear route; reopening may make it reachable.
            draft = data.get("draft")
            if draft:
                self.draft_id = draft["draft_id"]
                self.draft = PlanDraft(draft["data"], Path(draft["output_path"]),
                                       base_revision=draft["base_revision"], current_revision=draft["current_revision"],
                                       base_data=draft["base_data"], previous=draft.get("previous"),
                                       existing_building=draft.get("existing_building", False),
                                       acknowledged_warnings=draft.get("acknowledged_warnings", False))
        self.save_session()

    def save_session(self) -> None:
        draft = None
        if self.draft is not None and not self.draft.cancelled:
            draft = {"draft_id": self.draft_id, "data": self.draft.data,
                     "output_path": str(self.draft.output_path), "base_revision": self.draft.base_revision,
                     "current_revision": self.draft.current_revision, "base_data": self.draft.base_data,
                     "previous": self.draft.previous, "existing_building": self.draft.existing_building,
                     "acknowledged_warnings": self.draft.acknowledged_warnings}
        JsonBuildingStore.save(self.directory / "session.json", {
            "notes_database": str(self.notes_database), "report_session_id": self.report_session_id,
            "facility_numbers": self.facility_numbers,
            "current_location": self.current_location, "preferences": self.preferences, "draft": draft,
            "pending_plan": self.pending_plan,
            "local_state": {bid: {"selection": item["map"].selection, "active_request": item["map"].active_request}
                            for bid, item in self.campus.buildings.items()},
        })

    def building(self, building_id: str | None = None) -> dict:
        building_id = building_id or self.campus.selected_building_id
        if building_id not in self.campus.buildings:
            raise MapError("Select a registered building first; use list_buildings/select_building.")
        return self.campus.buildings[building_id]

    def register(self, path: str, *, facility_number: str | None = None) -> dict:
        raw_path = Path(path)
        require_navigation_records(JsonBuildingStore.load(raw_path))
        source = BuildingMap.load(raw_path)
        bid = safe_id(source.data["building"]["id"])
        if facility_number is not None and not str(facility_number).strip():
            raise ValueError("Give a non-empty facility number.")
        if bid in self.campus.buildings:
            raise MapError(f"Building {bid!r} is already loaded; select it or start a reviewed edit.")
        target = self.directory / "buildings" / bid / "original.json"
        source.save(target)
        self.campus.register_building(bid, target, source.data["building"]["name"])
        if self.campus.selected_building_id is None:
            self.campus.select_building(bid)
        if facility_number is not None:
            self.facility_numbers[bid] = str(facility_number).strip()
        self.save_session()
        return {"buildings": self.campus.list_buildings(), "resume": str(self.directory)}

    def preview(self) -> dict:
        if self.draft is None:
            raise PlanError("There is no plan draft. Create a plan or begin a building edit first.")
        result = self.draft.preview()
        before = {row["id"]: row for key in ("spaces", "openings", "vertical_connectors", "assets")
                  for row in self.draft.base_data.get(key, []) if isinstance(row, dict) and isinstance(row.get("id"), str)}
        after = {row["id"]: row for key in ("spaces", "openings", "vertical_connectors", "assets")
                 for row in self.draft.data.get(key, []) if isinstance(row, dict) and isinstance(row.get("id"), str)}
        changed_ids = [eid for eid in before.keys() | after.keys() if before.get(eid) != after.get(eid)]
        result["changed_ids"] = sorted(changed_ids)
        images = []
        metadata = self.draft.data.get("import_metadata", {})
        missing_sources = []
        for floor in self.draft.data.get("floors", []):
            source = metadata.get("sources", {}).get(floor["id"], {})
            source_path = Path(source["source_path"]) if source.get("source_path") else None
            if source_path is not None and not source_path.is_file():
                missing_sources.append(str(source_path))
                source_path = None
            output = self.directory / "drafts" / self.draft_id / f"preview-{safe_id(floor['id'])}.png"
            try:
                draw_plan_preview(self.draft.data, output,
                                  source_path=source_path,
                                  calibration=metadata.get("calibrations", {}).get(floor["id"]),
                                  floor_id=floor["id"], issues=result["validation_issues"], changed_ids=changed_ids)
            except (MapError, KeyError, TypeError, ValueError) as error:
                images.append({"floor_id": floor["id"], "error": f"Correct invalid draft records before rendering: {error}"})
            else:
                images.append({"floor_id": floor["id"], "image": str(output)})
        result.update(draft_id=self.draft_id, images=images, status="pending_review", missing_source_images=missing_sources)
        self.save_session()
        return result

    def begin_edit(self, building_id: str | None = None) -> dict:
        self._check_no_pending_draft()
        item = self.building(building_id)
        data = copy.deepcopy(item["map"].data)
        data["navigation_state"] = {"closed": sorted(item["map"].closed)}
        self._new_draft(data, item["revision"], data)
        self.draft.existing_building = True
        return self.preview()

    def _check_no_pending_draft(self):
        if self.pending_plan:
            raise PlanError("Calibrate or cancel the pending plan before starting another draft.")
        if self.draft is not None and not self.draft.cancelled:
            bid = self.draft.data.get("building", {}).get("id")
            if bid not in self.campus.buildings or self.draft.data != self.draft.base_data:
                raise PlanError("Review/apply or cancel the pending draft before starting another.")

    def _new_draft(self, data: dict, revision: int, base_data: dict | None = None):
        self.draft_id = uuid.uuid4().hex[:12]
        path = self.directory / "drafts" / self.draft_id / "building.json"
        self.draft = PlanDraft(data, path, base_revision=revision, current_revision=revision, base_data=base_data)

    def create_plan(self, building_id: str, name: str, floors: list[dict], license: str,
                    attribution: str) -> dict:
        """Each floor supplies source_path, metadata, measured scale and an aligned frame."""
        self._check_no_pending_draft()
        safe_id(building_id)
        if building_id in self.campus.buildings:
            raise PlanError("That building ID already exists; begin_building_edit preserves its identity.")
        if not license.strip() or not attribution.strip():
            raise PlanError("Supply the source's declared license and attribution; use 'unknown' explicitly if unknown.")
        if self.client is None or self.model is None:
            raise PlanError("Plan vision extraction needs the configured Anthropic client and model.")
        if not floors:
            raise PlanError("Supply at least one floor and its calibration.")
        calibrations, sources, records = {}, {}, []
        observations = {key: [] for key in ("spaces", "openings", "assets", "vertical_connectors", "uncertainties")}
        for floor in floors:
            fid = safe_id(floor["id"])
            if fid in calibrations:
                raise PlanError(f"Duplicate floor ID {fid!r}.")
            for required in ("name", "level", "elevation_m", "source_path"):
                if required not in floor:
                    raise PlanError(f"Floor {fid} needs {required} before extraction.")
            if len(floors) > 1 and floor.get("alignment_confirmed") is not True:
                raise PlanError("For multiple floors, confirm common anchors/orientation with alignment_confirmed=true.")
            cal = Calibration.from_known_distance(**floor["calibration"]) if floor.get("calibration") else None
            image_path = Path(floor["source_path"]).resolve()
            saved_source = self.directory / "sources" / uuid.uuid4().hex[:12] / image_path.name
            saved_source.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(image_path, saved_source)
            result = extract_plan(self.client, self.model, saved_source, floor_id=fid,
                                  calibration=cal, metadata={"license": license, "floor": floor})
            if cal is None and result.get("calibration_transform"):
                evidence = result.get("calibration", {})
                cal = Calibration.from_known_distance(evidence["point_a_px"], evidence["point_b_px"], evidence["distance_m"])
            result["_provenance"]["original_source_path"] = str(image_path)
            if cal is not None:
                calibrations[fid] = cal
            sources[fid] = result.get("_provenance", {})
            records.append({key: floor[key] for key in ("id", "name", "level", "elevation_m")})
            for key in observations:
                for row in result.get(key, []):
                    if key not in ("vertical_connectors", "uncertainties"):
                        row.setdefault("floor_id", fid)
                    observations[key].append(row)
        if len(calibrations) != len(records):
            # Keep every floor's pixels and copied source, so later calibration cannot
            # silently turn a multi-floor request into a single-floor building.
            self.pending_plan = {"building_id": building_id, "name": name, "floors": records,
                                 "calibrations": {fid: cal.as_dict() for fid, cal in calibrations.items()},
                                 "sources": sources, "observations": observations,
                                 "license": license, "attribution": attribution}
            self.save_session()
            return self._pending_calibration_status()
        data = observations_to_building(building_id=building_id, name=name, floors=records,
                                        observations=observations, calibrations=calibrations,
                                        source_ref=sources, license=license, attribution=attribution)
        data["import_metadata"]["sources"] = sources
        self.pending_plan = None
        self._new_draft(data, 0)
        return self.preview()

    def import_image(self, path: str) -> dict:
        """Path-only single-floor import; drawing dimension annotations are metres."""
        source = Path(path)
        bid = re.sub(r"[^A-Za-z0-9_.-]+", "-", source.stem).strip("-_.") or "building"
        return self.create_plan(bid, source.stem, [{"id": "F0", "name": "Plan floor",
            "level": 0, "elevation_m": 0.0, "source_path": str(source)}], "unknown", "User-supplied plan; attribution unspecified")

    def _pending_calibration_status(self) -> dict:
        pending = self.pending_plan
        missing = [floor["id"] for floor in pending["floors"] if floor["id"] not in pending["calibrations"]]
        return {"status": "needs_calibration", "building_id": pending["building_id"],
                "pending_floor_ids": missing, "source_image": pending["sources"][missing[0]]["source_path"],
                "sources": copy.deepcopy(pending["sources"]), "observations": copy.deepcopy(pending["observations"]),
                "reason": "Supply a measured calibration for each listed floor. Geometry remains uncalibrated; navigation is unavailable.",
                "resume": str(self.directory)}

    def calibrate_pending(self, calibration: dict, floor_id: str | None = None) -> dict:
        if not self.pending_plan:
            raise PlanError("There is no uncalibrated plan awaiting a scale.")
        pending = copy.deepcopy(self.pending_plan)
        # Sessions saved before multi-floor calibration used a single floor record.
        if "floors" not in pending:
            floor = pending.pop("floor")
            pending["floors"] = [floor]
            pending["calibrations"] = {}
            pending["sources"] = {floor["id"]: pending["observations"]["_provenance"]}
        missing = [floor["id"] for floor in pending["floors"] if floor["id"] not in pending["calibrations"]]
        if floor_id is None:
            if len(missing) != 1:
                raise PlanError(f"Supply floor_id to calibrate one of {missing}.")
            floor_id = missing[0]
        if floor_id not in missing:
            raise PlanError(f"Floor {floor_id!r} is not awaiting calibration; choose one of {missing}.")
        cal = Calibration.from_known_distance(**calibration)
        pending["calibrations"][floor_id] = cal.as_dict()
        pending["sources"][floor_id]["calibration"] = cal.as_dict()
        if len(missing) > 1:
            self.pending_plan = pending
            self.save_session()
            return self._pending_calibration_status()
        calibrations = {fid: Calibration(tuple(value["anchor_px"]), value["metres_per_pixel"],
                                         tuple(value["origin_m"]), value["rotation_deg"])
                        for fid, value in pending["calibrations"].items()}
        data = observations_to_building(building_id=pending["building_id"], name=pending["name"],
                                        floors=pending["floors"], observations=pending["observations"],
                                        calibrations=calibrations, source_ref=pending["sources"],
                                        license=pending["license"], attribution=pending["attribution"])
        data["import_metadata"]["sources"] = pending["sources"]
        self.pending_plan = None
        self._new_draft(data, 0)
        return self.preview()

    def correct(self, actions: list[dict]) -> dict:
        if self.draft is None:
            raise PlanError("There is no draft to correct.")
        self.draft.correct(actions)
        return self.preview()

    def apply(self, acknowledge_warnings: bool = False, undo: bool = False) -> dict:
        if self.draft is None:
            raise PlanError("There is no draft to apply or undo.")
        bid = safe_id(self.draft.data["building"]["id"])
        item = self.campus.buildings.get(bid)
        current = item["revision"] if item else 0
        if current != self.draft.base_revision:
            raise PlanError("The building changed after this preview. Begin a fresh edit before applying.")
        before = copy.deepcopy(self.draft)
        self.draft.output_path = self.directory / "buildings" / bid / "revisions" / f"{uuid.uuid4().hex}.json"
        try:
            result = self.draft.undo() if undo else self.draft.apply(
                expected_revision=current, acknowledge_warnings=acknowledge_warnings)
            if item:
                route_update = self.campus.replace_building(bid, self.draft.output_path)
            else:
                self.campus.register_building(bid, self.draft.output_path, self.draft.data["building"]["name"])
                route_update = None
        except Exception:
            self.draft = before
            raise
        warnings = []
        try:
            self.campus.select_building(bid)
        except OSError as error:
            warnings.append(f"Building committed, but saving its browsing selection failed: {error}")
        self.draft.current_revision = self.campus.buildings[bid]["revision"]
        self.draft.base_revision = self.draft.current_revision
        if self.current_location and self.current_location.get("building_id") == bid:
            if self.current_location.get("element_id") not in self.campus.buildings[bid]["map"].spaces:
                self.current_location = None
        try:
            self.save_session()
        except OSError as error:
            warnings.append(f"Building committed, but draft/undo session state could not be saved: {error}")
        return {**result, "building_id": bid, "revision": self.draft.current_revision,
                "resume": str(self.directory), "campus_route": route_update,
                "warnings": warnings,
                "overview": self.building(bid)["map"].overview()}


class ScopedTool(ArgumentCheckedTool):
    """Keep existing tool schemas while resolving their map at each call, even within a turn."""

    def __init__(self, template, workspace: Workspace):
        super().__init__(template.func)
        self.workspace = workspace
        self.input_schema = copy.deepcopy(template.input_schema)
        self.input_schema.setdefault("properties", {})["building_id"] = {
            "type": "string", "description": "Registered building ID; omitted uses the explicitly selected building."}

    def call(self, input: object) -> str:
        if not isinstance(input, dict):
            raise ToolError("Tool arguments must be an object.")
        args = dict(input)
        try:
            item = self.workspace.building(args.pop("building_id", None))
            bid = item["building_id"]
            if self.name == "set_closed":
                element = item["map"].find_element(args["element"])
                update = self.workspace.campus.close({"building_id": bid, "element_id": element}, args["closed"])
                self.workspace.save_session()
                return as_json({"building_id": bid, "element_id": element, "closed": args["closed"],
                                "saved_to": str(self.workspace.campus.path), "campus_route": update})
            building = item["map"]
            if self.name == "add_door":
                building = BuildingMap(copy.deepcopy(building.data))
                building.closed = set(item["map"].closed)
            output = self.workspace.directory / "buildings" / safe_id(bid) / f"revision-{item['revision']}"
            if self.name == "show_route" and building.last_route is not None:
                identity = json.dumps(route_json(building.last_route), sort_keys=True)
                output /= "route-" + hashlib.sha256(identity.encode()).hexdigest()[:12]
            elif self.name == "show_location":
                output /= "location-" + uuid.uuid4().hex[:12]
            current = next(t for t in make_tools(
                building, output, notes_database=self.workspace.notes_database,
                facility_number=self.workspace.facility_numbers.get(bid), session_id=self.workspace.report_session_id,
            ) if t.name == self.name)
            retained_request = None
            if self.name == "find_route":
                # Preserve a valid requested journey even when the current closures make it unreachable.
                args.setdefault("step_free", self.workspace.preferences.get("step_free", False))
                args.setdefault("min_width_m", self.workspace.preferences.get("min_width_m", 0))
                args.setdefault("travel_mode", (building.active_request or {}).get("travel_mode", "walking"))
                for reference in [args["start"], *(args.get("via") or []), args["destination"]]:
                    building.resolve_space(reference)
                retained_request = {"start": args["start"], "destination": args["destination"],
                                    "via": args.get("via"), "step_free": args["step_free"],
                                    "min_width_m": args["min_width_m"], "entrance": args.get("entrance"),
                                    "travel_mode": args["travel_mode"]}
            try:
                result = json.loads(current.call(args))
            except ToolError:
                if retained_request is not None:
                    building.active_request = retained_request
                    self.workspace.save_session()
                raise
            if self.name == "add_door":
                self.workspace.campus.replace_building(bid, result["saved_to"])
            if self.name in {"find_route", "show_location", "add_door"}:
                self.workspace.save_session()
            return as_json({"building_id": bid, "revision": self.workspace.building(bid)["revision"], **result})
        except (MapError, PlanError, OSError, KeyError) as error:
            raise ToolError(str(error)) from error


class ScopedEmergencyTool(ArgumentCheckedTool):
    """Resolve emergency tools at call time without binding an emergency to an old selected map."""

    def __init__(self, template, workspace: Workspace):
        super().__init__(template.func)
        self.workspace = workspace
        self.input_schema = copy.deepcopy(template.input_schema)
        self.input_schema.setdefault("properties", {})["building_id"] = {
            "type": "string", "description": "Building for this simulated emergency; omitted uses the selected building."}

    def call(self, input: object) -> str:
        if not isinstance(input, dict):
            raise ToolError("Tool arguments must be an object.")
        args = dict(input)
        try:
            item = self.workspace.building(args.pop("building_id", None))
            bid, building = item["building_id"], item["map"]
            cached = self.workspace.emergency_tools.get(bid)
            if cached is None or cached[0] is not building:
                output = self.workspace.directory / "buildings" / safe_id(bid) / f"revision-{item['revision']}" / "emergency"
                tools = {tool.name: tool for tool in make_emergency_tools(building, output)}
                cached = (building, tools)
                self.workspace.emergency_tools[bid] = cached
            result = json.loads(cached[1][self.name].call(args))
            return as_json({**result, "building_id": bid, "revision": item["revision"]})
        except (MapError, OSError) as error:
            raise ToolError(str(error)) from error


def make_workspace_tools(workspace: Workspace, emergency: bool = False) -> list:
    tools = []

    def register(function):
        def checked(**kwargs):
            try:
                return as_json(function(**kwargs))
            except (MapError, PlanError, OSError, ValueError, KeyError, TypeError) as error:
                raise ToolError(str(error)) from error
        tools.append(ArgumentCheckedTool(checked, name=function.__name__, description=function.__doc__,
                                         input_schema=ArgumentCheckedTool(function).input_schema))
        return function

    @register
    def list_buildings() -> dict:
        """List registered buildings, exact IDs, floors, revisions, selected scope and explicit walkways."""
        return {"buildings": workspace.campus.list_buildings(), "walkways": list(workspace.campus.walkways.values()),
                "walkway_status": workspace.campus.walkway_status(),
                "current_location": workspace.current_location, "resume": str(workspace.directory)}

    @register
    def select_building(building_id: str) -> dict:
        """Select a building for subsequent local tools. This never moves the person or route endpoints."""
        return {**workspace.campus.select_building(building_id), "overview": workspace.building()["map"].overview()}

    @register
    def register_building(path: str) -> dict:
        """Load an existing building JSON/directory into this session under its original building ID."""
        return workspace.register(path)

    @register
    def search_campus(query: str, building_id: str | None = None) -> dict:
        """Search rooms/assets in one building, or all registered buildings when scope is omitted. Results are scoped."""
        results = []
        ids = [building_id] if building_id else list(workspace.campus.buildings)
        for bid in ids:
            for result in workspace.building(bid)["map"].search(query):
                results.append({**result, "building_id": bid, "element_id": result["id"]})
        return {"results": results, "matches": len(results)}

    @register
    def confirm_location(building_id: str, element_id: str, step_free: bool | None = None,
                         min_width_m: float | None = None) -> dict:
        """Record a user-confirmed current room and optional accessibility preferences; selection alone is not location."""
        item = workspace.building(building_id)
        sid = item["map"].resolve_space(element_id)
        preferences = dict(workspace.preferences)
        if step_free is not None:
            preferences["step_free"] = step_free
        if min_width_m is not None:
            from .building_map import check_number
            preferences["min_width_m"] = check_number("min_width_m", min_width_m, 0)
        old_location, old_preferences = workspace.current_location, workspace.preferences
        workspace.current_location = {"building_id": building_id, "element_id": sid, "kind": "space"}
        workspace.preferences = preferences
        try:
            workspace.save_session()
        except OSError:
            workspace.current_location, workspace.preferences = old_location, old_preferences
            raise
        return {"current_location": workspace.current_location, "preferences": workspace.preferences}

    @register
    def add_walkway(walkway_id: str, name: str, endpoint_a: dict, endpoint_b: dict,
                    length_m: float, width_m: float, step_free: bool) -> dict:
        """Add a measured bidirectional walkway between {building_id,opening_id} entrances. Supply actual length/access."""
        return workspace.campus.add_walkway(walkway_id, name, endpoint_a, endpoint_b, length_m, width_m, step_free)

    @register
    def find_campus_route(start: dict, destination: dict, via: list[dict] | None = None,
                          step_free: bool | None = None, min_width_m: float | None = None) -> dict:
        """Route across floors/buildings. Each endpoint is {building_id,kind:space|asset,element_id}; retain via order.

        Missing constraints use confirmed session preferences. Return ordered indoor and walkway legs or unreachable.
        """
        result = workspace.campus.find_route(start, destination, via,
                                             workspace.preferences.get("step_free", False) if step_free is None else step_free,
                                             workspace.preferences.get("min_width_m", 0) if min_width_m is None else min_width_m)
        return {**result, "walkway_status": workspace.campus.walkway_status()}

    @register
    def show_campus_route() -> dict:
        """Generate the current campus journey's ordered floor and walkway images; unreachable routes clear old views."""
        route = workspace.campus.last_route
        if not route or not route.get("reachable"):
            raise MapError("No reachable current campus route to display. Compute a permitted route first.")
        views = draw_campus_route(workspace.campus, route, workspace.directory / "routes" / route["route_id"])
        return {"route_id": route["route_id"], "views": views}

    @register
    def set_campus_closed(target: dict, closed: bool) -> dict:
        """Close/reopen {walkway_id} or {building_id,element_id}; persist then recompute the same requested journey."""
        update = workspace.campus.close(target.get("walkway_id", target), closed)
        return {"saved_to": str(workspace.campus.path), "closed": closed, "campus_route": update}

    @register
    def create_building_from_plan(building_id: str, name: str, floors: list[dict], license: str, attribution: str) -> dict:
        """Extract PNG/JPEG plan images into a pending draft. Never apply without reviewed preview and explicit user apply.

        Each floor needs id,name,level,elevation_m,source_path,calibration. calibration contains point_a_px:[x,y],
        point_b_px:[x,y],distance_m; optionally origin_m:[x,y],rotation_deg. Multi-floor imports also need
        alignment_confirmed:true and calibrated common-frame anchors/orientations. Ask for missing scale/elevation/
        alignment or attribution rather than inventing it. A one-page PDF is rendered to PNG before extraction.
        """
        return workspace.create_plan(building_id, name, floors, license, attribution)

    @register
    def import_plan_image(path: str) -> dict:
        """Start from a PNG, JPEG, or one-page PDF path. Printed dimensions/scale are metres; use visible metric evidence only.
        The first single floor uses level 0 and elevation 0 as a local datum, source/license stay explicitly unknown.
        Produces a pending draft or needs_calibration; never claims navigation on an uncalibrated image.
        """
        return workspace.import_image(path)

    @register
    def calibrate_plan(calibration: dict, floor_id: str | None = None) -> dict:
        """Calibrate already-extracted pending pixels without another vision request. Supply point_a_px,
        point_b_px,distance_m and optional origin_m/rotation_deg. Choose floor_id when multiple floors
        await scale; omitted uses the sole remaining floor. All drawing dimensions are metres.
        """
        return workspace.calibrate_pending(calibration, floor_id)

    @register
    def correct_plan_pixels(floor_id: str, actions: list[dict]) -> dict:
        """Apply source-image pixel corrections to the current draft. Set actions may use polygon_px,
        position_px or width_px; converts deterministically into metre fields before the usual preview.
        """
        if workspace.draft is None:
            raise PlanError("There is no plan draft.")
        calibration = workspace.draft.data.get("import_metadata", {}).get("calibrations", {}).get(floor_id)
        if not calibration:
            raise PlanError("This floor has no source-image calibration.")
        cal = Calibration(tuple(calibration["anchor_px"]), calibration["metres_per_pixel"],
                          tuple(calibration["origin_m"]), calibration["rotation_deg"])
        converted = copy.deepcopy(actions)
        for action in converted:
            field = action.get("field")
            if field == "polygon_px":
                action["field"], action["value"] = "polygon", [cal.transform(p) for p in action["value"]]
            elif field == "position_px":
                action["field"], action["value"] = "position", cal.transform(action["value"])
            elif field == "width_px":
                action["field"], action["value"] = "width_m", action["value"] * cal.metres_per_pixel
            else:
                raise PlanError("Pixel corrections support polygon_px, position_px and width_px.")
        return workspace.correct(converted)

    @register
    def begin_building_edit(building_id: str | None = None) -> dict:
        """Copy an existing building into a reviewable draft; current geometry and routes stay active until apply."""
        return workspace.begin_edit(building_id)

    @register
    def preview_plan() -> dict:
        """Show pending geometry, source-plan overlay, validation issues, draft/base revision and exact IDs."""
        return workspace.preview()

    @register
    def correct_plan(actions: list[dict]) -> dict:
        """Patch the draft and regenerate preview. Set: {kind:'set',element_type:'space'|'opening'|'connector'|'asset',
        id,field,value}. Space fields name/type/room_type/polygon; opening position/width_m/step_free/space_ids;
        connector floor_ids/space_ids/step_free; asset space_id/floor_id/position/footprint.
        Coordinates are building metres. For ambiguous geometry ask for source points or dimensions.
        Add a missing element with {kind:'add',element_type,value:<complete schema record>}; remove a false
        opening with {kind:'delete',element_type:'opening',id}. Resolve uncertainty using the set fields
        and kind:'resolve_uncertainty' after the user confirms the fact.
        """
        return workspace.correct(actions)

    @register
    def apply_plan(acknowledge_warnings: bool = False) -> dict:
        """Commit the reviewed current draft only after the user requests apply. Invalid/stale drafts are rejected.
        Set acknowledge_warnings only after the user reviewed the explicit warnings and accepted their consequences.
        """
        return workspace.apply(acknowledge_warnings)

    @register
    def cancel_plan() -> dict:
        """Discard pending draft changes without changing the registered building or current saved bytes."""
        if workspace.pending_plan:
            workspace.pending_plan = None
            workspace.save_session()
            return {"cancelled": True}
        if workspace.draft is None:
            raise PlanError("There is no draft to cancel.")
        result = workspace.draft.cancel()
        workspace.save_session()
        return result

    @register
    def undo_plan() -> dict:
        """Undo the most recent committed plan/edit, persist and reload it, invalidating affected route artifacts."""
        return workspace.apply(undo=True)

    # A placeholder only supplies schemas for an empty new-building workspace.
    template_map = workspace.campus.selected_map or BuildingMap({
        "building": {"id": "new", "name": "New building", "source": "pending"},
        "floors": [], "spaces": [], "openings": [], "assets": [], "vertical_connectors": []})
    tools.extend(ScopedTool(t, workspace) for t in make_tools(
        template_map, workspace.directory, notes_database=workspace.notes_database, session_id=workspace.report_session_id,
    ))
    if emergency:
        tools.extend(ScopedEmergencyTool(t, workspace) for t in make_emergency_tools(template_map, workspace.directory))
    return tools


def main(argv: list[str] | None = None) -> None:
    from .agent import BuildingAgent, MODELS, add_model_argument
    parser = argparse.ArgumentParser(description="Chat across buildings, or build one from calibrated plan images.")
    parser.add_argument("--building", action="append", default=[], help="Existing building directory or JSON; repeat to load more.")
    parser.add_argument("--plan", type=Path, help="Create a reviewed single-floor draft directly from a PNG/JPEG path; dimensions are metres.")
    parser.add_argument("--resume", type=Path, help="Exact existing workspace directory to resume.")
    parser.add_argument("--output", type=Path, default=Path("agent_output/workspaces"))
    parser.add_argument("--commands", type=Path, help="Run a JSON array of {tool,input} commands instead of chatting.")
    parser.add_argument("--notes-db", type=Path, help="shared local SQLite reports database; resumed chats retain their saved path")
    parser.add_argument("--facility-number", help="report facility key for the selected building or new plan")
    add_model_argument(parser)
    args = parser.parse_args(argv)
    import anthropic
    workspace = Workspace(args.resume or args.output / uuid.uuid4().hex[:12],
                          client=anthropic.Anthropic(), model=MODELS[args.model],
                          notes_database=args.notes_db if args.notes_db is not None else
                          (None if args.resume else args.output.parent / "room_notes.sqlite3"))
    for source in args.building:
        workspace.register(source)
    print(f"Workspace/resume: {workspace.directory}")
    if args.plan:
        import time
        started = time.monotonic()
        result = workspace.import_image(str(args.plan))
        print(as_json({**result, "extraction_elapsed_s": round(time.monotonic() - started, 2)}))
    if args.facility_number is not None:
        if not args.facility_number.strip():
            parser.error("Give a non-empty facility number.")
        building_id = (workspace.draft.data["building"]["id"] if workspace.draft is not None
                       else workspace.campus.selected_building_id)
        if building_id is None:
            parser.error("--facility-number needs a loaded building or plan.")
        workspace.facility_numbers[building_id] = args.facility_number.strip()
        workspace.save_session()
    if args.commands:
        tools = {tool.name: tool for tool in make_workspace_tools(workspace, emergency=True)}
        for command in json.loads(args.commands.read_text(encoding="utf-8")):
            print(tools[command["tool"]].call(command.get("input", {})))
        return
    agent = BuildingAgent(workspace.campus.selected_map, workspace.directory, client=workspace.client,
                          model=workspace.model, workspace=workspace, emergency=True)
    print("Ask about a building, load another, or supply a plan image. Type exit to stop.")
    while True:
        try:
            message = input("\nyou> ").strip()
            if message.lower() in {"exit", "quit", "bye"}:
                break
            if message:
                print(f"\nguide> {agent.ask(message)}")
        except (EOFError, KeyboardInterrupt):
            break
        except Exception as error:
            print(f"Could not complete this request: {error}")


if __name__ == "__main__":
    main()
