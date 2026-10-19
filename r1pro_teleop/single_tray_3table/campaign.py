"""Explicit fresh source campaigns; plans and failures are never expert data."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib
import json
import math
import os
import subprocess
import threading
import time
import tempfile

from ..vla.data_three_table_single_tray import PROFILE, RULE_REVISION, LABELS


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    descriptor, name = tempfile.mkstemp(prefix=path.name+'.writing.', dir=path.parent)
    temporary = Path(name)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def build_plan(selection, inventory_path, manifest_path, registry_path, *, scene_options=None):
    """Validate explicit parent/seed choices against the original split registry."""
    inventory_path, manifest_path, registry_path = map(lambda p: Path(p).resolve(),
                                                      (inventory_path, manifest_path, registry_path))
    inventory = json.loads(inventory_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    registry = json.loads(registry_path.read_text())
    if inventory.get('schema') != 'airport_registered_parent_split_inventory/1':
        raise ValueError('original_registered_parent_inventory_required')
    if digest(manifest_path) != inventory['parent_manifest_sha256'] or digest(registry_path) != inventory['canonical_split_registry_sha256']:
        raise ValueError('original_parent_manifest_or_registry_changed')
    if selection.get('schema') != 'airport_three_table_campaign_selection/1' or not selection.get('variants'):
        raise ValueError('explicit_nonempty_parent_seed_selection_required')
    options = dict(scene_options or {})
    allowed = {'source_base_distance', 'target_base_standoff', 'target_tray_x', 'target_base_yaw', 'target_yaw_offset'}
    if set(options) - allowed:
        raise ValueError('scene_options_cannot_change_route_split_or_task')
    for value in options.values():
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('finite_explicit_scene_options_required')
    rows = []
    identities = set()
    for variant in selection['variants']:
        if set(variant) != {'parent_scene_id', 'variant_seed'} or type(variant['variant_seed']) is not int:
            raise ValueError('explicit_parent_and_integer_variant_seed_required')
        parent_id, seed = variant['parent_scene_id'], variant['variant_seed']
        matches = [r for r in inventory['parent_rows'] if r['parent_scene_id'] == parent_id]
        registered = [r for r in manifest['scenes'] if r['scene_id'] == parent_id]
        if len(matches) != 1 or len(registered) != 1 or parent_id not in registry:
            raise ValueError('parent_not_in_original_registry')
        source = matches[0]
        parent_path = (manifest_path.parent / registered[0]['json']).resolve()
        if digest(parent_path) != source['source_parent_json_sha256']:
            raise ValueError('actual_parent_json_changed')
        parent = json.loads(parent_path.read_text())
        if parent['scene_id'] != parent_id or registry[parent_id] != source['registered_split']:
            raise ValueError('original_parent_split_identity_changed')
        split = {'validation': 'val'}.get(registry[parent_id], registry[parent_id])
        if split not in ('train', 'val', 'test'):
            raise ValueError('registered_parent_split_required')
        identity = (parent_id, seed)
        if identity in identities:
            raise ValueError('duplicate_parent_variant')
        identities.add(identity)
        rows.append(dict(parent_scene_id=parent_id, variant_seed=seed, split=split,
                         parent_resource_split=parent.get('split'), parent_scene_json=str(parent_path),
                         parent_scene_json_sha256=digest(parent_path), scene_options=dict(options)))
    return dict(schema='airport_three_table_source_campaign_plan/1', task_profile=PROFILE,
                task_rule_revision=RULE_REVISION, source='simulation/program_generated',
                route_goal_observation_policy='fixed_registered_rear_to_front_left_route',
                route_coverage='rear_to_front_left_only_not_all_three_table_routes',
                push_axis_feedback_enabled=False,
                source_table='rear', target_table='front_left',
                randomization='Existing generator seed controls tabletop XY/yaw; no hidden route or split randomization.',
                split_policy='Original registered parent split inherited by every variant.',
                inventory=str(inventory_path), inventory_sha256=digest(inventory_path),
                parent_manifest=str(manifest_path), parent_manifest_sha256=digest(manifest_path),
                split_registry=str(registry_path), split_registry_sha256=digest(registry_path),
                variants=rows, selected=len(rows), dataset_ready=False, training_started=False)


def verified_case(result_path, expected):
    result_path = Path(result_path)
    result = json.loads(result_path.read_text())
    audit_path = result_path.parent / 'source_qualification_audit.json'
    source_path = result_path.parent / 'source_proof/source.json'
    if any(result.get(k) is not True for k in ('task_completed', 'physics_success', 'training_eligible')):
        return False
    if result.get('task_profile') != PROFILE or result.get('split') != expected['split'] or result.get('task_rule_revision') != RULE_REVISION:
        raise ValueError('complete_source_scope_or_split_changed')
    audit = json.loads(audit_path.read_text())
    source = json.loads(source_path.read_text())
    if audit.get('verified') is not True or audit.get('action_spans') != 3 or source.get('parent_scene_id') != expected['parent_scene_id'] or source.get('variant_seed') != expected['variant_seed'] or source.get('split') != expected['split']:
        raise ValueError('actual_complete_source_qualification_required')
    if source.get('parent_scene_json_sha256') != expected['parent_scene_json_sha256']:
        raise ValueError('qualified_parent_identity_changed')
    if Path(audit.get('source_manifest','')).resolve()!=source_path.resolve():
        raise ValueError('source_qualification_manifest_identity_changed')
    for key in ('trace','scene_xml','scene_json','result','events'):
        if digest(source[key])!=source[key+'_sha256']:
            raise ValueError('qualified_source_bytes_changed:'+key)
    spans = result.get('action_spans', [])
    if tuple(s.get('action_label') for s in spans) != LABELS:
        raise ValueError('exact_three_whole_action_spans_required')
    previous = 0
    for span in spans:
        a, b, end = (span.get(k) for k in ('start_frame', 'end_frame', 'measured_endpoint_frame'))
        if any(type(v) is not int for v in (a, b, end)) or not previous <= a <= end < b <= result['frames'] or span.get('verified') is not True:
            raise ValueError('actual_nonoverlapping_completed_windows_required')
        previous = b
    return True


def case_commands(plan, variant, directory, release, sim_python, config, reference):
    release, directory = Path(release), Path(directory)
    generate = [str(sim_python), str(release/'scripts/generate_three_table_single_tray.py'),
                '--output', str(directory/'scene'), '--seed', str(variant['variant_seed']),
                '--parent-scene', variant['parent_scene_json'], '--parent-manifest', plan['parent_manifest'],
                '--split-registry', plan['split_registry']]
    for key, value in variant['scene_options'].items():
        generate.extend(['--'+key.replace('_', '-'), str(value)])
    collect = [str(sim_python), str(release/'scripts/collect_three_table_full_source.py'),
               '--scene', str(directory/'scene/scene.json'), '--config', str(config),
               '--push-reference-scene', str(reference), '--no-axis-feedback',
               '--output', str(directory/'observed_source')]
    return generate, collect


def execute(plan, output, *, release, sim_python, config, reference, workers=1, runner=None):
    """Execute only after explicit CLI --execute; one independent directory/case."""
    if type(workers) is not int or not 1 <= workers <= 64:
        raise ValueError('explicit_positive_cpu_worker_count_resource_cap_64_required')
    out = Path(output); out.mkdir(parents=True, exist_ok=False)
    atomic_json(out/'plan.json', plan)
    release = Path(release).resolve()
    env = dict(os.environ, CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    state = dict(schema='airport_three_table_source_campaign_status/1', task_profile=PROFILE,
                 task_rule_revision=RULE_REVISION, pid=os.getpid(), selected=plan['selected'],
                 completed=0, stage='collecting_physical_candidates', results=[],
                 source_plan_sha256=digest(out/'plan.json'), dataset_ready=False, training_started=False,
                 route_coverage=plan['route_coverage'], workers=workers, resource_worker_cap=64,
                 child_cpu_threads=1, peak_active_child_processes=0,
                 child_process_receipts_are_actual=runner is None)
    atomic_json(out/'status.json', state)
    active=set(); process_lock=threading.Lock()
    def run(argv, log):
        with log.open('xb') as stream:
            process=subprocess.Popen(argv, cwd=release, env=env, stdin=subprocess.DEVNULL,
                                     stdout=stream, stderr=subprocess.STDOUT)
            receipt=log.with_name(log.name+'.process.json')
            row=dict(pid=process.pid,argv=argv,cwd=str(release),cpu_threads=1,cuda_visible_devices='',status='running')
            atomic_json(receipt,row)
            with process_lock:
                active.add(process.pid)
                state['peak_active_child_processes']=max(state['peak_active_child_processes'],len(active))
            try:
                code=process.wait()
                row.update(status='exited',returncode=code);atomic_json(receipt,row)
                return code
            finally:
                with process_lock:active.discard(process.pid)
    invoke = runner or run
    def one(index, variant):
        directory=out/f'case_{index:04d}'; directory.mkdir()
        result_path=directory/'observed_source/result.json'; error=None; code=-1; success=False
        try:
            for key in ('inventory','parent_manifest','split_registry'):
                if digest(plan[key])!=plan[key+'_sha256']:
                    raise ValueError('registered_campaign_inputs_changed:'+key)
            if digest(variant['parent_scene_json']) != variant['parent_scene_json_sha256']:
                raise ValueError('parent_changed_after_campaign_plan')
            generate, collect=case_commands(plan,variant,directory,release,sim_python,config,reference)
            atomic_json(directory/'commands.json',dict(generate=generate,collect=collect))
            code=invoke(generate,directory/'generate.log')
            if code==0:code=invoke(collect,directory/'collect.log')
            if code==0:success=verified_case(result_path,variant)
        except Exception as exc:error=repr(exc);code=-1
        if not result_path.exists():
            result_path=directory/'failure_result.json'
            atomic_json(result_path,dict(task_profile=PROFILE,task_completed=False,physics_success=False,
                                        training_eligible=False,split=variant['split'],error=error or 'child_nonzero_exit'))
        return dict(index=index,parent_scene_id=variant['parent_scene_id'],variant_seed=variant['variant_seed'],
                    split=variant['split'],result=str(result_path.resolve()),result_sha256=digest(result_path),
                    returncode=code,task_completed=success,source_qualified=success,error=error)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(one,i,v) for i,v in enumerate(plan['variants'])]
        for future in as_completed(futures):
            state['results'].append(future.result());state['results'].sort(key=lambda r:r['index'])
            state['completed']=len(state['results']);atomic_json(out/'status.json',state)
    state.update(stage='physical_candidates_complete', successful=sum(r['task_completed'] for r in state['results']),
                 finished_unix=time.time(), source_gpu_processes_started=False)
    atomic_json(out/'status.json',state)
    return state
