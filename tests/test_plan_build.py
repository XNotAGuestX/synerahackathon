import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from final_agent.plan_build import Calibration, PlanBuilder, PlanDraft, PlanError, extract_plan, validate_building
from final_agent.storage import JsonBuildingStore


def building():
    return {
        "building": {"id": "b", "name": "B", "source": "plan_import", "license": "CC0-1.0", "units": "m"},
        "floors": [{"id": "f0", "level": 0, "name": "Ground", "elevation_m": 0.0}],
        "spaces": [{"id": "s0", "floor_id": "f0", "type": "room", "room_type": "office",
                    "name": "Office", "polygon": [[0, 0], [4, 0], [4, 4], [0, 4]]}],
        "openings": [{"id": "o0", "floor_id": "f0", "space_ids": ["s0", "outside"],
                      "kind": "entrance", "position": [2, 0], "width_m": 1.0, "step_free": True}],
        "vertical_connectors": [], "assets": [],
    }


class PlanBuildTests(unittest.TestCase):
    def test_validator_reports_unhashable_ids_and_asset_references(self):
        for key in ("floors", "spaces", "openings", "vertical_connectors", "assets"):
            with self.subTest(collection=key):
                data = building()
                data[key].append({"id": []})
                self.assertTrue(any(i["severity"] == "error" for i in validate_building(data)))
        data = building()
        data["assets"] = [{"id": "a", "type": "desk", "floor_id": "f0", "space_id": [], "position": [1, 1]}]
        self.assertTrue(any("known floor and room" in i["reason"] for i in validate_building(data)))

    def test_pixel_calibration_converts_scale_and_image_y_axis(self):
        cal = Calibration.from_known_distance((10, 10), (110, 10), 5, origin_m=(2, 3))
        self.assertEqual(cal.transform([110, 110]), [7.0, -2.0])
        self.assertEqual(cal.as_dict()["pixel_to_metre"]["scale_m_per_px"], 0.05)

    def test_validator_rejects_duplicate_ids_and_cross_floor_opening(self):
        data = building()
        data["floors"].append({"id": "f1", "level": 1, "name": "Up", "elevation_m": 3.2})
        data["spaces"].append({"id": "s1", "floor_id": "f1", "polygon": [[0,0],[2,0],[2,2],[0,2]]})
        data["spaces"].append(dict(data["spaces"][0]))
        data["openings"].append({"id": "o1", "floor_id": "f0", "space_ids": ["s0", "s1"],
                                 "position": [2, 0], "width_m": 1})
        reasons = [i["reason"] for i in validate_building(data)]
        self.assertTrue(any("Duplicate space ID" in x for x in reasons))
        self.assertTrue(any("across floors" in x for x in reasons))

    def test_correct_cancel_apply_undo_and_stale_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "building.json"
            original = building()
            JsonBuildingStore.save(path, original)
            draft = PlanDraft(original, path, base_revision=0, current_revision=0)
            draft.correct([{"kind":"set", "element_type":"space", "id":"s0", "field":"name", "value":"Studio"}])
            self.assertEqual(JsonBuildingStore.load(path)["spaces"][0]["name"], "Office")
            with self.assertRaises(PlanError): draft.apply(expected_revision=1)
            draft.cancel()
            self.assertEqual(JsonBuildingStore.load(path)["spaces"][0]["name"], "Office")

            draft = PlanDraft(original, path)
            draft.correct([{"kind":"set", "element_type":"space", "id":"s0", "field":"name", "value":"Studio"}])
            draft.apply()
            self.assertEqual(JsonBuildingStore.load(path)["spaces"][0]["name"], "Studio")
            draft.undo()
            self.assertEqual(JsonBuildingStore.load(path)["spaces"][0]["name"], "Office")

    def test_failed_save_keeps_saved_bytes_and_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "building.json"
            JsonBuildingStore.save(path, building())
            before = path.read_bytes()
            draft = PlanDraft(building(), path)
            draft.correct([{"kind":"set", "element_type":"space", "id":"s0", "field":"name", "value":"New"}])
            def fail(target, candidate):
                target.write_text(json.dumps(candidate))
                raise OSError("disk full")
            with self.assertRaises(PlanError): draft.apply(save_fn=fail)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(draft.current_revision, 0)

    def test_invalid_raw_records_and_unresolved_access_are_blocking(self):
        self.assertTrue(validate_building({"building": [], "floors": [None], "spaces": [None], "openings": [5] }))
        data=building()
        data["openings"][0]["width_m"]=None
        data["openings"][0]["step_free"]=None
        data["import_metadata"]={"uncertainties":[{"element_id":"o0","field":"width_m","reason":"not shown"}]}
        with tempfile.TemporaryDirectory() as tmp:
            draft=PlanDraft(data,Path(tmp)/"b.json")
            self.assertTrue(any(i["severity"]=="error" for i in draft.validate()))
            with self.assertRaises(PlanError): draft.apply(acknowledge_warnings=True)

    def test_existing_map_preserves_preexisting_errors_as_warnings(self):
        data=building()
        data["openings"][0]["step_free"]="unknown"
        with tempfile.TemporaryDirectory() as tmp:
            draft=PlanBuilder.begin_existing(data,Path(tmp)/"b.json")
            self.assertTrue(any(i["severity"]=="warning" and i.get("preexisting") for i in draft.validate()))

    def test_existing_preexisting_issue_stays_blocking_after_geometry_change(self):
        data=building(); data["openings"][0]["step_free"]="unknown"
        with tempfile.TemporaryDirectory() as tmp:
            draft=PlanBuilder.begin_existing(data,Path(tmp)/"b.json")
            draft.correct([{"kind":"set","element_type":"space","id":"s0","field":"polygon",
                            "value":[[0,0],[5,0],[5,4],[0,4]]}])
            self.assertTrue(any(i["severity"]=="error" and "step_free" in i["reason"] for i in draft.validate()))

    def test_overlapping_spaces_are_reported(self):
        data=building()
        data["spaces"].append({"id":"s1","floor_id":"f0","type":"room","room_type":"office",
                               "name":"Overlap","polygon":[[3,0],[5,0],[5,2],[3,2]]})
        self.assertTrue(any("overlap" in i["reason"] for i in validate_building(data)))

    def test_image_extraction_sends_bytes_and_records_dimensions_without_assuming_scale(self):
        from PIL import Image
        import io
        image=Image.new("RGB",(13,7),"white")
        buffer=io.BytesIO(); image.save(buffer,format="PNG")
        class Client:
            messages=None
            def __init__(self): self.messages=self
            def create(self,**kwargs):
                self.request=kwargs
                return SimpleNamespace(content=[SimpleNamespace(type="text",text='{"spaces":[],"openings":[],"assets":[],"vertical_connectors":[]}')])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"plan.png"; path.write_bytes(buffer.getvalue())
            client=Client()
            result=extract_plan(client,"fake-model",path,floor_id="f0")
        self.assertEqual(client.request["messages"][0]["content"][0]["type"],"image")
        self.assertEqual(result["_provenance"]["image_width_px"],13)
        self.assertEqual(result["_provenance"]["image_height_px"],7)
        self.assertNotIn("calibration",result)
        self.assertIsNone(result["_provenance"]["calibration"])

    def test_image_extraction_parses_only_evidenced_metric_calibration(self):
        from PIL import Image
        import io
        image=Image.new("RGB",(5,5),"white"); buffer=io.BytesIO(); image.save(buffer,format="PNG")
        class Client:
            def __init__(self): self.messages=self
            def create(self,**kwargs):
                text='{"spaces":[],"openings":[],"assets":[],"vertical_connectors":[],"calibration":{"point_a_px":[0,0],"point_b_px":[100,0],"distance_m":5,"evidence":"printed 5 m dimension"}}'
                return SimpleNamespace(content=[SimpleNamespace(type="text",text=text)])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"plan.png"; path.write_bytes(buffer.getvalue())
            result=extract_plan(Client(),"fake-model",path,floor_id="f0")
        self.assertEqual(result["calibration_transform"]["metres_per_pixel"],0.05)
        self.assertEqual(result["calibration"]["evidence"],"printed 5 m dimension")

    def test_truncated_vision_response_fails_without_parsing_partial_json(self):
        from PIL import Image
        import io
        image=Image.new("RGB",(5,5),"white"); buffer=io.BytesIO(); image.save(buffer,format="PNG")
        class Client:
            def __init__(self): self.messages=self; self.calls=0
            def create(self,**kwargs):
                self.calls+=1
                return SimpleNamespace(content=[SimpleNamespace(type="text",text='{"spaces": []')],stop_reason="max_tokens")
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"plan.png"; path.write_bytes(buffer.getvalue())
            client=Client()
            with self.assertRaisesRegex(PlanError,"16,000-token limit"):
                extract_plan(client,"fake-model",path,floor_id="f0")
        self.assertEqual(client.calls,1)

    def test_malformed_response_gets_one_text_only_syntax_repair(self):
        from PIL import Image
        import io
        image=Image.new("RGB",(5,5),"white"); buffer=io.BytesIO(); image.save(buffer,format="PNG")
        class Client:
            def __init__(self): self.messages=self; self.calls=[]
            def create(self,**kwargs):
                self.calls.append(kwargs)
                text='{"spaces": [],}' if len(self.calls)==1 else '{"spaces":[],"openings":[],"assets":[],"vertical_connectors":[]}'
                return SimpleNamespace(content=[SimpleNamespace(type="text",text=text)],stop_reason="end_turn",
                                       usage=SimpleNamespace(input_tokens=4,output_tokens=6))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"plan.png"; path.write_bytes(buffer.getvalue())
            client=Client(); result=extract_plan(client,"fake-model",path,floor_id="f0")
        self.assertEqual(len(client.calls),2)
        self.assertEqual(client.calls[0]["max_tokens"],16000)
        self.assertEqual(result["_provenance"]["usage"],{"input_tokens":8,"output_tokens":12})
        self.assertIn("malformed response",client.calls[1]["messages"][0]["content"][0]["text"].lower())
        self.assertEqual(len(client.calls[1]["messages"][0]["content"]),1)


if __name__ == "__main__":
    unittest.main()
