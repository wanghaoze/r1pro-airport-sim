"""Independent read-only check of physical timing, release and video closure."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.isaac_dataset import video_probe,sha


def audit(case, *, receipt_path=None):
    case=Path(case);result=json.loads((case/'result.json').read_text());errors=[]
    if result.get('scope')=='physics_only_probe_not_video_demo' or result.get('video_demo_complete') is False:
        return dict(schema='isaac_fast_pickplace_independent_audit/1',passed=False,
                    errors=['physics_only_probe_is_not_a_closed_video_demo'],case=str(case),
                    model_executed=False,training_eligible=False)
    receipt=json.loads((Path(receipt_path) if receipt_path is not None else case.parent/(case.name+'.exit.json')).read_text())
    if receipt.get('actual_child_wait') is not True or receipt['returncode']!=0:errors.append('actual_native_wait_not_zero')
    if not result['passed'] or result['model_executed'] or result['training_eligible']:errors.append('benchmark_scope_or_status_invalid')
    z=np.load(case/'native_trace.npz');n=len(z['raw_action']);spans=result['actions'];evidence=[]
    if len(z['state'])!=n+1 or z['submitted_control'].shape[:2]!=(n,25):errors.append('state_control_substep_alignment')
    if not all(np.isfinite(z[k]).all() for k in ('state','raw_action','submitted_control','tray_pose')):errors.append('nonfinite_native_record')
    mapping=json.loads((case/'native_mapping.json').read_text());height=next(t for t in mapping['task_tables'] if t['table_id']=='front_left');height=float(height['center_world'][2]+height['dimensions_m'][2])
    footprint_review=None
    if result.get('case',{}).get('exact_collision_footprint',False):
        import hashlib
        from scipy.spatial.transform import Rotation
        from r1pro_teleop.real2sim.isaac_collision_footprint import maximum_union_overhang
        row=json.loads((case/'tray_0_collision_footprint.json').read_text());points=np.asarray(row['body_local_vertices_m'],float)
        if (row['vertices_sha256']!=hashlib.sha256(points.tobytes()).hexdigest() or
                row['validated_scene_sha256']!=mapping['scene_sha256'] or row['geometry_modified'] or row['tolerance_modified']):
            errors.append('native_collision_footprint_identity_invalid')
        distances=[]
        for pose in z['tray_pose'][:,0]:
            R=Rotation.from_quat(pose[[4,5,6,3]]).as_matrix()
            distances.append(maximum_union_overhang(points@R.T+pose[:3],mapping['task_tables']))
        if not np.array_equal(np.asarray(distances)<=.05,z['boundary_ok'][:,0]):errors.append('native_collision_boundary_recalculation_mismatch')
        footprint_review=dict(mode='native_collision_vertices',maximum_actual_overhang_m=max(distances),tolerance_m=.05,
                              old_failed_labels_unchanged=True,measurement_correction_not_control_accuracy_improvement=True)
    for span in spans:
        lo,hi=span['start'],span['end'];actual_time=float(z['time'][hi]-z['time'][lo]);q=z['raw_action'][lo:hi][:,[7,15]]
        diverse=result.get('case',{}).get('diverse_preadjustment',False)
        core=span.get('core_motion_start',lo) if diverse else lo
        if (hi-core!=60 or abs(float(z['time'][hi]-z['time'][core])-3.)>2e-5 or
                abs(actual_time-(hi-lo)/20)>2e-5 or core<lo):errors.append('physical_three_second_time_invalid')
        if not diverse and hi-lo!=60:errors.append('unexpected_preparation_in_legacy_benchmark')
        if q.min()<0 or q.max()>.08+1e-7:errors.append('raw_gripper_outside_0_80mm')
        if span['prompt']=='Pick up the tray':
            lift=float(z['tray_pose'][hi,0,2]-z['tray_pose'][lo,0,2]);force=z['finger_contact_force'][hi-1,-1,0];edges=z['long_edge_sign'][hi,0]
            if lift<.02 or np.min(force)<=.5 or np.prod(edges)!=-1 or z['table_force'][hi-1,-1,0]>.01:errors.append('actual_pick_endpoint_unverified')
            evidence.append(dict(prompt=span['prompt'],actual_seconds=actual_time,core_motion_seconds=float(z['time'][hi]-z['time'][core]),included_preparation_seconds=float(z['time'][core]-z['time'][lo]),actual_lift_m=lift,actual_finger_force_n=force.tolist(),opposed_long_edges=bool(np.prod(edges)==-1)))
        elif span['prompt']=='Place the tray':
            release=lo+28;gap=float(z['tray_pose'][release,0,2]-height)
            if gap>.02:errors.append('actual_release_above_2cm')
            opening=z['raw_action'][release:release+8][:,[7,15]]
            if not np.all(opening[0]>z['raw_action'][release-1,[7,15]]) or not np.all(opening[-1]>=.08-1e-7):errors.append('actual_release_ramp_not_at_declared_frames')
            forces=z['finger_contact_force'][hi-10:hi,-1,0];support=z['table_force'][hi-10:hi,-1,0];speed=np.linalg.norm(np.diff(z['tray_pose'][hi-10:hi+1,0,:3],axis=0),axis=1)*20
            if np.max(forces)>.5 or np.min(support)<=.01 or np.max(speed)>=.01 or not z['boundary_ok'][hi,0]:errors.append('actual_place_final_support_release_or_boundary_unverified')
            evidence.append(dict(prompt=span['prompt'],actual_seconds=actual_time,actual_release_gap_m=gap,final_table_force_n=float(support[-1]),final_finger_force_n=forces[-1].tolist(),maximum_final_speed_m_s=float(speed.max())))
        else:errors.append('unexpected_benchmark_prompt')
    if [s['prompt'] for s in spans]!=['Pick up the tray','Place the tray']:errors.append('missing_action_pair')
    videos={}
    for camera,row in result['native_encoders'].items():
        path=Path(row['path']);probe=video_probe(path)
        if probe['frames']!=n or probe['fps']!=20 or row['returncode']!=0:errors.append('native_video_not_closed:'+camera)
        videos[camera]=dict(**probe,sha256=sha(path),path=str(path))
    count=0
    for line in (case/'native_steps.jsonl').open():
        row=json.loads(line)
        if row['frame']!=count or row['completed_real_substeps']!=25:errors.append('native_substep_journal_invalid');break
        count+=1
    if count!=n:errors.append('native_substep_journal_incomplete')
    visual=json.loads((case/'visual_translation.json').read_text())
    if not visual['physics_and_original_cameras_unchanged'] or visual['room_objects']!=45:errors.append('visual_equivalence_not_closed')
    return dict(schema='isaac_fast_pickplace_independent_audit/1',passed=not errors,errors=errors,
        scope='native_fast_benchmark_not_full_three_tray_not_model_test',case=str(case),source_result_sha256=sha(case/'result.json'),
        trace_sha256=sha(case/'native_trace.npz'),frames=n,real_substeps=25*n,original_speed=True,model_executed=False,training_eligible=False,
        actions=evidence,videos=videos,motion=result['motion'],visual=visual,boundary_measurement=footprint_review)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--case',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=audit(a.case);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('videos','visual')},indent=2));raise SystemExit(0 if result['passed'] else 1)
