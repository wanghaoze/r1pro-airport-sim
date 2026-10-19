"""Continuous old empty primitives + registered passengers + loaded controller.

This candidate is diagnostic and ineligible for training until source evidence
qualification. It never restores a tray/robot snapshot between actions.
"""
from pathlib import Path
import sys,argparse,json,hashlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.airport_fsm.contracts import Config,json_default
from r1pro_teleop.single_tray_3table.control import empty_motion_diagnostic
from r1pro_teleop.single_tray_3table.loaded_bridge import LoadedBridgeController,derive_bridge_profile
from r1pro_teleop.single_tray_lab.control import ControlProfile
from r1pro_teleop.single_tray_lab.three_table_scene import passenger_load_three_table
from dataclasses import asdict,replace


def run(scene,config,reference_scene,output,*,transient_boundary_extra_m=None,disable_axis_feedback=False):
    manifest=json.loads(Path(scene).read_text());reference=json.loads(Path(reference_scene).read_text())
    profile=ControlProfile(**reference['control_profile']).validate()
    source_sha=hashlib.sha256(Path(reference_scene).read_bytes()).hexdigest()
    def continuation(r,m,scene):
        p=derive_bridge_profile(r,scene,profile)
        if disable_axis_feedback:p=replace(p,push_axis_feedback_enabled=False).validate()
        if transient_boundary_extra_m is not None:
            p=replace(p,push_transient_boundary_extra_m=transient_boundary_extra_m).validate()
        r.trace.event('loaded_controller_bound_same_live',model_data_identity_unchanged=True,
            base_actuator_global_origin_unchanged=True,source_push_scene=str(reference_scene),
            source_push_scene_sha256=source_sha,loaded_profile=asdict(p),
            source_collision_contract_m=r.cfg.completion_collision_penetration_m,
            transient_boundary_source_declaration=scene.get('loaded_push_target',{}),
            grasp_provider='legacy_opposed_long_rims',numeric_solver_physics_unchanged=True)
        c=LoadedBridgeController.bind(r,p,passenger_loader=lambda sim:passenger_load_three_table(sim,scene))
        c.passenger_load();c.push_loaded();obs=c.observation()
        return dict(push_loaded_completed=bool(c.handover_verified and c.loaded_goal_reached(obs)
            and obs['payload_support_contacts']>0 and not obs['payload_floor_contacts']
            and obs['payload_mass_kg']>=obs['payload_total_mass_kg']-1e-6
            and max(obs['gripper_contact_force'].values())<=p.contact_n),
            actual_handover_verified=c.handover_verified,actions=c.actions,final_loaded_observation=obs,
            final_gate_evidence=getattr(c,'final_gate_evidence',None),
            original_live_model_data_preserved=True,controller_binding_only=True,
            guarded_substeps=c.guarded_substeps,hard_penetration_peak_m=c.observed_hard_penetration_peak_m,
            soft_payload_penetration_peak_m=c.observed_soft_payload_penetration_peak_m,
            strict_continuous_push_table_contact_gate=c.strict_continuous_push_table_contact_gate)
        # Extra boundary statistics are live-only and report the stricter gate
        # separately; no final task predicate is changed by this profile.
    return empty_motion_diagnostic(manifest,Path(output),cfg=Config.load(config),continuation=continuation,record_substeps=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--scene',required=True);parser.add_argument('--config',required=True)
    parser.add_argument('--push-reference-scene',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--transient-boundary-extra',type=float,default=None,
        help='Optional explicit override; absent uses scene declaration (old scenes default zero)')
    parser.add_argument('--no-axis-feedback',action='store_true',help='Explicitly retain the original push servo for this candidate')
    args=parser.parse_args();result=run(args.scene,args.config,args.push_reference_scene,args.output,
        transient_boundary_extra_m=args.transient_boundary_extra,disable_axis_feedback=args.no_axis_feedback)
    print(json.dumps({k:v for k,v in result.items() if k!='final_observation'},default=json_default))
