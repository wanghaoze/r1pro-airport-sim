"""Independent whole-task collection with actual pre-action observer evidence.

Never resumes/relabels a diagnostic source. No model training is launched here.
"""
from pathlib import Path
import json,hashlib,shutil,time,traceback
from dataclasses import asdict,replace
import numpy as np
from ..airport_fsm.contracts import Config,State,atomic_json,json_default
from ..airport_fsm.geometry import Operation,quat_yaw_tilt
from ..single_tray_lab.control import ControlProfile
from ..single_tray_lab.three_table_scene import passenger_load_three_table
from ..vla.data_three_table_single_tray import PROFILE,RULE_REVISION,FINAL_ORIENTATION_DEFINITION
from .control import ThreeTableRuntime,ThreeTableMachine,horizontal_axis_alignment_error
from .loaded_bridge import LoadedBridgeController,derive_bridge_profile
from .observer import ThreeTableObserver,normalize_observed_trace,normalize_observer_events

def existing_confirmation_rule(cfg,reference_profile):
    """Describe the existing two controllers; never impose nominal-close on contact-stop."""
    if cfg.fps!=20 or reference_profile.fps!=20 or reference_profile.stable_contact_frames!=3 or reference_profile.contact_n!=cfg.criteria.contact_n or reference_profile.open_command!=cfg.gripper_open_m:raise ValueError('existing_controller_confirmation_rules_differ_require_explicit_contract')
    rule=dict(schema='airport_existing_grasp_confirmation_rule/1',stable_duration_s=.15,contact_n=cfg.criteria.contact_n,release_evidence_mode='existing_low_force_commanded_open',existing_open_command_m=cfg.gripper_open_m,old_close_semantics='contact_stop_then_existing_150ms_bilateral_force_wait',loaded_close_semantics='existing_nominal_command_then_three_stable_measured_force_frames',nominal_close_command_is_not_a_measured_aperture_acceptance_gate=True)
    rule['rule_id']='sha256:'+hashlib.sha256(json.dumps(rule,sort_keys=True).encode()).hexdigest()
    return rule

def collect(scene_path,config_path,reference_path,output,*,confirmation_rule=None,disable_axis_feedback=False):
    out=Path(output);out.mkdir(parents=True,exist_ok=False);scene_path=Path(scene_path)
    scene=json.loads(scene_path.read_text());reference=json.loads(Path(reference_path).read_text());cfg=Config.load(config_path)
    if scene.get('task_rule_revision')!=RULE_REVISION or scene.get('final_orientation_definition')!=FINAL_ORIENTATION_DEFINITION:raise ValueError('fresh_forward_scene_required')
    (out/'scene').mkdir();shutil.copyfile(scene_path,out/'scene/scene.json')
    from ..airport_fsm import runtime as runtime_module,machine as machine_module,primitives as primitives_module
    from ..single_tray_lab import control as inherited_control_module
    sources=[Path(runtime_module.__file__),Path(machine_module.__file__),Path(primitives_module.__file__),Path(inherited_control_module.__file__),Path(__file__),Path(__file__).with_name('observer.py'),Path(__file__).with_name('loaded_bridge.py'),Path(__file__).with_name('control.py')]
    bindings={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources};controller_sha=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    rule=dict(confirmation_rule or existing_confirmation_rule(cfg,ControlProfile(**reference['control_profile']).validate()),controller_sha256=controller_sha,transition_journal_complete=True)
    r=ThreeTableRuntime(scene,cfg);m=ThreeTableMachine(r,out/'original_attempt',scene);bridge=[None];release_start=[None]
    def environment_numeric():
        if bridge[0] is not None:
            c=bridge[0];e=c.observation();connected=c._contacts()['supported_payload_entities'];supported=[]
            for name in ('passenger_laptop','passenger_backpack','passenger_coat'):
                if name=='passenger_coat':supported.append('payload_flex' in connected)
                else:supported.append(bool(c._descendants(c.m.body(name).id)&connected))
            return dict(payload_supported_objects=np.asarray(supported,bool),payload_loaded=e['payload_loaded'],payload_mass=e['payload_mass_kg'],floor_contact=e['payload_floor_contacts']+int(observer.old_observation()['floor_contact'][0]),tray_clearance=float(r.observation()['min_z'][0]-r.initial_bottom[0]),tray_goal_reached=bool(c.loaded_goal_reached(e)))
        e=observer.old_observation()
        return dict(payload_supported_objects=np.zeros(3,bool),payload_loaded=False,payload_mass=0.,floor_contact=np.int32(e['floor_contact'][0]),tray_clearance=float(e['min_z'][0]-r.initial_bottom[0]),tray_goal_reached=False)
    observer=ThreeTableObserver(r,scene,numeric_provider=environment_numeric,confirmation_rule=rule,guard_domain_provider=lambda: bool(bridge[0] is not None and bridge[0]._in_push_contact_domain()))
    original_transition=m.transition
    def transition(state,phase,**kw):
        result=original_transition(state,phase,**kw)
        table=scene['source_table'] if observer.action and observer.action[0]=='pick_empty' else scene['target_table']
        observer.set_operation_region(table,state in (State.APPROACH_TRAY,State.GRASP_TRAY,State.ADJUST_TRAY,State.PLACE_TRAY))
        if state==State.GRASP_TRAY and phase=='load_transfer':observer.confirm_grasp(('left','right'),stable_frames=3,contact_n=cfg.criteria.contact_n)
        if state==State.PLACE_TRAY and phase=='open':release_start[0]=m.log.count;observer.begin_release(('left','right'))
        return result
    m.transition=transition;started=time.monotonic();result=dict(task_profile=PROFILE,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,task_completed=False,physics_success=False,training_eligible=False,source='simulation/program_generated',scene_id=scene['scene_id'],split=scene['split'])
    try:
        observer.begin_action('pick_empty',table_id=scene['source_table'],manipulating=False);r.allowed_tray=0;r.target_slot=0
        m.transition(State.ALIGN_BASE,'initial_posture',tray=0,slot=0);r.joints(r.tucked,minimum_seconds=.3)
        face,offset=m.prepare_pick(0,0);m.grasp(0,face,offset)
        r.tick();observer.complete_action(verified=True,measured_endpoint_frame=m.log.count-1)
        observer.begin_action('place_empty',table_id=scene['target_table'],manipulating=False)
        p=scene['place_target'];position=np.asarray(p['position_world'],float);yaw=float(p['yaw_world']);m.g.goals[0]=position;m.g.goal_yaw[0]=yaw
        m.carry_place(Operation(0,0,position,yaw));e=r.observation()
        error=horizontal_axis_alignment_error(r.d.body('tray').xmat.reshape(3,3)[:,0],r.d.body('base_link').xmat.reshape(3,3)[:,0])
        if e['support_contact'][0]<=0 or np.any(e['gripper_contact_force'][0]>cfg.criteria.contact_n) or error>np.deg2rad(15):raise ValueError('actual_empty_place_endpoint_unverified')
        if release_start[0] is None:raise ValueError('actual_release_start_event_missing')
        observer.release_grasp(('left','right'));r.tick();observer.complete_action(verified=True,measured_endpoint_frame=m.log.count-1,release_start_frame=release_start[0])
        profile=derive_bridge_profile(r,scene,ControlProfile(**reference['control_profile']).validate())
        if disable_axis_feedback:profile=replace(profile,push_axis_feedback_enabled=False).validate()
        c=LoadedBridgeController.bind(r,profile,passenger_loader=lambda sim:passenger_load_three_table(sim,scene),observer=observer);bridge[0]=c
        original_release=c.release
        def recorded_release(sides,**kwargs):
            observer.begin_release(sides);return original_release(sides,**kwargs)
        c.release=recorded_release
        c.passenger_load();c.push_loaded();e=c.observation()
        completed=bool(c.handover_verified and c.loaded_goal_reached(e) and e['payload_support_contacts']>0 and max(e['gripper_contact_force'].values())<=profile.contact_n)
        if len(observer.spans)!=3 or not completed:raise ValueError('actual_full_task_endpoint_unverified')
        result.update(task_completed=True,physics_success=True,training_eligible=True,actual_handover_verified=True)
    except Exception as exc:
        result.update(error_code=getattr(exc,'code',type(exc).__name__),error=str(exc));(out/'exception.txt').write_text(traceback.format_exc())
    finally:
        if bridge[0] is not None:
            result['robot_payload_contact_statistics']=bridge[0].robot_payload_contact_statistics()
            bridge[0].event('actual_robot_payload_contact_summary',statistics=result['robot_payload_contact_statistics'],
                qualification='diagnostic_actual_contacts_not_grasp_support_or_task_success')
        observer.detach();m.log.file.attrs['terminal_snapshot_json']=json.dumps(dict(qpos=r.d.qpos.tolist(),qvel=r.d.qvel.tolist(),time=float(r.d.time)))
        original_meta=json.loads(m.log.file.attrs['metadata_json']);frames=m.log.count;m.log.close();r.sim.close()
        result.update(frames=frames,sim_seconds=float(r.d.time),wall_seconds=time.monotonic()-started,action_spans=observer.spans,qualification_limits=dict(contact_n=cfg.criteria.contact_n,lifted_m=cfg.criteria.lifted_m,final_yaw_tolerance_rad=float(np.deg2rad(15))))
        meta=dict(original_meta,table_contact_semantics='actual_mujoco_tray_table_contacts_without_force_cutoff_matching_loaded_bridge',task_profile=PROFILE,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,scene=scene,fps=20,integration_state_spec=int(r.integration_spec),scene_xml_sha256=scene['xml_sha256'],base_mode='planar_mobile_table_front',base_actuated=True,model_action_mask=[True]*19,controller_sha256=controller_sha,controller_source_bindings=bindings,contact_evidence_semantics='actual_mujoco_finger_tray_contacts_local',grasp_confirmation_rule=rule,qualification_limits=result['qualification_limits'])
        if bridge[0] is not None:
            from ..vla.data_single_tray import canonical_hash
            bp=bridge[0].p
            meta['robot_payload_contact_statistics']=result['robot_payload_contact_statistics']
            meta['payload_support_object_order']=['laptop','backpack','coat'];meta['payload_support_evidence_semantics']='actual_tray_contact_graph_registered_payload_entities'
            meta['loaded_bridge_profile']=asdict(bp);meta['loaded_bridge_profile_sha256']=canonical_hash(meta['loaded_bridge_profile'])
            meta['table_support_acceptance_rule']=dict(schema='airport_recorded_table_support_acceptance/1',controller_sha256=controller_sha,loaded_bridge_profile_sha256=meta['loaded_bridge_profile_sha256'],coverage='every_guarded_physics_substep',table_geometry_sha256=canonical_hash(scene['tables']),existing_footprint_margin_m=float(getattr(bp,'supported_boundary_margin_m',.005)),extra_transient_footprint_margin_m=bp.push_transient_boundary_extra_m,grace_duration_s=bp.push_table_contact_grace_frames/bp.fps,gap_cap_m=bp.push_table_contact_grace_gap_m,physics_timestep_s=float(r.m.opt.timestep),substeps_per_interval=int(r.sim.nstep))
        attempt=out/'attempt';attempt.mkdir()
        if frames:
            receipt=normalize_observed_trace(out/'original_attempt/trace.h5',attempt/'trace.h5',metadata=meta)
        else:
            receipt=dict(frames=0,source_unchanged=True,training_ready=False,unavailable_reason='no_recorded_physics_frames')
            result['training_eligible']=False
        receipt['events']=normalize_observer_events(out/'original_attempt/events.jsonl',attempt/'events.jsonl')
        result['source_recording_audit']=receipt;atomic_json(out/'result.json',result)
        if result['task_completed']:
            try:
                from ..vla.data_three_table_lerobot import build_source
                source,plan=build_source(out,out/'source_proof')
                atomic_json(out/'source_qualification_audit.json',dict(verified=True,action_spans=len(plan['segments']),source_manifest=str(out/'source_proof/source.json'),dataset_ready=False))
            except Exception as exc:
                result['training_eligible']=False;atomic_json(out/'source_qualification_audit.json',dict(verified=False,error=str(exc),dataset_ready=False));atomic_json(out/'result.json',result)
    return result
