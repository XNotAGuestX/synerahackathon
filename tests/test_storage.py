import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from final_agent.building_map import BuildingMap, MapError
from final_agent.storage import JsonBuildingStore


def example_building() -> dict:
    return {
        "building": {"id": "test", "name": "Test building", "units": "m"},
        "floors": [
            {"id": "F0", "level": 0, "name": "Ground"},
            {"id": "F1", "level": 1, "name": "First"},
        ],
        "spaces": [
            {"id": "left", "name": "Left", "floor_id": "F0", "room_type": "office",
             "polygon": [[-4, -2], [0, -2], [0, 2], [-4, 2]]},
            {"id": "right", "name": "Right", "floor_id": "F0", "room_type": "office",
             "polygon": [[0, -2], [4, -2], [4, 2], [0, 2]]},
            {"id": "upstairs", "name": "Upstairs", "floor_id": "F1", "room_type": "office",
             "polygon": [[-4, -2], [0, -2], [0, 2], [-4, 2]]},
        ],
        "assets": [
            {"id": "printer", "name": "Printer", "floor_id": "F0", "space_id": "left",
             "position": [-2, 0], "type": "printer"},
            {"id": "desk", "name": "Desk", "floor_id": "F1", "space_id": "upstairs",
             "position": [-2, 0], "type": "desk"},
        ],
        "openings": [],
        "vertical_connectors": [],
        "custom_metadata": {"note": "Grüße"},
    }


class StorageTests(unittest.TestCase):
    def test_save_reload_preserves_building_edits_and_closures(self):
        with tempfile.TemporaryDirectory() as temporary:
            building = BuildingMap(example_building())
            with self.assertRaises(MapError):
                building.route("left", "right")
            door = building.add_door("left", "right")
            length = building.route("left", "right").length_m
            building.set_closed(door["id"], True)
            target = Path(temporary) / "nested" / "building.json"
            building.save(target)
            restored = BuildingMap.load(target.parent)
            self.assertEqual(restored.data["custom_metadata"], {"note": "Grüße"})
            self.assertIn(door["id"], restored.closed)
            with self.assertRaises(MapError):
                restored.route("left", "right")
            restored.set_closed(door["id"], False)
            self.assertEqual(restored.route("left", "right").length_m, length)
            restored.save(target)
            self.assertEqual(BuildingMap.load(target).closed, set())

    def test_failed_save_preserves_existing_json_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "building.json"
            original = example_building()
            JsonBuildingStore.save(target, original)
            with patch("final_agent.storage.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    JsonBuildingStore.save(target, {"changed": True})
            self.assertEqual(JsonBuildingStore.load(target), original)
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_saving_snapshot_does_not_mutate_input(self):
        data = example_building()
        original = copy.deepcopy(data)
        building = BuildingMap(data)
        building.set_closed("left", True)
        with tempfile.TemporaryDirectory() as temporary:
            building.save(Path(temporary))
            self.assertEqual(data, original)
            self.assertEqual(json.loads((Path(temporary) / "building.json").read_text())[
                "navigation_state"], {"closed": ["left"]})


class SpatialIndexTests(unittest.TestCase):
    def setUp(self):
        self.building = BuildingMap(example_building())

    def test_containment_uses_floor_and_includes_boundaries(self):
        results = self.building.spatial_search(-2, 0, 0, kind="space")
        self.assertEqual([result["id"] for result in results], ["left"])
        self.assertEqual(results[0]["distance_m"], 0)
        self.assertEqual(
            {result["id"] for result in self.building.spatial_search(0, 0, 0, kind="space")},
            {"left", "right"},
        )
        self.assertEqual(
            [result["id"] for result in self.building.spatial_search(-2, 0, 1, kind="space")],
            ["upstairs"],
        )

    def test_radius_uses_exact_distance_and_filters_kind(self):
        self.assertEqual(self.building.spatial_search(-5, 0, 0, 2, "asset"), [])
        results = self.building.spatial_search(-5, 0, 0, 3, "asset")
        self.assertEqual([result["id"] for result in results], ["printer"])
        self.assertEqual(results[0]["distance_m"], 3)
        results = self.building.spatial_search(-5, 0, 0, 6)
        self.assertEqual([result["id"] for result in results], ["left", "printer", "right"])
        # The printer is inside this bounding square, but outside the search circle.
        self.assertEqual(self.building.spatial_search(-4, -2, 0, 2, "asset"), [])

    def test_door_edits_rebuild_existing_index(self):
        self.assertEqual(self.building.spatial_search(0, -2, 0, 1, "opening"), [])
        opening = self.building.add_door("left", "right")
        results = self.building.spatial_search(*opening["position"], 0, kind="opening")
        self.assertEqual([result["id"] for result in results], [opening["id"]])

    def test_invalid_search_arguments_raise_map_errors(self):
        for arguments in (
            (0, 0, 0, -1), (float("nan"), 0, 0), (0, float("inf"), 0),
            (0, 0, 0, float("inf")), (0, 0, 99), (0, 0, 0, 1, "unknown"),
        ):
            with self.subTest(arguments=arguments), self.assertRaises(MapError):
                self.building.spatial_search(*arguments)


if __name__ == "__main__":
    unittest.main()
