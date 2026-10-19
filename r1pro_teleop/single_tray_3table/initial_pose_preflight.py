"""Random-pose rejection sampling with real, side-effect-free long-rim planning.

This certifies a private grasp proposal only. Contact dynamics, navigation,
complete tasks and training eligibility still require actual collection.
"""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import json
import os
import time

import numpy as np
from .campaign import atomic_json, build_plan, digest


def probe_initial_pose(scene, config):
    from .control import ThreeTableRuntime, ThreeTableMachine
    from ..airport_fsm.geometry import quat_yaw_tilt, wrap_angle
    from ..airport_fsm.reachability_planner import planning_copy, _set_private_configuration, alternate_candidate_lattice, candidate_lattice, screen_candidates
    runtime = ThreeTableRuntime(scene, config)
    before = {name: getattr(runtime.d, name).copy() for name in ('qpos', 'qvel', 'ctrl')}
    before.update(time=float(runtime.d.time), arm_target=runtime.sim.target.copy(), base_target=runtime.sim.base_target.copy())
    try:
        machine = ThreeTableMachine.__new__(ThreeTableMachine)
        machine.r = runtime; machine.g = runtime.g; machine.c = config
        machine.rng = np.random.default_rng(scene['seed']); machine.attempt = 0; machine.recovery_used = False
        machine.grasp_stagger = 0.; machine.grasp_rim_pair = None; machine.manifest = scene
        pose = machine._poses()[0]
        normal = machine._inward_yaw(pose[:3]); yaw, _ = quat_yaw_tilt(pose[3:])
        face = normal + float(wrap_angle(yaw - normal, np.pi))
        initial = machine._candidate_list(0)
        extra = (alternate_candidate_lattice(pose[:3], runtime.g.sizes[0], yaw, normal,
                    inset=config.rim_inset_m, rim_jitter=config.rim_x_jitter_m)
                 if config.alternate_rim_enabled else candidate_lattice(pose[:3], face, normal, rim_jitter=config.rim_x_jitter_m))
        # Same hook as live align: no short-edge candidate can earn a certificate.
        pool = machine._screen_candidate_list(0, initial[:2] + list(extra) + initial[2:])
        private = planning_copy(runtime)
        # Predict the existing initial tucked posture, without executing a tick.
        _set_private_configuration(private, runtime.tucked)
        report = screen_candidates(private, 0, pool, max_probes=config.reachability_max_probes,
                                   max_qualified=config.reachability_max_qualified)
        unchanged = all(np.array_equal(getattr(runtime.d, name), before[name]) for name in ('qpos', 'qvel', 'ctrl'))
        unchanged = unchanged and runtime.d.time == before['time'] and np.array_equal(runtime.sim.target, before['arm_target']) and np.array_equal(runtime.sim.base_target, before['base_target'])
        if not unchanged:
            raise ValueError('private_preflight_mutated_live_initial_state')
        accepted = []
        for candidate, detail in report.candidates:
            pair = candidate.rim_pair
            accepted.append(dict(base_world=candidate[0].tolist(), face=candidate[1], rim_x=candidate[2],
                                 rim_geometry=dict(axis=pair.axis, face=pair.face, half_span=pair.half_span, edge_half_length=pair.edge_half_length),
                                 actual_probe=detail))
        return dict(schema='airport_actual_initial_pose_private_preflight/1', accepted=bool(accepted),
                    initial_pose=scene['initial_tray_pose'], scene_id=scene['scene_id'], parent_scene_id=scene['parent_scene_id'],
                    seed=scene['seed'], split=scene['split'], config=config.dump(),
                    source_base_distance_m=float(np.linalg.norm(np.asarray(scene['initial_robot_pose']['position_world'])[:2] - np.asarray(scene['initial_tray_pose']['position_world'])[:2])),
                    initial_posture_policy='private_prediction_of_existing_tucked_posture',
                    candidate_count=len(pool), examined=report.examined, accepted_candidates=accepted, rejected_candidates=report.rejected,
                    probe_budget=config.reachability_max_probes, qualified_budget=config.reachability_max_qualified,
                    planning_wall_seconds=report.planning_wall_seconds, candidate_budget_exhausted=not report.exhausted,
                    live_state_unchanged=True, physical_ticks=0, physics_success_certified=False,
                    training_eligible=False, qualification='private_pregrasp_descent_closure_requires_actual_live_execution',
                    orientation_window_used=False, proposal_yaw_changed=False)
    finally:
        runtime.sim.close()


def evaluate_proposal(job):
    """One immutable proposal with a process lock and recoverable final receipt."""
    from ..airport_fsm.contracts import Config
    from ..single_tray_lab.three_table_scene import generate_three_table_scene
    directory = Path(job['directory']); directory.mkdir(parents=True, exist_ok=True)
    import fcntl
    handle = (directory / 'proposal.lock').open('a+')
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    receipt = directory / 'preflight.json'
    binding = {k:v for k,v in job.items() if k != 'directory'}
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if saved.get('proposal_binding') != binding:
            raise ValueError('immutable_proposal_binding_changed')
        if digest(job['config']) != saved['config_sha256'] or digest(saved['scene']) != saved['scene_sha256'] or digest(saved['scene_xml']) != saved['scene_xml_sha256']:
            raise ValueError('preflight_reuse_source_bytes_changed')
        return saved
    for source, expected in job['source_bindings'].items():
        if digest(source) != expected:
            raise ValueError('preflight_runtime_binding_changed')
    scene_path = directory / 'scene/scene.json'
    if scene_path.exists():
        scene = json.loads(scene_path.read_text())
    else:
        partial = directory / 'scene'
        if partial.exists():
            number = 0
            while (directory / f'scene_partial_preserved_{number:02d}').exists(): number += 1
            partial.rename(directory / f'scene_partial_preserved_{number:02d}')
        scene = generate_three_table_scene(directory / 'scene', job['parent_scene'], job['parent_manifest'], job['seed'],
                    split_registry=job['split_registry'], source_base_distance_m=job['source_base_distance'])
    if scene['seed'] != job['seed'] or scene['parent_scene_id'] != job['parent_scene_id'] or scene['split'] != job['split']:
        raise ValueError('proposal_scene_identity_changed')
    result = probe_initial_pose(scene, Config.load(job['config']))
    result.update(proposal_binding=binding, scene=str(scene_path.resolve()), scene_sha256=digest(scene_path),
                  scene_xml=scene['xml'], scene_xml_sha256=digest(scene['xml']), config_sha256=digest(job['config']))
    atomic_json(receipt, result)
    return result


def freeze_selection(records, targets):
    selected = []
    counts = {s:0 for s in ('train', 'val', 'test')}
    for row in records:
        split = row['split']
        if row['accepted'] and counts[split] < targets[split]:
            selected.append(dict(parent_scene_id=row['parent_scene_id'], variant_seed=row['seed']))
            counts[split] += 1
    return dict(schema='airport_three_table_campaign_selection/1', variants=selected), counts


def collect_plan(options):
    """Bounded proposals, deterministic parent rotation, no angular filtering."""
    if options.get('schema') != 'airport_three_table_preflight_plan_options/1':
        raise ValueError('explicit_preflight_options_required')
    output = Path(options['output']); output.mkdir(parents=True, exist_ok=True)
    import fcntl
    handle = (output / 'preflight.lock').open('a+'); fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    binding_path = output / 'options_binding.json'
    if binding_path.exists() and json.loads(binding_path.read_text()) != options:
        raise ValueError('frozen_preflight_options_changed')
    if not binding_path.exists(): atomic_json(binding_path, options)
    targets = options.get('targets', dict(train=100, val=10, test=10))
    limits = options.get('proposal_limits', dict(train=6000, val=600, test=600))
    workers = options.get('workers', 8)
    if set(targets) != {'train', 'val', 'test'} or set(limits) != set(targets) or type(workers) is not int or not 1 <= workers <= 64:
        raise ValueError('explicit_split_targets_and_workers_required')
    if any(type(targets[s]) is not int or targets[s] < (100 if s == 'train' else 10) or type(limits[s]) is not int or limits[s] < targets[s] for s in targets):
        raise ValueError('bounded_at_least_100_train_10_val_10_test_required')
    if type(options.get('seed_start')) is not int or options['seed_start'] < 0:
        raise ValueError('explicit_nonnegative_integer_seed_start_required')
    parents = options['parents']
    if set(parents) != set(targets):
        raise ValueError('all_original_parent_split_groups_required')
    release = Path(__file__).resolve().parents[1]
    source_paths = [Path(__file__), release / 'single_tray_3table/control.py',
        release / 'airport_fsm/runtime.py', release / 'airport_fsm/machine.py',
        release / 'airport_fsm/reachability_planner.py', release / 'airport_fsm/rim_affordances.py',
        release / 'single_tray_lab/scene.py', release / 'single_tray_lab/three_table_scene.py', Path(options['config'])]
    source_bindings = {str(p.resolve()):digest(p) for p in source_paths}
    parent_variants = [dict(parent_scene_id=p, variant_seed=options['seed_start']) for values in parents.values() for p in values]
    parent_plan = build_plan(dict(schema='airport_three_table_campaign_selection/1', variants=parent_variants), options['inventory'], options['parent_manifest'], options['split_registry'], scene_options=dict(source_base_distance=options.get('source_base_distance', .5)))
    parent_rows = {r['parent_scene_id']:r for r in parent_plan['variants']}
    for split, values in parents.items():
        if not values or any(parent_rows[p]['split'] != split for p in values):
            raise ValueError('original_registered_parent_split_required')
    records = []; counts = {s:0 for s in targets}; statistics = {}; status_path = output / 'status.json'
    def status(stage, **fields):
        atomic_json(status_path, dict(schema='airport_three_table_preflight_plan_status/1', stage=stage, pid=os.getpid(),
            heartbeat_unix=time.time(), qualified_candidate_counts=counts, targets=targets, statistics=statistics,
            physical_sources_completed=0, training_started=False, dataset_ready=False, **fields))
    status('sampling_and_actual_private_preflight')
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            seed_offset = 0
            for number, split in enumerate(('train', 'val', 'test')):
                statistics[split] = dict(proposals=0, accepted=0, rejected=0)
                for batch_start in range(0, limits[split], workers):
                    jobs = []
                    for index in range(batch_start, min(batch_start + workers, limits[split])):
                        parent = parents[split][index % len(parents[split])]; parent_row = parent_rows[parent]
                        seed = options['seed_start'] + seed_offset + index
                        jobs.append(dict(directory=str(output / 'proposals' / split / f'proposal_{index:06d}'),
                            seed=seed, parent_scene_id=parent, split=split, parent_scene=parent_row['parent_scene_json'],
                            parent_manifest=options['parent_manifest'], split_registry=options['split_registry'],
                            config=options['config'], source_base_distance=options.get('source_base_distance', .5)))
                        jobs[-1]['source_bindings'] = source_bindings
                    futures = [pool.submit(evaluate_proposal, job) for job in jobs]
                    while not all(f.done() for f in futures):
                        status('sampling_and_actual_private_preflight', active_split=split, active_proposal_batch=batch_start)
                        time.sleep(2)
                    for future in futures:
                        row = future.result()
                        # Complete private evidence remains per proposal; the index
                        # stays compact rather than duplicating every solver/config.
                        records.append({k:row[k] for k in ('parent_scene_id', 'seed', 'split', 'accepted', 'scene', 'initial_pose')})
                        statistics[split]['proposals'] += 1
                        statistics[split]['accepted' if row['accepted'] else 'rejected'] += 1
                    selection, counts = freeze_selection(records, targets)
                    atomic_json(output / 'proposal_index.json', dict(records=records, selection=selection, counts=counts, statistics=statistics))
                    status('sampling_and_actual_private_preflight', active_split=split, active_proposal_batch=batch_start)
                    if counts[split] >= targets[split]: break
                seed_offset += limits[split]
        selection, counts = freeze_selection(records, targets)
        ready = all(counts[s] >= targets[s] for s in targets)
        atomic_json(output / 'accepted_selection.json', selection)
        receipts = [dict(parent_scene_id=r['parent_scene_id'], variant_seed=r['seed'], split=r['split'], scene=r['scene'], initial_pose=r['initial_pose'], preflight=str(Path(r['scene']).parent.parent / 'preflight.json')) for r in records if r['accepted']]
        atomic_json(output / 'qualified_initial_pose_index.json', dict(schema='airport_qualified_random_initial_pose_index/1', records=receipts,
            coverage='direct_opposed_long_rim_reachable_random_initial_pose_subset_without_single_arm_preparation',
            fixed_angle_filter_used=False, proposal_yaw_changed=False, training_eligible=False))
        status('preflight_candidates_ready' if ready else 'blocked_preflight_proposal_budget_exhausted', selection=str(output / 'accepted_selection.json'), selection_sha256=digest(output / 'accepted_selection.json'),
               task_success_not_certified=True, direct_feasible_subset_coverage=True)
        return ready
    except BaseException as error:
        status('blocked_preflight_implementation_or_integrity_error', last_error=repr(error))
        raise
