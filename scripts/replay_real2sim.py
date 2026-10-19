"""Replay original real Pick/Place in a separate full-joint model; simulation only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.real2sim import replay, r1pro_map
from r1pro_teleop.real2sim.trajectory import from_record, sha256, write_json
from r1pro_teleop.real2sim.backends import MujocoBackend
from r1pro_teleop.real2sim.model import build_model
from r1pro_teleop.real2sim.registration import estimate_registration, validate_registration
from r1pro_teleop.real2sim.mujoco_registration import recorded_pad_centres, apply_initial_registration, contact_diagnostics


class Video:
    def __init__(self, path, fps, size):
        self.path = path
        w, h = size
        self.process = subprocess.Popen(["ffmpeg", "-v", "error", "-n", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0",
            "-an", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
        self.frames = 0

    def append(self, rgb):
        self.process.stdin.write(np.ascontiguousarray(rgb).tobytes()); self.frames += 1

    def close(self):
        self.process.stdin.close()
        code = self.process.wait(timeout=60)
        if code:
            raise RuntimeError(f"real2sim_ffmpeg_exit_{code}")
        return dict(path=str(self.path), frames=self.frames, sha256=sha256(self.path))


def execute(args, out):
    import h5py
    import mujoco
    manifest = json.loads(Path(args.source_manifest).read_text())
    chosen = []
    for prompt in ("Pick up the tray", "Place the tray"):
        chosen.extend([e for e in manifest["episodes"] if e["prompt"] == prompt][:args.per_task])
    if len(chosen) != 2 * args.per_task:
        raise ValueError("real2sim_insufficient_pick_place_sources")
    write_json(out / "selection.json", dict(records=chosen, manifest_sha256=sha256(args.source_manifest),
               selection="first_N_per_prompt_in_frozen_manifest_order_not_success_selected"))
    model_path = out / "model.xml"
    build_model(args.scene_xml, args.urdf, model_path, torso_kp=args.torso_kp, torso_kv=args.torso_kv,
                finger_collision_bundle=args.finger_collision_bundle,tray_width_scale=args.tray_width_scale)
    mapping = r1pro_map()
    results = []
    for number, record in enumerate(chosen):
        case = out / f"case_{number:03d}"; case.mkdir()
        trajectory = from_record(record); trajectory.save(case / "source")
        backend = MujocoBackend(model_path, mapping)
        case_model = model_path
        if args.registration:
            if args.registration == 'estimate':
                registration = estimate_registration(trajectory, recorded_pad_centres(backend.model, trajectory, mapping))
            else:
                registration = validate_registration(json.loads((Path(args.registration)/f'case_{number:03d}.json').read_text()))
            if registration['source_parquet_sha256'] != trajectory.provenance['parquet_sha256']:
                raise ValueError('real2sim_registration_source_mismatch')
            write_json(case/'registration.json', registration)
            apply_initial_registration(backend.model, registration)
            xml = ET.parse(model_path)
            xml.find("./keyframe/key[@name='real2sim_home']").set('qpos', ' '.join(format(v, '.17g') for v in backend.model.key('real2sim_home').qpos))
            case_model = case/'registered_model.xml'; xml.write(case_model, encoding='utf-8', xml_declaration=True)
            backend = MujocoBackend(case_model, mapping)
        audit = backend.limit_audit(trajectory)
        write_json(case / "limits.json", audit)
        result = dict(prompt=record["prompt"], source_episode=record["episode_index"],
                      source_dataset=record["dataset"], source_frames=len(trajectory.timestamps),
                      task_success=None, scene_registration_verified=False,
                      scope="real_command_dynamic_replay_diagnostic_not_task_success",
                      initial_velocity_policy="zero_velocity_once_at_recorded_first_joint_position",
                      feedback_limit_violations=sum(e["feedback"]["outside_count"] for e in audit),
                      command_limit_violations=sum(e["command"]["outside_count"] for e in audit))
        result['registration'] = 'estimated_not_measured' if args.registration else 'absent'
        writers, renderers, contacts = {}, {}, []
        with h5py.File(case / "physics.h5", "x") as trace:
            trace.attrs["source_domain"] = "real_world/user_provided"
            trace.attrs["execution_domain"] = "simulation/real_command_replay"
            trace.attrs["model_sha256"] = sha256(case_model)
            trace.attrs["alignment"] = "PRE-step qpos/qvel/ctrl; each row one physics interval"
            datasets = {}
            try:
                if args.video:
                    (case / "videos").mkdir()
                    for c in ("head_left", "head_right", "left_wrist", "right_wrist"):
                        # Retain camera extrinsics/FOV; previews are explicitly resized.
                        if mujoco.mj_name2id(backend.model, mujoco.mjtObj.mjOBJ_CAMERA, c) < 0:
                            raise ValueError("real2sim_required_camera_missing")
                        renderers[c] = mujoco.Renderer(backend.model, height=360, width=640)
                        writers[c] = Video(case / "videos" / f"{c}.mp4", 30, (640, 360))
                def sample(index, stamp, positions):
                    d = backend.data
                    contacts.append(dict(frame=index, time=stamp, contacts=backend.contacts(),
                                         **contact_diagnostics(backend)))
                    for c, renderer in renderers.items():
                        option = mujoco.MjvOption(); option.geomgroup[3:] = 0
                        renderer.update_scene(d, camera=c, scene_option=option)
                        writers[c].append(renderer.render())
                def step(tick, source_index, target):
                    d = backend.data
                    values = dict(time=np.float64(d.time), source_index=np.int64(source_index),
                                  qpos=d.qpos.copy(), qvel=d.qvel.copy(), ctrl=d.ctrl.copy(),
                                  qacc_warmstart=d.qacc_warmstart.copy(), act=d.act.copy(),
                                  target=target, max_penetration_m=np.float64(max([0.] + [-c.dist for c in d.contact])))
                    for name, value in values.items():
                        value = np.asarray(value)
                        if value.size == 0:
                            continue
                        if name not in datasets:
                            datasets[name] = trace.create_dataset(name, shape=(0,) + value.shape,
                                maxshape=(None,) + value.shape, dtype=value.dtype, chunks=True)
                        ds = datasets[name]; ds.resize(tick + 1, axis=0); ds[tick] = value
                    if tick % 500 == 0:
                        trace.flush()
                        write_json(out / "status.json", dict(stage="replaying", case=number,
                            total=len(chosen), physics_steps=tick, source_frame=source_index,
                            heartbeat_unix=time.time(), pid=os.getpid()))
                report = replay(trajectory, mapping, backend, on_sample=sample, on_step=step)
                contact_evidence = dict(initial=contacts[0], final=contacts[-1],
                    peak_tray_bottom_z_m=max(c['tray_xyz'][2] for c in contacts),
                    min_tray_bottom_z_m=min(c['tray_xyz'][2] for c in contacts),
                    peak_left_finger_tray_force_n=max(c['left_tray_n'] for c in contacts),
                    peak_right_finger_tray_force_n=max(c['right_tray_n'] for c in contacts),
                    sampled_bilateral_contact_frames=sum(c['left_tray_n']>0 and c['right_tray_n']>0 for c in contacts),
                    sampled_frames=len(contacts), task_success=None,
                    note='raw force and pose evidence; contact alone does not prove opposed grasp or successful Place')
                # Full initial/final contact lists stay in contacts.json.
                for key in ('initial','final'):
                    contact_evidence[key] = {k:v for k,v in contact_evidence[key].items() if k != 'contacts'}
                write_json(case/'contact_diagnostics.json', contact_evidence)
                result['contact_diagnostics'] = contact_evidence
                arrays = {k: report.pop(k) for k in ("actual", "feedback_at_actual_time", "actual_times", "source_times", "source_command_indices")}
                np.savez_compressed(case / "comparison.npz", **arrays)
                result.update(report)
                trace.create_dataset("terminal_qpos", data=backend.data.qpos)
                trace.create_dataset("terminal_qvel", data=backend.data.qvel)
                trace.attrs["terminal_time"] = backend.data.time
            except Exception as error:
                result.update(replay_completed=False, error=repr(error))
                (case / "exception.txt").write_text(traceback.format_exc())
            finally:
                result["videos"] = [v.close() for v in writers.values()]
                for renderer in renderers.values():
                    renderer.close()
                result["video_format"] = "640x360 30fps preview at original numeric sample timestamps; not native resolution"
                write_json(case / "contacts.json", contacts)
                write_json(case / "result.json", result)
        results.append(result)
    write_json(out / "summary.json", dict(cases=results, completed=sum(r.get("replay_completed", False) for r in results),
               total=len(results), task_success=None, hardware_identity_verified=False,
               missing_calibration=["real_table_and_tray_poses_dimensions", "real_base_to_scene_transform",
                                    "initial_held_tray_pose_for_Place", "actuator_gains_friction_and_contact_parameters"],
               scope="independent_original_real_Pick_Place_motion_replay_not_whole_task"))
    paths = [v["path"] for r in results for v in r["videos"]]
    (out / "VIDEO_PATHS.txt").write_text("\n".join(paths) + ("\n" if paths else ""))
    return 0 if all(r.get("replay_completed") for r in results) else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-manifest", required=True)
    p.add_argument("--scene-xml", required=True)
    p.add_argument("--urdf", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--per-task", type=int, default=1)
    p.add_argument("--video", action="store_true")
    p.add_argument('--registration', help="'estimate' or directory containing source-bound case_NNN.json portable initial poses")
    p.add_argument('--torso-kp', type=float, default=250., help='Simulation torso position gain, not a measured hardware gain')
    p.add_argument('--torso-kv', type=float, default=25.)
    p.add_argument('--finger-collision-bundle', help='Opt-in source-bound convex parts for the independent model only')
    p.add_argument('--tray-width-scale',type=float,default=1.,help='Explicit estimated tray width; scales visual/collision/inertia in the new model')
    args = p.parse_args()
    if args.per_task < 1:
        p.error("per-task must be positive")
    out = Path(args.output).resolve(); out.mkdir(parents=True, exist_ok=False)
    # Exclusive directory allocation is the run lock; never resume into old evidence.
    write_json(out / "launch.json", dict(pid=os.getpid(), cwd=os.getcwd(), argv=sys.argv,
               started_unix=time.time(), code_root=str(Path(__file__).resolve().parents[1])))
    code = 1
    try:
        code = execute(args, out)
    except Exception:
        (out / "exception.txt").write_text(traceback.format_exc())
        raise
    finally:
        write_json(out / "exit.json", dict(exit_code=code, finished_unix=time.time()))
        write_json(out / "status.json", dict(stage="complete" if code == 0 else "failed",
                    exit_code=code, task_success=None, heartbeat_unix=time.time()))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
