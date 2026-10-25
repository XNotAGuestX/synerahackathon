"""Run the local two-building walkway demonstration and write a viewable report.

The web session still loads one building. This demo loads both fixture buildings,
registers the measured walkways, and shows the short route, the detour, and the
recovered route.
"""

from __future__ import annotations

import html
import shutil
import webbrowser
from pathlib import Path

from .building_map import MapError
from .campus import Campus
from .viewer import draw_campus_route
from .workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
ATRIUM = ROOT / "examples" / "level34" / "demo-atrium"
LAB = ROOT / "examples" / "level34" / "demo-lab"
DEFAULT_OUTPUT = ROOT / "agent_output" / "campus-demo"
START = {"building_id": "demo-atrium", "kind": "space", "element_id": "R202"}
DESTINATION = {"building_id": "demo-lab", "kind": "space", "element_id": "R101"}
EXPECTED_M = (35.0, 57.0, 35.0)


def run_campus_walkway(output: Path | None = None) -> dict:
    """Load the demo campus, walk the short link, close it, then reopen it."""
    output = Path(output or DEFAULT_OUTPUT)
    if output.exists():
        shutil.rmtree(output)
    workspace = Workspace(output)
    workspace.register(str(ATRIUM))
    workspace.register(str(LAB))
    campus = workspace.campus
    campus.add_walkway(
        "walk-short", "Garden path",
        {"building_id": "demo-atrium", "opening_id": "E0"},
        {"building_id": "demo-lab", "opening_id": "E0"},
        8, 1.2, True,
    )
    campus.add_walkway(
        "walk-long", "Covered detour",
        {"building_id": "demo-atrium", "opening_id": "E1"},
        {"building_id": "demo-lab", "opening_id": "E1"},
        30, 1.2, True,
    )
    stages = [
        _stage(campus, output, "short", "Short walkway"),
        _after_close(campus, output, "walk-short", True, "detour", "Short walkway closed"),
        _after_close(campus, output, "walk-short", False, "reopened", "Short walkway reopened"),
    ]
    report = _write_report(output, stages)
    return {
        "workspace": str(output),
        "report": str(report),
        "stages": stages,
        "lengths_m": [stage["length_m"] for stage in stages],
        "expected_m": list(EXPECTED_M),
        "matches_expected": [stage["length_m"] for stage in stages] == list(EXPECTED_M),
    }


def _after_close(campus: Campus, output: Path, walkway_id: str, closed: bool, slug: str, title: str) -> dict:
    campus.close(walkway_id, closed)
    return _stage(campus, output, slug, title)


def _stage(campus: Campus, output: Path, slug: str, title: str) -> dict:
    route = campus.find_route(START, DESTINATION, step_free=True, min_width_m=1.2)
    if not route.get("reachable"):
        raise MapError(route.get("reason", "Campus route is unreachable."))
    image_dir = output / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    images = []
    for view in draw_campus_route(campus, route, output / "routes" / route["route_id"]):
        source = Path(view["image"])
        name = f"{slug}-{view['kind']}-{view['leg_index']}.png"
        shutil.copyfile(source, image_dir / name)
        images.append({"name": name, "kind": view["kind"], "label": view.get("name") or view["kind"]})
    return {"id": slug, "title": title, "length_m": route["total_m"], "images": images}


def _write_report(output: Path, stages: list[dict]) -> Path:
    sections = []
    for stage in stages:
        pictures = "\n".join(
            f'<figure><img src="images/{html.escape(image["name"])}" alt="{html.escape(stage["title"])}">'
            f'<figcaption>{html.escape(image["label"])}</figcaption></figure>'
            for image in stage["images"]
        )
        sections.append(
            f'<section><h2>{html.escape(stage["title"])}</h2>'
            f'<p class="length">{stage["length_m"]:g} m</p>{pictures}</section>'
        )
    page = output / "index.html"
    page.write_text(
        """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Campus walkway</title>
<style>
body { font-family: Segoe UI, sans-serif; margin: 2rem; color: #17212b; background: #f6f3ee; }
h1 { font-size: 1.6rem; } .length { font-size: 1.4rem; font-weight: 700; }
section { margin: 1.5rem 0; padding: 1rem; background: white; }
img { max-width: 100%; height: auto; }
</style></head><body>
<h1>Demo Atrium to Demo Lab</h1>
<p>Step-free route through a measured walkway. Closing the short link uses the longer one.</p>
""" + "\n".join(sections) + "</body></html>",
        encoding="utf-8",
    )
    return page


def main() -> None:
    result = run_campus_walkway()
    print(" -> ".join(f"{length:g} m" for length in result["lengths_m"]))
    print(result["report"])
    if not result["matches_expected"]:
        raise SystemExit("Campus walkway lengths did not match 35 m, 57 m, 35 m.")
    webbrowser.open(Path(result["report"]).resolve().as_uri())


if __name__ == "__main__":
    main()
