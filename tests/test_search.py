"""Search, pagination and list_spaces checks on a small synthetic building (no API calls)."""

import json
import tempfile
import unittest
from pathlib import Path

from anthropic.lib.tools import ToolError

from final_agent.agent import BuildingAgent
from final_agent.building_map import BuildingMap, MapError
from test_storage import example_building

CHAIRS_UP = 31


def search_building_data() -> dict:
    """Example building plus a basement, broad space types, similar types and 31 chairs upstairs."""
    data = example_building()
    data["building"]["source"] = "test"
    data["floors"].append({"id": "FB", "level": -1, "name": "Basement"})
    for space in data["spaces"]:
        space["type"] = "room"
    data["spaces"][1]["room_type"] = "office_kitchen"
    data["spaces"] += [
        {"id": "hall", "name": "Hall", "floor_id": "F0", "type": "hall", "room_type": "lobby",
         "polygon": [[4, -2], [8, -2], [8, 2], [4, 2]]},
        {"id": "cellar", "name": "Cellar", "floor_id": "FB", "type": "room", "room_type": "storage",
         "polygon": [[0, 0], [4, 0], [4, 4], [0, 4]]},
    ]
    data["assets"] += [
        {"id": f"chair{number:02d}", "name": f"Chair {number:02d}", "floor_id": "F1", "space_id": "upstairs",
         "position": [-3, 0], "type": "chair", "category": "furniture"}
        for number in range(CHAIRS_UP)
    ]
    data["assets"].append({"id": "stool", "name": "Stool", "floor_id": "F0", "space_id": "left",
                           "position": [-1, 0], "type": "Bar-Stool", "category": "furniture"})
    return data


def space_data(count: int) -> dict:
    data = search_building_data()
    data["spaces"] = [
        {"id": f"s{number:03d}", "name": f"Room {number:03d}", "floor_id": "F0", "type": "room",
         "room_type": "office", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}
        for number in range(count)
    ]
    data["assets"] = []
    return data


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.building = BuildingMap(search_building_data())

    def pages(self, size: int, *arguments) -> list[dict]:
        pages, page = [], 1
        while page:
            pages.append(self.building.paginate(self.building.search(*arguments), page, size))
            page = pages[-1]["next_page"]
        return pages

    def test_page_counts_for_0_15_16_and_over_30_matches(self):
        for count, total_pages in ((0, 0), (15, 1), (16, 2), (31, 3)):
            with self.subTest(count=count):
                page = self.building.paginate(list(range(count)))
                self.assertEqual((page["matches"], page["total_pages"]), (count, total_pages))
                self.assertEqual(len(page["results"]), min(count, 15))
                self.assertEqual(page["has_more"], count > 15)
                self.assertEqual(page["next_page"], 2 if count > 15 else None)

    def test_every_id_exactly_once_across_pages_and_sizes(self):
        everything = [item["id"] for item in self.building.search("", asset_type="chair")]
        self.assertEqual(len(everything), CHAIRS_UP)
        for size in (1, 7, 15, 30, 100):
            with self.subTest(size=size):
                pages = self.pages(size, "", None, "all", None, "chair")
                self.assertEqual([item["id"] for page in pages for item in page["results"]], everything)
                self.assertEqual({page["matches"] for page in pages}, {CHAIRS_UP})
                self.assertEqual(len(pages), -(-CHAIRS_UP // size))
        self.assertEqual(len(set(everything)), CHAIRS_UP)

    def test_last_and_out_of_range_pages(self):
        found = self.building.search("", asset_type="chair")
        last = self.building.paginate(found, 3)
        self.assertEqual((len(last["results"]), last["has_more"], last["next_page"]), (1, False, None))
        beyond = self.building.paginate(found, 9)
        self.assertEqual((beyond["results"], beyond["matches"], beyond["total_pages"], beyond["next_page"]),
                         ([], CHAIRS_UP, 3, None))

    def test_exact_type_filters_versus_query_text(self):
        office = self.building.search("", room_type="Office")
        self.assertEqual([item["id"] for item in office], ["left", "upstairs"])
        self.assertEqual([item["id"] for item in self.building.search("", room_type="office kitchen")], ["right"])
        self.assertEqual({item["id"] for item in self.building.search("office")}, {"left", "right", "upstairs"})
        self.assertEqual([item["id"] for item in self.building.search("", asset_type="bar stool")], ["stool"])
        self.assertEqual(self.building.search("", asset_type="bar"), [])
        self.assertEqual([item["id"] for item in self.building.search("", space_type="hall")], ["hall"])
        self.assertEqual(len(self.building.search("", space_type="room")), 4)
        self.assertEqual(self.building.search("", asset_type="chair", floor_level=0), [])

    def test_result_identity_fields(self):
        space = self.building.search("hall", kind="space")[0]
        self.assertEqual(
            (space["kind"], space["type"], space["room_type"], space["floor_level"], space["floor"]),
            ("space", "hall", "lobby", 0, "Ground"),
        )
        asset = self.building.search("stool")[0]
        self.assertEqual((asset["space_id"], asset["category"], asset["floor_level"]), ("left", "furniture", 0))
        self.assertIn("Left", asset["in"])

    def test_negative_floor_and_sorting(self):
        self.assertEqual([item["id"] for item in self.building.search("", floor_level=-1)], ["cellar"])
        everything = self.building.search("", floor_level=0)
        keys = [(item["kind"], item["floor_level"], item["name"], item["id"]) for item in everything]
        self.assertEqual(keys, sorted(keys))

    def test_invalid_arguments_are_actionable(self):
        search = self.building.search
        for call in (
            lambda: search(""),
            lambda: search("   "),
            lambda: search("x", kind="asset", room_type="office"),
            lambda: search("x", kind="space", asset_type="chair"),
            lambda: search("x", asset_type="chair", room_type="office"),
            lambda: search("x", asset_type="chair", space_type="room"),
            lambda: search("x", kind="opening"),
            lambda: search("x", floor_level=99),
            lambda: search("x", floor_level=True),
            lambda: search("x", room_type=5),
        ):
            with self.subTest(call=call), self.assertRaises(MapError):
                call()
        for page, size in ((0, 15), (-1, 15), (True, 15), (1.5, 15), ("2", 15), (1, 0), (1, 101), (1, 2.0), (1, False)):
            with self.subTest(page=page, size=size), self.assertRaises(MapError):
                self.building.paginate([1], page, size)

    def test_item_on_second_page_resolves_by_id_and_search_does_not_cap(self):
        found = self.building.search("chair")
        self.assertEqual(len(found), CHAIRS_UP)
        second_page = self.building.paginate(found, 2)["results"]
        self.assertTrue(second_page)
        self.assertEqual(self.building.resolve_space(second_page[0]["id"]), "upstairs")
        self.assertEqual(self.building.resolve_space(found[-1]["id"]), "upstairs")

    def test_spatial_results_carry_identity(self):
        results = self.building.spatial_search(-2, 0, 0, 1)
        by_id = {item["id"]: item for item in results}
        self.assertEqual(by_id["left"]["room_type"], "office")
        self.assertEqual(by_id["left"]["distance_m"], 0)
        self.assertEqual(by_id["stool"]["space_id"], "left")
        self.assertEqual(by_id["stool"]["type"], "Bar-Stool")


class SearchToolTests(unittest.TestCase):
    def tools(self, data: dict, directory: str) -> dict:
        agent = BuildingAgent(BuildingMap(data), Path(directory), client=object())
        return {tool.name: tool for tool in agent.tools}

    def test_tool_json_shape_zero_matches_and_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            tools = self.tools(search_building_data(), temporary)
            call = lambda name, **arguments: json.loads(tools[name].call(arguments))
            first = call("search_building", query="", floor_level=1, asset_type="chair")
            self.assertEqual((first["matches"], first["page"], first["page_size"], first["total_pages"]),
                             (CHAIRS_UP, 1, 15, 3))
            self.assertEqual((len(first["results"]), first["has_more"], first["next_page"]), (15, True, 2))
            last = call("search_building", query="", floor_level=1, asset_type="chair", page=3, page_size=15)
            self.assertEqual((len(last["results"]), last["next_page"]), (1, None))
            small = call("search_building", query="", asset_type="chair", page_size=100)
            self.assertEqual((len(small["results"]), small["has_more"]), (CHAIRS_UP, False))
            empty = call("search_building", query="zebra")
            self.assertEqual((empty["matches"], empty["results"], empty["total_pages"]), (0, [], 0))
            self.assertIn("hint", empty)
            with self.assertRaises(ToolError):
                call("search_building", query="")
            with self.assertRaises(ToolError):
                call("search_building", query="x", page=0)
            with self.assertRaises(ToolError):
                call("spatial_search", x_m=0, y_m=0, floor_level=0, page_size=500)

    def test_list_spaces_is_complete_and_spaces_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            tools = self.tools(space_data(40), temporary)
            ids, page = [], 1
            while page:
                result = json.loads(tools["list_spaces"].call({"page": page, "page_size": 12}))
                self.assertEqual(result["matches"], 40)
                ids += [item["id"] for item in result["results"]]
                page = result["next_page"]
            self.assertEqual(ids, [f"s{number:03d}" for number in range(40)])
            self.assertEqual(json.loads(tools["list_spaces"].call({}))["total_pages"], 3)
        with tempfile.TemporaryDirectory() as temporary:
            tools = self.tools(search_building_data(), temporary)
            everything = json.loads(tools["list_spaces"].call({"page_size": 100}))
            self.assertEqual(everything["matches"], 5)
            self.assertEqual({item["kind"] for item in everything["results"]}, {"space"})
            self.assertEqual({item["type"] for item in everything["results"]}, {"room", "hall"})
            halls = json.loads(tools["list_spaces"].call({"space_type": "hall"}))
            self.assertEqual([item["id"] for item in halls["results"]], ["hall"])
            none = json.loads(tools["list_spaces"].call({"room_type": "dungeon"}))
            self.assertEqual(none["matches"], 0)
            self.assertIn("hint", none)


if __name__ == "__main__":
    unittest.main()
