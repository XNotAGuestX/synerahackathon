"""Integration checks for the independently runnable project agent (no API calls)."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from anthropic.lib.tools import ToolError

from benchmark.evaluate import load_agent
from final_agent.agent import BuildingAgent
from final_agent.building_map import BuildingMap
from test_storage import example_building


ROOT = Path(__file__).resolve().parents[1]


class FinalAgentIntegrationTests(unittest.TestCase):
    def make_map(self):
        data = example_building()
        data["building"]["source"] = "test"
        return BuildingMap(data)

    def test_entry_point_and_modules_work_with_starter_imports_blocked(self):
        script = textwrap.dedent("""
            import importlib.abc
            import runpy
            import sys
            from unittest.mock import patch

            class NoStarter(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split('.')[0] == 'starter_agent':
                        raise AssertionError('Unexpected starter dependency: ' + fullname)

            sys.meta_path.insert(0, NoStarter())
            from final_agent import agent, benchmark, building_map, evaluate, storage, tools, viewer
            for module in (agent, benchmark, evaluate, tools, viewer):
                assert module.BuildingMap is building_map.BuildingMap, module.__name__
            assert tools.MapError is evaluate.MapError is building_map.MapError
            assert building_map.JsonBuildingStore is storage.JsonBuildingStore
            sys.argv = ['final_agent', 'example-building']
            with patch.object(agent, 'chat') as chat:
                runpy.run_module('final_agent', run_name='__main__')
                assert chat.call_count == 1
                assert str(chat.call_args.args[0]) == 'example-building'
            assert not any(name.split('.')[0] == 'starter_agent' for name in sys.modules)
        """)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_agent_tools_use_spatial_storage_and_viewer(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "nested" / "outputs"
            agent = BuildingAgent(self.make_map(), output, client=object())
            tools = {tool.name: tool for tool in agent.tools}
            result = json.loads(tools["spatial_search"].call({
                "x_m": -2, "y_m": 0, "floor_level": 0, "kind": "asset",
            }))
            self.assertEqual([item["id"] for item in result["results"]], ["printer"])
            added = json.loads(tools["add_door"].call({
                "first_space": "left", "second_space": "right",
            }))["added"]
            route = json.loads(tools["find_route"].call({"start": "left", "destination": "right"}))
            self.assertGreater(route["length_m"], 0)
            images = json.loads(tools["show_route"].call({}))["images"]
            self.assertEqual(len(images), 1)
            self.assertTrue(Path(images[0]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            tools["set_closed"].call({"element": added["id"], "closed": True})
            snapshot = BuildingMap.load(output / "building_edited.json")
            self.assertIn(added["id"], snapshot.openings)
            self.assertIn(added["id"], snapshot.closed)
            with self.assertRaises(ToolError):
                tools["find_route"].call({"start": "left", "destination": "right"})
            tools["set_closed"].call({"element": added["id"], "closed": False})
            self.assertEqual(BuildingMap.load(output / "building_edited.json").closed, set())

    def test_map_errors_are_exposed_as_tool_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            agent = BuildingAgent(self.make_map(), Path(temporary), client=object())
            tools = {tool.name: tool for tool in agent.tools}
            for name, arguments in (
                ("spatial_search", {"x_m": 0, "y_m": 0, "floor_level": 99}),
                ("find_route", {"start": "missing", "destination": "right"}),
                ("set_closed", {"element": "missing", "closed": True}),
                ("add_door", {"first_space": "left", "second_space": "upstairs"}),
            ):
                with self.subTest(tool=name), self.assertRaises(ToolError):
                    tools[name].call(arguments)

    def test_benchmark_callable_isolates_maps_conversations_and_outputs(self):
        agents = []
        outputs = []

        def ask(agent, question):
            self.assertEqual(agent.map.closed, set())
            self.assertEqual(agent.messages, [])
            agent.map.set_closed("left", True)
            # Exercise the actual tool save into the adapter's per-question output directory.
            tool = next(tool for tool in agent.tools if tool.name == "set_closed")
            saved = json.loads(tool.call({"element": "right", "closed": True}))
            output = Path(saved["saved_to"])
            self.assertTrue(output.is_file())
            agents.append(agent)
            outputs.append(output)
            agent.messages.append({"role": "user", "content": question})
            return "Answer: " + question

        with tempfile.TemporaryDirectory() as temporary:
            building = Path(temporary) / "building.json"
            self.make_map().save(building)
            original = building.read_bytes()
            answer = load_agent("final_agent.benchmark:answer")
            # The committed run library would load the embedding model; isolation needs no examples.
            with patch("final_agent.agent.anthropic.Anthropic", return_value=object()), patch.object(
                BuildingAgent, "ask", ask
            ), patch("final_agent.benchmark.run_index", return_value=None):
                self.assertEqual(answer(building.parent, "first"), "Answer: first")
                self.assertEqual(answer(building.parent, "second"), "Answer: second")
            self.assertIsNot(agents[0].map, agents[1].map)
            self.assertNotEqual(outputs[0].parent, outputs[1].parent)
            self.assertTrue(all(not output.parent.exists() for output in outputs))
            self.assertEqual(building.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
