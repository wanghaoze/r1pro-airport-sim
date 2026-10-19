"""Read-only failed-state qualification of both physical rim pairs.

Uses the frozen release's own planner and guards, replacing only pure target
geometry on private planning copies. Output is never physical success evidence.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import sys
import h5py
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--module', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-probes', type=int, default=36)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Refuse to overwrite diagnostic output')
    sys.path.insert(0, str(args.release))
    from r1pro_teleop.airport_fsm.runtime import Runtime
    from r1pro_teleop.airport_fsm.registry import config_for
    from r1pro_teleop.airport_fsm.geometry import quat_yaw_tilt
    from r1pro_teleop.airport_fsm.reachability_planner import candidate_lattice, screen_candidates
    spec = importlib.util.spec_from_file_location('alternate_rim_geometry', args.module)
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    root = args.release/'runs/regression'
    results = []
    for case, frame, tray, normal in ((6, 857, 2, np.pi), (7, 662, 1, 0.)):
        scene = next((root/'scenes').glob(f'airport_{case:04d}_*'))
        attempt = next((root/'attempts'/scene.name).glob('a*'))
        runtime = Runtime(json.loads((scene/'scene.json').read_text()), scene/'mobile.xml', config_for(root), render=False)
        with h5py.File(attempt/'trace.h5', 'r') as trace:
            runtime.mj.mj_setState(runtime.m, runtime.d, trace['integration_state'][frame], runtime.integration_spec)
            runtime.mj.mj_forward(runtime.m, runtime.d)
            runtime.sim.target = trace['action'][frame-1].copy()
            runtime.sim.base_target = trace['base_action'][frame-1].copy()
            pose = trace['tray_pose'][frame, tray].copy()
        yaw = quat_yaw_tilt(pose[3:])[0]
        runtime.holding = runtime.retained_contact = None
        runtime.allowed_tray = tray
        for pair in module.rim_pairs(runtime.g.sizes[tray], yaw, normal, inset=runtime.cfg.rim_inset_m):
            def goals(center, face, *, x_offset=0., sides=('left', 'right'), pair=pair, cfg=runtime.cfg):
                if abs(np.arctan2(np.sin(face-pair.face), np.cos(face-pair.face))) > 1e-8:
                    raise ValueError('Candidate face must match chosen edge pair')
                return pair.goals(center, x_offset=x_offset, sides=sides, pitch_deg=cfg.rim_pitch_deg, roll_deg=cfg.rim_roll_deg)
            runtime.rim_goals = goals
            candidates = list(candidate_lattice(pose[:3], pair.face, normal, rim_jitter=runtime.cfg.rim_x_jitter_m))
            # Cover every distance before exhausting a single distance's variants.
            candidates = [candidate for offset in range(9) for candidate in candidates[offset::9]]
            result = screen_candidates(runtime, tray, candidates, max_probes=args.max_probes, max_qualified=2)
            row = dict(case=case, frame=frame, tray=tray, axis=pair.axis, face=pair.face,
                       half_span_m=pair.half_span, examined=result.examined, rejected=result.rejected,
                       qualified=[dict(base=c[0].tolist(), face=c[1], rim=c[2], detail=d) for c, d in result.candidates],
                       planning_wall_seconds=result.planning_wall_seconds,
                       qualification='private_kinematic_only_no_live_execution')
            results.append(row)
            print(json.dumps(row), flush=True)
        runtime.sim.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
