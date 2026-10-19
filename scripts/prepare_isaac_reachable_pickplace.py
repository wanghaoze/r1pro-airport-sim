"""Freeze a bounded direct-reachable candidate batch for native collection.

Private IK checks are NOT successful trajectories. The existing collector is
still responsible for actual PhysX completion, native media, and pair audits.
Each invocation keeps one original parent split and one episode-initial base.
Use a different output directory for another station; never mutate a batch.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import random
import subprocess
import sys


def candidates(template, seed, count, base):
    rng = random.Random(seed)
    # Two previously physically successful geometries lead the new batch;
    # they must still pass fresh native execution with the new initialization.
    geometry = [(0.84, -0.01, -5., .14), (.85, 0., 0., .18)]
    geometry += [(rng.uniform(.825, .86), rng.uniform(-.035, .035),
                  rng.uniform(-10., 5.), rng.uniform(.12, .18))
                 for _ in range(max(0, count - 2))]
    for index, (x, y, angle, lift) in enumerate(geometry[:count]):
        case = copy.deepcopy(template)
        case.pop('output', None)
        case.update(case_id=f'reachable_{seed}_{index:04d}', seed=seed+index,
                    tray_pose=[x, y, .801, math.cos(math.radians(angle)/2),
                               0., 0., math.sin(math.radians(angle)/2)],
                    xy_offset_m=[x-.85, y], yaw_degrees=angle,
                    lift_height_m=lift, fixed_base_world=list(base),
                    initial_base_world=list(base), search_front_stations=False,
                    diverse_preadjustment=True, direct_grasp_only=True,
                    reset_arms_after_preadjustment=False,
                    collection_scope='diverse_fixed_pickplace_physical_candidate',
                    exact_collision_footprint=True, record_cameras=True,
                    camera_resolutions=dict(head_left=[320, 256], head_right=[320, 256],
                                            left_wrist=[320, 180], right_wrist=[320, 180]),
                    presentation_resolution=[640, 360])
        yield case


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--template', type=Path, required=True,
                   help='Existing collector config, not a raw case config')
    p.add_argument('--code', type=Path, required=True, help='New frozen release')
    p.add_argument('--run', type=Path, required=True, help='New collection directory')
    p.add_argument('--seed', type=int, default=2026101606)
    p.add_argument('--target-pairs', type=int, default=100)
    p.add_argument('--max-candidates', type=int, default=320)
    p.add_argument('--precheck-python', default=sys.executable,
                   help='Non-base environment with the scene-compatible MuJoCo')
    p.add_argument('--base', type=float, nargs=3, default=[.3, 0., 0.])
    a = p.parse_args()
    if a.target_pairs < 1 or a.max_candidates < a.target_pairs:
        p.error('Require positive target and max-candidates >= target-pairs')
    cfg = json.loads(a.template.read_text())
    if cfg['parent_split'] not in ('train', 'val', 'test'):
        raise ValueError('Original parent split must be preserved')
    a.run.mkdir(parents=True, exist_ok=False)
    preflight = a.run/'private_preflight'; preflight.mkdir()
    accepted, rows = [], []
    for index, case in enumerate(candidates(cfg['cases'][0], a.seed, a.max_candidates, a.base)):
        case['parent_scene_id'] = cfg['parent_scene_id']
        case['parent_split'] = cfg['parent_split']
        casepath = preflight/f'candidate_{index:04d}.json'
        resultpath = preflight/f'candidate_{index:04d}.result.json'
        casepath.write_text(json.dumps(case, indent=2))
        with (preflight/f'candidate_{index:04d}.log').open('w') as log:
            result = subprocess.run([a.precheck_python,
                str(a.code/'scripts/probe_isaacsim_pad_station.py'),
                '--project', cfg['project'], '--code', str(a.code),
                '--output', str(resultpath), '--aligned-legacy',
                '--case-config', str(casepath)], stdout=log, stderr=subprocess.STDOUT)
        report = json.loads(resultpath.read_text()) if resultpath.exists() else {}
        passed = result.returncode == 0 and report.get('passed') is True
        rows.append(dict(candidate=str(casepath), report=str(resultpath),
                         returncode=result.returncode, private_path_available=passed))
        if passed:
            accepted.append(case)
        status = dict(scope='private_ik_candidates_not_physical_data',
                      tested=len(rows), accepted_candidates=len(accepted),
                      target_pairs=a.target_pairs, complete_source_pairs=0,
                      training_started=False, registry=rows)
        (a.run/'preflight_status.json').write_text(json.dumps(status, indent=2))
        if result.returncode != 0 or not report:
            raise RuntimeError('Private probe implementation/environment failed; inspect preserved log before more candidates')
        print(f'private preflight {len(rows)}/{a.max_candidates}; accepted {len(accepted)}/{a.target_pairs}', flush=True)
        if len(accepted) >= a.target_pairs:
            break
    if not accepted:
        raise RuntimeError('No registered candidate passed private direct path checks')
    cfg.update(run=str(a.run), code=str(a.code), cases=accepted,
               producer_entry=str(a.code/'scripts/collect_isaac_fixed_pickplace.py'),
               fixed_base_world=a.base, allow_supported_preadjustment=True,
               allow_episode_front_station_search=False,
               fixed_base_from_initialization=True,
               allow_partial_native_batch=True,
               collection_route='direct_reachable_subset_parallel_to_preadjustment_research',
               preparation_registry=str(a.run/'preflight_status.json'))
    for key in ('wait_before_start', 'rejected_preflight_cases'):
        cfg.pop(key, None)
    (a.run/'config.json').write_text(json.dumps(cfg, indent=2))
    print(json.dumps(dict(config=str(a.run/'config.json'),
                          private_accepted_candidates=len(accepted),
                          physical_successes=0, train_started=False)))


if __name__ == '__main__':
    main()
