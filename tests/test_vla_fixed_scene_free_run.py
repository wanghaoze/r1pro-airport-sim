"""Standalone unittest checks; no simulator, GPU or remote model required."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location("fixed_scene_diag", Path(__file__).parents[1] / "scripts/run_vla_fixed_scene.py")
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


class FixedSceneFreeRunTests(unittest.TestCase):
    def test_training_render_keeps_camera_names_and_pads_to224_without_native_render(self):
        calls = []
        def render(sim, camera, maximum):
            calls.append((camera, maximum))
            # Exact aspect ratios of head and wrist remain at low render size.
            return np.ones((176, 220, 3) if camera.startswith("head") else (126, 224, 3), np.uint8)
        def pad(image, height, width):
            output = np.zeros((height, width, 3), np.uint8)
            y, x = (height-image.shape[0])//2, (width-image.shape[1])//2
            output[y:y+image.shape[0], x:x+image.shape[1]] = image
            return output
        images = diag.training_images(object(), render_fn=render, pad_fn=pad)
        self.assertEqual(calls, [(camera, 224) for camera in diag.CAMERAS])
        for image in images.values():
            self.assertEqual(image.shape, (224, 224, 3))
            self.assertEqual(image.dtype, np.uint8)
            self.assertFalse(image[0].any())
            self.assertTrue(image[112].any())

    def test_stage_restore_selects_pre_action_frame_and_preserves_three_prompts(self):
        result = {"action_spans": [dict(action_label=label, start_frame=a, end_frame=b, verified=True)
                  for label, a, b in (("pick_empty", 0, 224), ("place_empty", 224, 611), ("push_loaded", 651, 1379))]}
        self.assertEqual([diag.initial_frame(result, k, 1379) for k in diag.PROMPTS], [0, 224, 651])
        self.assertEqual([v[0] for v in diag.PROMPTS.values()],
                         ["Pick up the tray", "Place the tray", "Flush tray to the left"])
        result["action_spans"][1]["verified"] = False
        with self.assertRaises(ValueError):
            diag.initial_frame(result, "place", 1379)

    def test_five_minutes_is_6000_intervals_and_fractional_frame_is_rejected(self):
        self.assertEqual(diag.frame_budget(300), 6000)
        for value in (0, -1, float("nan"), float("inf"), .001):
            with self.assertRaises(ValueError):
                diag.frame_budget(value)

    def runtime(self, fail_at=None):
        data = SimpleNamespace(qpos=np.zeros(19), qvel=np.zeros(19), ctrl=np.zeros(19),
                               qacc_warmstart=np.zeros(19), act=np.zeros(0), time=0.)
        sim = SimpleNamespace(nstep=25, target=np.zeros(16), base_target=np.zeros(3))
        sim.state = lambda: data.qpos[:16].astype(np.float32)
        sim.base_joint_state = lambda: data.qpos[16:].copy()
        sim.base_state = lambda: data.qpos[16:].copy()
        def apply():
            data.ctrl[:16] = sim.target
            data.ctrl[[7, 15]] /= 2
            data.ctrl[16:] = sim.base_target
        sim.apply_target = apply
        counter = [0]
        def step(model, state):
            counter[0] += 1
            state.time += .002
            if fail_at == counter[0]:
                state.qpos[0] = float("nan")
        mj = SimpleNamespace(mj_getState=lambda m, d, out, spec: out.fill(d.time),
                             mj_step=step, mj_forward=lambda m, d: None)
        def forbidden_guard():
            raise AssertionError("Task guard must never execute in free-run")
        runtime = SimpleNamespace(m=SimpleNamespace(nu=19), d=data, sim=sim, mj=mj,
                                  integration_size=2, integration_spec=0, cfg=SimpleNamespace(fps=20),
                                  steps=0, guard=forbidden_guard,
                                  observation=lambda: {"table_contact": np.zeros(1), "illegal_collision": np.int32(7)})
        return runtime, counter

    def test_raw_targets_not_clipped_base_origin_not_replaced_and_guards_not_called(self):
        runtime, count = self.runtime()
        action = np.arange(19, dtype=np.float32) + 100  # deliberately outside nominal target bounds
        action[[7, 15]] = [.13, -.02]
        origin = np.array([.7, -.4, .1])
        row, error = diag.advance_interval(runtime, action, origin, 0)
        self.assertIsNone(error)
        np.testing.assert_array_equal(row["raw_model_action"], action)
        np.testing.assert_array_equal(runtime.sim.target, action[:16])
        np.testing.assert_array_equal(runtime.sim.base_target, action[16:] + origin)
        self.assertEqual(count[0], 25)
        self.assertEqual(row["executed_substeps"], 25)
        self.assertTrue(row["transition_completed"])
        self.assertEqual(row["illegal_collision"], 7)  # observed without termination
        self.assertAlmostEqual(runtime.d.time, .05)
        np.testing.assert_allclose(row["state19"][16:], -origin)

    def test_numeric_failure_retains_real_substep_prefix_without_padding(self):
        runtime, count = self.runtime(fail_at=4)
        row, error = diag.advance_interval(runtime, np.zeros(19), np.zeros(3), 0)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(count[0], 4)
        self.assertEqual(row["executed_substeps"], 4)
        self.assertFalse(row["transition_completed"])
        self.assertEqual(runtime.steps, 0)

    def test_invalid_model_action_never_reaches_physics(self):
        runtime, count = self.runtime()
        action = np.zeros(19)
        action[0] = float("nan")
        with self.assertRaises(ValueError):
            diag.advance_interval(runtime, action, np.zeros(3), 0)
        self.assertEqual(count[0], 0)


if __name__ == "__main__":
    unittest.main()
