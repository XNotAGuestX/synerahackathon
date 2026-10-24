"""Short end-to-end checks through the tools used by workspace conversation."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

from PIL import Image

from final_agent.storage import JsonBuildingStore
from final_agent.workspace import Workspace, make_workspace_tools


def model(building_id):
    return {"building": {"id": building_id, "name": building_id, "source": "test", "units": "m"},
            "floors": [{"id": "f0", "name": "Ground", "level": 0, "elevation_m": 0}],
            "spaces": [{"id": "r", "name": "101", "type": "room", "room_type": "office", "floor_id": "f0",
                        "polygon": [[0, 0], [4, 0], [4, 4], [0, 4]]}],
            "openings": [{"id": "entry", "floor_id": "f0", "space_ids": ["r", "outside"], "kind": "entrance",
                          "position": [0, 2], "width_m": 1.2, "step_free": True}],
            "assets": [], "vertical_connectors": []}


class WorkspaceTests(unittest.TestCase):
    def test_scope_campus_closure_and_reviewed_edit_reload_undo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = Workspace(root / "session")
            for bid in ("a", "b"):
                path = root / f"{bid}.json"
                JsonBuildingStore.save(path, model(bid))
                workspace.register(str(path))
            tools = {t.name: t for t in make_workspace_tools(workspace)}
            def call(tool_name, **args):
                return json.loads(tools[tool_name].call(args))
            self.assertEqual(call("search_campus", query="101")["matches"], 2)
            call("select_building", building_id="b")
            self.assertEqual(call("show_location", element="r")["building_id"], "b")
            self.assertIsNone(workspace.current_location)
            call("add_walkway", walkway_id="w", name="Courtyard", endpoint_a={"building_id": "a", "opening_id": "entry"},
                 endpoint_b={"building_id": "b", "opening_id": "entry"}, length_m=10, width_m=1.2, step_free=True)
            journey = {"start": {"building_id": "a", "element_id": "r"},
                       "destination": {"building_id": "b", "element_id": "r"}, "step_free": True, "min_width_m": 1.2}
            self.assertTrue(call("find_campus_route", **journey)["reachable"])
            self.assertEqual(len(call("show_campus_route")["views"]), 3)
            self.assertFalse(call("set_campus_closed", target={"walkway_id": "w"}, closed=True)["campus_route"]["reachable"])
            self.assertTrue(call("set_campus_closed", target={"walkway_id": "w"}, closed=False)["campus_route"]["reachable"])
            call("begin_building_edit", building_id="b")
            call("correct_plan", actions=[{"kind": "set", "element_type": "space", "id": "r", "field": "name", "value": "Studio"}])
            result = call("apply_plan")
            self.assertEqual(workspace.building("b")["map"].spaces["r"]["name"], "Studio")
            restored = Workspace(workspace.directory)
            restored.apply(undo=True)
            self.assertEqual(restored.building("b")["map"].spaces["r"]["name"], "101")
            self.assertTrue(Path(result["path"]).is_file())

    def test_image_bytes_to_corrected_saved_reload_and_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "plan.png"
            Image.new("RGB", (120, 80), "white").save(source)
            data = model("new")
            observations = {"spaces": [], "openings": [], "assets": [], "vertical_connectors": [], "uncertainties": []}
            # Mock only model perception; calibration, validation, preview, persistence and routing are real.
            for s in data["spaces"]:
                observations["spaces"].append({**s, "polygon_px": [[x * 10, 80 - y * 10] for x, y in s["polygon"]]})
                observations["spaces"][-1].pop("polygon")
            for o in data["openings"]:
                observations["openings"].append({**o, "position_px": [0, 60]})
                observations["openings"][-1].pop("position")
            client = Mock()
            client.messages.create.return_value.content = [Mock(type="text", text=json.dumps(observations))]
            client.messages.create.return_value.usage = SimpleNamespace(input_tokens=0, output_tokens=0)
            client.messages.create.return_value.stop_reason = "end_turn"
            workspace = Workspace(root / "session", client=client, model="test-model")
            preview = workspace.create_plan("new", "New", [{"id": "f0", "name": "Ground", "level": 0,
                "elevation_m": 0, "source_path": str(source), "calibration": {
                    "point_a_px": [0, 80], "point_b_px": [40, 80], "distance_m": 4}}], "CC0-1.0", "Test")
            self.assertTrue(Path(preview["images"][0]["image"]).is_file())
            self.assertEqual(client.messages.create.call_args.kwargs["messages"][0]["content"][0]["type"], "image")
            workspace.correct([{"kind": "set", "element_type": "space", "id": "r", "field": "name", "value": "Lab"}])
            workspace.apply()
            restored = Workspace(workspace.directory)
            self.assertEqual(restored.building()["map"].spaces["r"]["name"], "Lab")
            self.assertEqual(restored.building()["map"].compute_route("r", "r", True).length_m, 0)


if __name__ == "__main__":
    unittest.main()
