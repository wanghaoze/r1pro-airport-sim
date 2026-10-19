"""Generate a new, recorded physical single-tray candidate; never train failures."""
from pathlib import Path
from dataclasses import asdict,replace
import argparse,json,sys,time,traceback
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_lab.scene import generate_scene,LabSceneConfig,passenger_load
from r1pro_teleop.single_tray_lab.control import SingleTrayController,ControlProfile,ACTION_PROMPTS
from r1pro_teleop.airport_fsm.trace import Trace
from r1pro_teleop.airport_fsm.contracts import json_default,sha256_file


def run(output,config,*,grasp_half_separation=None,lift_stop_margin=None,place_release_clearance=None,
        follow_tray_pose=False,soft_payload_penetration=None,grasp_mode=None,rim_height=None,held_tracking_tolerance=None,
        push_command_reference=False,push_reference_lead=None,hard_penetration_limit=None,place_inboard_slow_recipe=False,push_vertical_relief=None,push_table_contact_grace_frames=None,
        push_lead_frame=None,push_right_outward_release=False,handover_left_tangent=None):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    scene=generate_scene(output/'scene',config);controller=None;trace=None;started=time.monotonic()
    result=dict(schema='airport_single_tray_result/1',task_completed=False,physics_success=False,
        training_eligible=False,source='simulation/program_generated',human_demonstration=False,
        task_profile='single_tray_action3_v1',scene_id=scene['scene_id'],split=scene['split'])
    try:
        profile=ControlProfile.from_scene(scene)
        if grasp_half_separation is not None:
            profile=replace(profile,grasp_half_separation=grasp_half_separation).validate()
        if lift_stop_margin is not None:profile=replace(profile,lift_stop_margin_m=lift_stop_margin).validate()
        if place_release_clearance is not None:profile=replace(profile,place_release_clearance_m=place_release_clearance).validate()
        profile=replace(profile,follow_tray_pose=follow_tray_pose).validate()
        if soft_payload_penetration is not None:profile=replace(profile,soft_payload_penetration_m=soft_payload_penetration).validate()
        if grasp_mode is not None:profile=replace(profile,grasp_mode=grasp_mode).validate()
        if rim_height is not None:profile=replace(profile,rim_height=rim_height).validate()
        if held_tracking_tolerance is not None:profile=replace(profile,held_tracking_tolerance_m=held_tracking_tolerance).validate()
        profile=replace(profile,push_command_reference=push_command_reference).validate()
        profile=replace(profile,place_inboard_slow_recipe=place_inboard_slow_recipe).validate()
        if push_reference_lead is not None:profile=replace(profile,push_reference_lead_m=push_reference_lead).validate()
        if push_vertical_relief is not None:profile=replace(profile,push_vertical_relief_m=push_vertical_relief).validate()
        if push_table_contact_grace_frames is not None:profile=replace(profile,push_table_contact_grace_frames=push_table_contact_grace_frames).validate()
        if push_lead_frame is not None:profile=replace(profile,push_lead_frame=push_lead_frame).validate()
        profile=replace(profile,push_right_outward_release=push_right_outward_release).validate()
        if handover_left_tangent is not None:profile=replace(profile,handover_left_tangent_m=handover_left_tangent).validate()
        if hard_penetration_limit is not None:
            if not 0<hard_penetration_limit<=.01:raise ValueError('Explicit hard contact limit must be positive and at most 1 cm')
            profile=replace(profile,max_penetration_m=hard_penetration_limit).validate()
        # Freeze the actual control contract before the first physical tick;
        # new learned evaluations must reconstruct the same declared guards.
        scene['control_profile']=asdict(profile)
        (output/'scene/scene.json').write_text(json.dumps(scene,default=json_default,indent=2,allow_nan=False))
        controller=SingleTrayController(scene['xml'],profile,passenger_loader=lambda sim:passenger_load(sim,scene))
        attributes=dict(scene=scene,scene_xml_sha256=scene['xml_sha256'],task_profile='single_tray_action3_v1',
            config=dict(substep_control_enabled=True),control_profile=asdict(profile),source='simulation/program_generated',fps=20,
            action_semantics='absolute_mobile19',base_mode='fixed_front',base_actuated=False,
            model_action_mask=[True]*16+[False]*3,action_prompts=ACTION_PROMPTS,
            controller_sha256=sha256_file(Path(__file__).resolve().parents[1]/'r1pro_teleop/single_tray_lab/control.py'),
            placement_recipe_sha256=sha256_file(Path(__file__).resolve().parents[1]/'r1pro_teleop/single_tray_lab/placement_recipe.py'),
            runner_sha256=sha256_file(Path(__file__).resolve()),
            integration_state_spec=int(controller.integration_spec),substeps_per_frame=controller.sim.nstep,
            physics_timestep_s=float(controller.m.opt.timestep),
            environment_updates='Explicit passenger payload initialization journal; old airport Replay unsupported')
        trace=Trace(output/'attempt',attributes);trace.file.attrs['schema']='airport_single_tray_raw/2'
        initial_bottom=controller.observation()['tray_bottom_z']
        def record(row):
            row=dict(row)
            measured=row.pop('measurement_before');row.pop('measured',None)
            row.update(payload_loaded=bool(measured['payload_loaded']),payload_mass=float(measured['payload_mass_kg']),
                payload_total_mass=float(measured['payload_total_mass_kg']),
                gripper_contact_force=np.array([measured['gripper_contact_force'][s] for s in ('left','right')]),
                gripper_openings=measured['gripper_openings'],support_contact=measured['table_contacts'],
                floor_contact=measured['payload_floor_contacts'],tray_clearance=measured['tray_bottom_z']-initial_bottom,
                tray_position=measured['tray_position'],tray_rotation=measured['tray_rotation'],
                tray_goal_reached=controller.loaded_goal_reached(measured),
                max_penetration=measured['max_penetration'],hard_max_penetration=measured['hard_max_penetration'],
                soft_payload_max_penetration=measured['soft_payload_max_penetration'],
                observed_hard_penetration_peak_m=controller.observed_hard_penetration_peak_m,
                observed_soft_payload_penetration_peak_m=controller.observed_soft_payload_penetration_peak_m,
                strict_continuous_push_table_contact_gate=controller.strict_continuous_push_table_contact_gate)
            row.pop('holding_sides',None);trace.append(row)
        def event(row):
            data=dict(row);kind=data.pop('event');trace.event(kind,**data)
        controller.on_frame=record;controller.on_event=event
        actual=controller.run();result.update(actual,physics_success=True,training_eligible=True)
    except Exception as exc:
        result.update(failure_code=getattr(exc,'code',type(exc).__name__),failure_detail=str(exc))
        (output/'exception.txt').write_text(traceback.format_exc())
    finally:
        if controller is not None:
            result.update(frames=controller.frames,action_spans=controller.actions,actual_handover_verified=controller.handover_verified,
                final_observation=controller.observation(),control_profile=asdict(controller.p),wall_seconds=time.monotonic()-started,sim_seconds=float(controller.d.time))
            recoveries=[row for row in controller.events if row['event'] in ('empty_place_one_hand_recovery','empty_place_footprint_correction')]
            result.update(recovery_used=bool(recoveries),recovery_events=recoveries)
            peaks=dict(schema='airport_single_tray_guard_penetration_peaks/1',
                observed_hard_penetration_peak_m=controller.observed_hard_penetration_peak_m,
                observed_soft_payload_penetration_peak_m=controller.observed_soft_payload_penetration_peak_m,
                guarded_substeps=controller.guarded_substeps,coverage='every_guarded_physics_substep')
            result.update({k:peaks[k] for k in ('observed_hard_penetration_peak_m',
                'observed_soft_payload_penetration_peak_m','guarded_substeps')})
            result['strict_continuous_push_table_contact_gate']=controller.strict_continuous_push_table_contact_gate
            result['push_table_contact_grace']=dict(episodes=controller.push_table_contact_grace_episodes,
                recoveries=controller.push_table_contact_grace_recoveries,
                max_absent_duration_s=controller.push_table_contact_max_absent_duration_s,
                max_gap_m=controller.push_table_contact_max_gap_m)
            result['contact_acceptance']=dict(selected_hard_limit_m=controller.p.max_penetration_m,
                selected_soft_limit_m=controller.p.soft_payload_penetration_m,
                approximate_limits_used=controller.p.max_penetration_m>.003 or controller.p.soft_payload_penetration_m>.005,
                strict_hard_limit_m=.003,strict_soft_limit_m=.005,
                strict_contact_gate_passed=controller.observed_hard_penetration_peak_m<=.003 and
                    controller.observed_soft_payload_penetration_peak_m<=.005,
                qualification='Declared acceptance conditions; not a claim of improved contact accuracy')
            if trace is not None:
                trace.file.attrs['guard_penetration_peaks_json']=json.dumps(peaks,allow_nan=False)
                trace.close(dict(qpos=controller.d.qpos,qvel=controller.d.qvel,time=float(controller.d.time)))
            controller.close()
        (output/'result.json').write_text(json.dumps(result,default=json_default,indent=2,allow_nan=False))
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    p.add_argument('--seed',type=int,default=20261005);p.add_argument('--robot-x',type=float,default=.10)
    p.add_argument('--robot-y',type=float,default=0.);p.add_argument('--tray-y',type=float,default=-.24)
    p.add_argument('--split',choices=('train','val','test'),default='train');p.add_argument('--rigid-coat',action='store_true')
    p.add_argument('--grasp-half-separation',type=float)
    p.add_argument('--lift-clearance',type=float,default=.18)
    p.add_argument('--gripper-kp',type=float,default=2000.)
    p.add_argument('--arm-kp',type=float,default=250.)
    p.add_argument('--noslip-iterations',type=int,default=0)
    p.add_argument('--friction-impratio',type=float,default=10.)
    p.add_argument('--lift-stop-margin',type=float)
    p.add_argument('--place-release-clearance',type=float)
    p.add_argument('--follow-tray-pose',action='store_true')
    p.add_argument('--soft-payload-penetration',type=float)
    p.add_argument('--grasp-mode',choices=('front_wall','wall_mid_taper'))
    p.add_argument('--rim-height',type=float)
    p.add_argument('--held-tracking-tolerance',type=float)
    p.add_argument('--push-command-reference',action='store_true')
    p.add_argument('--push-reference-lead',type=float)
    p.add_argument('--hard-penetration-limit',type=float,help='Explicit approximate contact limit; default original 3 mm')
    p.add_argument('--place-inboard-slow-recipe',action='store_true')
    p.add_argument('--push-vertical-relief',type=float)
    p.add_argument('--push-table-contact-grace-frames',type=int)
    p.add_argument('--push-lead-frame',choices=('tray_anchor','measured_tcp'))
    p.add_argument('--push-right-outward-release',action='store_true')
    p.add_argument('--handover-left-tangent',type=float)
    a=p.parse_args(argv);result=run(a.output,LabSceneConfig(seed=a.seed,robot_x=a.robot_x,robot_y=a.robot_y,
        tray_y=a.tray_y,split=a.split,cloth_enabled=not a.rigid_coat,lift_clearance=a.lift_clearance,
        gripper_kp=a.gripper_kp,arm_kp=a.arm_kp,noslip_iterations=a.noslip_iterations,friction_impratio=a.friction_impratio),grasp_half_separation=a.grasp_half_separation,
        lift_stop_margin=a.lift_stop_margin,place_release_clearance=a.place_release_clearance,
        follow_tray_pose=a.follow_tray_pose,soft_payload_penetration=a.soft_payload_penetration,
        grasp_mode=a.grasp_mode,rim_height=a.rim_height,held_tracking_tolerance=a.held_tracking_tolerance,
        push_command_reference=a.push_command_reference,push_reference_lead=a.push_reference_lead,
        hard_penetration_limit=a.hard_penetration_limit,place_inboard_slow_recipe=a.place_inboard_slow_recipe,
        push_vertical_relief=a.push_vertical_relief,push_table_contact_grace_frames=a.push_table_contact_grace_frames,
        push_lead_frame=a.push_lead_frame,push_right_outward_release=a.push_right_outward_release,handover_left_tangent=a.handover_left_tangent)
    print(json.dumps(result,default=json_default));return 0 if result['task_completed'] else 2


if __name__=='__main__':raise SystemExit(main())
