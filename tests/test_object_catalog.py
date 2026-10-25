import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from final_agent.object_catalog import CATALOG_PATH, object_height, read_catalog, register_asset_types
from final_agent.plan_build import PlanDraft, PlanError
from scripts.build_object_models import glb_stats
from tests.test_plan_build import building


ROOT = Path(__file__).resolve().parents[1]


class ObjectCatalogTests(unittest.TestCase):
    def test_every_dataset_type_has_a_reasoned_height_and_bounded_local_glb(self):
        catalog = read_catalog()
        types = {asset['type'] for path in (ROOT / 'data').glob('*/*/building.json')
                 for asset in json.loads(path.read_text())['assets']}
        self.assertTrue(types <= catalog['objects'].keys())
        for object_type in types:
            with self.subTest(object_type=object_type):
                entry = catalog['objects'][object_type]
                self.assertGreater(entry['height_m'], 0)
                self.assertGreater(len(entry['height_reason']), 20)
                self.assertNotEqual(entry['model_kind'], 'placeholder')
                stats = glb_stats(ROOT / 'frontend/public' / entry['model_path'].lstrip('/'))
                self.assertLessEqual(stats['triangles'], 2000)
        glb_stats(ROOT / 'frontend/public/models/objects/unknown.glb')

    def test_unknown_registration_is_persistent_idempotent_and_keeps_curated_heights(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            path.write_bytes(CATALOG_PATH.read_bytes())
            assets = [{'type': ' Inspection-Table ', 'category': 'equipment'},
                      {'type': 'portable_sensor', 'category': 'equipment'},
                      {'type': 'custom_sensor', 'category': 'equipment', 'height_m': .27},
                      {'type': 'desk', 'category': 'furniture', 'height_m': 10}]
            self.assertEqual(register_asset_types(assets, path), ['inspection_table', 'portable_sensor', 'custom_sensor'])
            catalog = read_catalog(path)
            self.assertEqual(catalog['objects']['inspection_table']['height_m'], .75)
            self.assertEqual(catalog['objects']['portable_sensor']['height_m'], 1)
            self.assertEqual(catalog['objects']['custom_sensor']['height_m'], .27)
            self.assertEqual(catalog['objects']['desk']['height_m'], .74)
            self.assertEqual(catalog['objects']['inspection_table']['model_path'], '/models/objects/unknown.glb')
            before = path.read_bytes()
            self.assertEqual(register_asset_types(assets, path), [])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(object_height(assets[-1], catalog), 10)
            self.assertEqual(object_height({'type': 'new_machine', 'category': 'machine', 'height_m': float('nan')}, catalog), 1.8)

    def test_only_successful_applies_register_and_catalog_failure_rolls_back_the_building(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'building.json'
            original = building()
            path.write_text(json.dumps(original))
            draft_data = copy.deepcopy(original)
            draft_data['assets'].append({'id': 'sensor', 'type': 'new_sensor', 'category': 'equipment',
                                         'space_id': 's0', 'floor_id': 'f0', 'position': [2, 2]})
            draft = PlanDraft(draft_data, path, base_data=original)
            with patch('final_agent.object_catalog.register_asset_types') as register:
                draft.preview()
                register.assert_not_called()
                draft.apply()
                register.assert_called_once_with(draft_data['assets'])
            before = path.read_bytes()
            draft = PlanDraft(original, path)
            with patch('final_agent.object_catalog.register_asset_types', side_effect=OSError('catalog read-only')):
                with self.assertRaisesRegex(PlanError, 'catalog read-only'):
                    draft.apply()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(draft.current_revision, 0)


if __name__ == '__main__':
    unittest.main()
