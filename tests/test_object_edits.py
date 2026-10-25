"""Object editor core rules on a real dev building: placement, stacks, heights, removal, undo and files."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anthropic.lib.tools import ToolError

from final_agent import object_edits
from final_agent.building_map import BuildingMap, MapError
from final_agent.stacking import STACKING_FILE
from final_agent.storage import JsonBuildingStore
from final_agent.tools import make_tools

BUILDING = Path(__file__).resolve().parents[1] / "data" / "dev" / "proc-campus-dev-000"
F0, F1 = "proc-campus-dev-000-F0", "proc-campus-dev-000-F1"
OFFICE, CORRIDOR, OTHER_OFFICE = f"{F0}-S002", f"{F0}-S001", f"{F0}-S007"
OFFICE_ABOVE = f"{F1}-S002"
DESK = "proc-campus-dev-000-A00002"  # Desk 0.02-A, 1.4 x 0.7 m at (2.855, -0.42) in Office 0.02
DOOR = f"{F0}-O0001"  # dataset door between Office 0.02 and Corridor 0.01


class ObjectEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = JsonBuildingStore.load(BUILDING)

    def setUp(self):
        self.map = BuildingMap(copy.deepcopy(self.data))

    def apply(self, **proposal) -> dict:
        return object_edits.apply_edit(self.map, proposal)

    def assert_rejected(self, reason: str, **proposal) -> MapError:
        state = self.map.snapshot()
        with self.assertRaises(MapError) as caught:
            self.apply(**proposal)
        self.assertEqual(caught.exception.reason, reason, str(caught.exception))
        self.assertEqual(self.map.snapshot()["assets"], state["assets"])
        self.assertEqual(self.map.stacking, state["stacking"])
        return caught.exception

    def put_on_desk(self, **extra) -> str:
        return self.apply(kind="add_object", type="coffee_machine", on_top_of=["Desk 0.02-A"], **extra)["changed_ids"][0]

    def test_add_places_in_room_and_rejects_walls_and_outside(self):
        result = self.apply(kind="add_object", type="desk", space="Office 0.02")
        asset = result["assets"][0]
        self.assertEqual(result["summary"], "Add Desk 0.02 in Office 0.02.")
        self.assertEqual((asset["id"], asset["space_id"], asset["source"]), (f"{F0}-A-new945", OFFICE, "user_edit"))
        self.assertEqual((asset["footprint"]["width_m"], asset["footprint"]["depth_m"]), (1.4, 0.7))
        moved = self.apply(kind="update_object", object_ref=asset["id"], position=[3.0, -2.0])
        self.assertEqual(moved["summary"], "Move Desk 0.02 within Office 0.02.")
        error = self.assert_rejected("crosses_wall", kind="update_object", object_ref=asset["id"], position=[5.9, -2.0])
        self.assertEqual(error.field, "position")
        self.assert_rejected("outside_space", kind="add_object", type="desk", space="Office 0.02", position=[7.0, -1.0])
        self.assert_rejected("unknown_type", kind="add_object", type="flux_capacitor", space="Office 0.02")
        self.assert_rejected("invalid_field", kind="add_object", type="desk")

    def test_stacking_requires_support_and_rejects_cycles(self):
        machine = self.put_on_desk()
        self.assertEqual(self.map.assets[machine]["position"], [2.855, -0.42])
        self.assertEqual(self.map.stacking[machine], [DESK])
        self.assert_rejected("floating", kind="update_object", object_ref=machine, position=[2.855, -2.5])
        error = self.assert_rejected("support_cycle", kind="update_object", object_ref=DESK, on_top_of=[machine])
        self.assertEqual(error.field, "on_top_of")
        self.assert_rejected("support_other_space", kind="add_object", type="printer", space="Office 0.07",
                             on_top_of=[DESK])
        down = self.apply(kind="update_object", object_ref=machine, on_top_of=[])
        self.assertEqual(down["summary"], "Take Coffee machine 0.02 off Desk 0.02-A.")
        self.assertEqual(self.map.stacking, {})

    def test_moving_a_support_carries_its_stack_into_another_room(self):
        machine = self.put_on_desk(position=[3.2, -0.42])
        result = self.apply(kind="update_object", object_ref=DESK, space="Office 0.07")
        desk = self.map.assets[DESK]
        self.assertEqual(result["summary"], "Move Desk 0.02-A to Office 0.07 with 1 object on top (on the floor).")
        self.assertEqual(sorted(result["changed_ids"]), sorted([DESK, machine]))
        self.assertEqual(self.map.assets[machine]["space_id"], OTHER_OFFICE)
        self.assertAlmostEqual(self.map.assets[machine]["position"][0] - desk["position"][0], 0.345)
        self.assertEqual(self.map.stacking[machine], [DESK])

    def test_stacked_object_moved_to_another_room_lands_on_the_floor(self):
        machine = self.put_on_desk()
        result = self.apply(kind="update_object", object_ref=machine, space="Office 0.07")
        self.assertEqual(result["summary"], "Move Coffee machine 0.02 to Office 0.07 (on the floor).")
        self.assertNotIn(machine, self.map.stacking)

    def test_shrinking_a_support_that_would_strand_objects_is_refused(self):
        self.put_on_desk(position=[3.4, -0.42])
        self.assert_rejected("would_strand", kind="update_object", object_ref=DESK, width_m=0.6)
        self.assertEqual(self.map.assets[DESK]["footprint"]["width_m"], 1.4)

    def test_height_override_lifts_the_stack_above_the_room_height(self):
        machine = self.put_on_desk()
        result = self.apply(kind="update_object", object_ref=DESK, height_m=0.9)
        self.assertEqual(result["summary"], "Set the height of Desk 0.02-A to 0.9 m.")
        layers = self.map.stacking_document()["layers"]
        self.assertEqual(layers[0]["objects"], [{
            "object_id": DESK, "on_top_of": [], "height_m": 0.9, "height_source": "override", "elevation_m": 0.0,
        }])
        self.assertEqual(layers[1]["objects"][0]["elevation_m"], 0.9)
        self.assertEqual(layers[1]["objects"][0]["height_source"], "catalog")
        # Without an override the shared 3D catalog height applies.
        self.assertEqual(object_edits.effective_height(self.map, machine),
                         object_edits.default_height(self.map.assets[machine]))
        self.apply(kind="update_object", object_ref=DESK, height_m=3.5)
        layers = self.map.stacking_document()["layers"]
        self.assertEqual(layers[1]["objects"][0]["elevation_m"], 3.5)
        top = self.apply(kind="add_object", type="printer", on_top_of=[machine], height_m=4.0)["changed_ids"][0]
        layers = self.map.stacking_document()["layers"]
        self.assertEqual(layers[2]["objects"][0]["object_id"], top)
        self.assertAlmostEqual(layers[2]["objects"][0]["elevation_m"],
                               3.5 + object_edits.effective_height(self.map, machine))
        self.assert_rejected("invalid_field", kind="update_object", object_ref=DESK, height_m=0)
        self.assertEqual(self.map.height_overrides, {DESK: 3.5, top: 4.0})

    def test_remove_takes_the_stack_and_undo_brings_it_back(self):
        machine = self.put_on_desk()
        self.apply(kind="update_object", object_ref=DESK, height_m=0.8)
        self.map.select("Desk 0.02-A")
        result = self.apply(kind="remove_object", object_ref="Desk 0.02-A")
        self.assertEqual(result["summary"], "Remove Desk 0.02-A and 1 object on top.")
        self.assertEqual(result["removed_ids"], sorted([DESK, machine]))
        self.assertNotIn(DESK, self.map.assets)
        self.assertEqual((self.map.stacking, self.map.height_overrides, self.map.selection), ({}, {}, None))
        undone = self.apply(kind="undo_edit")
        self.assertEqual(undone["summary"], "Undo: Remove Desk 0.02-A and 1 object on top.")
        self.assertEqual(sorted(undone["changed_ids"]), sorted([DESK, machine]))
        self.assertEqual((self.map.stacking, self.map.height_overrides), ({machine: [DESK]}, {DESK: 0.8}))
        self.assert_rejected("not_removable", kind="remove_object", object_ref=DOOR)

    def test_undo_keeps_current_closures_and_drops_vanished_ones(self):
        door = self.apply(kind="add_opening", first_space=OFFICE, second_space="Kitchen 0.03")["changed_ids"][0]
        self.map.set_closed("Lift 1", True)
        self.map.set_closed(door, True)
        self.apply(kind="undo_edit")
        self.assertNotIn(door, self.map.openings)
        self.assertEqual(self.map.closed, {"proc-campus-dev-000-V02"})
        self.assert_rejected("nothing_to_undo", kind="undo_edit")

    def test_check_edit_never_changes_the_map_and_its_proposal_reapplies(self):
        before = self.map.snapshot()
        checked = object_edits.check_edit(self.map, {"kind": "add_object", "type": "Coffee machine",
                                                     "on_top_of": ["Desk 0.02-A"]})
        self.assertEqual(self.map.snapshot()["assets"], before["assets"])
        self.assertEqual(self.map.undo_stack, [])
        self.assertEqual(checked["proposal"]["on_top_of"], [DESK])
        self.assertEqual(checked["preview"]["space_ids"], [OFFICE])
        applied = object_edits.apply_edit(self.map, checked["proposal"])
        self.assertEqual(applied["assets"], checked["preview"]["assets"])
        self.assertEqual(applied["summary"], checked["summary"])

    def test_adapter_round_trip_reads_manual_override_edits(self):
        machine = self.put_on_desk()
        self.apply(kind="update_object", object_ref=DESK, height_m=0.9)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "building_edited.json"
            self.map.save(path)
            adapter = Path(temporary) / STACKING_FILE
            text = adapter.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("}\n") and "\r" not in text)
            document = json.loads(text)
            self.assertEqual(document, self.map.stacking_document())
            document["layers"][0]["objects"][0]["height_m"] = 1.1
            document["layers"][1]["objects"][0]["elevation_m"] = 42  # derived values are recomputed
            adapter.write_text(json.dumps(document), encoding="utf-8")
            loaded = BuildingMap.load(path)
            self.assertEqual((loaded.stacking, loaded.height_overrides), ({machine: [DESK]}, {DESK: 1.1}))
            self.assertEqual(loaded.stacking_document()["layers"][1]["objects"][0]["elevation_m"], 1.1)
            document["building_id"] = "another-building"
            adapter.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(MapError):
                BuildingMap.load(path)

    def test_escalator_routes_like_stairs_and_step_free_avoids_it(self):
        result = self.apply(kind="add_connector", connector_kind="escalator", spaces=["Office 0.02", OFFICE_ABOVE])
        escalator = result["connectors"][0]
        self.assertEqual(result["summary"], "Add Escalator 1 between Ground floor and Floor 1.")
        self.assertEqual((escalator["step_free"], escalator["id"]), (False, "proc-campus-dev-000-V-new7"))
        route = self.map.compute_route(OFFICE, OFFICE_ABOVE)
        self.assertEqual((route.element_path, route.length_m), ([escalator["id"]], 7.6))
        self.assertNotIn(escalator["id"], self.map.compute_route(OFFICE, OFFICE_ABOVE, step_free=True).element_path)
        self.assert_rejected("same_floor", kind="add_connector", connector_kind="lift", spaces=[OFFICE, CORRIDOR])
        self.assert_rejected("not_stacked", kind="add_connector", connector_kind="lift",
                             spaces=[OFFICE, f"{F1}-S020"])

    def test_add_opening_from_a_wall_position(self):
        result = self.apply(kind="add_opening", opening_kind="opening", floor_id=F0, position=[6.05, -3.5],
                            width_m=1.0)
        opening = result["openings"][0]
        self.assertEqual(result["summary"], "Add a passage between Office 0.02 and Corridor 0.01.")
        self.assertEqual((opening["kind"], opening["position"], set(opening["space_ids"])),
                         ("opening", [6.0, -3.5], {OFFICE, CORRIDOR}))
        self.assert_rejected("not_adjacent", kind="add_opening", floor_id=F0, position=[3.0, -1.0])
        legacy = self.apply(kind="add_door", first_space="Office 0.02", second_space="Kitchen 0.03")
        self.assertEqual(legacy["kind"], "add_opening")
        self.assertEqual(self.apply(kind="undo_edit")["removed_ids"], legacy["changed_ids"])

    def test_update_checks_fields_per_target(self):
        error = self.assert_rejected("invalid_field", kind="update_object", object_ref=DOOR, name="Front door")
        self.assertEqual(error.field, "name")
        self.assert_rejected("invalid_field", kind="update_object", object_ref="Staircase 1", step_free=True)
        widened = self.apply(kind="update_object", object_ref=DOOR, width_m=1.2, opening_kind="opening")
        self.assertEqual((widened["openings"][0]["width_m"], widened["openings"][0]["kind"]), (1.2, "opening"))
        self.assertEqual(self.map.resolve_object("lift 1"), "proc-campus-dev-000-V02")
        with self.assertRaises(MapError) as caught:
            self.map.resolve_object("No such thing")
        self.assertEqual(caught.exception.reason, "not_found")

    def test_clone_is_independent(self):
        self.put_on_desk()
        clone = self.map.clone()
        object_edits.apply_edit(clone, {"kind": "remove_object", "object_ref": DESK})
        object_edits.apply_edit(clone, {"kind": "undo_edit"})
        object_edits.apply_edit(clone, {"kind": "undo_edit"})
        self.assertIn(DESK, self.map.assets)
        self.assertEqual(len(self.map.undo_stack), 1)
        self.assertEqual(len(self.map.stacking), 1)
        self.assertEqual((len(clone.undo_stack), clone.stacking), (0, {}))

    def test_failed_save_rolls_back_everything(self):
        self.put_on_desk()
        before, undo = self.map.snapshot(), list(self.map.undo_stack)
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_tools(self.map, Path(temporary))}
            for target in ("final_agent.building_map.JsonBuildingStore.save", "final_agent.stacking.save"):
                with self.subTest(target=target), patch(target, side_effect=OSError("disk full")):
                    for name, arguments in (
                        ("add_object", {"type": "printer", "on_top_of": [DESK]}),
                        ("update_object", {"object": DESK, "space": "Office 0.07", "height_m": 1.0}),
                        ("remove_object", {"object": DESK}),
                        ("undo_last_edit", {}),
                    ):
                        with self.assertRaisesRegex(ToolError, "NOT applied.*disk full"):
                            tools[name].call(arguments)
                        after = self.map.snapshot()
                        for key in ("assets", "openings", "vertical_connectors", "stacking", "height_overrides"):
                            self.assertEqual(after[key], before[key], f"{name}: {key}")
                        self.assertEqual(self.map.undo_stack, undo)
            saved = json.loads(tools["undo_last_edit"].call({}))
            self.assertEqual(saved["summary"], "Undo: Add Coffee machine 0.02 on Desk 0.02-A.")
            self.assertTrue((Path(temporary) / STACKING_FILE).exists())


if __name__ == "__main__":
    unittest.main()
