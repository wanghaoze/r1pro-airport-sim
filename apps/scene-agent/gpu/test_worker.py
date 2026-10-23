import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bridge', Path(__file__).with_name('worker.py'))
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        seed_path=Path(__file__).parents[1] / 'lib/initial-snapshot.json'
        if not seed_path.exists():seed_path=Path(__file__).with_name('initial-snapshot.json')
        seed = json.loads(seed_path.read_text())
        self.payload = {'profile': 'isaac32_fixed_base_pickplace', 'revision': 1, 'rooms': seed['rooms']}
        self.base = self.root / 'base.json'
        bridge.write(self.base, {'rooms': 32, 'cases': [{'split': 'train', 'seed': i, 'preflight': True, 'task_gate': 123} for i in range(32)]})

    def test_scene_config_preserves_gates_and_invalidates_preflight(self):
        out = self.root / 'job'
        with patch.object(bridge, 'BASE_CONFIG', self.base):
            result = bridge.scene_sync(self.payload, out)
        config = bridge.read(out / 'native_config.draft.json')
        self.assertEqual(result['status'], 'draft_synced')
        self.assertFalse(result['simulationStarted'])
        for case in config['cases']:
            self.assertEqual(case['task_gate'], 123)
            self.assertEqual(case['split'], 'train')
            self.assertNotIn('preflight', case)
            self.assertEqual(case['initial_base_world'], case['fixed_base_world'])
            self.assertAlmostEqual(sum(v*v for v in case['tray_pose'][3:]), 1)
        self.assertTrue(bridge.read(self.base)['cases'][0]['preflight'])

    def test_receipt_replay_does_not_execute_twice(self):
        job = {'id': 'smoke_12345678', 'kind': 'scene.sync', 'payload': self.payload}
        with patch.object(bridge, 'BASE_CONFIG', self.base):
            first = bridge.execute_job(job, self.root)
        with patch.object(bridge, 'scene_sync', side_effect=AssertionError('must not repeat')):
            self.assertEqual(first, bridge.execute_job(job, self.root))
        job['payload']['revision'] = 2
        with self.assertRaisesRegex(ValueError, 'request_id_conflict'):
            bridge.execute_job(job, self.root)

    def test_invalid_paths_and_nonfinite_pose_rejected(self):
        with self.assertRaisesRegex(ValueError, 'invalid_request_id'):
            bridge.execute_job({'id': '../../escape'}, self.root)
        self.payload['rooms'][0]['tray_pose'][0] = float('inf')
        with self.assertRaisesRegex(ValueError, 'invalid_finite_vector'):
            bridge.validate_rooms(self.payload['rooms'])

    def test_missing_supervisor_blocks_without_launch(self):
        with patch.object(bridge, 'TRAINING', self.root / 'absent'), patch.object(bridge, 'identity', return_value=None):
            result = bridge.training_attach({'datasets': list(bridge.ALLOWED_DATASETS), 'recipe': 'real50_isaac300_duration_bc'}, self.root / 'observation')
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse(result['newProcessStarted'])


if __name__ == '__main__':
    unittest.main()
