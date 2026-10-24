"""Checks for find_navigation_landmarks on a compact synthetic building (no API calls)."""

import json
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError

from final_agent.building_map import BuildingMap, MapError
from final_agent.tools import make_tools

QUERY = (5.0, 5.0, 0)  # centre of room r1 on floor 0


def square(x: float, y: float, size: float) -> list[list[float]]:
    return [[x, y], [x + size, y], [x + size, y + size], [x, y + size]]


def asset(asset_id: str, x: float, y: float, asset_type: str = "fire_extinguisher", space: str = "r1",
          floor: str = "G", name: str | None = None, footprint: dict | None = None) -> dict:
    record = {"id": asset_id, "name": name or asset_id, "type": asset_type, "space_id": space,
              "floor_id": floor, "position": [x, y]}
    if footprint is not None:
        record["footprint"] = footprint
    return record


def building(assets: list[dict]) -> BuildingMap:
    def room(space_id: str, floor_id: str, polygon: list[list[float]], room_type: str = "office") -> dict:
        return {"id": space_id, "name": space_id.upper(), "type": "room", "room_type": room_type,
                "floor_id": floor_id, "polygon": polygon}

    return BuildingMap({
        "building": {"id": "t", "name": "T", "source": "test", "units": "m"},
        "floors": [{"id": "G", "level": 0, "name": "G", "elevation_m": 0.0},
                   {"id": "F1", "level": 1, "name": "F1", "elevation_m": 4.0}],
        "spaces": [room("r1", "G", square(0, 0, 10)), room("r2", "G", square(10, 0, 10)),
                   room("big", "G", square(0, 10, 10), "warehouse_zone"),
                   room("big2", "G", square(10, 10, 10), "warehouse_zone"),
                   room("upper", "F1", square(0, 0, 10))],
        "assets": assets, "openings": [], "vertical_connectors": [],
    })


def landmarks(assets: list[dict], inner: float = 2.0, outer: float = 6.0, **options: object) -> dict:
    return building(assets).find_navigation_landmarks(*QUERY, inner, outer, **options)


def by_id(result: dict) -> dict[str, dict]:
    return {item["id"]: item for item in result["candidates"]}


class LandmarkTests(unittest.TestCase):
    def test_unique_extinguisher(self) -> None:
        result = landmarks([asset("e1", 5, 6, footprint={"width_m": 0.3, "depth_m": 0.4})])
        [item] = result["candidates"]
        self.assertEqual((item["id"], item["kind"], item["type"]), ("e1", "asset", "fire_extinguisher"))
        self.assertTrue(item["is_unambiguous"])
        self.assertEqual((item["similar_count_outer"], item["competitor_ids"]), (0, []))
        self.assertEqual((item["distance_m"], item["size_m2"], item["position"]), (1.0, 0.12, [5.0, 6.0]))
        self.assertEqual(item["space"], {"id": "r1", "name": "R1"})
        self.assertEqual((item["floor_level"], item["visibility"]), (0, "unknown"))
        self.assertEqual(result["query"]["kind"], "asset")
        self.assertIn("m", result["size_convention"])

    def test_similar_object_in_outer_ring_makes_it_ambiguous(self) -> None:
        result = landmarks([asset("e1", 5, 6), asset("e2", 5, 10.5, space="big")])
        self.assertEqual(result["candidate_count"], 1)
        item = result["candidates"][0]
        self.assertFalse(item["is_unambiguous"])
        self.assertEqual((item["similar_count_outer"], item["competitor_ids"]), (1, ["e2"]))

    def test_competitor_inside_inner_circle_and_unambiguous_first(self) -> None:
        result = landmarks([
            asset("e1", 5, 6), asset("e2", 6, 5), asset("bin", 5, 3.5, "bin"),
        ])
        items = by_id(result)
        self.assertEqual(items["e1"]["competitor_ids"], ["e2"])
        self.assertEqual(items["e2"]["competitor_ids"], ["e1"])
        self.assertEqual([item["id"] for item in result["candidates"]], ["bin", "e1", "e2"])
        self.assertEqual(result["unambiguous_count"], 1)

    def test_radius_equality_boundaries(self) -> None:
        # 3-4-5 triangles give exact distances: inner 5 and outer 10.
        result = landmarks(
            [asset("near", 8, 9), asset("far", 5, 15, space="big"), asset("beyond", 5, 15.001, space="big")],
            inner=5.0, outer=10.0,
        )
        self.assertEqual([item["id"] for item in result["candidates"]], ["near"])
        self.assertEqual(result["candidates"][0]["competitor_ids"], ["far"])
        result = landmarks([asset("near", 8, 9), asset("out", 8, 9.001)], inner=5.0, outer=5.0)
        self.assertEqual([item["id"] for item in result["candidates"]], ["near"])
        self.assertTrue(result["candidates"][0]["is_unambiguous"])

    def test_other_floor_is_ignored(self) -> None:
        result = landmarks([asset("e1", 5, 6), asset("up", 5, 6, space="upper", floor="F1")])
        self.assertEqual(by_id(result)["e1"]["competitor_ids"], [])
        self.assertEqual(result["candidate_count"], 1)

    def test_unknown_and_partial_footprints(self) -> None:
        assets = [asset("none", 5, 6), asset("partial", 5, 4, footprint={"width_m": 1.0}),
                  asset("known", 4, 5, footprint={"width_m": 2.0, "depth_m": 1.5, "rotation_deg": 90})]
        items = by_id(landmarks(assets))
        self.assertEqual((items["none"]["size_m2"], items["partial"]["size_m2"]), (None, None))
        self.assertEqual(items["known"]["size_m2"], 3.0)
        # Known size first among equally distant candidates; unknown last.
        self.assertEqual([item["id"] for item in landmarks(assets)["candidates"]][0:1], ["known"])
        filtered = landmarks(assets, min_size=3.0)  # equality passes
        self.assertEqual(list(by_id(filtered)), ["known"])
        self.assertEqual(filtered["candidates"][0]["similar_count_outer"], 2)

    def test_small_footprint_is_not_candidate_but_still_competitor(self) -> None:
        assets = [asset("big", 5, 6, "printer", footprint={"width_m": 1.0, "depth_m": 1.0}),
                  asset("tiny", 5, 4, "printer", footprint={"width_m": 0.1, "depth_m": 0.1}),
                  asset("unknown", 6, 5, "printer")]
        result = landmarks(assets, min_size=0.5)
        self.assertEqual(list(by_id(result)), ["big"])
        self.assertEqual(result["candidates"][0]["competitor_ids"], ["tiny", "unknown"])

    def test_numbered_names_do_not_make_objects_unique(self) -> None:
        result = landmarks([asset("a1", 5, 6, name="Fire extinguisher 1"),
                            asset("a2", 5, 4, name="Fire extinguisher 2")])
        self.assertEqual({item["similar_count_outer"] for item in result["candidates"]}, {1})
        # Case/spacing of the type is normalized; a different type is not a competitor.
        result = landmarks([asset("a1", 5, 6), asset("a2", 5, 4, "Fire Extinguisher"),
                            asset("a3", 4, 5, "fire_extinguisher_cabinet")])
        self.assertEqual(by_id(result)["a1"]["competitor_ids"], ["a2"])

    def test_colocated_objects_compete(self) -> None:
        result = landmarks([asset("e1", 5, 6), asset("e2", 5, 6)])
        self.assertEqual([item["competitor_ids"] for item in result["candidates"]], [["e2"], ["e1"]])

    def test_many_competitors_are_all_counted(self) -> None:
        crowd = [asset(f"c{index:02d}", 5 + index * 0.1, 5, space="r1") for index in range(18)]
        result = landmarks(crowd + [asset("lone", 5, 5, "bin")], inner=0.0)
        items = by_id(result)
        self.assertTrue(items["lone"]["is_unambiguous"])
        result = landmarks(crowd, inner=0.5, outer=6.0)
        first = result["candidates"][0]
        self.assertEqual(first["similar_count_outer"], 17)
        self.assertEqual(len(first["competitor_ids"]), 10)
        self.assertEqual(first["competitor_ids"], sorted(first["competitor_ids"]))

    def test_candidates_are_capped_with_total_count(self) -> None:
        result = landmarks([asset(f"b{index:02d}", 5, 5, "bin") for index in range(25)])
        self.assertEqual((len(result["candidates"]), result["candidate_count"], result["truncated"]),
                         (20, 25, True))

    def test_within_spaces_rejects_cue_in_another_room_but_counts_it(self) -> None:
        assets = [asset("near_wall", 9.5, 5, "bin", space="r2"), asset("e1", 5, 6),
                  asset("e_other", 10.5, 5, space="r2")]
        self.assertEqual(landmarks(assets, inner=6.0, outer=7.0)["candidate_count"], 3)
        result = landmarks(assets, inner=6.0, outer=7.0, within_spaces=["R1"])
        self.assertEqual(list(by_id(result)), ["e1"])
        self.assertEqual(result["candidates"][0]["competitor_ids"], ["e_other"])
        self.assertEqual(result["query"]["within_spaces"], ["r1"])

    def test_empty_result(self) -> None:
        result = landmarks([asset("far", 9, 9)], inner=1.0)
        self.assertEqual((result["candidates"], result["candidate_count"], result["truncated"]), ([], 0, False))
        self.assertIn("hint", result)

    def test_space_kind_uses_polygon_distance_and_area(self) -> None:
        result = building([]).find_navigation_landmarks(5, 9.5, 0, 1.0, 20.0, 50.0, "space")
        self.assertEqual([item["id"] for item in result["candidates"]], ["r1", "big"])  # r1 is 100 m2 and holds the point
        by_space = by_id(result)
        self.assertEqual((by_space["big"]["distance_m"], by_space["big"]["size_m2"]), (0.5, 100.0))
        self.assertEqual(by_space["big"]["position"], [5.0, 10.0])
        self.assertEqual(by_space["big"]["competitor_ids"], ["big2"])
        self.assertEqual(by_space["big"]["similar_count_outer"], 1)
        self.assertEqual(by_space["r1"]["competitor_ids"], ["r2"])  # same room_type, not 'big'
        self.assertEqual(by_space["r1"]["space"]["id"], "r1")

    def test_kind_all_returns_both_and_compares_within_kind(self) -> None:
        result = building([asset("e1", 5, 6)]).find_navigation_landmarks(*QUERY, 2.0, 6.0, kind="all")
        self.assertEqual({item["kind"] for item in result["candidates"]}, {"asset", "space"})

    def test_index_refreshes_after_add_door(self) -> None:
        building_map = building([asset("e1", 5, 6)])
        before = building_map.find_navigation_landmarks(*QUERY, 2.0, 6.0)
        index = building_map._spatial_index
        building_map.add_door("r1", "r2")
        self.assertIsNone(building_map._spatial_index)
        after = building_map.find_navigation_landmarks(*QUERY, 2.0, 6.0)
        self.assertIsNot(building_map._spatial_index, index)
        self.assertEqual(after, before)

    def test_invalid_arguments(self) -> None:
        building_map = building([asset("e1", 5, 6)])
        bad_calls = [
            dict(x_m=float("nan")), dict(y_m=float("inf")), dict(inner_radius=-1.0),
            dict(outer_radius=1.0), dict(outer_radius=float("inf")), dict(min_size=-0.1),
            dict(floor_level=7), dict(floor_level=True), dict(kind="opening"), dict(kind="x"),
            dict(within_spaces=[]), dict(within_spaces=["nowhere"]),
        ]
        for override in bad_calls:
            arguments = {"x_m": 5.0, "y_m": 5.0, "floor_level": 0, "inner_radius": 2.0, "outer_radius": 6.0,
                         **override}
            with self.subTest(override), self.assertRaises(MapError):
                building_map.find_navigation_landmarks(**arguments)

    def test_tool_returns_json_and_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tools = {tool.name: tool for tool in make_tools(building([asset("e1", 5, 6)]), Path(temporary))}
        tool = tools["find_navigation_landmarks"]
        result = json.loads(tool.call({"x_m": 5, "y_m": 5, "floor_level": 0, "inner_radius": 2,
                                       "outer_radius": 6, "within_spaces": ["r1"]}))
        self.assertEqual(result["candidates"][0]["id"], "e1")
        with self.assertRaises(ToolError):
            tool.call({"x_m": 5, "y_m": 5, "floor_level": 0, "inner_radius": 5, "outer_radius": 1})


if __name__ == "__main__":
    unittest.main()
