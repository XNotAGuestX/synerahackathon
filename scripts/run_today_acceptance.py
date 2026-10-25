"""One-process acceptance run for the remaining 25 October challenge gaps.

Records the live factory conversation, one campus conversation, an unscaled plan,
and a two-floor plan import. Does not invent Sunday answers.
"""

import json
import time
import traceback
import uuid
from pathlib import Path

import anthropic
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from final_agent.agent import MODEL, BuildingAgent
from final_agent.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "agent_output" / "acceptance"
FACTORY = ROOT / "data" / "dev" / "proc-factory-dev-003"
ATRIUM = ROOT / "examples" / "level34" / "demo-atrium"
LAB = ROOT / "examples" / "level34" / "demo-lab"

TURNS = [
    "Where is the CNC mill?",
    "Where is the desk?",
    "I am at Warehouse zone H-C2.",
    "How do I get to CNC mill H-A1-A without stairs?",
    "Now go to the kitchen instead.",
    "Close the office lift.",
    "Yes, close the office lift.",
    "Reopen the office lift.",
    "Yes, reopen the office lift.",
    "Visit Warehouse zone H-C2, then Production zone H-A1, in that order, and finish at Assembly zone H-A2.",
    "Where is room 9.99?",
]


def draw_plan(path: Path, title: str, *, scaled: bool) -> None:
    """A tiny two-room plan. Scaled copies print the same 10 m by 4 m evidence."""
    figure, axes = plt.subplots(figsize=(8, 5), dpi=80)
    axes.set_xlim(0, 800)
    axes.set_ylim(500, 0)
    axes.set_aspect("equal")
    axes.axis("off")
    axes.set_facecolor("white")
    axes.plot([100, 700, 700, 100, 100], [80, 80, 400, 400, 80], color="#17212b", lw=4)
    axes.plot([400, 400], [80, 220], color="#17212b", lw=4)
    axes.plot([400, 400], [300, 400], color="#17212b", lw=4)
    axes.text(250, 240, "LOBBY", ha="center", fontsize=16, weight="bold")
    axes.text(550, 240, "LAB", ha="center", fontsize=16, weight="bold")
    axes.text(400, 40, title, ha="center", fontsize=12)
    if scaled:
        axes.annotate("", xy=(700, 440), xytext=(100, 440),
                      arrowprops={"arrowstyle": "<->", "color": "#17212b"})
        axes.text(400, 460, "10 m", ha="center", fontsize=14, weight="bold")
    figure.savefig(path, dpi=80, facecolor="white")
    plt.close(figure)


def finish_plan(workspace: Workspace) -> dict:
    """Confirm the printed 1.2 m step-free doors, apply the reviewed draft, and route inside it."""
    if workspace.draft is None:
        return {"status": "no_draft"}
    actions = []
    for opening in workspace.draft.data.get("openings", []):
        if opening.get("width_m") in (None, "") or opening.get("step_free") is not True:
            actions.append({"kind": "set", "element_type": "opening", "id": opening["id"], "field": "width_m", "value": 1.2})
            actions.append({"kind": "set", "element_type": "opening", "id": opening["id"], "field": "step_free", "value": True})
    try:
        if actions:
            workspace.correct(actions)
        applied = workspace.apply(acknowledge_warnings=True)
        building = workspace.campus.selected_map
        spaces = list(building.spaces)
        route = None
        if len(spaces) >= 2:
            result = building.compute_route(spaces[0], spaces[1], step_free=True)
            route = {"length_m": result.length_m, "space_path": result.space_path, "profile": result.route_profile}
        return {"applied": applied.get("applied", True), "route": route, "spaces": spaces}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def ask(agent: BuildingAgent, text: str) -> dict:
    before = len(agent.tool_calls())
    started = time.perf_counter()
    try:
        reply = agent.ask(text)
        error = None
    except Exception as exc:
        reply = ""
        error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    elapsed = round(time.perf_counter() - started, 2)
    calls = agent.tool_calls()[before:]
    record = {"user": text, "reply": reply, "tools": calls, "elapsed_s": elapsed, "error": error}
    print(f"\nYOU> {text}\nGUIDE> {reply}\nTOOLS> {[call['name'] for call in calls]} ({elapsed}s)")
    if error:
        print("ERROR>", error)
    return record


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    images = OUT / "plans"
    images.mkdir(exist_ok=True)
    unscaled = images / "unscaled.png"
    floor0 = images / "floor0.png"
    floor1 = images / "floor1.png"
    draw_plan(unscaled, "LEVEL 0", scaled=False)
    import importlib.util
    spec = importlib.util.spec_from_file_location("create_new_plan", ROOT / "examples" / "level34" / "create_new_plan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.draw(floor0, 0, 0)
    module.draw(floor1, 1, 4)

    started = time.perf_counter()
    workspace = Workspace(
        OUT / "workspaces" / uuid.uuid4().hex[:12], client=anthropic.Anthropic(), model=MODEL,
        notes_database=OUT / "notes.sqlite3",
    )
    workspace.register(str(FACTORY))
    agent = BuildingAgent(
        workspace.campus.selected_map, workspace.directory, client=workspace.client,
        model=workspace.model, workspace=workspace, emergency=False,
    )
    evidence = {
        "model": MODEL,
        "workspace": str(workspace.directory),
        "factory_turns": [ask(agent, text) for text in TURNS],
    }
    for source in (ATRIUM, LAB):
        if source.name not in {item["building_id"] for item in workspace.campus.list_buildings()}:
            workspace.register(str(source))
    workspace.campus.add_walkway(
        "walk-short", "Garden path",
        {"building_id": "demo-atrium", "opening_id": "E0"},
        {"building_id": "demo-lab", "opening_id": "E0"},
        8, 1.2, True,
    )
    workspace.campus.add_walkway(
        "walk-long", "Covered detour",
        {"building_id": "demo-atrium", "opening_id": "E1"},
        {"building_id": "demo-lab", "opening_id": "E1"},
        30, 1.2, True,
    )
    evidence["campus_turn"] = ask(
        agent,
        "I am in the upper lab of Demo Atrium. Take me to the lab reception in Demo Lab without stairs, and show the route.",
    )
    evidence["campus_route"] = workspace.campus.last_route
    try:
        evidence["unscaled_plan"] = workspace.import_image(str(unscaled))
    except Exception as exc:
        evidence["unscaled_plan"] = {"error": f"{type(exc).__name__}: {exc}"}
    workspace.pending_plan = None
    calibration = {"point_a_px": [200, 650], "point_b_px": [1000, 650], "distance_m": 10}
    try:
        evidence["two_floor_plan"] = workspace.create_plan(
            "demo-stack", "Demo stack",
            [
                {"id": "F0", "name": "Ground", "level": 0, "elevation_m": 0.0,
                 "source_path": str(floor0), "calibration": calibration, "alignment_confirmed": True},
                {"id": "F1", "name": "Upper", "level": 1, "elevation_m": 4.0,
                 "source_path": str(floor1), "calibration": calibration, "alignment_confirmed": True},
            ],
            "CC0-1.0", "Generated for the 25 October acceptance run",
        )
    except Exception as exc:
        evidence["two_floor_plan"] = {"error": f"{type(exc).__name__}: {exc}"}
    evidence["plan_route"] = finish_plan(workspace)
    evidence["elapsed_s"] = round(time.perf_counter() - started, 2)
    evidence["usage"] = agent.usage
    path = OUT / "evidence.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {path} in {evidence['elapsed_s']}s")


if __name__ == "__main__":
    main()
