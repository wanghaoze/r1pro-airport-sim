"""Read-only private 0.25 s MuJoCo release probes from an existing raw/1 frame.

Run with frozen release/collection paths. No collection file is written and the
probe does not claim a production-valid one-arm control mode.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import h5py
import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args):
    release = args.release.resolve()
    collection = args.collection.resolve()
    attempt = collection / "attempts" / args.scene / args.attempt
    scene = collection / "scenes" / args.scene
    xml = scene / "mobile.xml"
    if args.output.exists():
        raise ValueError("Output already exists; choose a fresh diagnostic path")
    sys.path.insert(0, str(release))
    from r1pro_teleop.airport_fsm.runtime import Runtime
    from r1pro_teleop.airport_fsm.registry import config_for
    from r1pro_teleop.airport_fsm.contracts import State
    import mujoco

    with h5py.File(attempt / "trace.h5", "r") as h:
        if h.attrs["schema"] != "airport_fsm_raw/1":
            raise ValueError("Expected raw/1 trace; raw/2 needs substep control journal")
        meta = json.loads(h.attrs["metadata_json"])
        xml_hash = sha(xml)
        if xml_hash != meta["scene_xml_sha256"]:
            raise ValueError("Recorded/frozen XML hash mismatch")
        frame = args.frame if args.frame >= 0 else len(h["timestamp"]) - 1
        if not 0 <= frame < len(h["timestamp"]):
            raise ValueError("Frame outside saved trace")
        saved = {key: np.asarray(h[key][frame]).copy() for key in (
            "integration_state", "qacc_warmstart", "ctrl", "action", "base_action",
            "tray_pose", "min_z", "gripper_contact_force", "table_contact", "support_contact")}
        record = {"schema": str(h.attrs["schema"]), "frame": frame,
                  "recorded_time_s": float(h["timestamp"][frame]),
                  "target_tray": int(h["target_tray"][frame]),
                  "fsm_state": h["fsm_state"][frame].decode(),
                  "transition_completed": bool(h["transition_completed"][frame]),
                  "xml_sha256": xml_hash, "trace_sha256": sha(attempt / "trace.h5")}

    spec = json.loads((scene / "scene.json").read_text())
    cfg = config_for(collection)
    outcomes = {}
    for retained in ("both", "left", "right"):
        r = Runtime(spec, xml, cfg, render=False)
        try:
            if r.integration_size != saved["integration_state"].size:
                raise ValueError("Integration schema mismatch")
            if not np.allclose(r.m.actuator_forcerange, meta["limits"]["actuator_forcerange"], atol=1e-9):
                raise ValueError("Frozen Runtime actuator force limits differ from trace")
            mujoco.mj_setState(r.m, r.d, saved["integration_state"], r.integration_spec)
            mujoco.mj_forward(r.m, r.d)
            r.d.qacc_warmstart[:] = saved["qacc_warmstart"]
            r.d.ctrl[:] = saved["ctrl"]
            r.sim.target = saved["action"].astype(np.float32)
            r.sim.base_target = saved["base_action"].astype(np.float32)
            initial = r.observation()
            tray = record["target_tray"]
            r.allowed_tray = tray
            r.holding = tray
            r.fsm_state = State.TRANSPORT_TRAY
            r.phase = "transport"
            if tray < 0 or np.max(np.abs(initial["tray_pose"] - saved["tray_pose"])) > 1e-5:
                raise ValueError("Restored tray pose disagrees with raw trace")
            if np.max(np.abs(initial["gripper_contact_force"] - saved["gripper_contact_force"])) > 0.1:
                raise ValueError("Restored contact force disagrees with raw trace")
            original = saved["action"].copy()
            steps = int(round(args.seconds / r.m.opt.timestep))
            if steps * r.m.opt.timestep > .250001:
                raise ValueError("Probe longer than 0.25 s")
            samples = []
            prev_other_z = np.asarray(initial["min_z"]).copy()
            for i in range(steps + 1):
                e = r.observation()
                body = r.d.body(r.g.ids[tray])
                normal = body.xmat.reshape(3, 3)[:, 2]
                tilt = float(np.degrees(np.arccos(np.clip(normal[2], -1, 1))))
                samples.append({"time_s": round(i * float(r.m.opt.timestep), 6),
                    "bottom_z_m": float(e["min_z"][tray]),
                    "center_z_m": float(e["tray_pose"][tray, 2]),
                    "tilt_deg": tilt,
                    "gripper_force_n": np.asarray(e["gripper_contact_force"][tray], float).tolist(),
                    "table_contact": int(e["table_contact"][tray]),
                    "support_contact": int(e["support_contact"][tray]),
                    "other_bottom_delta_m": (np.asarray(e["min_z"]) - prev_other_z).tolist(),
                    "max_penetration_m": float(e["max_penetration"]),
                    "floor_contact": np.asarray(e["floor_contact"]).astype(int).tolist(),
                    "camera_guard_passed": bool(r.camera_guard(contact_sides=[
                        side for j, side in enumerate(("left", "right"))
                        if e["gripper_contact_force"][tray, j] > .5])),
                    "illegal_collision": r.collision()})
                if i == steps:
                    break
                target = original.copy()
                if retained != "both":
                    released = "right" if retained == "left" else "left"
                    col = 15 if released == "right" else 7
                    progress = min(1., (i + 1) * float(r.m.opt.timestep) / args.open_seconds)
                    target[col] = original[col] + progress * (cfg.gripper_open_m - original[col])
                r.sim.target = target.astype(np.float32)
                r.sim.apply_target()
                mujoco.mj_step(r.m, r.d)
                if not np.isfinite(r.d.qpos).all() or not np.isfinite(r.d.qvel).all():
                    raise ValueError("Nonfinite private dynamics")
            bottom = np.array([s["bottom_z_m"] for s in samples])
            tilts = np.array([s["tilt_deg"] for s in samples])
            forces = np.array([s["gripper_force_n"] for s in samples])
            other = np.array([s["other_bottom_delta_m"] for s in samples])
            idx = 0 if retained == "left" else 1
            outcomes[retained] = {
                "samples": samples,
                "summary": {"steps": steps,
                    "min_bottom_delta_m": float(np.min(bottom - bottom[0])),
                    "max_bottom_delta_m": float(np.max(bottom - bottom[0])),
                    "max_tilt_deg": float(np.max(tilts)),
                    "final_tilt_deg": float(tilts[-1]),
                    "retained_force_min_n": float(np.min(forces[:, idx])) if retained != "both" else None,
                    "released_force_final_n": float(forces[-1, 1 - idx]) if retained != "both" else None,
                    "released_force_max_after_open_n": float(np.max(forces[int(round(args.open_seconds / r.m.opt.timestep)):, 1 - idx])) if retained != "both" else None,
                    "other_max_upward_m": float(np.max(other[:, [j for j in range(3) if j != tray]])),
                    "illegal_collision_samples": int(sum(bool(s["illegal_collision"]) for s in samples)),
                    "floor_contact_samples": int(sum(any(s["floor_contact"]) for s in samples)),
                    "max_penetration_m": float(max(s["max_penetration_m"] for s in samples))}}
        finally:
            r.sim.close()
    payload = {"qualification": "private_short_dynamics_probe_not_controller_or_episode_success",
               "source": record, "parameters": {"duration_s": args.seconds,
                 "release_open_seconds": args.open_seconds,
                 "constant_joint_and_base_target_except_released_gripper": True},
               "outcomes": outcomes}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({k: v["summary"] for k, v in outcomes.items()}))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--release", type=Path, required=True)
    p.add_argument("--collection", type=Path, required=True)
    p.add_argument("--scene", default="airport_0015_20270931")
    p.add_argument("--attempt", default="a002")
    p.add_argument("--frame", type=int, default=-1)
    p.add_argument("--seconds", type=float, default=.25)
    p.add_argument("--open-seconds", type=float, default=.10)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if not 0 < a.open_seconds <= a.seconds <= .25:
        p.error("Require 0 < open-seconds <= seconds <= 0.25")
    run(a)


if __name__ == "__main__":
    main()
