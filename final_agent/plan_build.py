"""Calibrated plan observations, strict building validation, and reviewed edits.

Vision is used only to report pixel-space observations. All coordinate conversion,
validation, patching and persistence remain deterministic here.
"""
from __future__ import annotations

import base64
import copy
from collections import Counter
import hashlib
import json
import math
import io
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class PlanError(ValueError):
    """Invalid plan, correction, or draft lifecycle operation."""


@dataclass(frozen=True)
class Calibration:
    """Pixel-to-building transform; origin is the metre coordinate of anchor_px."""
    anchor_px: tuple[float, float]
    metres_per_pixel: float
    origin_m: tuple[float, float] = (0.0, 0.0)
    rotation_deg: float = 0.0
    check_residual_m: float | None = None

    @classmethod
    def from_known_distance(
        cls, point_a_px: tuple[float, float], point_b_px: tuple[float, float],
        distance_m: float, *, origin_m: tuple[float, float] = (0.0, 0.0),
        rotation_deg: float = 0.0,
    ) -> "Calibration":
        vals = (*point_a_px, *point_b_px, *origin_m, distance_m, rotation_deg)
        if not all(_number(v) for v in vals) or distance_m <= 0:
            raise PlanError("Calibration requires finite coordinates and a positive known distance.")
        pixels = math.dist(point_a_px, point_b_px)
        if pixels <= 0:
            raise PlanError("Calibration points must be distinct.")
        return cls(tuple(map(float, point_a_px)), distance_m / pixels,
                   tuple(map(float, origin_m)), float(rotation_deg))

    def transform(self, point_px: Any) -> list[float]:
        x, y = _pair(point_px, "pixel point")
        if not _number(self.metres_per_pixel) or self.metres_per_pixel <= 0:
            raise PlanError("Calibration scale must be positive and finite.")
        theta = math.radians(self.rotation_deg)
        dx = (x - self.anchor_px[0]) * self.metres_per_pixel
        dy = -(y - self.anchor_px[1]) * self.metres_per_pixel  # image y points down
        return [self.origin_m[0] + dx * math.cos(theta) - dy * math.sin(theta),
                self.origin_m[1] + dx * math.sin(theta) + dy * math.cos(theta)]

    def check_distance(self, point_a_px: tuple[float,float], point_b_px: tuple[float,float],
                       distance_m: float) -> float:
        """Return signed measured-minus-declared residual for a second known dimension."""
        if not _number(distance_m) or distance_m <= 0:
            raise PlanError("Check distance must be positive and finite.")
        measured=math.dist(self.transform(point_a_px),self.transform(point_b_px))
        return measured-float(distance_m)

    def as_dict(self) -> dict[str, Any]:
        return {"anchor_px": list(self.anchor_px), "origin_m": list(self.origin_m),
                "metres_per_pixel": self.metres_per_pixel, "rotation_deg": self.rotation_deg,
                "y_axis_inverted": True, "check_residual_m": self.check_residual_m,
                "pixel_to_metre": {"scale_m_per_px": self.metres_per_pixel,
                                   "origin_px": list(self.anchor_px), "origin_m": list(self.origin_m),
                                   "rotation_rad": math.radians(self.rotation_deg),
                                   "y_axis_inverted": True}}


def extract_plan(client: Any, model: str, image_path: str | Path, *, floor_id: str,
                 calibration: Calibration | None = None, metadata: dict | None = None) -> dict:
    """Ask a vision model for raw pixel observations from actual PNG/JPEG bytes."""
    path = Path(image_path)
    content = path.read_bytes()
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        mime="image/png"
    elif content.startswith(b"\xff\xd8\xff"):
        mime="image/jpeg"
    else:
        raise PlanError("Plan input must be a PNG or JPEG image.")
    if not content:
        raise PlanError("Plan image is empty.")
    try:
        from PIL import Image
        with Image.open(io.BytesIO(content)) as image:
            width_px,height_px=image.size
            image.verify()
    except Exception as exc:
        raise PlanError(f"Plan image is not a readable PNG or JPEG: {exc}") from exc
    prompt = ("Extract only visible/supplied observations from this floor plan. Return one JSON object "
              "with arrays spaces, openings, assets, vertical_connectors, uncertainties. Space fields: "
              "id,floor_id,type,room_type,name,polygon_px (unclosed [[x,y],...]),synthetic. Opening fields: "
              "id,floor_id,space_ids (two spaces or a space and outside),kind,position_px,width_m,step_free,synthetic. "
              "Asset fields: id,name,category,type,space_id,floor_id,position_px,footprint. Connector fields: "
              "id,kind,name,floor_ids,space_ids,step_free,synthetic. Use pixel coordinates from top left. "
              "Room polygons that share a wall must use the same pixel coordinates along that boundary. Preserve "
              "uncertainty; use null for unobservable width_m or step_free and add uncertainty objects "
              "{element_id,field,reason}. Do not infer scale, doors, access, equipment, or connections not visible. "
              f"Every element ID must be unique and start with {floor_id!r} + '-'. Every floor_id must equal "
              f"{floor_id!r}; do not invent fields beyond this schema. Include calibration ONLY if a visible printed dimension or scale "
              "bar gives an explicit metric measurement. Use exactly {point_a_px:[x,y],point_b_px:[x,y],distance_m:number,"
              "evidence:string}; distance_m is metres and evidence identifies the visible label/bar. Otherwise omit "
              "calibration entirely; do not estimate scale. The only supported drawing dimensions are metres. "
              f"The floor id is {floor_id!r}. Supplied calibration, if any: "
              f"{json.dumps(calibration.as_dict() if calibration else None)}. Metadata: {json.dumps(metadata or {})}.")
    started=time.perf_counter()
    response = client.messages.create(model=model, max_tokens=16000, messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": mime,
                                       "data": base64.b64encode(content).decode("ascii")}},
        {"type": "text", "text": prompt},
    ]}])
    total_usage=_usage(response)
    if getattr(response,"stop_reason",None)=="max_tokens":
        raise PlanError("Plan extraction reached the model's 16,000-token limit; simplify the plan image or extract floors separately.")
    text = "\n".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    try:
        data = _parse_json_response(text)
    except (json.JSONDecodeError, PlanError) as first_error:
        # A bounded text-only repair may fix formatting but cannot see the plan or add facts.
        repaired=client.messages.create(model=model,max_tokens=6000,messages=[{"role":"user","content":[
            {"type":"text","text":("Repair only the JSON syntax of the following model response. Preserve every existing "
             "observation and value exactly. Do not infer, complete, add, remove, or correct any facts. "
             "Return only one valid JSON object.\n\nMalformed response:\n"+text)}
        ]}])
        total_usage=_add_usage(total_usage,_usage(repaired))
        if getattr(repaired,"stop_reason",None)=="max_tokens":
            raise PlanError("The JSON repair response also reached its token limit; extract fewer rooms at once.") from first_error
        repaired_text="\n".join(block.text for block in repaired.content if getattr(block,"type",None)=="text")
        try:
            data=_parse_json_response(repaired_text)
        except (json.JSONDecodeError,PlanError) as repair_error:
            raise PlanError(f"Vision response remained invalid after one syntax-only repair: {repair_error}") from repair_error
    if not isinstance(data, dict):
        raise PlanError("Vision response must be a JSON object.")
    evidence_calibration=data.get("calibration")
    if evidence_calibration is None and calibration is not None:
        data["calibration"]=calibration.as_dict()
    elif evidence_calibration is not None:
        try:
            if (not isinstance(evidence_calibration,dict)
                    or not isinstance(evidence_calibration.get("evidence"),str)
                    or not evidence_calibration["evidence"].strip()):
                raise PlanError("Visible scale evidence must include an explanation.")
            parsed=Calibration.from_known_distance(evidence_calibration["point_a_px"],
                    evidence_calibration["point_b_px"],evidence_calibration["distance_m"])
            data["calibration_transform"]=parsed.as_dict()
        except (KeyError,TypeError,PlanError) as exc:
            data["calibration_issue"]={"severity":"error","reason":f"Invalid visible calibration: {exc}"}
    data["_provenance"] = {"source_path": str(path.resolve()), "source_sha256": hashlib.sha256(content).hexdigest(),
                           "source_license": (metadata or {}).get("license"),
                           "image_width_px": width_px,"image_height_px": height_px,
                           "source_page": (metadata or {}).get("page"),
                           "extraction": "vision_observations",
                           "calibration": calibration.as_dict() if calibration else data.get("calibration_transform"),
                           "usage": total_usage,"elapsed_seconds": round(time.perf_counter()-started,3)}
    return data


def _parse_json_response(text: str) -> dict:
    """Parse a complete object; accept an optional Markdown JSON fence, never partial braces."""
    stripped=text.strip()
    if stripped.startswith("```"):
        lines=stripped.splitlines()
        if lines and lines[0].startswith("```"): lines=lines[1:]
        if lines and lines[-1].strip()=="```": lines=lines[:-1]
        stripped="\n".join(lines).strip()
        if stripped.startswith("json"): stripped=stripped[4:].lstrip()
    data=json.loads(stripped)
    if not isinstance(data,dict): raise PlanError("Vision response must be a JSON object.")
    return data


def _usage(response: Any) -> dict[str,int]:
    usage=getattr(response,"usage",None)
    return {"input_tokens":int(getattr(usage,"input_tokens",0) or 0),
            "output_tokens":int(getattr(usage,"output_tokens",0) or 0)}


def _add_usage(first: dict[str,int], second: dict[str,int]) -> dict[str,int]:
    return {key:first.get(key,0)+second.get(key,0) for key in ("input_tokens","output_tokens")}


def observations_to_building(*, building_id: str, name: str, floors: list[dict],
                             observations: dict, calibrations: dict[str, Calibration],
                             source_ref: Any = None, license: str | None = None,
                             attribution: str | None = None) -> dict:
    """Convert observation pixel coordinates into the existing building JSON schema."""
    floor_ids = {f["id"] for f in floors}
    if set(calibrations) != floor_ids:
        raise PlanError("Each floor needs an explicit pixel-to-building calibration.")
    data = {"building": {"id": building_id, "name": name, "source": "plan_import",
                          "source_ref": copy.deepcopy(source_ref), "license": license,
                          "attribution": attribution, "units": "m"},
            "floors": copy.deepcopy(floors), "spaces": [], "openings": [],
            "vertical_connectors": [], "assets": [],
            "import_metadata": {"provenance": copy.deepcopy(observations.get("_provenance", {})),
                                "uncertainties": copy.deepcopy(observations.get("uncertainties", [])),
                                "calibrations": {k: v.as_dict() for k, v in calibrations.items()}}}
    for key in ("spaces", "openings", "assets", "vertical_connectors"):
        for row in observations.get(key, []):
            item = copy.deepcopy(row)
            if not isinstance(item,dict):
                data[key].append(item)
                continue
            floor_id = item.setdefault("floor_id", floors[0]["id"] if len(floors) == 1 else None)
            if key == "vertical_connectors":
                positions=item.pop("position_px_by_floor", {})
                if isinstance(positions,dict):
                    item["position_by_floor"] = {fid: calibrations[fid].transform(p)
                                                   for fid,p in positions.items() if fid in calibrations}
                    if any(fid not in calibrations for fid in positions): item["untransformed_position_px_by_floor"]={fid:p for fid,p in positions.items() if fid not in calibrations}
                data[key].append(item); continue
            if not isinstance(floor_id,str) or floor_id not in floor_ids:
                data[key].append(item)
                continue
            cal = calibrations[floor_id]
            if key == "spaces":
                item["polygon"] = [cal.transform(p) for p in item.pop("polygon_px", [])]
            else:
                item["position"] = cal.transform(item.pop("position_px"))
            item["synthetic"] = bool(item.get("synthetic", False))
            data[key].append(item)
    data["import_metadata"]["validation_issues"] = validate_building(data)
    return data


def validate_building(raw: dict, *, strict: bool = True) -> list[dict]:
    """Validate raw records before indexing, returning actionable structured issues."""
    issues: list[dict] = []
    def issue(reason: str, element_id: str | None = None, floor_id: str | None = None,
              severity: str = "error", repair: str = "") -> None:
        issues.append({"severity": severity, "element_id": element_id, "floor_id": floor_id,
                       "reason": reason, "repair": repair})
    if not isinstance(raw, dict): return [{"severity":"error","element_id":None,"floor_id":None,"reason":"Building must be an object.","repair":"Supply building JSON."}]
    meta=raw.get("building")
    if not isinstance(meta,dict): issue("Building metadata must be an object.",repair="Supply building ID and name.")
    elif not isinstance(meta.get("id"),str) or not meta.get("id").strip() or not isinstance(meta.get("name"),str) or not meta.get("name").strip():
        issue("Building ID and name must be nonempty strings.",repair="Supply a stable building ID and name.")
    floors = raw.get("floors", []); spaces = raw.get("spaces", []); openings = raw.get("openings", [])
    connectors = raw.get("vertical_connectors", []); assets = raw.get("assets", [])
    import_meta=raw.get("import_metadata",{})
    if not isinstance(import_meta,dict): import_meta={}
    uncertainties_for_openings=import_meta.get("uncertainties",[])
    if not isinstance(uncertainties_for_openings,list): uncertainties_for_openings=[]
    if not all(isinstance(raw.get(k, []), list) for k in ("floors","spaces","openings","vertical_connectors","assets")):
        issue("Element collections must be arrays.", repair="Use arrays for all schema collections."); return issues
    if not floors: issue("Building must contain at least one floor.",repair="Add a measured floor before navigation.")
    if not spaces: issue("Building must contain at least one space.",repair="Extract or add at least one room.")
    global_ids=set()
    floor_ids = _unique_records(floors, "floor", issues, global_ids)
    space_ids = _unique_records(spaces, "space", issues, global_ids)
    opening_ids = _unique_records(openings, "opening", issues, global_ids)
    connector_ids = _unique_records(connectors, "connector", issues, global_ids)
    asset_ids = _unique_records(assets, "asset", issues, global_ids)
    levels = set()
    for f in floors:
        if not isinstance(f,dict): continue
        fid=f.get("id"); elev=f.get("elevation_m")
        if isinstance(f.get("level"), bool) or not isinstance(f.get("level"), int): issue("Floor level must be an integer.",fid,fid)
        if not _number(elev): issue("Floor elevation_m must be finite.",fid,fid)
        if isinstance(f.get("level"),int) and not isinstance(f.get("level"),bool):
            if f["level"] in levels: issue("Floor levels must be unique.",fid,fid)
            levels.add(f["level"])
    floor_map={f.get("id"):f for f in floors if isinstance(f,dict)}
    space_map={s.get("id"):s for s in spaces if isinstance(s,dict)}
    for s in spaces:
        if not isinstance(s,dict): continue
        sid=s.get("id"); fid=s.get("floor_id"); poly=s.get("polygon")
        if not isinstance(s.get("name"),str) or not s.get("name").strip(): issue("Space name must be a nonempty string.",sid,fid)
        if not isinstance(s.get("room_type"),str) or not s.get("room_type").strip(): issue("Space room_type must be a nonempty string.",sid,fid)
        if not isinstance(fid,str) or fid not in floor_ids: issue("Space references an unknown floor.",sid,fid,repair="Choose an existing floor ID.")
        if not isinstance(s.get("type"),str) or not s.get("type").strip(): issue("Space type must be a nonempty string.",sid,fid)
        if not isinstance(poly,list) or len(poly)<3 or any(not _valid_pair(p) for p in poly): issue("Space polygon needs at least three finite XY points.",sid,fid,repair="Correct boundary coordinates.")
        else:
            try:
                from shapely.geometry import Polygon
                geom=Polygon(poly)
                if not geom.is_valid or geom.area <= 1e-8: issue("Space polygon must be valid and have positive area.",sid,fid,repair="Correct the outline; no automatic geometry repair is applied.")
            except Exception: issue("Space polygon could not be checked.",sid,fid)
    polygons = {}
    for s in spaces:
        if isinstance(s,dict) and isinstance(s.get("polygon"),list) and len(s["polygon"]) >= 3 and all(_valid_pair(p) for p in s["polygon"]):
            try:
                from shapely.geometry import Polygon
                polygons[s.get("id")] = Polygon(s["polygon"])
            except Exception: pass
    for index, first in enumerate(spaces):
        if not isinstance(first,dict) or first.get("id") not in polygons: continue
        for second in spaces[index+1:]:
            if (not isinstance(second,dict) or second.get("floor_id")!=first.get("floor_id")
                    or second.get("id") not in polygons): continue
            try:
                overlap=polygons[first["id"]].intersection(polygons[second["id"]]).area
                if overlap > 0.01:
                    issue(f"Spaces overlap by {overlap:.3f} m².",first.get("id"),first.get("floor_id"),repair=f"Review overlap with space {second.get('id')}.")
            except Exception: pass
    for o in openings:
        if not isinstance(o,dict): continue
        oid=o.get("id"); fid=o.get("floor_id"); ids=o.get("space_ids",[]); width=o.get("width_m")
        if not isinstance(fid,str) or fid not in floor_ids: issue("Opening references an unknown floor.",oid,fid)
        if o.get("kind") not in {"door","opening","entrance"}: issue("Opening kind must be door, opening, or entrance.",oid,fid)
        if not isinstance(o.get("step_free"),bool): issue("Opening step_free must be a confirmed boolean.",oid,fid,repair="Confirm step-free access before navigation.")
        if (not isinstance(ids,list) or len(ids)!=2 or any(not isinstance(x,str) for x in ids)
                or ids[0]==ids[1] or any(x!="outside" and x not in space_ids for x in ids)):
            issue("Opening must join two distinct known spaces, or one space and outside.",oid,fid)
        elif o.get("kind")=="entrance" and "outside" not in ids:
            issue("Entrance opening must connect to outside.",oid,fid)
        elif any(x!="outside" and space_map[x].get("floor_id")!=fid for x in ids): issue("Opening cannot connect across floors.",oid,fid,repair="Use a vertical connector for floor changes.")
        if not _number(width) or width<=0:
            unresolved=any(isinstance(u,dict) and u.get("element_id")==oid and u.get("field")=="width_m" for u in uncertainties_for_openings)
            issue("Opening width_m must be positive and finite.",oid,fid,"error", "Review the source and enter a measured width." if unresolved else "Supply a positive width.")
        if not _valid_pair(o.get("position")): issue("Opening position must be finite XY metres.",oid,fid)
        elif isinstance(ids,list) and len(ids)==2:
            try:
                from shapely.geometry import Point
                point=Point(o["position"])
                connected=[sid for sid in ids if sid!="outside"]
                if len(connected)==2:
                    shared=polygons[connected[0]].boundary.intersection(polygons[connected[1]].boundary)
                    if _number(width) and shared.length + 1e-6 < width:
                        issue("Opening is wider than the shared wall stretch.",oid,fid,repair="Choose a valid wall segment or reduce to a measured opening width.")
                    if shared.distance(point) > 0.15:
                        issue("Opening position is not on the shared wall.",oid,fid,repair="Place it on the shared boundary.")
                elif len(connected)==1 and _number(width):
                    wall=polygons[connected[0]].boundary
                    if wall.length + 1e-6 < width:
                        issue("Entrance is wider than the available room boundary.",oid,fid)
                for sid in ids:
                    if sid != "outside" and sid in polygons and polygons[sid].boundary.distance(point) > 0.15:
                        issue("Opening position is not on the wall boundary of a connected space.",oid,fid,repair="Move the opening onto the shared wall or entrance wall.")
            except Exception: pass
    for c in connectors:
        if not isinstance(c,dict): continue
        cid=c.get("id"); fids=c.get("floor_ids",[]); sids=c.get("space_ids",[])
        if c.get("kind") not in {"stairs","lift"}: issue("Connector kind must be stairs or lift.",cid)
        if not isinstance(c.get("step_free"),bool): issue("Connector step_free must be a confirmed boolean.",cid,repair="Confirm accessibility before navigation.")
        if not isinstance(fids,list) or not isinstance(sids,list) or len(fids)<2 or len(fids)!=len(sids): issue("Connector needs paired floor and stop-space arrays with at least two stops.",cid)
        elif any(not isinstance(x,str) for x in fids+sids) or len(set(fids))!=len(fids) or len(set(sids))!=len(sids) or any(fid not in floor_ids for fid in fids) or any(sid not in space_ids for sid in sids): issue("Connector stops must be unique and reference known floors/spaces.",cid)
        else:
            for fid,sid in zip(fids,sids):
                if space_map[sid].get("floor_id")!=fid: issue("Connector stop space must belong to its paired floor.",cid,fid)
            elevs=[floor_map[fid].get("elevation_m") for fid in fids]
            if any(not _number(v) for v in elevs) or len(set(elevs))!=len(elevs): issue("Connector requires distinct measured floor elevations.",cid)
            centers=[]
            for sid in sids:
                if sid in polygons:
                    p=polygons[sid].representative_point(); centers.append((p.x,p.y))
            if len(centers)==len(sids) and any(math.dist(centers[0],p)>10 for p in centers[1:]):
                issue("Connector stop spaces are more than 10 m apart in the shared XY frame.",cid,severity="warning",repair="Confirm floor alignment or correct the connector stops.")
    for a in assets:
        if not isinstance(a,dict): continue
        aid=a.get("id"); fid=a.get("floor_id"); sid=a.get("space_id")
        if (not isinstance(fid,str) or fid not in floor_ids or not isinstance(sid,str) or sid not in space_ids): issue("Asset must reference a known floor and room.",aid,fid)
        elif space_map[sid].get("floor_id")!=fid: issue("Asset floor must match its containing room.",aid,fid)
        if not _valid_pair(a.get("position")): issue("Asset position must be finite XY metres.",aid,fid)
        elif sid in polygons:
            try:
                from shapely.geometry import Point
                if not polygons[sid].covers(Point(a["position"])):
                    issue("Asset position is outside its proposed room.",aid,fid,repair="Move it inside the assigned room or change its assignment.")
            except Exception: pass
        fp=a.get("footprint")
        if fp:
            if not isinstance(fp,dict) or any(not _number(fp.get(k)) or fp[k]<=0 for k in ("width_m","depth_m")): issue("Known asset footprint dimensions must be positive and finite.",aid,fid)
    uncertainties=import_meta.get("uncertainties",[])
    if not isinstance(uncertainties,list):
        issue("Import uncertainties must be an array.",repair="Correct import metadata."); uncertainties=[]
    for uncertainty in uncertainties:
        if not isinstance(uncertainty,dict) or not all(uncertainty.get(k) for k in ("element_id","field","reason")):
            issue("Uncertainty records require element_id, field, and reason.",repair="Record each unresolved extracted fact explicitly.")
        elif uncertainty.get("field") != "width_m":
            issue(f"Unresolved {uncertainty['field']}: {uncertainty['reason']}",uncertainty["element_id"],severity="warning",repair="Review the source and supply a confirmed value.")
    if not any(item["severity"] == "error" for item in issues):
        import networkx as nx
        graph = nx.Graph()
        graph.add_nodes_from(space_ids)
        entrances = set()
        for opening in openings:
            first, second = opening["space_ids"]
            if "outside" in (first, second):
                entrances.add(second if first == "outside" else first)
                if opening["step_free"] is False:
                    issue("Entrance is not step-free.", opening["id"], opening["floor_id"], "warning",
                          "Step-free journeys cannot use this entrance.")
            else:
                graph.add_edge(first, second)
        for connector in connectors:
            for first, second in zip(connector["space_ids"], connector["space_ids"][1:]):
                graph.add_edge(first, second)
        for component in nx.connected_components(graph):
            if not component & entrances:
                for sid in sorted(component):
                    issue("Room is disconnected from every entrance.", sid, space_map[sid]["floor_id"], "warning",
                          "Confirm this is intentional, or correct the observed doors/connectors; none will be invented.")
    return issues


@dataclass
class PlanDraft:
    """Isolated candidate plus revision-checked apply/cancel/undo lifecycle."""
    data: dict
    output_path: Path
    base_revision: int = 0
    current_revision: int = 0
    base_data: dict | None = None
    previous: dict | None = None
    cancelled: bool = False
    history: list[dict] = field(default_factory=list)
    acknowledged_warnings: bool = False
    existing_building: bool = False

    def __post_init__(self) -> None:
        self.data = copy.deepcopy(self.data)
        self.base_data = copy.deepcopy(self.base_data if self.base_data is not None else self.data)
        self.output_path = Path(self.output_path)
        self._initial_revision = self.current_revision

    def correct(self, actions: list[dict]) -> dict:
        self._active()
        candidate=copy.deepcopy(self.data)
        for action in actions:
            _apply_action(candidate, action)
        self.history.append(self.data); self.data=candidate
        return self.preview()

    def validate(self) -> list[dict]:
        self._active()
        current=validate_building(self.data)
        current_meta=self.data.get("building") if isinstance(self.data,dict) else None
        base_meta=self.base_data.get("building") if isinstance(self.base_data,dict) else None
        if (not self.existing_building or self.base_data is None or not isinstance(current_meta,dict)
                or not isinstance(base_meta,dict) or current_meta.get("id") != base_meta.get("id")):
            return current
        baseline=validate_building(self.base_data)
        geometry_unchanged=_geometry_state(self.data)==_geometry_state(self.base_data)
        key=lambda i:(i.get("reason"),i.get("element_id"),i.get("floor_id"))
        counts=Counter(key(i) for i in baseline)
        adjusted=[]
        for item in current:
            item=copy.deepcopy(item); k=key(item)
            if counts[k]:
                counts[k]-=1
                if item["severity"]=="error" and geometry_unchanged:
                    item["severity"]="warning"; item["preexisting"]=True
            adjusted.append(item)
        return adjusted

    def preview(self) -> dict:
        return {"building_id":self.data.get("building",{}).get("id"),"base_revision":self.base_revision,
                "current_revision":self.current_revision,"validation_issues":self.validate(),
                "proposed_building":copy.deepcopy(self.data)}

    def apply(self, *, expected_revision: int | None = None,
              save_fn: Callable[[Path,dict],None] | None = None,
              acknowledge_warnings: bool = False) -> dict:
        self._active()
        expected=self.base_revision if expected_revision is None else expected_revision
        if expected != self.current_revision: raise PlanError("Draft is stale; revalidate against the current revision.")
        errors=[i for i in self.validate() if i["severity"]=="error"]
        if errors: raise PlanError("Cannot apply invalid draft: " + "; ".join(x["reason"] for x in errors))
        warnings=[i for i in self.validate() if i["severity"]=="warning"]
        if warnings and not (acknowledge_warnings or self.acknowledged_warnings):
            raise PlanError("Draft has warnings; review them and pass acknowledge_warnings=True to apply.")
        from .storage import JsonBuildingStore
        saver=save_fn or (lambda p,d: JsonBuildingStore.save(p,d))
        old_bytes=self.output_path.read_bytes() if self.output_path.exists() else None
        prior=copy.deepcopy(self.base_data)
        try: saver(self.output_path,copy.deepcopy(self.data))
        except Exception as exc:
            # The store itself is atomic; restore bytes if a custom saver partially wrote.
            try:
                if old_bytes is None: self.output_path.unlink(missing_ok=True)
                else: self.output_path.write_bytes(old_bytes)
            except OSError: pass
            raise PlanError(f"Save failed; current building remains unchanged: {exc}") from exc
        self.previous=prior; self.current_revision+=1; self.base_revision=self.current_revision
        self.acknowledged_warnings = self.acknowledged_warnings or acknowledge_warnings
        self.base_data=copy.deepcopy(self.data)
        return {"applied":True,"revision":self.current_revision,"path":str(self.output_path)}

    def cancel(self) -> dict:
        self._active(); self.data=copy.deepcopy(self.base_data); self.cancelled=True
        return {"cancelled":True,"revision":self.current_revision}

    def undo(self, *, save_fn: Callable[[Path,dict],None] | None = None) -> dict:
        self._active()
        if self.previous is None: raise PlanError("No committed revision is available to undo.")
        restored=copy.deepcopy(self.previous)
        temp=PlanDraft(restored,self.output_path,self.current_revision,self.current_revision,restored,
                       existing_building=self.existing_building)
        result=temp.apply(save_fn=save_fn, acknowledge_warnings=True)
        self.previous=copy.deepcopy(self.base_data); self.data=restored; self.base_data=restored
        self.current_revision=result["revision"]; self.base_revision=self.current_revision
        return {"undone":True,"revision":self.current_revision,"path":str(self.output_path)}

    def _active(self) -> None:
        if self.cancelled: raise PlanError("Draft is cancelled.")


class PlanBuilder:
    """Small factory for isolated new-building and existing-building drafts."""

    @staticmethod
    def begin_new(building_id: str, name: str, floors: list[dict],
                  output_path: str | Path) -> PlanDraft:
        data={"building":{"id":building_id,"name":name,"source":"plan_import","units":"m"},
              "floors":copy.deepcopy(floors),"spaces":[],"openings":[],
              "vertical_connectors":[],"assets":[],"import_metadata":{"uncertainties":[]}}
        return PlanDraft(data,Path(output_path))

    @staticmethod
    def begin_existing(building: dict, output_path: str | Path, revision: int = 0) -> PlanDraft:
        """Copy an existing building including custom fields; edits stay isolated."""
        return PlanDraft(copy.deepcopy(building),Path(output_path),revision,revision,copy.deepcopy(building),existing_building=True)

    @staticmethod
    def extract(client: Any, model: str, image_path: str | Path, floor_id: str,
                calibration: Calibration | None = None, metadata: dict | None = None) -> dict:
        return extract_plan(client,model,image_path,floor_id=floor_id,calibration=calibration,metadata=metadata)


def _apply_action(data: dict, action: dict) -> None:
    if not isinstance(action,dict): raise PlanError("Correction action must be an object.")
    kind=action.get("kind"); collection={"space":"spaces","opening":"openings","connector":"vertical_connectors","asset":"assets"}.get(action.get("element_type"))
    allowed={"space":{"name","type","room_type","polygon"},"opening":{"position","width_m","step_free","space_ids","kind"},"connector":{"floor_ids","space_ids","step_free"},"asset":{"space_id","floor_id","position","footprint"}}
    if kind in {"add","delete"}:
        element_type=action.get("element_type")
        key={"space":"spaces","opening":"openings","connector":"vertical_connectors","asset":"assets"}.get(element_type)
        if key is None: raise PlanError("Add/delete correction requires a supported element_type.")
        if kind=="add":
            value=action.get("value")
            if not isinstance(value,dict) or not isinstance(value.get("id"),str) or any(x.get("id")==value.get("id") for x in sum((data.get(k,[]) for k in ("floors","spaces","openings","vertical_connectors","assets")),[])):
                raise PlanError("Added element must be an object with a globally unique ID.")
            data.setdefault(key,[]).append(copy.deepcopy(value)); return
        before=len(data.get(key,[])); data[key]=[x for x in data.get(key,[]) if x.get("id")!=action.get("id")]
        if before==len(data[key]): raise PlanError("Correction target does not exist.")
        if element_type=="space" and any(action["id"] in o.get("space_ids",[]) for o in data.get("openings",[])):
            raise PlanError("Remove or reassign openings before deleting a connected space.")
        return
    if kind=="resolve_uncertainty":
        _apply_action(data,{"kind":"set","element_type":action.get("element_type"),"id":action.get("id"),"field":action.get("field"),"value":action.get("value")})
        uncertainties=data.setdefault("import_metadata",{}).setdefault("uncertainties",[])
        data["import_metadata"]["uncertainties"]=[u for u in uncertainties if not (u.get("element_id")==action.get("id") and u.get("field")==action.get("field"))]
        return
    target=next((x for x in data.get(collection or "",[]) if x.get("id")==action.get("id")),None) if collection else None
    if target is None: raise PlanError("Correction target does not exist.")
    if kind!="set" or action.get("field") not in allowed[action["element_type"]]: raise PlanError("Unsupported correction; use a permitted set action.")
    target[action["field"]]=copy.deepcopy(action.get("value"))


def _unique_records(rows: list, label: str, issues: list[dict], global_ids: set) -> set:
    seen=set()
    for row in rows:
        if not isinstance(row,dict):
            issues.append({"severity":"error","element_id":None,"floor_id":None,"reason":f"{label.title()} record must be an object.","repair":"Correct the record."}); continue
        eid=row.get("id")
        if not isinstance(eid,str) or not eid.strip():
            issues.append({"severity":"error","element_id":None,"floor_id":row.get("floor_id"),"reason":f"{label.title()} ID must be nonempty.","repair":"Assign a stable unique ID."})
            continue
        if eid in seen or eid in global_ids: issues.append({"severity":"error","element_id":eid,"floor_id":row.get("floor_id"),"reason":f"Duplicate {label} ID.","repair":"Assign unique IDs before indexing."})
        seen.add(eid)
        global_ids.add(eid)
    return seen


def _number(value: Any) -> bool:
    return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)


def _geometry_state(data: dict) -> tuple:
    """Relevant geometry/access values for deciding whether old issues still apply."""
    def rows(key: str, fields: tuple[str,...]) -> tuple:
        result=[]
        for row in data.get(key,[]) if isinstance(data.get(key,[]),list) else []:
            if not isinstance(row,dict): result.append(repr(row)); continue
            result.append(tuple((field,json.dumps(row.get(field),sort_keys=True,allow_nan=True)) for field in fields))
        return tuple(result)
    return (
        rows("floors",("id","level","elevation_m")),
        rows("spaces",("id","floor_id","type","room_type","polygon")),
        rows("openings",("id","floor_id","space_ids","kind","position","width_m","step_free")),
        rows("vertical_connectors",("id","kind","floor_ids","space_ids","step_free")),
        rows("assets",("id","floor_id","space_id","position","footprint")),
    )

def _pair(value: Any, label: str) -> tuple[float,float]:
    if not _valid_pair(value): raise PlanError(f"{label} must contain two finite numbers.")
    return float(value[0]),float(value[1])

def _valid_pair(value: Any) -> bool:
    return isinstance(value,(list,tuple)) and len(value)==2 and all(_number(v) for v in value)
