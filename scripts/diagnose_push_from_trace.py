"""Bounded private push rollout from frozen evidence; never an episode result.

First use the original controller to verify reconstruction against its recorded
trajectory. Candidate rollouts retain every Runtime guard and primitive budget.
"""
import argparse
import csv
from dataclasses import replace
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import h5py
import numpy as np


def serial(value):
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    raise TypeError(type(value).__name__)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--controller',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--case',type=int,default=4)
    p.add_argument('--handoff-index',type=int,default=0)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--estimator',type=Path,required=True)
    p.add_argument('--command-reference',choices=['original','false','true'],default='original')
    p.add_argument('--preload-scale',type=float)
    p.add_argument('--timestep',type=float,choices=[.001,.0005])
    p.add_argument('--arm-kv-scale',type=float,choices=[1.5,2.])
    p.add_argument('--cartesian-withdraw-middle',action='store_true')
    p.add_argument('--full-push-operation',action='store_true')
    p.add_argument('--push-compensation',type=float)
    p.add_argument('--yaw-compensation-deg',type=float,choices=[-1.5,-3.,-4.5])
    p.add_argument('--yaw-feedback-suffix',action='store_true')
    p.add_argument('--force-feedback-suffix',action='store_true')
    p.add_argument('--force-feedback-zero-gain',action='store_true')
    p.add_argument('--place-retained-side',choices=['original','left'])
    p.add_argument('--free-retreat-rise',type=float,choices=[.06,.08])
    p.add_argument('--withdraw-middle-progress',type=float,choices=[.45,.60])
    p.add_argument('--duration-rejection-baseline',type=Path)
    p.add_argument('--planning-only',action='store_true')
    p.add_argument('--yaw-backtrack-once',action='store_true')
    p.add_argument('--yaw-normal-lift-once',action='store_true')
    p.add_argument('--yaw-normal-lift-m',type=float,choices=[.00005,.0001],default=.00005)
    args=p.parse_args()
    if args.force_feedback_zero_gain:args.force_feedback_suffix=True
    source=args.source.resolve();output=args.output.resolve()
    if output==source or source in output.parents:raise ValueError('Output must be outside frozen source')
    output.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(args.controller))
    from r1pro_teleop.airport_fsm.runtime import Runtime, _homogeneous
    from r1pro_teleop.airport_fsm.registry import config_for
    from r1pro_teleop.airport_fsm.geometry import Operation
    from r1pro_teleop.airport_fsm.contracts import State, Fault
    from r1pro_teleop.airport_fsm.primitives import push
    from r1pro_teleop.airport_fsm import primitives
    if args.yaw_backtrack_once or args.yaw_normal_lift_once:
        if args.yaw_backtrack_once and args.yaw_normal_lift_once:raise ValueError('Only one private yaw candidate')
        if args.withdraw_middle_progress!=.45 or args.planning_only:raise ValueError('Backtracking requires the already validated .45 physical candidate')
        from r1pro_teleop.airport_fsm import yaw_feedback
        from diagnostic_yaw_backtrack import execute_backtracking
        if args.yaw_normal_lift_once:
            from functools import partial
            yaw_feedback.execute_feedback=partial(execute_backtracking,normal_endpoint_lift_m=args.yaw_normal_lift_m)
        else:yaw_feedback.execute_feedback=execute_backtracking
    place=primitives.place
    if args.place_retained_side is not None:
        if any((args.yaw_feedback_suffix,args.force_feedback_suffix,args.cartesian_withdraw_middle,args.yaw_compensation_deg is not None)):
            raise ValueError('Place side swap is one independent candidate')
        source_place=inspect.getsource(place)
        side_selection="        keep=min(('left','right'),key=lambda s:np.dot(r.sim.tcp(s)[0][:2]-staged[:2],direction))"
        if source_place.count(side_selection)!=1:raise ValueError('Unknown place-side selection logic')
        if args.place_retained_side=='left':source_place=source_place.replace(side_selection,"        keep='left'",1)
        namespace=vars(primitives).copy();exec(compile(source_place,'<private_place_side>','exec'),namespace)
        place=namespace['place']
        (output/'private_place_source.py').write_text(source_place)
    candidate_source=None
    if args.cartesian_withdraw_middle or args.yaw_compensation_deg is not None or args.yaw_feedback_suffix or args.force_feedback_suffix or args.free_retreat_rise is not None or args.withdraw_middle_progress is not None:
        from r1pro_teleop.airport_fsm import primitives
        original=inspect.getsource(primitives.push)
        old="""            cols=np.arange(0,7) if side=='left' else np.arange(8,15)
            middle[cols]+=.3*(held_points[-1][cols]-middle[cols])"""
        new="""            middle=r.solve_pair({
                side:(start_p+.3*(T[:3,3]-start_p),rotations(.3).as_matrix()),
                free:(free_goal[1],free_goal[2])},middle)
            middle[7 if side=='left' else 15]=c.gripper_close_m
            machine.log.event('diagnostic_cartesian_withdraw_middle',fraction=.3,
                retained_target=start_p+.3*(T[:3,3]-start_p),free_target=free_goal[1])"""
        candidate_source=original
        if args.withdraw_middle_progress is not None:
            if any((args.yaw_feedback_suffix,args.force_feedback_suffix,args.cartesian_withdraw_middle,args.yaw_compensation_deg is not None,args.place_retained_side is not None,args.free_retreat_rise is not None)):
                raise ValueError('Middle progress is an independent candidate')
            if args.duration_rejection_baseline is None:raise ValueError('Verified original duration rejection is required')
            old_middle='            middle[cols]+=.3*(held_points[-1][cols]-middle[cols])'
            if candidate_source.count(old_middle)!=1:raise ValueError('Unknown withdrawal middle expression')
            candidate_source=candidate_source.replace(old_middle,f'            middle[cols]+={args.withdraw_middle_progress!r}*(held_points[-1][cols]-middle[cols])',1)
        if args.free_retreat_rise is not None:
            if any((args.yaw_feedback_suffix,args.force_feedback_suffix,args.cartesian_withdraw_middle,args.yaw_compensation_deg is not None,args.place_retained_side is not None)):
                raise ValueError('Free retreat rise is an independent candidate')
            old_rise='            p[2]+=.10'
            if candidate_source.count(old_rise)!=1:raise ValueError('Unknown free retreat target expression')
            candidate_source=candidate_source.replace(old_rise,f'            p[2]+={args.free_retreat_rise!r}',1)
        if args.cartesian_withdraw_middle:
            if original.count(old)!=1:raise ValueError('Frozen push function does not match the reviewed intervention')
            candidate_source=original.replace(old,new,1)
        if args.yaw_compensation_deg is not None:
            old_yaw='R=rz(float(wrap_angle(operation.yaw-yaw,machine.g.period)))@R'
            new_yaw=f'R=rz(float(wrap_angle(operation.yaw+{float(np.deg2rad(args.yaw_compensation_deg))!r}-yaw,machine.g.period)))@R'
            if candidate_source.count(old_yaw)!=1:raise ValueError('Frozen push yaw command does not match intervention')
            candidate_source=candidate_source.replace(old_yaw,new_yaw,1)
        namespace=vars(primitives).copy()
        if args.planning_only:
            original_plan=namespace['plan']
            def planning_probe(runtime,points,**kwargs):
                planned=original_plan(runtime,points,**kwargs)
                path,frames=planned
                raise Fault('diagnostic_planning_accepted',dict(controller=type(path).__name__,frames=frames,duration_s=frames/runtime.cfg.fps,
                            available_s=kwargs['available'],reference_bounds=path.reference_bounds,knots=np.asarray(points)))
            namespace['plan']=planning_probe
        if args.force_feedback_suffix:
            if args.yaw_feedback_suffix or args.yaw_compensation_deg is not None or args.cartesian_withdraw_middle:raise ValueError('Force feedback is an independent candidate')
            from diagnostic_force_suffix import execute_force_feedback
            old_execute='        execute(r,planned)'
            if candidate_source.count(old_execute)==1:
                replacement='        execute_force_feedback(machine,planned,operation,side,position,R,relation,free_goal)'
            else:
                old_execute='        execute(r,plan(r,points,available=available,minimum=min(2.4,available-.05),allow_shortcut=not withdraw_free))'
                if candidate_source.count(old_execute)!=1:raise ValueError('Frozen push execution does not match intervention')
                replacement='        planned=plan(r,points,available=available,minimum=min(2.4,available-.05),allow_shortcut=not withdraw_free)\n        execute_force_feedback(machine,planned,operation,side,position,R,relation,free_goal)'
            if args.force_feedback_zero_gain:replacement=replacement.replace('relation,free_goal)','relation,free_goal,force_gain=0.)')
            candidate_source=candidate_source.replace(old_execute,replacement,1)
            namespace['execute_force_feedback']=execute_force_feedback
        if args.yaw_feedback_suffix:
            if args.yaw_compensation_deg is not None or args.cartesian_withdraw_middle:raise ValueError('Feedback is one independent candidate')
            from diagnostic_yaw_suffix import execute_feedback
            old_execute='        execute(r,planned)'
            if candidate_source.count(old_execute)!=1:raise ValueError('Frozen push execution does not match intervention')
            candidate_source=candidate_source.replace(old_execute,'        execute_feedback(machine,planned,operation,side,position,R,relation,free_goal,normal_check)',1)
            namespace['execute_feedback']=execute_feedback
        exec(compile(candidate_source,'<diagnostic_cartesian_withdraw_middle>','exec'),namespace)
        push=namespace['push']
        primitives.push=push  # Private process only; Machine.push imports this same module.
        (output/'private_candidate_source.py').write_text(candidate_source)
    spec=importlib.util.spec_from_file_location('push_diagnostic_support',args.estimator)
    support=importlib.util.module_from_spec(spec);sys.modules[spec.name]=support;spec.loader.exec_module(support)
    scene=next((source/'scenes').glob(f'airport_{args.case:04d}_*'))
    attempt=source/'attempts'/scene.name/'a000'
    events=[json.loads(line) for line in (attempt/'events.jsonl').read_text().splitlines()]
    selected=[e for e in events if e['event']=='primitive_push_compliance_reference'][args.handoff_index]
    frame=selected['frame'];side=selected['side']
    if args.withdraw_middle_progress is not None:
        baseline=json.loads(args.duration_rejection_baseline.read_text())
        failure=baseline.get('failure') or {}
        candidates=(failure.get('detail') or {}).get('candidates',[])
        if not (baseline['source']==str(source) and baseline['case']==args.case and baseline['frame']==frame and baseline['elapsed_s']==0 and
                failure.get('code')=='primitive_path_infeasible' and candidates and all(x.get('reason')=='duration' for x in candidates)):
            raise ValueError('Baseline is not same-entry original zero-motion duration rejection')
    staged=None
    if args.place_retained_side is not None:
        placement=next(e for e in reversed(events) if e['event']=='primitive_start' and e.get('primitive')=='place' and e['frame']<=frame)
        staged=np.array(placement['parameters']['staged'])
        previous_lift=next(e for e in reversed(events) if e['event']=='primitive_lift_path_selected' and e['frame']<=placement['frame'])
        alignments=[e for e in events if e['event']=='primitive_start' and e.get('primitive')=='transport_align' and previous_lift['frame']<e['frame']<=placement['frame']]
        frame=alignments[-1]['frame'] if alignments else placement['frame']
    op_event=[e for e in events if e['event']=='operation_selected' and e['frame']<=frame][-1]
    operation=Operation(**{**op_event['operation'],'destination':np.array(op_event['operation']['destination'])})
    lift=[e for e in events if e['event']=='primitive_lift_path_selected' and e['frame']<=frame][-1]
    cfg=config_for(source)
    modifications={}
    if args.command_reference!='original':
        modifications['loaded_command_reference_enabled']=args.command_reference=='true'
        modifications['loaded_command_reference_scope']='push'
    if args.preload_scale is not None:modifications['push_withdraw_preload_scale']=args.preload_scale
    if args.push_compensation is not None:modifications['primitive_push_compensation_m']=args.push_compensation
    if modifications:cfg=replace(cfg,**modifications).validate()
    r=Runtime(json.loads((scene/'scene.json').read_text()),scene/'mobile.xml',cfg,render=False)
    servo=[]
    for actuator in r.aids:
        gain=r.m.actuator_gainprm[actuator].copy();bias=r.m.actuator_biasprm[actuator].copy()
        standard=(r.m.actuator_gaintype[actuator]==r.mj.mjtGain.mjGAIN_FIXED and
            r.m.actuator_biastype[actuator]==r.mj.mjtBias.mjBIAS_AFFINE and
            r.m.actuator_dyntype[actuator]==r.mj.mjtDyn.mjDYN_NONE and
            r.m.actuator_trntype[actuator]==r.mj.mjtTrn.mjTRN_JOINT and
            gain[0]>0 and bias[2]<0 and np.isclose(bias[0],0.) and
            np.isclose(bias[1],-gain[0]) and np.allclose(gain[1:],0.) and np.allclose(bias[3:],0.))
        if not standard:raise ValueError('Actuator is not a standard fixed-gain affine position servo; refuse field assumptions')
        servo.append(dict(name=r.m.actuator(int(actuator)).name,kp=float(gain[0]),
            kv_before=float(-bias[2]),kv_after=float(-bias[2]*(args.arm_kv_scale or 1.))))
    if args.arm_kv_scale is not None:
        before_bias=r.m.actuator_biasprm.copy()
        r.m.actuator_biasprm[r.aids,2]*=args.arm_kv_scale
        expected=before_bias.copy();expected[r.aids,2]*=args.arm_kv_scale
        if not np.array_equal(r.m.actuator_biasprm,expected):raise ValueError('Unexpected actuator parameter change')
    source_dt=float(r.m.opt.timestep)
    if args.timestep is not None:
        r.m.opt.timestep=args.timestep
        r.sim.nstep=round(1/cfg.fps/args.timestep)
        if abs(r.sim.nstep*args.timestep*cfg.fps-1)>1e-12:raise ValueError('Nonintegral sample period')
    trajectory=[];recorded=[];generated=[];sampled=[]
    entry_restore='recorded_integration_state';restore_validation=[]
    with h5py.File(attempt/'trace.h5') as h:
        metadata=json.loads(h.attrs['metadata_json'])
        r.m.actuator_forcerange[:]=metadata['limits']['actuator_forcerange']
        if frame==len(h['integration_state']):
            entry_restore='replayed_completed_terminal_interval_no_recorded_endpoint'
            for index in range(max(0,frame-3),frame):
                if not bool(h['transition_completed'][index]):raise ValueError('Cannot reconstruct from incomplete terminal interval')
                r.mj.mj_setState(r.m,r.d,h['integration_state'][index],r.integration_spec)
                r.mj.mj_forward(r.m,r.d);r.d.qacc_warmstart[:]=h['qacc_warmstart'][index]
                r.sim.target=h['action'][index].copy();r.sim.base_target=h['base_action'][index].copy()
                schema=str(h.attrs['schema'])
                if schema=='airport_fsm_raw/2':
                    if int(h['executed_substeps'][index])!=r.sim.nstep:raise ValueError('Incomplete raw2 control journal')
                    controls=h['ctrl_substeps'][index]
                elif schema=='airport_fsm_raw/1':
                    r.sim.apply_target();controls=np.repeat(r.d.ctrl[None,:],r.sim.nstep,axis=0)
                    if index+1<len(h['ctrl']) and not np.array_equal(controls[0],h['ctrl'][index+1]):raise ValueError('Reconstructed raw1 controls differ')
                else:raise ValueError('Unknown raw schema')
                for ctrl in controls:
                    r.d.ctrl[:]=ctrl;r.mj.mj_step(r.m,r.d);r.mj.mj_forward(r.m,r.d)
                if index+1<len(h['qpos']):
                    errors=dict(frame=index,qpos=float(np.max(abs(r.d.qpos-h['qpos'][index+1]))),qvel=float(np.max(abs(r.d.qvel-h['qvel'][index+1]))))
                    restore_validation.append(errors)
                    if errors['qpos']>1e-9 or errors['qvel']>1e-8:raise ValueError('Neighbor interval replay did not validate exactly')
        else:
            r.mj.mj_setState(r.m,r.d,h['integration_state'][frame],r.integration_spec)
            r.mj.mj_forward(r.m,r.d);r.d.qacc_warmstart[:]=h['qacc_warmstart'][frame]
        r.sim.target=h['action'][frame-1].copy()
        r.sim.base_target=h['base_action'][frame-1].copy()
        r.steps=frame;r.physical_time_start=float(h['sim_time'][0])
        r.allowed_tray=operation.tray;r.target_slot=operation.slot
        r.holding=None;r.grasp_rel=None;r.retained_contact=(operation.tray,side)
        r.fsm_state=State.ADJUST_TRAY;r.phase='adjust';r.recovery=bool(h['recovery'][min(frame,len(h['recovery'])-1)])
        if args.place_retained_side is not None:
            r.holding=operation.tray;r.retained_contact=None
            body=r.d.body(r.g.ids[operation.tray]);obj=_homogeneous(body.xpos,body.xmat.reshape(3,3))
            shadow=r._shadow(r.sim.target)
            r.grasp_rel={s:np.linalg.inv(obj)@_homogeneous(shadow.site(s+'_tcp').xpos.copy(),shadow.site(s+'_tcp').xmat.reshape(3,3).copy()) for s in ('left','right')}
            state=h['fsm_state'][frame];phase=h['phase'][frame]
            r.fsm_state=State(state.decode() if isinstance(state,bytes) else state)
            r.phase=phase.decode() if isinstance(phase,bytes) else str(phase)
        r.initial_bottom=h['min_z'][0].copy();r.primitive_lift_xy_shift_m=abs(lift['inward_m'])
        r.sim.workspace_rotation=r.d.body('base_link').xmat.reshape(3,3).copy()
        from r1pro_teleop.core import XR_TO_ROBOT
        r.sim.xr_to_world=r.sim.workspace_rotation@XR_TO_ROBOT
        entry=r.observation()
        from scipy.spatial.transform import Rotation
        entry_angles=Rotation.from_matrix(r.d.body(r.g.ids[operation.tray]).xmat.reshape(3,3)).as_euler('xyz',degrees=True)
        if args.place_retained_side is None and entry['table_contact'][operation.tray]<=0:raise ValueError('Cannot reconstruct retained support timer from unsupported entry')
        if args.place_retained_side is not None and np.any(entry['gripper_contact_force'][operation.tray]<=cfg.criteria.contact_n):raise ValueError('Cannot reset bilateral timer without real two-hand support')
        r.retained_support_missing_since=None;r.lost_time=0.
        class DiagnosticTrace:
            def event(self,name,**kwargs):generated.append(dict(frame=r.steps,event=name,**kwargs))
            def append(self,row):
                index=frame+len(trajectory)
                trajectory.append(dict(frame=index,qpos_error=float(np.max(abs(row['qpos']-h['qpos'][index]))) if index<len(h['qpos']) else None,
                    qvel_error=float(np.max(abs(row['qvel']-h['qvel'][index]))) if index<len(h['qpos']) else None,
                    action_error=float(np.max(abs(row['action']-h['action'][index]))) if index<len(h['qpos']) else None,
                    table_contacts=int(row['table_contact'][operation.tray]),
                    completed=bool(row['transition_completed'])))
        r.trace=DiagnosticTrace()
        from r1pro_teleop.airport_fsm.machine import Machine
        machine=Machine.__new__(Machine)
        machine.r=r;machine.c=cfg;machine.g=r.g;machine.log=r.trace
        initial_op=next(e for e in events if e['event']=='operation_selected')
        machine.scheduler=SimpleNamespace(mapping=r.g.best_mapping(h['tray_pose'][initial_op['frame']]))
        machine.pending_grasp_contact=None;machine.grasp_rim_pair=None
        def transition(state,phase,**kwargs):
            r.fsm_state=state;r.phase=phase
            e=r.observation()
            generated.append(dict(event='diagnostic_phase_snapshot',frame=r.steps,phase=phase,
                pose=e['tray_pose'][operation.tray].copy(),gripper_force=e['gripper_contact_force'][operation.tray].copy(),
                table_contact=int(e['table_contact'][operation.tray])))
        machine.transition=transition
        bid=r.m.body(r.g.ids[operation.tray]).id
        tables={r.m.body(name).id for name in ('front_left','front_right','rear')}
        fingers={b for b in range(r.m.nbody) if 'gripper_finger' in r.m.body(b).name}
        original_guard=r.guard
        def guarded_observation():
            try:original_guard()
            finally:
                force=support.measure_support_force(r.m,r.d,bid,tables)
                grip=support.measure_support_force(r.m,r.d,bid,fingers)
                e=r.observation()
                sampled.append(dict(time_s=float(r.d.time),table_contacts=force.qualifying_contact_count,
                    table_normal_n=force.signed_normal_n,gripper_vertical_n=grip.signed_normal_n,
                    bottom_z=float(e['min_z'][operation.tray])))
        r.guard=guarded_observation
        b=r.d.body(r.g.ids[operation.tray])
        relation=np.linalg.inv(_homogeneous(b.xpos,b.xmat.reshape(3,3)))@_homogeneous(*r.sim.tcp(side))
        failure=None;start_time=float(r.d.time);wall_start=time.monotonic()
        try:
            if args.place_retained_side is not None:place(machine,operation,staged)
            elif args.full_push_operation:machine.push(operation,retained_side=side)
            else:push(machine,operation,side,relation,free_retreat=True)
        except Fault as exc:failure=dict(code=exc.code,detail=exc.detail)
        rollout_wall=time.monotonic()-wall_start
        final=r.observation();elapsed=float(r.d.time-start_time)
        endpoint_index=frame+len(trajectory)
        endpoint_error=float(np.max(abs(r.d.qpos-h['qpos'][endpoint_index]))) if endpoint_index<len(h['qpos']) else None
    missing=longest=0
    for row in sampled:
        missing=missing+1 if row['table_contacts']==0 else 0;longest=max(longest,missing)
    def maximum(key):return max((x[key] for x in trajectory if x[key] is not None),default=None)
    prefix_match=bool(trajectory and maximum('qpos_error') is not None and maximum('qpos_error')<=1e-9 and maximum('qvel_error')<=1e-8)
    exact=prefix_match and endpoint_error is not None and endpoint_error<=1e-9
    from r1pro_teleop.airport_fsm.geometry import slot_geometry_ready,quat_yaw_tilt
    final_geometry=bool(slot_geometry_ready(r.g,final['tray_pose'],machine.scheduler.mapping,operation.tray,operation.slot,cfg.criteria))
    final_yaw=quat_yaw_tilt(final['tray_pose'][operation.tray,3:])[0]
    contact_bodies=tables|{r.m.body(name).id for name in r.g.ids}
    contact_geoms=[i for i in range(r.m.ngeom) if r.m.geom_bodyid[i] in contact_bodies and (r.m.geom_contype[i] or r.m.geom_conaffinity[i])]
    solver_settings=dict(integrator=r.mj.mjtIntegrator(int(r.m.opt.integrator)).name,
        solver=r.mj.mjtSolver(int(r.m.opt.solver)).name,iterations=int(r.m.opt.iterations),tolerance=float(r.m.opt.tolerance),
        geom_solref_unique=np.unique(r.m.geom_solref[contact_geoms],axis=0).tolist(),
        geom_solimp_unique=np.unique(r.m.geom_solimp[contact_geoms],axis=0).tolist())
    result=dict(qualification='private_local_push_diagnostic_not_complete_episode',source=str(source),
        controller=str(args.controller),case=args.case,frame=frame,tray=operation.tray,side=side,
        incoming_target_source='previous_recorded_action',modifications=modifications,
        entry_restore=entry_restore,entry_restore_neighbor_validation=restore_validation,
        cartesian_withdraw_middle=args.cartesian_withdraw_middle,entry_rollpitchyaw_deg=entry_angles.tolist(),
        full_push_operation=args.full_push_operation,final_slot_geometry_ready=final_geometry,
        yaw_compensation_deg=args.yaw_compensation_deg,operation_acceptance_yaw_unchanged=float(operation.yaw),
        yaw_feedback_suffix=args.yaw_feedback_suffix,
        force_feedback_suffix=args.force_feedback_suffix,
        force_feedback_zero_gain=args.force_feedback_zero_gain,
        place_retained_side=args.place_retained_side,
        free_retreat_rise_m=args.free_retreat_rise,
        withdraw_middle_progress=args.withdraw_middle_progress,planning_only=args.planning_only,
        yaw_backtrack_once=args.yaw_backtrack_once,
        yaw_normal_lift_once=args.yaw_normal_lift_once,
        yaw_normal_lift_m=args.yaw_normal_lift_m if args.yaw_normal_lift_once else None,
        final_all_poses=final['tray_pose'],slot_mapping=machine.scheduler.mapping,
        final_position_error_m=float(np.linalg.norm(final['tray_pose'][operation.tray,:3]-operation.destination)),
        final_yaw_rad=float(final_yaw),
        arm_kv_scale=args.arm_kv_scale,arm_position_servos=servo,
        timestep_intervention=args.timestep,source_timestep_s=source_dt,timestep_s=float(r.m.opt.timestep),
        substeps_per_frame=r.sim.nstep,rollout_wall_s=rollout_wall,solver_settings=solver_settings,
        restored_context=dict(retained_contact=r.retained_contact,initial_holding=operation.tray if args.place_retained_side is not None else None,phase='trace_phase' if args.place_retained_side is not None else 'adjust',
            primitive_lift_xy_shift_m=r.primitive_lift_xy_shift_m,initial_bottom=r.initial_bottom,
            support_timer='reset only after confirming actual entry support',
            warnings='fresh zero counters; source episode would have stopped at any prior warning',
            diagnostic_counters='wall budget restarted; historical peak power and inverse-call tallies not restored'),
        exact_original_trajectory_match=bool(exact),recorded_prefix_matches=prefix_match,
        maximum_qpos_error=maximum('qpos_error'),maximum_qvel_error=maximum('qvel_error'),
        maximum_action_error=maximum('action_error'),endpoint_qpos_error=endpoint_error,
        primitive_returned=failure is None,failure=failure,elapsed_s=elapsed,
        final_pose=final['tray_pose'][operation.tray],final_forces=final['gripper_contact_force'][operation.tray],
        final_table_contacts=int(final['table_contact'][operation.tray]),
        physics_samples=len(sampled),longest_physics_missing_s=longest*r.m.opt.timestep,
        table_force_peak_n=max((x['table_normal_n'] for x in sampled),default=None),
        support_fraction=sum(x['table_contacts']>0 for x in sampled)/len(sampled) if sampled else None)
    (output/'summary.json').write_text(json.dumps(result,default=serial,indent=2))
    (output/'events.json').write_text(json.dumps(generated,default=serial,indent=2))
    if sampled:
        with (output/'forces.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(sampled[0]));writer.writeheader();writer.writerows(sampled)
    print(json.dumps(result,default=serial));r.sim.close()


if __name__=='__main__':main()
