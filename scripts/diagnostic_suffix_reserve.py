"""One private C2 late-suffix budget allocation; no production import."""
import math,time
import numpy as np
from diagnostic_yaw_suffix import FixedDurationQuintic


def execute_force_feedback(machine,planned,operation,side,position,rotation,relation,free_goal):
    from r1pro_teleop.airport_fsm.contracts import ARM_COLUMNS,Fault
    from r1pro_teleop.airport_fsm.runtime import _homogeneous
    from r1pro_teleop.airport_fsm.trajectory import entry_limit_envelope
    r=machine.r;path,frames=planned;duration=frames/r.cfg.fps
    if getattr(r.cfg,'substep_control_enabled',False):raise ValueError('Original frame-control diagnostic only')
    boundary=round(1.5*r.cfg.fps)
    available=r.primitive_deadline_step-r.steps-math.ceil(r.cfg.primitive_settle_s*r.cfg.fps)
    if not boundary<frames<available:raise ValueError('Requires actual unused motion reserve')
    endpoint=path.evaluate(1,duration)
    if np.max(abs(endpoint[1]))>1e-9 or np.max(abs(endpoint[2]))>1e-8:raise ValueError('Original endpoint not at rest')
    zstart=float(r._shadow(r.sim.target).site(side+'_tcp').xpos[2]);zend=float((_homogeneous(position,rotation)@relation)[2,3])
    band=[min(zstart,zend)-.00025,max(zstart,zend)+.00025]
    r.trace.event('primitive_reference',duration_s=duration,controller=type(path).__name__,knot_stop_fallback=False,reference_bounds=path.reference_bounds)
    for frame in range(1,boundary+1):
        r.sim.target=path.evaluate(frame/frames,duration)[0];r.tick()
    q,v,a,_=path.evaluate(boundary/frames,duration);candidate=None;wall=time.monotonic()
    info=dict(boundary_s=boundary/r.cfg.fps,original_motion_s=duration,candidate_motion_s=available/r.cfg.fps,remaining_s=(available-boundary)/r.cfg.fps,normal_band_m=band)
    try:
        proposed=FixedDurationQuintic(q,v,a,endpoint[0],(available-boundary)/r.cfg.fps)
        info['boundary_errors']=[float(np.max(abs(proposed.evaluate(0)[i]-value))) for i,value in enumerate((q,v,a))]
        info['limit_ratios']={name:float(np.max(proposed.reference_bounds[name]/cap)) for name,cap in zip(('velocity','acceleration','jerk'),(r.v,r.a,r.j))}
        lo,hi=entry_limit_envelope(np.stack([q,endpoint[0]])[:,ARM_COLUMNS],*r.m.jnt_range[r.jids].T,r.cfg.joint_margin_rad)
        qlo,qhi=proposed.extrema[0];reason=None
        if max(info['limit_ratios'].values())>1+1e-9:reason=dict(reason='exact_derivative_limit')
        elif np.any(qlo[ARM_COLUMNS]<lo) or np.any(qhi[ARM_COLUMNS]>hi) or np.any(qlo[[7,15]]<-1e-8) or np.any(qhi[[7,15]]>.1+1e-8):reason=dict(reason='exact_joint_limit')
        if reason is None:reason=r._path_rejection(proposed,201,lo,hi,True)
        if reason is None:
            for u in np.linspace(0,1,201):
                z=float(r._shadow(proposed.evaluate(u)[0]).site(side+'_tcp').xpos[2])
                if not band[0]<=z<=band[1]:reason=dict(reason='supported_normal_reference_excursion',fraction=float(u),z_m=z,band=band);break
        if reason is None:
            for u in sorted(proposed.extremum_times|set(np.linspace(0,1,201))):
                cq,cv,ca,_=proposed.evaluate(u);r.audit_online_reference(cq,cv,ca)
            candidate=proposed
        info['rejection']=reason
    except (Fault,ValueError) as exc:info['rejection']=dict(reason=getattr(exc,'code',type(exc).__name__),detail=getattr(exc,'detail',str(exc)))
    info.update(accepted=candidate is not None,planning_wall_s=time.monotonic()-wall)
    r.trace.event('diagnostic_late_suffix_reserve',**info)
    count=frames if candidate is None else available
    for frame in range(boundary+1,count+1):
        r.sim.target=(path.evaluate(frame/frames,duration)[0] if candidate is None else candidate.evaluate((frame-boundary)/(available-boundary))[0])
        r.tick()
