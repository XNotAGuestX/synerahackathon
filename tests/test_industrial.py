"""Industrial route eligibility stays off the default kit path."""

import math
import unittest
from pathlib import Path

from final_agent.building_map import (
    INDUSTRIAL_PROFILE, BuildingMap, MapError, require_navigation_records,
)
from final_agent.storage import JsonBuildingStore
from test_storage import example_building

FACTORY = Path("data/dev/proc-factory-dev-003")
START = "proc-factory-dev-003-F0-S001"
MIDDLE = "proc-factory-dev-003-F0-S002"
DESTINATION = "proc-factory-dev-003-F0-S003"
AISLE = "proc-factory-dev-003-F0-S006"


class IndustrialRouteTests(unittest.TestCase):
    def test_default_profile_matches_the_unlabelled_route(self):
        building = BuildingMap.load(FACTORY)
        plain = building.compute_route(START, DESTINATION, min_width_m=3)
        labelled = building.compute_route(START, DESTINATION, min_width_m=3, profile="kit-1.1.0")
        self.assertEqual(plain.length_m, labelled.length_m)
        self.assertEqual(plain.space_path, labelled.space_path)
        self.assertIn(MIDDLE, plain.space_path)
        self.assertEqual(plain.route_profile, "kit-1.1.0")

    def test_industrial_profile_does_not_cross_a_production_bay(self):
        building = BuildingMap.load(FACTORY)
        route = building.compute_route(START, DESTINATION, profile=INDUSTRIAL_PROFILE)
        self.assertEqual(route.space_path[0], START)
        self.assertEqual(route.space_path[-1], DESTINATION)
        self.assertNotIn(MIDDLE, route.space_path)
        self.assertGreater(route.length_m, 34.2)
        self.assertEqual(route.route_profile, INDUSTRIAL_PROFILE)

    def test_industrial_delivery_may_end_in_a_production_bay(self):
        building = BuildingMap.load(FACTORY)
        route = building.compute_route(AISLE, START, profile=INDUSTRIAL_PROFILE)
        self.assertEqual(route.space_path[-1], START)
        self.assertNotIn(MIDDLE, route.space_path)

    def test_unknown_profile_is_rejected(self):
        building = BuildingMap.load(FACTORY)
        with self.assertRaises(MapError):
            building.compute_route(START, DESTINATION, profile="forklift")


class ConnectorSearchTests(unittest.TestCase):
    def test_office_lift_is_a_search_result(self):
        building = BuildingMap.load(FACTORY)
        found = [item for item in building.search("office lift") if item["kind"] == "connector"]
        self.assertEqual([item["name"] for item in found], ["Office lift"])
        self.assertEqual(building.find_element("Office lift"), found[0]["id"])


class ResolveAmbiguityTests(unittest.TestCase):
    def test_exact_room_and_asset_names_are_not_silently_collapsed(self):
        data = example_building()
        data["spaces"][0]["name"] = "Printer"
        data["spaces"][1]["name"] = "Printer"
        data["assets"][0]["name"] = "Printer"
        building = BuildingMap(data)
        with self.assertRaises(MapError) as caught:
            building.resolve_space("Printer")
        self.assertEqual(caught.exception.reason, "ambiguous")
        self.assertIn("left", str(caught.exception))
        self.assertIn("printer", str(caught.exception))


class NavigationRecordTests(unittest.TestCase):
    def test_dev_buildings_still_load(self):
        for path in sorted(Path("data/dev").glob("*/building.json")):
            require_navigation_records(JsonBuildingStore.load(path))
            BuildingMap.load(path.parent)

    def test_duplicate_id_nonfinite_coordinate_and_cross_floor_opening_are_rejected(self):
        data = example_building()
        data["spaces"].append(dict(data["spaces"][0]))
        with self.assertRaises(MapError):
            require_navigation_records(data)
        data = example_building()
        data["spaces"][0]["polygon"][0] = [math.nan, 0]
        with self.assertRaises(MapError):
            require_navigation_records(data)
        data = example_building()
        data["openings"] = [{
            "id": "cross", "floor_id": "F0", "space_ids": ["left", "upstairs"],
            "position": [0, 0], "width_m": 1.0,
        }]
        with self.assertRaises(MapError):
            require_navigation_records(data)


if __name__ == "__main__":
    unittest.main()
