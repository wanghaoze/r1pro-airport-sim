"""Read-only CPU planning of whole actions from complete simulation tasks.

Every inventory source produces one output row, including explicit exclusions.
No simulation execution, model loading, video processing or training occurs.
"""
from pathlib import Path
import argparse
from collections import Counter
import hashlib
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import h5py
from r1pro_teleop.vla.data_task_segments import complete_action_segments
from r1pro_teleop.vla.data_task_labels import ACTION_VOCABULARY, PROFILE, label_complete_action


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def verified_path(row,key,root):
    path=Path(row[key]).resolve(strict=True)
    if not path.is_relative_to(root):raise ValueError('source_path_outside_collection:'+key)
    if sha(path)!=row[key+'_sha256']:raise ValueError('source_sha_changed:'+key)
    return path


def plan_source(row):
    root=Path(row['collection']).resolve(strict=True)
    paths={key:verified_path(row,key,root) for key in
           ('trace','result','segments','events','physical_events','scene_json','scene_xml')}
    attempt=Path(row['attempt']).resolve(strict=True)
    if paths['trace'].parent!=attempt or paths['result'].parent!=attempt:
        raise ValueError('source_attempt_association_mismatch')
    scene=read(paths['scene_json']);result=read(paths['result']);phases=read(paths['segments'])
    if (scene['scene_id']!=row['scene_id'] or scene['split']!=row['split'] or
        result.get('scene_id')!=row['scene_id'] or result.get('split')!=row['split']):
        raise ValueError('scene_result_inventory_identity_mismatch')
    if result.get('task_completed') is not True or row.get('task_completed') is not True:
        raise ValueError('source_task_not_completed')
    intent=[json.loads(line) for line in paths['events'].read_text(encoding='utf-8').splitlines() if line.strip()]
    physical=read(paths['physical_events'])
    # Stable sorting preserves original same-frame intent event order. Physical
    # evidence follows intent at ties and never invents a transition.
    events=sorted(intent+physical,key=lambda e:e['frame'])
    with h5py.File(paths['trace'],'r') as trace:
        metadata=json.loads(trace.attrs['metadata_json'])
        schema=trace.attrs.get('schema','')
        if isinstance(schema,bytes):schema=schema.decode()
        if schema not in ('airport_fsm_raw/1','airport_fsm_raw/2'):
            raise ValueError('unsupported_raw_schema')
        if (metadata.get('scene')!=scene or metadata.get('scene_xml_sha256')!=row['scene_xml_sha256'] or
            metadata.get('controller_source','program_generated')!='program_generated'):
            raise ValueError('raw_metadata_source_identity_mismatch')
        n=int(trace.attrs['num_frames']);fps=float(metadata['fps'])
        if n!=row['frames'] or n!=result['frames'] or fps!=20:
            raise ValueError('raw_frame_count_or_fps_mismatch')
        complete=trace['transition_completed'][:].astype(bool)
        if len(complete)!=n or not complete.all():raise ValueError('incomplete_raw_control_interval')
        times=trace['sim_time'][:]
        if times.shape!=(n,) or not np.isfinite(times).all() or (n>1 and not np.allclose(np.diff(times),1/fps,atol=1e-8,rtol=0)):
            raise ValueError('raw_time_grid_mismatch')
        terminal=json.loads(trace.attrs['terminal_snapshot_json'])
        if (not np.isfinite(float(terminal['time'])) or abs(float(terminal['time'])-times[-1]-1/fps)>1e-8 or
            not np.isfinite(terminal['qpos']).all() or not np.isfinite(terminal['qvel']).all()):
            raise ValueError('raw_terminal_incomplete')
        for key,width in (('state',16),('action',16),('base_action',3)):
            value=trace[key][:]
            if value.shape!=(n,width) or not np.isfinite(value).all():raise ValueError('raw_numeric_contract:'+key)
        raw_states=[x.decode() if isinstance(x,bytes) else str(x) for x in trace['fsm_state'][:]]
        raw_phases=[x.decode() if isinstance(x,bytes) else str(x) for x in trace['phase'][:]]
        for phase in phases:
            a,b=phase['start_frame'],phase['end_frame']
            if not 0<=a<b<=n or any(value!=phase['state'] for value in raw_states[a:b]) or any(value!=phase['phase'] for value in raw_phases[a:b]):
                raise ValueError('phase_partition_disagrees_with_raw_trace')
        numeric={key:trace[key][:].tolist() for key in
                 ('target_tray','gripper_contact_force','support_contact','floor_contact','min_z')}
        contact=float(metadata['config']['criteria']['contact_n'])
        provenance=dict(scene_id=row['scene_id'],split=row['split'],trace=str(paths['trace']),
            trace_sha256=row['trace_sha256'],result=str(paths['result']),result_sha256=row['result_sha256'],
            scene_sha256=row['scene_json_sha256'],scene_xml_sha256=row['scene_xml_sha256'],
            collection=str(root),attempt=str(attempt),source='simulation/program_generated',
            observation_semantics=metadata.get('observation_semantics','state/images before action interval'),
            action_layout='mobile19',action_semantics='absolute_mobile19',
            source_segments_sha256=row['segments_sha256'],source_events_sha256=row['events_sha256'],
            source_physical_events_sha256=row['physical_events_sha256'])
        plan=complete_action_segments(phases,events,result,num_frames=n,fps=fps,
            transition_completed=complete,provenance=provenance,numeric_evidence=numeric,contact_threshold_n=contact,
            lifted_threshold_m=float(metadata['config']['criteria']['lifted_m']))
    # Reverify bytes after reading; a changing source is never published.
    for key,path in paths.items():
        if sha(path)!=row[key+'_sha256']:raise ValueError('source_changed_during_planning:'+key)
    labeled=[]
    excluded=[]
    for segment in plan['segments']:
        training,inventory=label_complete_action(segment)
        if training is not None:labeled.append(training)
        if inventory is not None:excluded.append(inventory)
    plan['boundary_segments']=plan['segments']
    plan['segments']=labeled
    plan['label_excluded_actions']=excluded
    for excluded_action in excluded:
        excluded_action['reason']=excluded_action['exclusion_reason']
    plan['inventory'].extend(excluded)
    plan['language_profile']=PROFILE
    plan['training_labeled_frames_with_explicit_overlap']=sum(r['frames'] for r in labeled)
    plan['temporary_carry_frames_preserved_raw_only']=sum(r['frames'] for r in excluded)
    return plan


def write_plans(inventory,output,label_spec,*,limit=None):
    inventory=Path(inventory).resolve(strict=True);output=Path(output).resolve();label_spec=Path(label_spec).resolve()
    rows=[json.loads(line) for line in inventory.read_text(encoding='utf-8').splitlines() if line.strip()]
    if limit is not None:rows=rows[:limit]
    if output.exists() or label_spec.exists():raise FileExistsError('Fresh plan/spec files required')
    if output==label_spec or output==inventory or label_spec==inventory:raise ValueError('Output paths must be distinct')
    for row in rows:
        root=Path(row['collection']).resolve()
        if output.is_relative_to(root) or label_spec.is_relative_to(root):raise ValueError('Never write source collection')
    output.parent.mkdir(parents=True,exist_ok=True);label_spec.parent.mkdir(parents=True,exist_ok=True)
    spec=dict(schema='airport_complete_task_action_label_spec/1',language_profile=PROFILE,label_profile=PROFILE,
        action_vocabulary=ACTION_VOCABULARY,mapping_status='user_confirmed',mapping_assumptions=[],
        final_slot_to_position={'slot_0':1,'slot_1':2,'slot_2':3},
        temporary_policy='Keep full source task; exclude temporary carry from action training',
        source_inventory=str(inventory),source_inventory_sha256=sha(inventory),
        whole_source_task_success_is_not_automatic_skill_qualification=True,
        action_episode_overlap='Explicit supported-push whole-place windows overlap push action episodes; raw source frames remain unique')
    with label_spec.open('x',encoding='utf-8') as stream:json.dump(spec,stream,indent=2)
    counts=Counter();failures=[]
    with output.open('x',encoding='utf-8') as stream:
        for index,row in enumerate(rows):
            record=dict(schema='airport_complete_task_action_plan_record/1',source_index=index,
                        scene_id=row.get('scene_id'),split=row.get('split'),original_inventory=row,
                        label_spec=str(label_spec),label_spec_sha256=sha(label_spec))
            try:
                plan=plan_source(row)
                record.update(status='planned',plan=plan,segments=plan['segments'],inventory=plan['inventory'],
                    raw_frames=plan['raw_frames'],action_candidate_frames=plan['action_candidate_frames'],
                    training_labeled_frames_with_explicit_overlap=plan['training_labeled_frames_with_explicit_overlap'])
                counts['planned_sources']+=1;counts['action_episodes']+=len(plan['segments'])
                counts['raw_unique_frames']+=plan['raw_frames']
                for segment in plan['segments']:counts['label:'+segment['action_label']]+=1
            except Exception as exc:
                record.update(status='excluded_from_action_plan_source_raw_preserved',excluded_reason=f'{type(exc).__name__}:{exc}')
                counts['excluded_sources']+=1;failures.append(dict(scene_id=row.get('scene_id'),reason=record['excluded_reason']))
            stream.write(json.dumps(record,allow_nan=False)+'\n');stream.flush()
            print(json.dumps(dict(source=index,scene_id=row.get('scene_id'),status=record['status'],excluded_reason=record.get('excluded_reason'))),flush=True)
    report=dict(schema='airport_complete_task_action_plan_summary/1',status='completed',
        source_rows=len(rows),output_rows=len(rows),counts=dict(counts),excluded_sources=failures,
        output=str(output),output_sha256=sha(output),label_spec=str(label_spec),label_spec_sha256=sha(label_spec),
        source_inventory_sha256=sha(inventory),cpu_only=True,training_started=False,rendering_started=False)
    with output.with_suffix('.summary.json').open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--label-spec',required=True);parser.add_argument('--limit',type=int)
    args=parser.parse_args(argv)
    if args.limit is not None and args.limit<1:parser.error('--limit must be positive')
    print(json.dumps(write_plans(args.inventory,args.output,args.label_spec,limit=args.limit),indent=2))


if __name__=='__main__':main()
