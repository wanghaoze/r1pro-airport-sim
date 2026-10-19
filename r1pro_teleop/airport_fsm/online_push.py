"""Opt-in local state-to-state retargeting. No cloud/waypoint API is used."""
from importlib.metadata import version
import numpy as np
from .contracts import Fault, wrap_angle
from .geometry import quat_yaw_tilt, rz


class OnlineJointReference:
    def __init__(self, position, velocity, acceleration, jerk, dt):
        from ruckig import Ruckig, InputParameter, OutputParameter
        self.solver=Ruckig(len(position),dt)
        self.input=InputParameter(len(position));self.output=OutputParameter(len(position))
        self.input.current_position=list(position)
        self.input.current_velocity=[0.]*len(position);self.input.current_acceleration=[0.]*len(position)
        self.input.target_position=list(position)
        self.input.target_velocity=[0.]*len(position);self.input.target_acceleration=[0.]*len(position)
        self.input.max_velocity=list(velocity);self.input.max_acceleration=list(acceleration);self.input.max_jerk=list(jerk)

    def target(self, position, minimum_seconds):
        self.input.target_position=list(position)
        self.input.minimum_duration=float(minimum_seconds)

    def brake(self):
        from ruckig import ControlInterface
        self.input.control_interface=ControlInterface.Velocity
        self.input.target_velocity=[0.]*len(self.input.current_position)
        self.input.target_acceleration=[0.]*len(self.input.current_position)
        self.input.minimum_duration=None

    def velocity_target(self, velocity):
        from ruckig import ControlInterface
        self.input.control_interface=ControlInterface.Velocity
        self.input.target_velocity=list(velocity)
        self.input.target_acceleration=[0.]*len(velocity)
        self.input.minimum_duration=None

    def step(self):
        from ruckig import Result
        status=self.solver.update(self.input,self.output)
        if status not in (Result.Working,Result.Finished):raise Fault('online_trajectory_error',str(status))
        q=np.array(self.output.new_position);v=np.array(self.output.new_velocity);a=np.array(self.output.new_acceleration)
        self.output.pass_to_input(self.input)
        return q,v,a,status==Result.Finished


def execute_push(machine, operation, side, relation, *, separation):
    from .runtime import _homogeneous
    r=machine.r;cfg=machine.c;tray=operation.tray;col=7 if side=='left' else 15
    tracker=OnlineJointReference(r.sim.target,r.v,r.a,r.j,1/cfg.fps)
    initial=r.observation();bottom=initial['min_z'][tray];z=float(initial['tray_pose'][tray,2])
    bias=np.zeros(2);retarget_every=4;braking=False;support_pause=False;contact_loss_frames=0;handoff=False
    budget=min(cfg.online_push_seconds,cfg.max_phase_seconds)
    machine.log.event('online_push_start',ruckig_version=version('ruckig'),control_hz=cfg.fps,
                      retarget_hz=cfg.fps/retarget_every,target_tray=tray,separation=separation)
    # Extra braking budget is bounded separately; no open-gripper transition
    # occurs with a deliberately nonzero reference velocity.
    for frame in range(int((budget+3)*cfg.fps)):
        e=r.observation();actual=e['tray_pose'][tray]
        yaw,_=quat_yaw_tilt(actual[3:]);delta=operation.destination[:2]-actual[:2]
        da=float(wrap_angle(operation.yaw-yaw,machine.g.period))
        done=np.linalg.norm(delta)<.006 and abs(da)<np.deg2rad(1.5)
        if separation:
            done=not machine.g.blockers(e['tray_pose'],tray,actual[:3],yaw,.055)
        near=not separation and np.linalg.norm(delta)<=cfg.online_push_handoff_m
        if not braking and (near or done or frame>=int(budget*cfg.fps)):
            handoff=bool(not done or near)
            tracker.brake();braking=True
            machine.log.event('online_push_brake',goal_reached=bool(done),near_target_handoff=bool(near),
                              budget_exhausted=frame>=int(budget*cfg.fps))
        if not braking and (frame%retarget_every==0 or cfg.online_push_mode=='velocity'):
            if not separation:
                bias+=.15*delta*((1 if cfg.online_push_mode=='velocity' else retarget_every)/cfg.fps)
                bias*=min(1.,.015/max(float(np.linalg.norm(bias)),1e-9))
            position=operation.destination.copy();position[:2]+=bias;position[2]=z
            T=_homogeneous(position,rz(yaw+da))@relation
            goals={side:(T[:3,3],T[:3,:3])}
            if cfg.online_push_mode=='velocity':
                tracker.velocity_target(cartesian_velocity(r,tracker,side,T,cfg.contact_tcp_speed))
            else:
                target=r.solve_pair(goals,np.asarray(tracker.input.current_position))
                target[col]=cfg.gripper_close_m
                if not r._target_valid(target,wrist=True):raise Fault('online_push_target_rejected')
                distance=float(np.linalg.norm(T[:3,3]-r.sim.tcp(side)[0]))
                tracker.target(target,max(.15,2*distance/cfg.contact_tcp_speed,abs(da)/.2))
            if frame%retarget_every==0:
                machine.log.event('push_feedback',controller='online_'+cfg.online_push_mode,target_tray=tray,
                                  position_error_m=float(np.linalg.norm(delta)),yaw_error_rad=da)
        previous=r.sim.target.copy()
        q,v,a,finished=tracker.step()
        for u in (.25,.5,.75,1.):
            if not r._target_valid(previous+u*(q-previous),wrist=True):raise Fault('online_push_path_rejected')
        r.audit_online_reference(q,v,a)
        r.sim.target=q;r.tick()
        e=r.observation()
        height_delta=float(e['min_z'][tray]-bottom)
        if height_delta>.015 or (e['support_contact'][tray]<=0 and abs(height_delta)>.002):
            raise Fault('push_lost_support')
        contact=e['gripper_contact_force'][tray,0 if side=='left' else 1]>.5
        contact_loss_frames=0 if contact else contact_loss_frames+1
        if not contact and contact_loss_frames==1:
            machine.log.event('online_push_contact_loss',target_tray=tray)
        if (e['support_contact'][tray]<=0 or contact_loss_frames>=4) and not support_pause:
            tracker.brake();braking=True;support_pause=True
            machine.log.event('push_support_brake',target_tray=tray,bottom_delta_m=height_delta)
        if braking and finished:
            if not support_pause:
                machine.log.event('online_push_handoff' if handoff else 'online_push_complete',
                                  target_tray=tray,reference_velocity_zero=True)
                return not handoff
            if not r.wait(.3,lambda x:x['support_contact'][tray]>0 and
                          x['gripper_contact_force'][tray,0 if side=='left' else 1]>.5,.05):
                raise Fault('online_push_contact_not_restored')
            tracker=OnlineJointReference(r.sim.target,r.v,r.a,r.j,1/cfg.fps)
            braking=False;support_pause=False;contact_loss_frames=0
            machine.log.event('push_support_resume',target_tray=tray)
    raise Fault('online_push_brake_timeout')


def cartesian_velocity(r, tracker, side, goal, speed):
    """Damped differential IK with measured task error and joint braking margin."""
    from scipy.spatial.transform import Rotation
    offset,index=(0,0) if side=='left' else (8,7)
    columns=np.arange(offset,offset+7);dofs=r.dofs[index:index+7]
    position,rotation=r.sim.tcp(side)
    linear=1.5*(goal[:3,3]-position)
    linear*=min(1.,speed/max(float(np.linalg.norm(linear)),1e-9))
    angular=1.5*Rotation.from_matrix(goal[:3,:3]@rotation.T).as_rotvec()
    angular*=min(1.,.2/max(float(np.linalg.norm(angular)),1e-9))
    jp=np.zeros((3,r.m.nv));jr=jp.copy()
    r.mj.mj_jacSite(r.m,r.d,jp,jr,r.m.site(side+'_tcp').id)
    J=np.vstack([jp[:,dofs],.4*jr[:,dofs]])
    desired=np.r_[linear,.4*angular]
    J[2]*=3.;desired[2]*=3.  # Keep the contact height while pushing in XY.
    q=np.asarray(tracker.input.current_position)[columns]
    current_v=np.asarray(tracker.input.current_velocity)[columns]
    lo,hi=r.m.jnt_range[r.jids[index:index+7]].T
    braking=current_v**2/(2*r.a[columns])+abs(current_v)*r.a[columns]/r.j[columns]+.02
    free=np.ones(7,dtype=bool);v=np.zeros(7)
    for _ in range(8):
        v[:]=0.
        if not free.any():break
        n=int(free.sum())
        v[free]=np.linalg.lstsq(np.vstack([J[:,free],.02*np.eye(n)]),
                               np.r_[desired,np.zeros(n)],rcond=None)[0]
        blocked=((v<0)&(q-lo<braking))|((v>0)&(hi-q<braking))
        if not np.any(blocked&free):break
        free[blocked]=False
    v*=min(1.,float(np.min(r.v[columns]/np.maximum(abs(v),1e-9))))
    result=np.zeros(16);result[columns]=v
    return result
