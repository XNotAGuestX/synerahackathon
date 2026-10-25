import tempfile
import unittest
import json
import copy
from pathlib import Path

from final_agent.campus import Campus
from final_agent.building_map import MapError


class CampusTests(unittest.TestCase):
    def test_same_room_keeps_its_floor_view_and_walkway_addition_recovers_route(self):
        from test_workspace import model
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campus = Campus(root / "campus.json")
            for bid in ("a", "b"):
                path = root / f"{bid}.json"
                path.write_text(json.dumps(model(bid)))
                campus.register_building(bid, path)
            start = {"building_id": "a", "element_id": "r"}
            end = {"building_id": "b", "element_id": "r"}
            same = campus.find_route(start, start)
            self.assertTrue(same["reachable"])
            self.assertEqual(same["total_m"], 0)
            self.assertEqual(same["space_path"], [{"building_id": "a", "space_id": "r"}])
            self.assertEqual(same["legs"][0]["floor_segments"][0]["floor_id"], "f0")
            self.assertFalse(campus.find_route(start, end)["reachable"])
            campus.add_walkway("w", "Walk", {"building_id": "a", "opening_id": "entry"},
                               {"building_id": "b", "opening_id": "entry"}, 10, 1.2, True)
            self.assertTrue(campus.last_route["reachable"])
            self.assertEqual(Campus(campus.path).last_route["route_id"], campus.last_route["route_id"])

    def test_registry_scoped_route_and_manifest_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "campus.json"
            campus = Campus(manifest)
            campus.register_building("proc-factory-dev-003", Path("data/dev/proc-factory-dev-003"))
            campus.select_building("proc-factory-dev-003")
            connector = next(c for c in campus.selected_map.connectors.values() if len(c["space_ids"]) >= 2)
            connector_route = campus.find_route(
                {"building_id": "proc-factory-dev-003", "kind": "space", "element_id": connector["space_ids"][0]},
                {"building_id": "proc-factory-dev-003", "kind": "space", "element_id": connector["space_ids"][1]},
            )
            self.assertTrue(connector_route["reachable"])
            self.assertIn(connector["id"], [element for leg in connector_route["legs"] if leg["kind"] == "indoor" for element in leg["edge_ids"]])
            spaces = list(campus.selected_map.spaces)
            result = campus.find_route(
                {"building_id": "proc-factory-dev-003", "kind": "space", "element_id": spaces[0]},
                {"building_id": "proc-factory-dev-003", "kind": "space", "element_id": spaces[-1]},
            )
            self.assertTrue(result["reachable"])
            self.assertEqual(result["building_revisions"]["proc-factory-dev-003"], 1)
            loaded = Campus(manifest)
            self.assertEqual(loaded.selected_building_id, "proc-factory-dev-003")
            self.assertEqual(set(loaded.buildings), {"proc-factory-dev-003"})
            self.assertTrue(loaded.last_route["reachable"])
            self.assertEqual(loaded.last_route["route_id"], result["route_id"])
            unreachable = loaded.find_route({"building_id": "missing", "element_id": "x"},
                                            {"building_id": "proc-factory-dev-003", "element_id": spaces[0]})
            self.assertFalse(unreachable["reachable"])
            self.assertIn("Unknown building", unreachable["reason"])

    def test_two_building_walkway_route_and_recovery(self):
        source = json.loads(Path("data/dev/proc-factory-dev-003/building.json").read_text())
        entrance = next(o for o in source["openings"] if o["kind"] == "entrance"
                        and len(o["space_ids"]) == 2 and "outside" in o["space_ids"])
        room = next(s for s in entrance["space_ids"] if s != "outside")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_b = copy.deepcopy(source)
            copy_b["building"]["id"] = "building-b"
            path_b = root / "building-b.json"
            path_b.write_text(json.dumps(copy_b))
            campus = Campus(root / "campus.json")
            campus.register_building(source["building"]["id"], Path("data/dev/proc-factory-dev-003"))
            campus.register_building("building-b", path_b)
            walkway_id = "measured-connector"
            campus.add_walkway(walkway_id, "East walk", {"building_id": source["building"]["id"], "opening_id": entrance["id"]},
                               {"building_id": "building-b", "opening_id": entrance["id"]}, 3.0, 1.0, True)
            upper_space = source["vertical_connectors"][0]["space_ids"][1]
            start = {"building_id": source["building"]["id"], "kind": "space", "element_id": upper_space}
            destination = {"building_id": "building-b", "kind": "space", "element_id": room}
            route = campus.find_route(start, destination, min_width_m=1.0)
            self.assertTrue(route["reachable"])
            self.assertEqual([leg["kind"] for leg in route["legs"]], ["indoor", "walkway", "indoor"])
            self.assertGreater(route["total_m"], 3.0)
            self.assertEqual(route["legs"][1]["walkway_id"], walkway_id)
            self.assertEqual(route["space_path"][0]["space_id"], upper_space)
            self.assertEqual(route["space_path"][-1], {"building_id": "building-b", "space_id": room})
            walkway_index = route["element_path"].index({"walkway_id": walkway_id})
            arrival_door = {"building_id": "building-b", "element_id": entrance["id"]}
            self.assertIn(arrival_door, route["element_path"][walkway_index + 1:])
            self.assertTrue(route["legs"][0]["floor_segments"])
            self.assertTrue(route["legs"][0]["geometry_complete"])
            self.assertEqual(route["legs"][0]["node_path"][-1], "door:" + entrance["id"])
            self.assertEqual(route["legs"][2]["node_path"][0], "door:" + entrance["id"])
            closed = campus.close(walkway_id)
            self.assertFalse(closed["reachable"])
            reopened = campus.close(walkway_id, closed=False)
            self.assertTrue(reopened["reachable"])


if __name__ == "__main__":
    unittest.main()
