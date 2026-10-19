"""Optional one-shot measured-yaw correction within an already planned push."""
import numpy as np
import time


class FixedDurationQuintic:
    """One polynomial with physical-time boundary derivatives and exact extrema."""
    def __init__(self,q,v,a,end,duration):
        self.duration=float(duration)
        if not np.isfinite(self.duration) or self.duration<=0:raise ValueError('Positive duration required')
        q,v,a,end=np.broadcast_arrays(*[np.asarray(x,float) for x in (q,v,a,end)])
        if q.ndim!=1 or not np.isfinite([q,v,a,end]).all():raise ValueError('Finite joint vectors required')
        T=self.duration
        self.coef=np.zeros((6,len(q)));self.coef[:3]=q,v*T,a*T*T/2
        d=end-(self.coef[0]+self.coef[1]+self.coef[2])
        self.coef[3:]=np.linalg.solve(np.array([[1,1,1],[3,4,5],[6,12,20]],float),
                                    np.stack([d,-self.coef[1]-2*self.coef[2],-2*self.coef[2]]))
        self.extrema={};self.extremum_times=set([0.,1.])
        for order in range(4):
            lows=[];highs=[]
            for joint in range(len(q)):
                coeff=np.polynomial.polynomial.polyder(self.coef[:,joint],order)
                roots=np.polynomial.polynomial.polyroots(np.polynomial.polynomial.polyder(coeff))
                u=[0.,1.]+[float(z.real) for z in roots if abs(z.imag)<1e-9 and 0<z.real<1]
                self.extremum_times.update(u)
                values=np.polynomial.polynomial.polyval(u,coeff)/T**order
                lows.append(min(values));highs.append(max(values))
            self.extrema[order]=(np.array(lows),np.array(highs))
        self.reference_bounds={name:np.maximum(abs(self.extrema[i][0]),abs(self.extrema[i][1]))
                               for i,name in enumerate(('velocity','acceleration','jerk'),1)}

    def evaluate(self,progress,duration=None):
        if duration is not None and abs(float(duration)-self.duration)>1e-10:raise ValueError('Suffix cannot be retimed')
        u=np.clip(np.asarray(progress,float),0,1)
        values=tuple(np.polynomial.polynomial.polyval(u,
                     np.polynomial.polynomial.polyder(self.coef,order,axis=0))/self.duration**order for order in range(4))
        return tuple(np.moveaxis(value,0,-1) if u.ndim else value for value in values)


def execute_feedback(machine,planned,operation,side,position,rotation,relation,free_goal,normal_check):
    """Execute original prefix; validate one candidate, else keep original suffix."""
    from r1pro_teleop.airport_fsm.contracts import ARM_COLUMNS,Fault,wrap_angle
    from r1pro_teleop.airport_fsm.geometry import quat_yaw_tilt,rz
    from r1pro_teleop.airport_fsm.runtime import _homogeneous
    from r1pro_teleop.airport_fsm.trajectory import entry_limit_envelope
    r=machine.r;path,frames=planned;duration=frames/r.cfg.fps
    if frames>r.primitive_deadline_step-r.steps:raise Fault('primitive_insufficient_time')
    boundary=max(1,round(r.cfg.push_yaw_feedback_seconds*r.cfg.fps))
    end_original=path.evaluate(1,duration)
    if not 0<boundary<frames or np.max(abs(end_original[1]))>1e-9 or np.max(abs(end_original[2]))>1e-8:
        from .primitives import execute
        r.trace.event('push_yaw_feedback_skipped',reason='no_suffix_budget_or_nonrest_endpoint',
                      feedback_frame=boundary,motion_frames=frames)
        return execute(r,planned)
    r.trace.event('primitive_reference',duration_s=duration,controller=type(path).__name__,
                  knot_stop_fallback=False,reference_bounds=path.reference_bounds)
    suffix=None
    for frame in range(1,frames+1):
        if frame==boundary+1:
            planning_start=time.monotonic()
            q,v,a,_=path.evaluate(boundary/frames,duration)
            pose=r.observation()['tray_pose'][operation.tray]
            yaw=quat_yaw_tilt(pose[3:])[0];error=float(wrap_angle(yaw-operation.yaw,machine.g.period))
            cap=np.deg2rad(r.cfg.push_yaw_feedback_max_deg)
            correction=-float(np.clip(r.cfg.push_yaw_feedback_gain*error,-cap,cap))
            info=dict(feedback_s=boundary/r.cfg.fps,remaining_s=(frames-boundary)/r.cfg.fps,
                      measured_yaw_error_deg=float(np.degrees(error)),command_yaw_correction_deg=float(np.degrees(correction)),
                      original_terminal_velocity_max=float(np.max(abs(end_original[1]))),
                      original_terminal_acceleration_max=float(np.max(abs(end_original[2]))))
            endpoint=None
            try:
                if abs(correction)<=1e-12:raise ValueError('zero_yaw_correction')
                target=_homogeneous(position,rz(correction)@rotation)@relation
                goals={side:(target[:3,3],target[:3,:3])}
                if free_goal is not None:goals[free_goal[0]]=(free_goal[1],free_goal[2])
                endpoint=r.solve_pair(goals,end_original[0].copy())
                endpoint[[7,15]]=end_original[0][[7,15]]
                candidate=FixedDurationQuintic(q,v,a,endpoint,(frames-boundary)/r.cfg.fps)
                info['boundary_errors']=[float(np.max(abs(candidate.evaluate(0)[i]-x))) for i,x in enumerate((q,v,a))]
                info['terminal_errors']=[float(np.max(abs(candidate.evaluate(1)[i]-x))) for i,x in enumerate((endpoint,np.zeros_like(q),np.zeros_like(q)))]
                info['limit_ratios']={name:float(np.max(candidate.reference_bounds[name]/cap)) for name,cap in zip(('velocity','acceleration','jerk'),(r.v,r.a,r.j))}
                low,high=r.m.jnt_range[r.jids].T
                lo,hi=entry_limit_envelope(np.stack([q,endpoint])[:,ARM_COLUMNS],low,high,r.cfg.joint_margin_rad)
                qlo,qhi=candidate.extrema[0]
                reason=None
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
            # A rejected geometric/limit certificate has not executed any
            # candidate motion. Retry once using the identical IK endpoint.
            if suffix is None and endpoint is not None and abs(correction)>1e-12 and r.cfg.push_yaw_feedback_additive_fallback_enabled:
                from .additive_yaw import AdditiveYawSuffix
                additive_start=time.monotonic()
                attempt=dict(original_quintic_rejection=info['rejection'],accepted=False)
                try:
                    low,high=r.m.jnt_range[r.jids].T
                    lo,hi=entry_limit_envelope(np.stack([q,endpoint])[:,ARM_COLUMNS],low,high,r.cfg.joint_margin_rad)
                    additive=AdditiveYawSuffix(path,duration,boundary/frames,endpoint,(r.v,r.a,r.j))
                    attempt['certificate']=additive.certificate
                    attempt['boundary_errors']=[float(np.max(abs(additive.evaluate(0)[i]-x))) for i,x in enumerate((q,v,a))]
                    attempt['terminal_errors']=[float(np.max(abs(additive.evaluate(1)[i]-x))) for i,x in enumerate((endpoint,np.zeros_like(q),np.zeros_like(q)))]
                    attempt['limit_ratios']={name:float(np.max(additive.reference_bounds[name]/cap)) for name,cap in zip(('velocity','acceleration','jerk'),(r.v,r.a,r.j))}
                    qlo,qhi=additive.extrema[0]
                    rejected=None
                    if max(attempt['boundary_errors']+attempt['terminal_errors'])>1e-8:
                        rejected=dict(reason='additive_boundary_mismatch')
                    elif max(attempt['limit_ratios'].values())>1+1e-9:
                        rejected=dict(reason='additive_derivative_certificate',ratios=attempt['limit_ratios'])
                    elif np.any(qlo[ARM_COLUMNS]<lo) or np.any(qhi[ARM_COLUMNS]>hi) or np.any(qlo[[7,15]]<-1e-8) or np.any(qhi[[7,15]]>.1+1e-8):
                        rejected=dict(reason='additive_joint_certificate')
                    if rejected is None:rejected=r._path_rejection(additive,201,lo,hi,True)
                    if rejected is None and normal_check is not None:rejected=normal_check(additive)
                    if rejected is None:
                        for u in sorted(additive.extremum_times|set(np.linspace(0.,1.,201))):
                            cq,cv,ca,_=additive.evaluate(u);r.audit_online_reference(cq,cv,ca)
                        suffix=additive
                    attempt['accepted']=suffix is not None;attempt['rejection']=rejected
                except (Fault,ValueError,ArithmeticError) as exc:
                    attempt['rejection']=dict(reason=getattr(exc,'code',type(exc).__name__),detail=getattr(exc,'detail',str(exc)))
                attempt['planning_wall_s']=time.monotonic()-additive_start
                info['additive_fallback']=attempt
                if suffix is not None:
                    info['selected_reference']='additive'
                    info['accepted']=True
                    info['rejection']=None
                r.trace.event('push_yaw_feedback_additive_fallback',**attempt)
            info['planning_wall_s']=time.monotonic()-planning_start
            info['fallback_original_suffix']=suffix is None
            r.trace.event('push_yaw_feedback_suffix',**info)
        active=path if suffix is None else suffix
        active_frames=frames if suffix is None else frames-boundary
        active_frame=frame if suffix is None else frame-boundary
        if r.cfg.substep_control_enabled:
            from .substep_control import sample_path_targets
            targets=sample_path_targets(active,active_frame-1,active_frames,r.sim.nstep,r.cfg.fps)
            r.sim.target=targets[-1].copy();r.tick(substep_targets=targets)
        else:
            r.sim.target=active.evaluate(active_frame/active_frames,active_frames/r.cfg.fps)[0]
            r.tick()
