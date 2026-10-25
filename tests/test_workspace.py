"""Short end-to-end checks through the tools used by workspace conversation."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

from PIL import Image
from anthropic.lib.tools import ToolError

from final_agent.storage import JsonBuildingStore
from final_agent.workspace import Workspace, make_workspace_tools
from final_agent.plan_build import PlanError


def model(building_id):
    return {"building": {"id": building_id, "name": building_id, "source": "test", "units": "m"},
            "floors": [{"id": "f0", "name": "Ground", "level": 0, "elevation_m": 0}],
            "spaces": [{"id": "r", "name": "101", "type": "room", "room_type": "office", "floor_id": "f0",
                        "polygon": [[0, 0], [4, 0], [4, 4], [0, 4]]}],
            "openings": [{"id": "entry", "floor_id": "f0", "space_ids": ["r", "outside"], "kind": "entrance",
                          "position": [0, 2], "width_m": 1.2, "step_free": True}],
            "assets": [], "vertical_connectors": []}


class WorkspaceTests(unittest.TestCase):
    def test_invalid_draft_ids_return_validation_issues_instead_of_crashing_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Workspace(Path(tmp))
            data = model("new")
            data["spaces"][0]["id"] = []
            workspace._new_draft(data, 0)
            preview = workspace.preview()
            self.assertTrue(any(i["severity"] == "error" for i in preview["validation_issues"]))
            self.assertIn("error", preview["images"][0])
            with self.assertRaises(PlanError):
                workspace.apply(acknowledge_warnings=True)

    def test_invalid_or_unsaved_location_update_leaves_confirmed_state_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "a.json"
            data = model("a")
            data["spaces"].append({**data["spaces"][0], "id": "s", "name": "102"})
            JsonBuildingStore.save(source, data)
            workspace = Workspace(root / "session")
            workspace.register(str(source))
            tool = next(t for t in make_workspace_tools(workspace) if t.name == "confirm_location")
            tool.call({"building_id": "a", "element_id": "r", "step_free": False, "min_width_m": 0})
            before = (copy.deepcopy(workspace.current_location), copy.deepcopy(workspace.preferences))
            with self.assertRaises(ToolError):
                tool.call({"building_id": "a", "element_id": "s", "step_free": True, "min_width_m": -1})
            self.assertEqual((workspace.current_location, workspace.preferences), before)
            with patch.object(workspace, "save_session", side_effect=OSError("disk full")):
                with self.assertRaises(ToolError):
                    tool.call({"building_id": "a", "element_id": "s", "step_free": True, "min_width_m": 1})
            self.assertEqual((workspace.current_location, workspace.preferences), before)
            restored = Workspace(workspace.directory)
            self.assertEqual((restored.current_location, restored.preferences), before)

    def test_pending_multifloor_calibration_preserves_every_floor_across_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "plan.png"
            Image.new("RGB", (80, 80), "white").save(source)
            calibration = {"point_a_px": [0, 40], "point_b_px": [40, 40], "distance_m": 4}
            floors = [{"id": f"f{i}", "name": f"Floor {i}", "level": i,
                       "elevation_m": i * 3, "source_path": str(source), "alignment_confirmed": True}
                      for i in range(3)]
            floors[0]["calibration"] = calibration

            def extract(client, model_name, path, *, floor_id, **kwargs):
                return {"spaces": [{"id": floor_id + "-r", "floor_id": floor_id, "name": "Room",
                                     "type": "room", "room_type": "office",
                                     "polygon_px": [[0, 40], [40, 40], [40, 0], [0, 0]]}],
                        "openings": [], "assets": [], "vertical_connectors": [], "uncertainties": [],
                        "_provenance": {"source_path": str(path)}}

            workspace = Workspace(root / "session", client=Mock(), model="test-model")
            with patch("final_agent.workspace.extract_plan", side_effect=extract) as vision:
                pending = workspace.create_plan("new", "New", floors, "CC0-1.0", "Test")
                self.assertEqual(vision.call_count, 3)
            self.assertEqual(pending["status"], "needs_calibration")
            self.assertEqual(pending["pending_floor_ids"], ["f1", "f2"])
            with self.assertRaises(PlanError):
                workspace.begin_edit()
            source.unlink()
            resumed = Workspace(workspace.directory)
            with self.assertRaisesRegex(PlanError, "floor_id"):
                resumed.calibrate_pending(calibration)
            self.assertEqual(resumed.calibrate_pending(calibration, floor_id="f1")["pending_floor_ids"], ["f2"])
            resumed = Workspace(workspace.directory)
            result = resumed.calibrate_pending(calibration)
            self.assertEqual(result["status"], "pending_review")
            self.assertEqual(len(resumed.draft.data["floors"]), 3)
            self.assertEqual({s["floor_id"] for s in resumed.draft.data["spaces"]}, {"f0", "f1", "f2"})
            self.assertEqual(set(resumed.draft.data["import_metadata"]["calibrations"]), {"f0", "f1", "f2"})
            self.assertTrue(all(Path(source["source_path"]).is_file()
                                for source in resumed.draft.data["import_metadata"]["sources"].values()))

    def test_reports_keep_chat_identity_and_survive_rendering_edits_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "a.json"
            data = model("a")
            data["spaces"].append({**data["spaces"][0], "id": "s", "name": "102",
                                   "polygon": [[4, 0], [8, 0], [8, 4], [4, 4]]})
            JsonBuildingStore.save(source, data)
            database = root / "shared.sqlite3"
            workspace = Workspace(root / "first", notes_database=database)
            workspace.register(str(source), facility_number="3")

            def call(session, name, **args):
                tools = {tool.name: tool for tool in make_workspace_tools(session)}
                return json.loads(tools[name].call(args))

            note = call(workspace, "add_room_note", space="r", text="Printer broken.")["note"]
            repeated = call(workspace, "confirm_room_note", space="r", note_id=note["note_id"])["note"]
            self.assertEqual((repeated["confirmation_count"], repeated["status"]), (1, "pending"))
            second = Workspace(root / "second", notes_database=database)
            second.register(str(source), facility_number="3")
            self.assertEqual(call(second, "get_room_notes", spaces=["r"])["room_notes"], [])
            confirmed = call(second, "confirm_room_note", space="r", note_id=note["note_id"])["note"]
            self.assertEqual((confirmed["confirmation_count"], confirmed["status"]), (2, "active"))
            hazard = call(workspace, "add_room_note", space="r", text="Wet floor.", category="safety")["note"]

            def note_ids(result):
                return {note["note_id"] for group in result["room_notes"] for note in group["notes"]}

            expected = {note["note_id"], hazard["note_id"]}
            self.assertEqual(note_ids(call(workspace, "show_location", element="r")), expected)
            call(workspace, "add_door", first_space="r", second_space="s")
            self.assertEqual(note_ids(call(workspace, "get_room_notes", spaces=["r"])), expected)
            self.assertEqual(note_ids(call(workspace, "find_route", start="r", destination="s")), expected)
            self.assertEqual(note_ids(call(workspace, "show_route")), expected)
            restored = Workspace(workspace.directory)
            self.assertEqual(restored.notes_database, database.resolve())
            self.assertEqual(restored.report_session_id, workspace.report_session_id)
            self.assertEqual(restored.facility_numbers, {"a": "3"})
            same_chat = call(restored, "confirm_room_note", space="r", note_id=note["note_id"])["note"]
            self.assertEqual(same_chat["confirmation_count"], 2)
            self.assertEqual(note_ids(call(restored, "get_room_notes", spaces=["r"])), expected)

            other = root / "b.json"
            JsonBuildingStore.save(other, model("b"))
            restored.register(str(other))
            self.assertEqual(call(restored, "get_room_notes", spaces=["r"], building_id="b")["room_notes"], [])

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
