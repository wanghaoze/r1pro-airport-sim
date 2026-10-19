"""Private one-step yaw amplitude backtracking, retaining every original guard."""
from diagnostic_additive_certificate import CertifiedAdditiveSuffix
import time
import numpy as np


def execute_backtracking(machine,planned,operation,side,position,rotation,relation,free_goal,normal_check,*,normal_endpoint_lift_m=0.):
    from r1pro_teleop.airport_fsm.contracts import ARM_COLUMNS,Fault,wrap_angle
    from r1pro_teleop.airport_fsm.geometry import quat_yaw_tilt,rz
    from r1pro_teleop.airport_fsm.runtime import _homogeneous
    from r1pro_teleop.airport_fsm.trajectory import entry_limit_envelope
    from r1pro_teleop.airport_fsm.yaw_feedback import FixedDurationQuintic
    r=machine.r;path,frames=planned;duration=frames/r.cfg.fps
    if frames>r.primitive_deadline_step-r.steps:raise Fault('primitive_insufficient_time')
    boundary=max(1,round(r.cfg.push_yaw_feedback_seconds*r.cfg.fps))
    end_original=path.evaluate(1,duration)
    if not 0<boundary<frames or np.max(abs(end_original[1]))>1e-9 or np.max(abs(end_original[2]))>1e-8:
        from r1pro_teleop.airport_fsm.primitives import execute
        r.trace.event('push_yaw_feedback_skipped',reason='no_suffix_budget_or_nonrest_endpoint',feedback_frame=boundary,motion_frames=frames)
        return execute(r,planned)
    r.trace.event('primitive_reference',duration_s=duration,controller=type(path).__name__,knot_stop_fallback=False,reference_bounds=path.reference_bounds)
    suffix=None
    for frame in range(1,frames+1):
        if frame==boundary+1:
            q,v,a,_=path.evaluate(boundary/frames,duration)
            yaw=quat_yaw_tilt(r.observation()['tray_pose'][operation.tray,3:])[0]
            error=float(wrap_angle(yaw-operation.yaw,machine.g.period))
            cap=np.deg2rad(r.cfg.push_yaw_feedback_max_deg)
            requested=-float(np.clip(r.cfg.push_yaw_feedback_gain*error,-cap,cap))
            attempts=[]
            trials=((1.,0.),)
            if normal_endpoint_lift_m:raise ValueError('No Z adjustment authorized')
            if normal_endpoint_lift_m not in (0.,.00005,.0001):raise ValueError('Only authorized 50 or 100 micrometer trials')
            for scale,endpoint_lift in trials:
                correction=requested*scale;wall=time.monotonic()
                info=dict(method='additive_original_curve_plus_quintic_delta',bound='combined_polynomial_bernstein_interval_certificate',scale=scale,measured_yaw_error_deg=float(np.degrees(error)),requested_correction_deg=float(np.degrees(requested)),
                          command_yaw_correction_deg=float(np.degrees(correction)),remaining_s=(frames-boundary)/r.cfg.fps,
                          endpoint_world_z_lift_m=endpoint_lift)
                try:
                    if abs(correction)<=1e-12:raise ValueError('zero_yaw_correction')
                    target=_homogeneous(position,rz(correction)@rotation)@relation
                    target[2,3]+=endpoint_lift
                    goals={side:(target[:3,3],target[:3,:3])}
                    if free_goal is not None:goals[free_goal[0]]=(free_goal[1],free_goal[2])
                    endpoint=r.solve_pair(goals,end_original[0].copy());endpoint[[7,15]]=end_original[0][[7,15]]
                    candidate=CertifiedAdditiveSuffix(path,duration,boundary/frames,endpoint,(r.v,r.a,r.j))
                    info["certificate"]=candidate.certificate
                    info['boundary_errors']=[float(np.max(abs(candidate.evaluate(0)[i]-x))) for i,x in enumerate((q,v,a))]
                    info['terminal_errors']=[float(np.max(abs(candidate.evaluate(1)[i]-x))) for i,x in enumerate((endpoint,np.zeros_like(q),np.zeros_like(q)))]
                    info['limit_ratios']={name:float(np.max(candidate.reference_bounds[name]/cap)) for name,cap in zip(('velocity','acceleration','jerk'),(r.v,r.a,r.j))}
                    low,high=r.m.jnt_range[r.jids].T
                    lo,hi=entry_limit_envelope(np.stack([q,endpoint])[:,ARM_COLUMNS],low,high,r.cfg.joint_margin_rad)
                    qlo,qhi=candidate.extrema[0];reason=None
                    if max(info['limit_ratios'].values())>1+1e-9:reason=dict(reason='exact_derivative_limit',ratios=info['limit_ratios'])
                    elif np.any(qlo[ARM_COLUMNS]<lo) or np.any(qhi[ARM_COLUMNS]>hi) or np.any(qlo[[7,15]]<-1e-8) or np.any(qhi[[7,15]]>.1+1e-8):reason=dict(reason='exact_joint_limit')
                    if reason is None:reason=r._path_rejection(candidate,201,lo,hi,True)
                    if reason is None and normal_check is not None:reason=normal_check(candidate)
                    if reason is None:
                        for u in sorted(candidate.extremum_times|set(np.linspace(0.,1.,201))):
                            cq,cv,ca,_=candidate.evaluate(u);r.audit_online_reference(cq,cv,ca)
                        suffix=candidate
                    info['accepted']=suffix is not None;info['rejection']=reason
                except (Fault,ValueError) as exc:
                    info['accepted']=False;info['rejection']=dict(reason=getattr(exc,'code',type(exc).__name__),detail=getattr(exc,'detail',str(exc)))
                info['planning_wall_s']=time.monotonic()-wall;attempts.append(info)
                r.trace.event('diagnostic_yaw_backtrack_attempt',**info)
                if info['accepted'] or (info.get('rejection') or {}).get('reason')!='supported_normal_reference_excursion':break
                if normal_endpoint_lift_m:
                    rejected=info['rejection']
                    if rejected.get('command_z_m',float('inf'))>=rejected.get('allowed_z_m',[-float('inf')])[0]:break
            r.trace.event('push_yaw_feedback_suffix',accepted=suffix is not None,fallback_original_suffix=suffix is None,
                          feedback_s=boundary/r.cfg.fps,remaining_s=(frames-boundary)/r.cfg.fps,attempts=attempts)
        active=path if suffix is None else suffix
        count=frames if suffix is None else frames-boundary
        index=frame if suffix is None else frame-boundary
        if r.cfg.substep_control_enabled:
            from r1pro_teleop.airport_fsm.substep_control import sample_path_targets
            targets=sample_path_targets(active,index-1,count,r.sim.nstep,r.cfg.fps)
            r.sim.target=targets[-1].copy();r.tick(substep_targets=targets)
        else:
            r.sim.target=active.evaluate(index/count,count/r.cfg.fps)[0];r.tick()
