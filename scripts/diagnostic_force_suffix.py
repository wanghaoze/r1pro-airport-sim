"""Private bounded real-contact force feedback; no production imports this file."""
from collections import deque
import time
import numpy as np
from diagnostic_yaw_suffix import FixedDurationQuintic


class ForceWindow:
    """Causal Newton-second integration and two-frame load estimate."""
    def __init__(self,entry_height,force_gain=25e-6):
        self.entry_height=float(entry_height);self.reference=[];self.window=deque(maxlen=2)
        self.force_gain=float(force_gain)
        if not np.isfinite(self.force_gain) or not 0<=self.force_gain<=25e-6:raise ValueError('Invalid diagnostic force gain')
        self.fref=None
    def append(self,samples,dt):
        if not samples or dt<=0:raise ValueError('Completed physical samples and positive dt required')
        force=np.asarray([x[0] for x in samples],float)
        height=np.asarray([x[1] for x in samples],float)
        if not np.isfinite(force).all() or not np.isfinite(height).all():raise ValueError('Nonfinite observations')
        row=dict(mean_force_n=float(np.sum(force*dt)/(len(force)*dt)),mean_height_m=float(height.mean()),
                 support_fraction=float(np.mean([x[2]>0 for x in samples])))
        self.window.append(row)
        if len(self.reference)<5:
            self.reference.append(row)
            if len(self.reference)==5 and all(x['support_fraction']>=.9 for x in self.reference):
                self.fref=float(np.mean([x['mean_force_n'] for x in self.reference]))
        return row
    def request(self):
        if self.fref is None or len(self.window)<2:return None,'reference_not_initialized'
        force=float(np.mean([x['mean_force_n'] for x in self.window]))
        height=float(np.mean([x['mean_height_m'] for x in self.window]))
        offset=-float(np.clip(self.force_gain*(self.fref-force),-.00015,.00015))
        if offset<0 and height<self.entry_height-.00005:return None,'already_compressed_height_gate'
        return dict(offset_m=offset,fref_n=self.fref,mean_force_n=force,mean_height_m=height),None


def checked_replacement(current,builder):
    """A rejected update preserves the previously accepted curve object."""
    try:
        candidate,reason=builder()
        return (current,reason) if reason is not None else (candidate,None)
    except ValueError as exc:return current,dict(reason='ValueError',detail=str(exc))


def execute_force_feedback(machine,planned,operation,side,position,rotation,relation,free_goal,*,force_gain=25e-6):
    from r1pro_teleop.airport_fsm.contracts import ARM_COLUMNS,Fault
    from r1pro_teleop.airport_fsm.runtime import _homogeneous
    from r1pro_teleop.airport_fsm.trajectory import entry_limit_envelope
    from push_diagnostic_support import measure_support_force
    r=machine.r;original,frames=planned;duration=frames/r.cfg.fps
    if getattr(r.cfg,'substep_control_enabled',False):raise ValueError('Private experiment requires original frame control')
    if frames>r.primitive_deadline_step-r.steps:raise Fault('primitive_insufficient_time')
    if not np.isclose(r.m.opt.timestep*r.sim.nstep,1/r.cfg.fps,atol=1e-12):raise ValueError('Inconsistent clock')
    tables={r.m.body(name).id for name in ('front_left','front_right','rear')}
    normals=[r.d.body(name).xmat.reshape(3,3)[:,2].copy() for name in ('front_left','front_right','rear')]
    normal=normals[0]
    if any(not np.allclose(n,normal,atol=1e-10) for n in normals):raise ValueError('Table normals differ; no shared projection')
    if not np.allclose(normal,[0,0,1],atol=1e-10):raise ValueError('Height gate requires horizontal support tables')
    bid=r.m.body(machine.g.ids[operation.tray]).id
    window=ForceWindow(r.observation()['min_z'][operation.tray],force_gain);observed=[]
    previous_guard=r.guard
    def guard():
        previous_guard()  # Physical failures propagate immediately; never converted to candidate rejection.
        measured=measure_support_force(r.m,r.d,bid,tables,normal=normal)
        observed.append((measured.signed_normal_n,float(r.observation()['min_z'][operation.tray]),measured.qualifying_contact_count))
    r.guard=guard
    active=original;offset_frame=0;active_frames=frames
    endpoint_original=original.evaluate(1,duration)
    if np.max(abs(endpoint_original[1]))>1e-9 or np.max(abs(endpoint_original[2]))>1e-8:raise ValueError('Nonrest original endpoint')
    startz=float(r._shadow(r.sim.target).site(side+'_tcp').xpos[2]);endT=_homogeneous(position,rotation)@relation
    zlow=min(startz,float(endT[2,3]))-.00025;zhigh=max(startz,float(endT[2,3]))+.00025
    r.trace.event('primitive_reference',duration_s=duration,controller=type(original).__name__,
                  knot_stop_fallback=False,reference_bounds=original.reference_bounds)
    try:
        for frame in range(1,frames+1):
            completed=frame-1
            if 30<=completed<40:
                wall=time.monotonic();request,reason=window.request()
                info=dict(completed_frame=completed,remaining_s=(frames-completed)/r.cfg.fps,
                          request=request,accepted=False,rejection=reason)
                if request is not None:
                    q,v,a,_=active.evaluate((completed-offset_frame)/active_frames,active_frames/r.cfg.fps)
                    def build():
                        target_position=np.asarray(position).copy()+request['offset_m']*normal
                        target=_homogeneous(target_position,rotation)@relation
                        goals={side:(target[:3,3],target[:3,:3])}
                        if free_goal is not None:goals[free_goal[0]]=(free_goal[1],free_goal[2])
                        endpoint=r.solve_pair(goals,endpoint_original[0].copy());endpoint[[7,15]]=endpoint_original[0][[7,15]]
                        candidate=FixedDurationQuintic(q,v,a,endpoint,(frames-completed)/r.cfg.fps)
                        ratios={name:float(np.max(candidate.reference_bounds[name]/cap)) for name,cap in zip(('velocity','acceleration','jerk'),(r.v,r.a,r.j))}
                        info['ratios']=ratios
                        info['boundary_errors']=[float(np.max(abs(candidate.evaluate(0)[i]-x))) for i,x in enumerate((q,v,a))]
                        if max(ratios.values())>1+1e-9:return None,dict(reason='exact_derivative_limit')
                        low,high=r.m.jnt_range[r.jids].T
                        lo,hi=entry_limit_envelope(np.stack([q,endpoint])[:,ARM_COLUMNS],low,high,r.cfg.joint_margin_rad)
                        qlo,qhi=candidate.extrema[0]
                        if np.any(qlo[ARM_COLUMNS]<lo) or np.any(qhi[ARM_COLUMNS]>hi) or np.any(qlo[[7,15]]<-1e-8) or np.any(qhi[[7,15]]>.1+1e-8):return None,dict(reason='exact_joint_limit')
                        rejection=r._path_rejection(candidate,201,lo,hi,True)
                        if rejection is not None:return None,rejection
                        for u in np.linspace(0,1,201):
                            z=float(r._shadow(candidate.evaluate(u)[0]).site(side+'_tcp').xpos[2])
                            if not zlow<=z<=zhigh:return None,dict(reason='supported_normal_reference_excursion',fraction=float(u),z_m=z,band=[zlow,zhigh])
                        for u in sorted(candidate.extremum_times|set(np.linspace(0,1,201))):
                            cq,cv,ca,_=candidate.evaluate(u);r.audit_online_reference(cq,cv,ca)
                        return candidate,None
                    try:
                        replacement,rejection=checked_replacement(active,build)
                    except Fault as exc:
                        replacement=active;rejection=dict(reason=exc.code,detail=exc.detail)
                    if replacement is not active:
                        active=replacement;offset_frame=completed;active_frames=frames-completed;info['accepted']=True
                    info['rejection']=rejection
                info['planning_wall_s']=time.monotonic()-wall
                r.trace.event('diagnostic_force_feedback_update',**info)
            observed.clear()
            r.sim.target=active.evaluate((frame-offset_frame)/active_frames,active_frames/r.cfg.fps)[0]
            r.tick()
            if len(observed)!=r.sim.nstep:raise ValueError('Expected exactly one force observation per physical step')
            row=window.append(observed,float(r.m.opt.timestep))
            r.trace.event('diagnostic_force_frame',completed_frame=frame,reference_n=window.fref,**row)
    finally:r.guard=previous_guard
