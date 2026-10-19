"""Evaluate one existing single-tray scene with a real checkpoint service."""
from pathlib import Path
import argparse, json, sys, traceback, time, inspect
from dataclasses import asdict
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def evaluate(scene, output, policy, *, execute_steps=5, max_steps=1200):
    from r1pro_teleop.airport_fsm.trace import Trace
    from r1pro_teleop.airport_fsm.contracts import json_default,sha256_file,camera_shapes
    from r1pro_teleop.single_tray_lab.control import SingleTrayController
    from r1pro_teleop.single_tray_lab.learned import LearnedSingleTray,NativePolicyImages
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    if sha256_file(scene['xml'])!=scene['xml_sha256']:raise ValueError('single_tray_scene_xml_identity_changed')
    if scene.get('payload_loaded_initially') is not False:raise ValueError('single_tray_evaluation_requires_empty_initial_scene')
    archive=output/'scene';archive.mkdir()
    (archive/'scene.json').write_text(json.dumps(scene,indent=2))
    (archive/'scene.xml').write_bytes(Path(scene['xml']).read_bytes())
    c=SingleTrayController.from_scene(scene);trace=None;images=None
    started=time.monotonic()
    result=dict(schema='airport_single_tray_result/1',task_profile='single_tray_action3_v1',task_completed=False,physics_success=False,training_eligible=False,source='simulation/program_generated',
        checkpoint_id=policy.contract.checkpoint_id,scene_id=scene['scene_id'],split=scene['split'],
        inverse_solver_calls=0,teacher_fallback_calls=0,execute_steps=execute_steps,max_action_steps=max_steps,
        planning_wall_clock_excluded=True,environment_phase_excluded=True)
    try:
        meta=dict(scene=scene,scene_xml_sha256=scene['xml_sha256'],source='simulation/program_generated',
            control_profile=asdict(c.p),
            fps=20,action_semantics='absolute_mobile19',task_profile='single_tray_action3_v1',
            checkpoint_id=policy.contract.checkpoint_id,base_mode='fixed_front',base_actuated=False,
            learned_executor_sha256=sha256_file(inspect.getfile(LearnedSingleTray)),
            controller_sha256=sha256_file(inspect.getfile(SingleTrayController)),
            native_camera_shapes={k:list(v) for k,v in camera_shapes(scene).items()},
            model_action_mask=[True]*16+[False]*3,integration_state_spec=int(c.integration_spec),
            substeps_per_frame=c.sim.nstep,physics_timestep_s=float(c.m.opt.timestep))
        trace=Trace(output/'attempt',meta);trace.file.attrs['schema']='airport_single_tray_raw/2'
        initial=c.observation()['tray_bottom_z']
        def record(row):
            row=dict(row);measured=row.pop('measurement_before');row.pop('measured',None);row.pop('holding_sides',None)
            row.update(gripper_contact_force=np.array([measured['gripper_contact_force'][s] for s in ('left','right')]),
                gripper_openings=measured['gripper_openings'],support_contact=measured['table_contacts'],
                floor_contact=measured['payload_floor_contacts'],tray_clearance=measured['tray_bottom_z']-initial,
                tray_position=measured['tray_position'],tray_rotation=measured['tray_rotation'],
                tray_goal_reached=c.loaded_goal_reached(measured),
                payload_mass=measured['payload_mass_kg'],payload_total_mass=measured['payload_total_mass_kg'],max_penetration=measured['max_penetration'],
                hard_max_penetration=measured['hard_max_penetration'],soft_payload_max_penetration=measured['soft_payload_max_penetration'],
                observed_hard_penetration_peak_m=c.observed_hard_penetration_peak_m,
                observed_soft_payload_penetration_peak_m=c.observed_soft_payload_penetration_peak_m,
                strict_continuous_push_table_contact_gate=c.strict_continuous_push_table_contact_gate)
            trace.append(row)
        def event(row):
            row=dict(row);kind=row.pop('event');trace.event(kind,**row)
        c.on_frame=record;c.on_event=event
        images=NativePolicyImages(c,scene,policy.contract.camera_names)
        learner=LearnedSingleTray(c,policy,images,output=output/'policy_decisions',execute_steps=execute_steps,max_steps=max_steps)
        result.update(learner.run())
    except Exception as exc:
        result.update(failure_code=getattr(exc,'code',type(exc).__name__),failure_detail=str(exc))
        (output/'exception.txt').write_text(traceback.format_exc())
    finally:
        result.update(frames=c.frames,sim_seconds=float(c.d.time),wall_seconds=time.monotonic()-started,
            action_spans=c.actions,actual_handover_verified=c.handover_verified,final_observation=c.observation(),control_profile=asdict(c.p))
        peaks=dict(schema='airport_single_tray_guard_penetration_peaks/1',
            observed_hard_penetration_peak_m=c.observed_hard_penetration_peak_m,
            observed_soft_payload_penetration_peak_m=c.observed_soft_payload_penetration_peak_m,
            guarded_substeps=c.guarded_substeps,coverage='every_guarded_physics_substep')
        result.update({k:peaks[k] for k in ('observed_hard_penetration_peak_m','observed_soft_payload_penetration_peak_m','guarded_substeps')})
        result['strict_continuous_push_table_contact_gate']=c.strict_continuous_push_table_contact_gate
        result['push_table_contact_grace']=dict(episodes=c.push_table_contact_grace_episodes,
            recoveries=c.push_table_contact_grace_recoveries,max_absent_duration_s=c.push_table_contact_max_absent_duration_s,
            max_gap_m=c.push_table_contact_max_gap_m)
        result['contact_acceptance']=dict(selected_hard_limit_m=c.p.max_penetration_m,selected_soft_limit_m=c.p.soft_payload_penetration_m,
            approximate_limits_used=c.p.max_penetration_m>.003 or c.p.soft_payload_penetration_m>.005,
            strict_hard_limit_m=.003,strict_soft_limit_m=.005,
            strict_contact_gate_passed=c.observed_hard_penetration_peak_m<=.003 and c.observed_soft_payload_penetration_peak_m<=.005,
            qualification='Declared acceptance conditions; not a claim of improved contact accuracy')
        if trace:
            trace.file.attrs['guard_penetration_peaks_json']=json.dumps(peaks,allow_nan=False)
            trace.close(dict(qpos=c.d.qpos,qvel=c.d.qvel,time=float(c.d.time)))
        if images:images.close()
        c.close();(output/'result.json').write_text(json.dumps(result,default=json_default,indent=2,allow_nan=False))
    return result


def main():
    from r1pro_teleop.vla.policy import PolicyContract
    from r1pro_teleop.single_tray_lab.learned import SingleTrayPolicy
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scene',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--checkpoint-id',required=True)
    p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8000)
    p.add_argument('--action-horizon',type=int,default=20);p.add_argument('--action-width',type=int,choices=(19,),default=19)
    p.add_argument('--execute-steps',type=int,default=5);p.add_argument('--max-action-steps',type=int,default=1200)
    a=p.parse_args();policy=SingleTrayPolicy.from_websocket(a.host,a.port,PolicyContract(a.checkpoint_id,
        action_horizon=a.action_horizon,action_width=a.action_width,prompt_mode='single_tray_action3_v1'))
    result=evaluate(json.loads(a.scene.read_text()),a.output,policy,execute_steps=a.execute_steps,max_steps=a.max_action_steps)
    print(json.dumps(dict(task_completed=result['task_completed'],frames=result['frames'])));return 0 if result['task_completed'] else 2


if __name__=='__main__':raise SystemExit(main())
