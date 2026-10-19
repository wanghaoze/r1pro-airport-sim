"""One prompt, one fixed scene, timed pure-VLA simulation and native videos.

Task guards/completion callbacks are never called. Physics and XML actuator
limits remain active. A recorded stage state is restored exactly once before
inference; no teacher motion, IK, online reset or hidden fallback is executed.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = Path(os.environ.get("VLA_CODE_ROOT", str(ROOT))).resolve()
sys.path.insert(0, str(CODE_ROOT))
PROMPTS = {
    "pick": ("Pick up the tray", "pick_empty"),
    "place": ("Place the tray", "place_empty"),
    "push": ("Flush tray to the left", "push_loaded"),
}
CAMERAS = ("head_left", "head_right", "left_wrist", "right_wrist")


def training_images(sim, *, render_fn=None, pad_fn=None):
    """Same camera/FOV, aspect-preserving small render and training padding."""
    if render_fn is None:
        from r1pro_teleop.vla.observations import render_model_observation
        render_fn = render_model_observation
    if pad_fn is None:
        from openpi_client.image_tools import resize_with_pad
        pad_fn = resize_with_pad
    images = {}
    for camera in CAMERAS:
        rgb = render_fn(sim, camera, 224)
        image = pad_fn(rgb, 224, 224)
        if image.shape != (224, 224, 3) or image.dtype != np.uint8:
            raise ValueError("fixed_scene_training_resolution_rgb_required")
        images[camera] = image
    return images


class DiagnosticVideoWriter:
    """One-second fragmented H.264 MP4, including usable completed fragments."""
    def __init__(self, path, shape):
        import av
        self.av = av
        self.closed = False
        self.container = av.open(str(path), "w", options={
            "movflags": "frag_keyframe+empty_moov+default_base_moof", "flush_packets": "1"})
        self.stream = self.container.add_stream("libx264", rate=20)
        self.stream.width, self.stream.height = shape[1], shape[0]
        self.stream.pix_fmt = "yuv420p"
        self.stream.options = {"crf": "18", "preset": "fast", "threads": "1", "g": "20", "bf": "0"}

    def write(self, image):
        for packet in self.stream.encode(self.av.VideoFrame.from_ndarray(image, format="rgb24")):
            self.container.mux(packet)

    def close(self):
        if self.closed:
            return
        for packet in self.stream.encode():
            self.container.mux(packet)
        self.container.close()
        self.closed = True


def file_sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def initial_frame(result, command, frame_count):
    label = PROMPTS[command][1]
    spans = [s for s in result.get("action_spans", []) if s.get("action_label") == label]
    if len(spans) != 1 or spans[0].get("verified") is not True:
        raise ValueError("fixed_scene_verified_initial_action_span_required")
    start, end = spans[0].get("start_frame"), spans[0].get("end_frame")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= frame_count:
        raise ValueError("fixed_scene_initial_frame_out_of_range")
    return start


def frame_budget(seconds, fps=20):
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("fixed_scene_positive_duration_required")
    frames = round(seconds * fps)
    if frames < 1 or not math.isclose(frames / fps, seconds, abs_tol=1e-9):
        raise ValueError("fixed_scene_duration_must_be_integer_frames")
    return frames


def advance_interval(runtime, action, base_origin, index):
    """Submit raw mobile19 references without task guards or extra clipping."""
    r = runtime
    action = np.asarray(action, dtype=np.float32)
    if action.shape != (19,) or not np.isfinite(action).all():
        raise ValueError("fixed_scene_invalid_model_action")
    origin = np.asarray(base_origin, dtype=float)
    r.sim.target = action[:16].copy()
    r.sim.base_target = origin + action[16:]
    r.sim.apply_target()
    integration = np.empty(r.integration_size, dtype=np.float64)
    r.mj.mj_getState(r.m, r.d, integration, r.integration_spec)
    measured = np.r_[r.sim.state(), r.sim.base_joint_state() - origin].astype(np.float32)
    row = dict(
        timestamp=np.float64(index / r.cfg.fps), sim_time=np.float64(r.d.time),
        integration_state=integration, qpos=r.d.qpos.copy(), qvel=r.d.qvel.copy(),
        qacc_warmstart=r.d.qacc_warmstart.copy(), act=r.d.act.copy(),
        ctrl=r.d.ctrl.copy(), state=measured[:16], state19=measured,
        action=action[:16].copy(), action19=action.copy(), raw_model_action=action.copy(),
        base_action=r.sim.base_target.copy(), base_state=r.sim.base_state(),
        ctrl_substeps=np.zeros((r.sim.nstep, r.m.nu), dtype=np.float64),
        executed_substeps=np.int32(0), transition_completed=np.bool_(False),
        **r.observation(),
    )
    before = float(r.d.time)
    try:
        for substep in range(r.sim.nstep):
            row["ctrl_substeps"][substep] = r.d.ctrl
            r.mj.mj_step(r.m, r.d)
            row["executed_substeps"] = np.int32(substep + 1)
            r.mj.mj_forward(r.m, r.d)
            if not np.isfinite(r.d.qpos).all() or not np.isfinite(r.d.qvel).all():
                raise RuntimeError("fixed_scene_nonfinite_physics")
        if not math.isclose(float(r.d.time) - before, 1 / r.cfg.fps, abs_tol=1e-9):
            raise RuntimeError("fixed_scene_physics_time_reset_or_drift")
        row["transition_completed"] = np.bool_(True)
        r.steps += 1
    except Exception as error:
        return row, error
    return row, None


def restore_stage(runtime, trace_path, frame):
    """Restore a recorded integration state once, retaining original base origin."""
    import h5py

    r = runtime
    with h5py.File(trace_path, "r") as source:
        metadata = json.loads(source.attrs["metadata_json"])
        if int(metadata["integration_state_spec"]) != int(r.integration_spec):
            raise ValueError("fixed_scene_integration_state_spec_mismatch")
        parameters = metadata.get("source_model_parameters", {})
        for key, values in parameters.get("unchanged_xml_parameter_arrays", {}).items():
            if not np.array_equal(getattr(r.m, key), np.asarray(values)):
                raise ValueError("fixed_scene_recorded_model_parameter_mismatch:" + key)
        for key in ("actuator_forcerange", "actuator_forcelimited"):
            if key in parameters:
                array = np.asarray(parameters[key], dtype=getattr(r.m, key).dtype)
                if array.shape != getattr(r.m, key).shape:
                    raise ValueError("fixed_scene_recorded_force_limit_shape_mismatch")
                getattr(r.m, key)[:] = array
        state = np.asarray(source["integration_state"][frame])
        if state.shape != (r.integration_size,) or not np.isfinite(state).all():
            raise ValueError("fixed_scene_invalid_initial_integration_state")
        # State/actions use the source episode origin, never the Place/Push start.
        base_columns = r.base_qids
        origin = np.asarray(source["qpos"][0])[base_columns].copy()
        r.mj.mj_setState(r.m, r.d, state, r.integration_spec)
        r.mj.mj_forward(r.m, r.d)
        if not np.allclose(r.d.qpos, source["qpos"][frame], rtol=0, atol=1e-10):
            raise ValueError("fixed_scene_initial_qpos_restore_mismatch")
        if not np.allclose(r.d.qvel, source["qvel"][frame], rtol=0, atol=1e-10):
            raise ValueError("fixed_scene_initial_qvel_restore_mismatch")
        r.sim.target = np.asarray(source["action"][frame], dtype=np.float32).copy()
        r.sim.base_target = np.asarray(source["base_action"][frame]).copy()
        return origin, metadata, state


def run(args):
    import h5py
    from openpi_client.websocket_client_policy import WebsocketClientPolicy
    from r1pro_teleop.airport_fsm.contracts import Config, atomic_json
    from r1pro_teleop.airport_fsm.trace import Trace
    from r1pro_teleop.single_tray_3table.control import ThreeTableRuntime
    from r1pro_teleop.single_tray_3table.learned import ThreeTablePolicy
    from r1pro_teleop.vla.policy import PolicyContract
    from r1pro_teleop.vla.data_three_table_single_tray import PROFILE

    budget = frame_budget(args.seconds)
    case = Path(args.source_case).resolve()
    source_trace = case / "attempt/trace.h5"
    source_result = case / "result.json"
    scene_path = case / "scene/scene.json"
    result = json.loads(source_result.read_text())
    scene = json.loads(scene_path.read_text())
    if result.get("task_completed") is not True or result.get("physics_success") is not True:
        raise ValueError("fixed_scene_complete_initial_source_required")
    with h5py.File(source_trace, "r") as f:
        frame = initial_frame(result, args.command, int(f.attrs["num_frames"]))
    if file_sha(scene["xml"]) != scene["xml_sha256"]:
        raise ValueError("fixed_scene_xml_identity_mismatch")
    identity = json.loads(Path(args.identity_file).read_text())
    client = WebsocketClientPolicy(host=args.host, port=args.port)
    server = client.get_server_metadata()
    contract = PolicyContract(identity["checkpoint_id"], action_horizon=int(server["action_horizon"]),
                              action_width=19, prompt_mode=PROFILE)
    if not 1 <= args.execute_steps <= contract.action_horizon:
        raise ValueError("fixed_scene_execute_steps_outside_model_horizon")
    policy = ThreeTablePolicy.from_client(client, contract)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "videos").mkdir()
    atomic_json(output / "scene.json", scene)
    source_hashes = {str(p): file_sha(p) for p in (source_trace, source_result, scene_path)}
    report = dict(schema="airport_fixed_scene_vla_free_run/1", diagnostic_only=True,
                  task_completed=None, training_eligible=False, controller_source="vla_generated",
                  source="simulation/program_generated", command=args.command, prompt=PROMPTS[args.command][0],
                  code_root=str(CODE_ROOT), diagnostic_script_sha256=file_sha(__file__),
                  requested_sim_seconds=args.seconds, requested_frames=budget, frames=0,
                  initial_restore_count=0, online_state_resets=0, checkpoint_id=contract.checkpoint_id,
                  server_metadata=server, checkpoint_path=identity.get("checkpoint_path"),
                  initial_source=str(case), initial_source_frame=frame, initial_source_hashes=source_hashes,
                  initial_state_origin="program_generated_teacher_snapshot_not_online_teacher_execution",
                  task_guards_enabled=False, completion_guards_enabled=False,
                  image_mode="native" if args.native_images else "training224_aspect_preserving_pad",
                  model_rgb_size=None if args.native_images else [224, 224],
                  camera_geometry_unchanged=True, mp4_fragmented=True,
                  dynamics_and_xml_actuator_limits_preserved=True, teacher_fallback_calls=0,
                  inverse_solver_calls=0, actual_inference_calls=0, status="starting")
    atomic_json(output / "status.json", report)
    r = trace = None
    writers = {}
    start = time.monotonic()
    timing = dict(render_seconds=0., inference_seconds=0., encode_seconds=0., physics_record_seconds=0.)
    report["timing"] = timing
    try:
        r = ThreeTableRuntime(scene, Config.load(args.config), render=True)
        if r.cfg.fps != 20:
            raise ValueError("fixed_scene_requires_20hz_source_config")
        origin, metadata, integration = restore_stage(r, source_trace, frame)
        report["initial_restore_count"] = 1
        np.savez_compressed(output / "initial_state.npz", integration_state=integration,
                            base_origin=origin, source_frame=np.int64(frame))
        trace = Trace(output / "attempt", dict(config=r.cfg.dump(), scene=scene,
                      source="simulation/program_generated", controller_source="vla_generated",
                      checkpoint_id=contract.checkpoint_id, diagnostic_only=True,
                      integration_state_spec=int(r.integration_spec), base_origin=origin.tolist(),
                      fps=20, source_model_parameters=metadata.get("source_model_parameters")))
        trace.file.attrs["schema"] = "airport_fixed_scene_vla_raw/1"
        trace.file.attrs["image_storage"] = "Live PRE-action RGB, videos/<camera>.mp4; resolution in result.json"
        for camera in CAMERAS:
            shape = r.sim.camera_shapes[camera] if args.native_images else (224, 224, 3)
            writers[camera] = DiagnosticVideoWriter(output / "videos" / (camera + ".mp4"), shape)
        chunk, cursor = None, 0
        for index in range(budget):
            measured_at = time.monotonic()
            images = ({camera: r.sim.image(camera) for camera in CAMERAS} if args.native_images else training_images(r.sim))
            timing["render_seconds"] += time.monotonic() - measured_at
            if chunk is None or cursor >= min(args.execute_steps, len(chunk)):
                state = np.r_[r.sim.state(), r.sim.base_joint_state() - origin].astype(np.float32)
                measured_at = time.monotonic()
                chunk = policy.infer(images, state, report["prompt"])
                timing["inference_seconds"] += time.monotonic() - measured_at
                np.savez_compressed(output / f"decision_{report['actual_inference_calls']:06d}.npz",
                                    state=state, raw_actions=chunk, frame=np.int64(index))
                report["actual_inference_calls"] += 1
                cursor = 0
            measured_at = time.monotonic()
            for camera, writer in writers.items():
                writer.write(images[camera])
            timing["encode_seconds"] += time.monotonic() - measured_at
            measured_at = time.monotonic()
            row, error = advance_interval(r, chunk[cursor], origin, index)
            trace.append(row)
            timing["physics_record_seconds"] += time.monotonic() - measured_at
            cursor += 1
            report["frames"] = trace.count
            report["completed_intervals"] = r.steps
            report["sim_seconds_executed"] = r.steps / r.cfg.fps
            if index % 20 == 0:
                atomic_json(output / "status.json", dict(report, status="running",
                            heartbeat_unix=time.time(), wall_seconds=time.monotonic() - start))
            if error is not None:
                raise error
        report["status"] = "timed_free_run_complete"
    except KeyboardInterrupt:
        report.update(status="interrupted_preserving_actual_prefix", error="KeyboardInterrupt")
    except Exception as error:
        report.update(status="failed_preserving_actual_prefix", error=repr(error))
        (output / "exception.txt").write_text(traceback.format_exc())
    finally:
        for camera, writer in writers.items():
            try:
                writer.close()
            except Exception as error:
                report.setdefault("video_close_errors", {})[camera] = repr(error)
        if trace is not None:
            trace.close(dict(qpos=r.d.qpos, qvel=r.d.qvel, time=float(r.d.time)))
        if r is not None:
            report["inverse_solver_calls"] = int(r.id_calls)
            r.sim.close()
        report["wall_seconds"] = time.monotonic() - start
        report["source_files_unchanged"] = all(file_sha(p) == digest for p, digest in source_hashes.items())
        if report["inverse_solver_calls"] or not report["source_files_unchanged"] or report.get("video_close_errors"):
            report["status"] = "failed_preserving_actual_prefix"
        videos = [{"camera": c, "path": str((output / "videos" / (c + ".mp4")).resolve()),
                   "sha256": file_sha(output / "videos" / (c + ".mp4"))}
                  for c in writers if (output / "videos" / (c + ".mp4")).is_file()]
        report["videos"] = videos
        atomic_json(output / "result.json", report)
        atomic_json(output / "status.json", report)
        (output / "VIDEO_PATHS.txt").write_text("".join(v["path"] + "\n" for v in videos))
        cards = "".join(f'<p>{c}</p><video controls preload="metadata" width="480" src="videos/{c}.mp4"></video>'
                        for c in writers)
        (output / "viewer.html").write_text('<!doctype html><meta charset="utf-8"><h1>VLA free-run diagnostic</h1><p>'
            + html.escape(report["prompt"]) + '</p><p>Task guards disabled; not a success-rate evaluation.</p>' + cards)
        print(json.dumps(report), flush=True)
    return 0 if report["status"] == "timed_free_run_complete" else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-case", required=True, help="Complete observed_source with raw stage snapshots")
    parser.add_argument("--config", required=True)
    parser.add_argument("--identity-file", required=True, help="JSON from serve_pi05_airport.py --identity-only")
    parser.add_argument("--command", required=True, choices=tuple(PROMPTS))
    parser.add_argument("--output", required=True, help="Fresh output directory; existing paths are rejected")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8027)
    parser.add_argument("--seconds", type=float, default=300)
    parser.add_argument("--execute-steps", type=int, default=5)
    parser.add_argument("--native-images", action="store_true", help="Explicit original-resolution diagnostic; default input/video 224x224")
    args = parser.parse_args(argv)
    frame_budget(args.seconds)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
