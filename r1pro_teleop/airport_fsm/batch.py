"""Bounded subprocess scheduling. Workers never rewrite shared registries."""
from __future__ import annotations
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from contextlib import contextmanager
import importlib.metadata
import json
import os
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
import numpy as np
from .contracts import atomic_json, Fault, sha256_file, fingerprint, camera_shapes
from .registry import config_for, scene_rows, materialize_scene, coverage, select_registered, preflight_coverage
from .geometry import quat_yaw_tilt

_CHILDREN = set()
_CHILD_LOCK = threading.RLock()
_CANCEL = threading.Event()


def environment_versions():
    out = {'python':sys.version.split()[0]}
    for name in ('mujoco','numpy','scipy','h5py','lerobot','av','torch','ruckig'):
        try: out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: out[name] = None
    return out


def code_hashes():
    here = Path(__file__).resolve().parent
    paths = sorted(here.glob('*.py')) + [here.parent/n for n in ('core.py','airport_mobile.py','airport_recording.py')]
    return {str(p.relative_to(here.parent)): sha256_file(p) for p in paths if p.is_file()}


def freeze_dependencies(root):
    """Hash each shared asset ONCE, not 400 times. Do not copy/change vendor."""
    root = Path(root)
    all_paths = set()
    seen_xml = set()
    def visit(xml):
        xml = Path(xml).resolve()
        if xml in seen_xml: return
        seen_xml.add(xml)
        tree = ET.parse(xml)
        compiler = tree.find('compiler')
        directories = {k: compiler.get(k, '') if compiler is not None else '' for k in ('meshdir','texturedir','assetdir')}
        for node in tree.getroot().iter():
            value = node.get('file')
            if not value: continue
            directory = directories['meshdir'] if node.tag == 'mesh' else directories['texturedir'] if node.tag == 'texture' else ''
            candidate = (xml.parent/directory/value).resolve()
            if not candidate.exists():
                candidate = (xml.parent/directories['assetdir']/value).resolve()
            if not candidate.is_file(): raise Fault('asset_missing', str(candidate))
            all_paths.add(candidate)
            if node.tag == 'include': visit(candidate)
    for row in scene_rows(root): visit(row['source_xml'])
    assets = {str(p):sha256_file(p) for p in sorted(all_paths)}
    cfg=config_for(root)
    configured={}
    for value in (cfg.hardware_profile,cfg.urdf):
        if value: configured[str(Path(value).expanduser().resolve())]=sha256_file(Path(value).expanduser())
    repository=Path(__file__).resolve().parents[2]
    for candidate in (repository/'vendor/GalaxeaManipSim/galaxea_sim/assets/r1_pro/robot.urdf',repository/'outputs/r1pro_tray_scene/assets/r1_pro/robot.urdf'):
        if candidate.is_file():configured[str(candidate)]=sha256_file(candidate)
    record = {'assets':assets, 'configured_inputs':configured, 'code':code_hashes(), 'physics_environment':{k:v for k,v in environment_versions().items() if k in (('mujoco','numpy','scipy','ruckig') if cfg.online_push else ('mujoco','numpy','scipy'))},
              'array_snapshot_storage':'numeric_HDF5_plus_single_canonical_native_video_store',
              'robot_model_assets_are_not_hardware_calibration':True}
    record['fingerprint'] = fingerprint(record)
    path = root/'dependencies.json'
    if path.exists() and json.loads(path.read_text())['fingerprint'] != record['fingerprint']:
        raise Fault('dependencies_changed', 'Use a new collection; do not mix physics/assets/code in a resume')
    atomic_json(path, record)
    return record


def assert_environment(root):
    root = Path(root)
    path = root/'dependencies.json'
    if not path.is_file(): raise Fault('preflight_required')
    record = json.loads(path.read_text())
    if record['code'] != code_hashes(): raise Fault('controller_code_changed_since_preflight')
    now = environment_versions()
    for k, v in record['physics_environment'].items():
        if now.get(k) != v: raise Fault('physics_environment_changed', {'package':k,'was':v,'now':now.get(k)})
    for p,digest in record.get('configured_inputs',{}).items():
        if sha256_file(p)!=digest:raise Fault('configured_limit_profile_changed',p)
    for row in scene_rows(root):
        p=root/'scenes'/row['scene_id']/'preflight.json'
        if p.exists():
            pf=json.loads(p.read_text())
            if pf.get('valid') and sha256_file(p.with_name('scene.json'))!=pf.get('scene_json_sha256'):
                raise Fault('materialized_scene_json_changed',row['scene_id'])
    for p, digest in record['assets'].items():
        if sha256_file(p) != digest: raise Fault('asset_changed_since_preflight', p)


def preflight_one(root, row):
    from .runtime import Runtime
    root = Path(root); r = None
    try:
        spec, xml = materialize_scene(root, row)
        r = Runtime(spec, xml, config_for(root))
        expected = np.array([t['position_world'] for t in spec['trays']])
        if np.max(np.abs(r.observation()['tray_pose'][:,:3]-expected)) > .002:
            raise Fault('initial_pose_disagrees_with_scene_json')
        shapes = camera_shapes(spec)
        max_height=max(v[0] for v in shapes.values());max_width=max(v[1] for v in shapes.values())
        if r.m.vis.global_.offwidth < max_width or r.m.vis.global_.offheight < max_height:
            raise Fault('framebuffer_smaller_than_native_contract')
        r.guard(); r.wait(2.)
        e = r.observation()
        settled = e['tray_pose']
        translation = np.linalg.norm(settled[:, :3]-expected, axis=1)
        tilt = np.array([quat_yaw_tilt(p[3:])[1] for p in settled])
        if np.max(translation) > .005:
            raise Fault('initial_scene_settle_drift', {
                'maximum_translation_m': float(np.max(translation)),
                'per_tray_translation_m': translation.tolist(),
            })
        if np.max(tilt) > np.deg2rad(5.):
            raise Fault('initial_scene_settle_tilt', {
                'maximum_tilt_deg': float(np.rad2deg(np.max(tilt))),
            })
        if np.any(e['support_contact'] <= 0): raise Fault('initial_tray_has_no_support')
        for p in e['tray_pose']:
            if r.g.support_table(p[:3]) is None: raise Fault('initial_com_not_supported')
        cameras = {}
        for name in shapes:
            cid = r.m.camera(name).id
            cameras[name] = {'body_id':int(r.m.cam_bodyid[cid]), 'body_name':r.m.body(int(r.m.cam_bodyid[cid])).name,
                             'position_in_parent':r.m.cam_pos[cid].tolist(), 'quaternion_wxyz':r.m.cam_quat[cid].tolist(),
                             'fovy_deg':float(r.m.cam_fovy[cid]), 'width':shapes[name][1],'height':shapes[name][0],
                             'calibration_status':spec.get('camera',{}).get('calibration_status','legacy_specification_approximation')}
        result = {'valid':True,'scene_id':row['scene_id'],'split':row['split'], 'scene_xml_sha256':sha256_file(xml),'scene_json_sha256':sha256_file(root/'scenes'/row['scene_id']/'scene.json'),
                  'limits':r.limits,'cameras':cameras,'initial_settle_s':2.,'rendering_tested':False,
                  'complete_task_tested':False,'environment':environment_versions()}
    except Exception as exc:
        result = {'valid':False,'scene_id':row['scene_id'],'split':row['split'],
                  'failure_code':exc.code if isinstance(exc,Fault) else 'preflight_exception','error':str(exc)}
    finally:
        if r: r.close()
    atomic_json(root/'scenes'/row['scene_id']/'preflight.json',result)
    return result


def stop_children():
    _CANCEL.set()
    with _CHILD_LOCK:
        children = list(_CHILDREN)
    for p in children:
        if p.poll() is None:
            try:
                if os.name == 'posix': os.killpg(p.pid, signal.SIGTERM)
                else: p.terminate()
            except ProcessLookupError: pass


@contextmanager
def generation_termination_scope():
    """Temporarily translate SIGTERM into owned-child cleanup and exit 143."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGTERM)
    terminating = False
    def terminate(signum, frame):
        nonlocal terminating
        if terminating:
            return
        terminating = True
        stop_children()
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def attempt_worker_timeout(cfg):
    """Approximate completion has no wall-clock failure gate; cancellation remains."""
    return None if getattr(cfg, 'approximate_completion_enabled', False) else cfg.max_attempt_wall_seconds + 30


def run_child(args, log, timeout):
    if _CANCEL.is_set(): raise Fault('batch_cancelled')
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
    with open(log,'x',encoding='utf-8') as stream:
        process = subprocess.Popen([sys.executable,'-m','r1pro_teleop.airport_fsm',*map(str,args)],
                                   stdout=stream,stderr=subprocess.STDOUT,env=env,start_new_session=os.name=='posix')
        with _CHILD_LOCK: _CHILDREN.add(process)
        try:
            # A signal can arrive between the initial check and registration.
            if _CANCEL.is_set():
                if process.poll() is None:
                    try:
                        if os.name == 'posix': os.killpg(process.pid, signal.SIGTERM)
                        else: process.terminate()
                    except ProcessLookupError: pass
            try: return process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == 'posix': os.killpg(process.pid,signal.SIGKILL)
                else: process.kill()
                process.wait()
                return 124
        finally:
            with _CHILD_LOCK: _CHILDREN.discard(process)


def preflight(root, workers=4, scene_ids=None):
    _CANCEL.clear()
    root = Path(root).resolve()
    registered=scene_rows(root)
    rows=select_registered(registered,scene_ids)
    # Reject mismatched cached evidence before starting any additional worker.
    preflight_coverage(root,registered,[r['scene_id'] for r in rows])
    versions = environment_versions()
    if versions['mujoco'] is None:
        raise Fault('mujoco_not_installed', 'Activate the existing r1pro-tray Conda environment first')
    freeze_dependencies(root)
    def job(row):
        out = root/'scenes'/row['scene_id']; out.mkdir(exist_ok=True)
        report = out/'preflight.json'
        if report.exists(): return json.loads(report.read_text())
        log=out/'preflight.log'
        if log.exists():log=out/f'preflight_resume_{time.time_ns()}.log'
        code = run_child(['preflight-one','--root',root,'--scene-id',row['scene_id']],log,180.)
        if not report.exists():
            atomic_json(report,{'valid':False,'scene_id':row['scene_id'],'split':row['split'],
                                'failure_code':'preflight_worker_timeout' if code==124 else 'preflight_worker_crashed','exit_code':code})
        return json.loads(report.read_text())
    results=[]
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures=[pool.submit(job,r) for r in rows]
            try:
                for future in as_completed(futures):
                    result=future.result();results.append(result)
                    print(json.dumps({'preflight':len(results),'total':len(rows),'scene':result['scene_id'],'valid':result['valid']}),flush=True)
            except BaseException:
                for future in futures: future.cancel()
                stop_children();raise
    except BaseException:
        stop_children();raise
    report={'total':len(rows),'valid':sum(r['valid'] for r in results),'rejected':sum(not r['valid'] for r in results),
            'rejection_codes':dict(Counter(r.get('failure_code') for r in results if not r['valid'])),
            'task_rollouts_validated':0,'rendering_tested':False}
    report.update(preflight_coverage(root,registered,[r['scene_id'] for r in rows]))
    atomic_json(root/'quality/preflight.json',report)
    return report


def selected_rows(root, limit=None, scene_ids=None):
    rows = select_registered(scene_rows(root),scene_ids)
    # Round robin across front counts and difficulties for an informative smoke
    # slice without relabelling or changing any of the 400 scenes.
    groups={}
    for row in rows: groups.setdefault((row['front_count'],row['difficulty']),[]).append(row)
    ordered=[]
    while any(groups.values()):
        for key in sorted(groups):
            if groups[key]: ordered.append(groups[key].pop(0))
    return ordered if limit is None else ordered[:limit]


def attempt_stopping_success(result, cfg, *, resumed=False):
    """Completion stops on the first actual completed task, including recovery."""
    if getattr(cfg, 'acceptance_profile', 'strict') == 'completion_first':
        return bool(not result.get('diagnostic_only') and
                    result.get('task_completed', result.get('physics_success', False)))
    return bool(result.get('physics_success', False) and not result.get('recovery_used', False)
                and not (resumed and result.get('export_rejected', False)))


def synthetic_attempt_failure(cfg, row, attempt, code, **extra):
    """A worker failure is an actual failed attempt under its configured profile."""
    return dict(scene_id=row['scene_id'], split=row['split'], attempt=attempt,
                physics_success=False, recovery_used=False, failure_code=code,
                acceptance_profile=getattr(cfg, 'acceptance_profile', 'strict'),
                approximate_completion_enabled=bool(getattr(cfg, 'approximate_completion_enabled', False)),
                effective_acceptance_profile=('approximate_completion' if
                    getattr(cfg, 'approximate_completion_enabled', False) else
                    getattr(cfg, 'acceptance_profile', 'strict')),
                task_completed=False, strict_success=False, diagnostic_only=False,
                **extra)


@generation_termination_scope()
def generate(root, workers=4, limit=None, scene_ids=None):
    _CANCEL.clear()
    root=Path(root).resolve();cfg=config_for(root);assert_environment(root)
    rows=selected_rows(root,limit,scene_ids)
    preflight_coverage(root,selected_ids=[r['scene_id'] for r in rows])
    # Validate the entire requested slice before starting any attempt workers.
    for row in rows:
        if not (root/'scenes'/row['scene_id']/'preflight.json').is_file():
            raise Fault('scene_preflight_missing',row['scene_id'])
    def job(row):
        pf=root/'scenes'/row['scene_id']/'preflight.json'
        if not pf.exists(): raise Fault('scene_preflight_missing',row['scene_id'])
        if not json.loads(pf.read_text()).get('valid'): return {'scene_id':row['scene_id'],'status':'preflight_rejected'}
        directory=root/'attempts'/row['scene_id'];directory.mkdir(exist_ok=True)
        def existing():
            reports=[]
            for p in sorted(directory.glob('a*/result.json')):
                report=json.loads(p.read_text())
                expected=int(p.parent.name[1:])
                if (report.get('scene_id')!=row['scene_id'] or
                        report.get('attempt',expected)!=expected or not 0<=expected<cfg.max_attempts_per_scene):
                    raise Fault('attempt_result_identity_mismatch',str(p))
                q=p.parent/'export_quality.json'
                report['export_rejected']=q.exists() and json.loads(q.read_text()).get('status')=='rejected'
                reports.append(report)
            return reports
        reports=existing()
        successes=sum(attempt_stopping_success(r,cfg,resumed=True) for r in reports)
        required_successes=1 if getattr(cfg,'acceptance_profile','strict')=='completion_first' else cfg.successes_per_scene
        used={int(p.name[1:]) for p in directory.glob('a*') if p.is_dir() and p.name[1:].isdigit()}
        if sorted(used)!=list(range(len(used))) or any(a>=cfg.max_attempts_per_scene for a in used):
            raise Fault('attempt_directory_sequence_invalid',sorted(used))
        for attempt in range(cfg.max_attempts_per_scene):
            if successes>=required_successes:break
            if attempt in used:
                # Preserve interrupted raw data and account for it explicitly.
                p=directory/f'a{attempt:03d}'
                if not (p/'result.json').exists():
                    atomic_json(p/'result.json',synthetic_attempt_failure(
                        cfg,row,attempt,'interrupted_attempt_retained'))
                continue
            log=directory/f'a{attempt:03d}.log'
            if log.exists():log=directory/f'a{attempt:03d}_resume_{time.time_ns()}.log'
            code=run_child(['attempt','--root',root,'--scene-id',row['scene_id'],'--attempt',attempt],log,attempt_worker_timeout(cfg))
            p=directory/f'a{attempt:03d}'/'result.json'
            if not p.exists():
                atomic_json(p,synthetic_attempt_failure(cfg,row,attempt,
                    'worker_timeout' if code==124 else 'worker_crashed',exit_code=code))
            result=json.loads(p.read_text())
            if result.get('scene_id')!=row['scene_id'] or result.get('attempt',attempt)!=attempt:
                raise Fault('attempt_result_identity_mismatch',str(p))
            successes+=int(attempt_stopping_success(result,cfg))
        return {'scene_id':row['scene_id'],'clean_successes':successes,
                'stopping_success_semantics':'task_completed_including_recovery' if getattr(cfg,'acceptance_profile','strict')=='completion_first' else 'legacy_clean_physics',
                'status':'physics_ready' if successes>=required_successes else 'attempted_failed'}
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures=[pool.submit(job,row) for row in rows]
            try:
                for i,future in enumerate(as_completed(futures),1):
                    print(json.dumps({'finished':i,'selected':len(rows),**future.result()}),flush=True)
            except BaseException:
                for future in futures: future.cancel()
                stop_children();raise
    except BaseException:
        stop_children();raise
    return coverage(root)
