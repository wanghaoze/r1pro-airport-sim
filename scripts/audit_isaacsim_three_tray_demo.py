"""Independent read-only closure audit of a completed native three-tray demo."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.isaac_dataset import validate_episode,sha


def main():
    p=argparse.ArgumentParser();p.add_argument('--case',type=Path,required=True);p.add_argument('--registry',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('audit_receipt_is_immutable')
    row=validate_episode(a.case,json.loads(a.registry.read_text()))
    q=json.loads((a.case/'qualification.json').read_text());events=json.loads((a.case/'observer_events.json').read_text())
    mapping=json.loads((a.case/'native_mapping.json').read_text())
    base=next(i for i,s in enumerate(mapping['sensor_paths']) if Path(s).name=='base_link')
    traces=np.load(a.case/'native_trace.npz',allow_pickle=False);cycles=[]
    for cycle in q['cycles']:
        ti=int(cycle['tray_id'].split('_')[-1]);stages={e['stage']:e['frame'] for e in events
            if e['event']=='actual_push_stage_start' and e['tray_id']==cycle['tray_id']}
        f=stages['left_push'];end=stages['left_release']
        # The observer freezes its left axis at RIGHT push start, then resets
        # only the tray origin for LEFT push. Use the same recorded reference.
        axis_frame=stages['right_push'];quat=traces['rigid_pose'][axis_frame,base,3:]
        left=Rotation.from_quat(quat[[1,2,3,0]]).as_matrix()[:,1]
        delta=(traces['tray_pose'][f:end+1,ti,:3]-traces['tray_pose'][f,ti,:3])@left
        measured=float(delta.max())
        if measured<.03 or abs(measured-cycle['actual_tray_left_displacement_m'])>2e-5:
            raise ValueError('recorded_native_tray_motion_does_not_close:'+cycle['tray_id'])
        stable=int(cycle['left_stable_grasp_frame']);released=int(cycle['actual_right_release_frame'])
        if not stable<=released<=f<end:raise ValueError('actual_handover_time_order_invalid')
        before=traces['finger_contact_force'][stable-1,-1,ti]
        after=traces['finger_contact_force'][released-1,-1,ti]
        if not np.all(before>.5) or after[0]<=.5 or after[1]>.5:
            raise ValueError('recorded_handover_forces_do_not_close')
        if traces['action'][released-1,15]<.1-1e-7:raise ValueError('right_release_command_absent')
        cycles.append(dict(tray_id=cycle['tray_id'],cycle_id=cycle['cycle_id'],
            actual_right_tray_displacement_m=cycle['actual_right_tray_displacement_m'],
            independently_measured_left_tray_displacement_m=measured,left_axis_reference_frame=axis_frame,left_stable_frame=stable,
            actual_right_release_frame=released,left_push_frame=f,left_release_frame=end,
            actual_place_axis_error_deg=float(np.rad2deg(cycle['actual_place_axis_error_rad']))))
    n=row['frames'];count=0
    for line in (a.case/'native_steps.jsonl').read_text().splitlines():
        step=json.loads(line)
        if step['frame']!=count or step['completed_real_substeps']!=25:raise ValueError('native_step_journal_not_closed')
        if not np.allclose(step['raw_action'],traces['raw_action'][count]):raise ValueError('raw_action_journal_mismatch')
        count+=1
    if count!=n:raise ValueError('actual_interval_count_differs_from_media')
    if not np.all(traces['payload_loaded'][-1]) or not np.all(traces['payload_on_tray'][-1]):raise ValueError('final_three_payload_sets_missing')
    if np.any(traces['payload_speed'][-1]>=.01) or not np.all(traces['boundary_ok'][-1]):raise ValueError('final_native_support_or_boundary_not_closed')
    if np.max(traces['finger_contact_force'][-1,-1])>.5:raise ValueError('final_release_not_closed')
    last=json.loads((a.case/'native_contacts.jsonl').read_text().splitlines()[-1]);upward={f'tray_{i}':0. for i in range(3)}
    for contact in last['contacts']:
        name=contact['sensor']
        if name in upward and contact['other'] in ('front_left','front_right','rear'):
            upward[name]+=max(0.,contact['normal_force_n']*contact['normal_world'][2])
    if min(upward.values())<=0:raise ValueError('table_contact_has_no_upward_support_witness')
    drift_evidence=dict(recorded=False)
    if 'front_manipulating' in traces:
        from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
        mask=np.asarray(traces['front_manipulating'],bool);positions=traces['rigid_pose'][:,base,:2]
        references=traces['front_reference_xy'];drift=np.linalg.norm(positions-references,axis=1)
        if mapping.get('front_drift_limit_m')!=.05:raise ValueError('native_front_drift_contract_changed')
        for frame in np.flatnonzero(mask):
            ti=int(traces['front_reference_table_index'][frame]);table=mapping['task_tables'][ti]
            if (ti<0 or table_front_region_violation(table,references[frame]) or drift[frame]>.05+1e-9 or
                    not traces['front_region_ok'][frame] or abs(drift[frame]-traces['front_drift_m'][frame])>1e-6):
                raise ValueError('native_front_reference_or_drift_witness_invalid')
        drift_evidence=dict(recorded=True,strict_front_reference_preserved=True,
            authorized_limit_m=.05,actual_maximum_manipulation_drift_m=float(drift[mask].max()) if mask.any() else 0.,
            frames_using_authorized_drift=int(np.asarray(traces['front_allowance_used'])[mask].sum()))
    result=dict(scope='native_expert_complete_three_tray_demo_not_vla_model_execution',passed=True,
        full_sources=1,action_segments=len(row['actions']),frames=n,control_hz=20,actual_recorded_substeps=25*n,
        trace_sha256=row['trace_sha256'],qualification_sha256=row['qualification_sha256'],cycles=cycles,
        last_recorded_pre_action_upward_table_support_n=upward,actual_final_table_force_n=traces['table_force'][-1,-1].tolist(),
        actual_final_payload_max_speed_m_s=traces['payload_speed'][-1].tolist(),
        all_three_payload_sets_on_trays=True,final_grippers_released=True,all_three_final_boundaries_pass=True,
        model_executed=False,teacher_only_for_collection=True,physics_engine='isaacsim/physx',front_drift_evidence=drift_evidence,
        videos=row['videos'],native_step_journal_sha256=sha(a.case/'native_steps.jsonl'),
        timestamp_semantics='NPZ time[i] = pre-action RGB/state; native_steps.sim_time = completed interval end')
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
