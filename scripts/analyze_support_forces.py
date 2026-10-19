"""Read-only force reconstruction from complete frozen MuJoCo trace states.

This standalone diagnostic imports no controller. Copy it and support_feedback.py
into an independent diagnostic directory when examining a frozen release.
Forces are reconstructed using mj_forward; original labels remain authoritative.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import h5py
import mujoco
import numpy as np
from scipy.spatial.transform import Rotation


def load_estimator(path):
    spec=importlib.util.spec_from_file_location('support_force_diagnostic_estimator',path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module.measure_support_force


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def descendants(model, names):
    roots={model.body(name).id for name in names}
    found=set()
    for bid in range(model.nbody):
        current=bid
        while current:
            if current in roots:
                found.add(bid);break
            current=int(model.body_parentid[current])
    return found


def decode(value):
    return value.decode() if isinstance(value,bytes) else str(value)


def analyze(root, attempt, output, measure):
    scene=attempt.parent.name
    scene_root=root/'scenes'/scene
    xml=scene_root/'mobile.xml'
    result=json.loads((attempt/'result.json').read_text())
    events=[json.loads(line) for line in (attempt/'events.jsonl').read_text().splitlines() if line.strip()]
    starts={int(e['frame']):e for e in events if e.get('event')=='primitive_start'}
    ends={int(e['frame']) for e in events if e.get('event') in ('primitive_complete','primitive_failed')}
    csv_path=output/f'{scene}_{attempt.name}.csv'
    model=mujoco.MjModel.from_xml_path(str(xml));data=mujoco.MjData(model)
    table_ids=descendants(model,('front_left','front_right','rear'))
    finger_ids={bid for bid in range(model.nbody) if 'gripper_finger' in model.body(bid).name}
    tray_ids=[model.body(f'tray_{i}').id for i in range(3)]
    push_segments={}
    with h5py.File(attempt/'trace.h5','r') as trace, csv_path.open('x',newline='',encoding='utf-8') as stream:
        metadata=json.loads(trace.attrs['metadata_json'])
        xml_hash=sha(xml)
        if xml_hash!=metadata['scene_xml_sha256']:
            raise ValueError(f'{scene}: frozen XML hash does not match recorded trace')
        model.actuator_forcerange[:]=np.asarray(metadata['limits']['actuator_forcerange'])
        state_type=mujoco.mjtState.mjSTATE_INTEGRATION
        if trace['integration_state'].shape[1]!=mujoco.mj_stateSize(model,state_type):
            raise ValueError(f'{scene}: integration state schema mismatch')
        fps=float(metadata['fps']);period=1/fps
        frames=len(trace['timestamp'])
        missing=np.zeros(3);push_missing=np.zeros(3)
        longest=np.zeros(3);force_max=np.zeros(3)
        active=None
        fields=['scene_id','attempt','frame','timestamp_s','primitive','primitive_start_frame','fsm_state','phase',
                'target_tray','tray','recorded_table_contact','reconstructed_qualifying_contacts',
                'table_normal_n','table_fx_n','table_fy_n','table_fz_n','gripper_fz_n',
                'recorded_min_z_m','recorded_roll_deg','recorded_pitch_deg','missing_table_s',
                'push_missing_table_s','restored_body_position_error_m']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        maximum_pose_error=0.
        for frame in range(frames):
            if frame in ends:active=None
            if frame in starts:active=starts[frame]
            mujoco.mj_setState(model,data,trace['integration_state'][frame],state_type)
            mujoco.mj_forward(model,data)
            target=int(trace['target_tray'][frame]);pose=trace['tray_pose'][frame]
            table=trace['table_contact'][frame];bottom=trace['min_z'][frame]
            primitive=active['primitive'] if active else ''
            start=int(active['frame']) if active else -1
            if primitive=='push' and start not in push_segments:
                push_segments[start]={'start_frame':start,'target_tray':target,'frames':0,
                                      'table_normal_peak_n':0.,'gripper_fz_min_n':None,'gripper_fz_max_n':None,
                                      'missing_frames':0,'longest_missing_s':0.,'min_z_max_m':None}
            for tray,bid in enumerate(tray_ids):
                support=measure(model,data,bid,table_ids)
                gripper=measure(model,data,bid,finger_ids)
                missing[tray]=missing[tray]+period if table[tray]<=0 else 0.
                is_push=primitive=='push' and target==tray
                push_missing[tray]=push_missing[tray]+period if is_push and table[tray]<=0 else 0.
                longest[tray]=max(longest[tray],missing[tray]);force_max[tray]=max(force_max[tray],support.load_n)
                angles=Rotation.from_quat(pose[tray,[4,5,6,3]]).as_euler('xyz',degrees=True)
                error=float(np.linalg.norm(data.body(bid).xpos-pose[tray,:3]))
                maximum_pose_error=max(maximum_pose_error,error)
                if is_push:
                    seg=push_segments[start];seg['frames']+=1
                    seg['table_normal_peak_n']=max(seg['table_normal_peak_n'],support.load_n)
                    for key,value,fn in [('gripper_fz_min_n',gripper.signed_normal_n,min),
                                         ('gripper_fz_max_n',gripper.signed_normal_n,max),
                                         ('min_z_max_m',float(bottom[tray]),max)]:
                        seg[key]=value if seg[key] is None else fn(seg[key],value)
                    seg['missing_frames']+=int(table[tray]<=0)
                    seg['longest_missing_s']=max(seg['longest_missing_s'],float(push_missing[tray]))
                writer.writerow(dict(zip(fields,[scene,attempt.name,frame,float(trace['timestamp'][frame]),primitive,start,
                    decode(trace['fsm_state'][frame]),decode(trace['phase'][frame]),target,tray,float(table[tray]),
                    support.qualifying_contact_count,support.signed_normal_n,*support.resultant_world_n,
                    gripper.signed_normal_n,float(bottom[tray]),float(angles[0]),float(angles[1]),
                    float(missing[tray]),float(push_missing[tray]),error])))
    summary={'scene_id':scene,'attempt':attempt.name,'source_trace':str(attempt/'trace.h5'),
             'source_xml_sha256':xml_hash,'frames':frames,'fps':fps,'csv':csv_path.name,
             'physics_success':result.get('physics_success'),'failure_code':result.get('failure_code'),
             'simulation_seconds':result.get('simulation_seconds'),
             'whole_trace_longest_missing_s_by_tray':longest.tolist(),
             'whole_trace_table_load_peak_n_by_tray':force_max.tolist(),
             'push_segments':list(push_segments.values()),'maximum_restored_body_position_error_m':maximum_pose_error}
    if maximum_pose_error>1e-8:
        raise ValueError(f'{scene}: restored state and recorded tray pose disagree: {maximum_pose_error}')
    return summary


def comparison(current, previous):
    old={(r['scene_id'],r['attempt']):r for r in previous['cases']}
    rows=[]
    for row in current['cases']:
        prior=old.get((row['scene_id'],row['attempt']))
        if prior is None:continue
        same=prior['source_xml_sha256']==row['source_xml_sha256']
        def metric(case,key):return max((seg[key] for seg in case['push_segments']),default=None)
        rows.append({'scene_id':row['scene_id'],'same_scene_xml':same,
                     'before_failure':prior['failure_code'],'after_failure':row['failure_code'],
                     'before_physics_success':prior['physics_success'],'after_physics_success':row['physics_success'],
                     'before_simulation_seconds':prior['simulation_seconds'],'after_simulation_seconds':row['simulation_seconds'],
                     'before_push_table_peak_n':metric(prior,'table_normal_peak_n'),
                     'after_push_table_peak_n':metric(row,'table_normal_peak_n'),
                     'before_push_longest_missing_s':metric(prior,'longest_missing_s'),
                     'after_push_longest_missing_s':metric(row,'longest_missing_s')})
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--cases',type=int,nargs='+',required=True)
    parser.add_argument('--output-directory',type=Path,required=True)
    parser.add_argument('--estimator',type=Path)
    parser.add_argument('--compare',type=Path)
    args=parser.parse_args()
    estimator=args.estimator or Path(__file__).with_name('support_feedback.py')
    if not estimator.exists():estimator=Path(__file__).resolve().parents[1]/'r1pro_teleop/airport_fsm/support_feedback.py'
    measure=load_estimator(estimator)
    root=args.root.resolve();output=args.output_directory.resolve()
    if output==root or root in output.parents:
        raise ValueError('Diagnostic output must be outside the frozen collection')
    selected=[]
    for index in args.cases:
        matches=sorted(path for path in (root/'attempts').glob(f'airport_{index:04d}_*/a*') if path.is_dir())
        if not matches:raise ValueError(f'Missing requested case {index}')
        for attempt in matches:
            if not (attempt/'result.json').is_file():raise ValueError(f'Incomplete attempt: {attempt}')
            selected.append(attempt)
    output.mkdir(parents=True,exist_ok=False)
    report={'qualification':'read_only_mj_forward_force_reconstruction_not_new_labels_or_accepted_episodes',
            'root':str(root),'mujoco_version':mujoco.__version__,
            'script_sha256':sha(__file__),'estimator_sha256':sha(estimator),
            'missing_time_semantics':'20 Hz sample durations; terminal rejected substep is not a complete recorded interval; full-trace missing time includes carrying',
            'cases':[]}
    for attempt in selected:
        row=analyze(root,attempt,output,measure);report['cases'].append(row)
        print(json.dumps({'scene_id':row['scene_id'],'frames':row['frames'],'push_segments':row['push_segments']}),flush=True)
    if args.compare:report['comparison']=comparison(report,json.loads(args.compare.read_text()))
    with (output/'summary.json').open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)


if __name__=='__main__':main()
