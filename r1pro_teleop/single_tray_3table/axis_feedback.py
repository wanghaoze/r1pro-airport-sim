"""Bounded coupled push reference math; no simulator state writes."""
from dataclasses import dataclass
import numpy as np
from r1pro_teleop.airport_fsm.contracts import wrap_angle
from r1pro_teleop.airport_fsm.geometry import rz


@dataclass(frozen=True)
class AxisProposal:
    body_reference: np.ndarray
    tcp_reference: np.ndarray
    tool_rotation: np.ndarray
    command_yaw: float
    yaw_delta: float
    body_delta: np.ndarray
    clearance: float
    paused_y: bool
    yaw_error: float


class PushAxisReference:
    def __init__(self,body_position,body_rotation,command_tcp,command_tool,forward):
        self.body_reference=np.asarray(body_position,float).copy()
        self.capture_rotation=np.asarray(body_rotation,float).copy()
        self.material_point=self.capture_rotation.T@(np.asarray(command_tcp)-self.body_reference)
        self.relative_tool=self.capture_rotation.T@np.asarray(command_tool)
        self.initial_yaw=float(np.arctan2(self.capture_rotation[1,0],self.capture_rotation[0,0]))
        self.command_yaw=self.initial_yaw
        heading=float(np.arctan2(forward[1],forward[0]))
        self.goal_yaw=self.initial_yaw+float(wrap_angle(heading-self.initial_yaw,np.pi))
        self.tcp_reference=np.asarray(command_tcp,float).copy()
        self.previous_clearance=None

    def propose(self,obs,actual_tcp,profile,remaining):
        forward=-np.asarray(profile.front_normal);left=np.asarray(profile.robot_left)
        corners=np.asarray(obs['tray_corners']);centre=float(np.r_[profile.table_center_xy,0.]@forward)
        half=float(np.asarray(profile.table_half_sizes_xy)@np.abs(forward[:2]))
        lower=centre-half;upper=centre+half
        clearance=min(float(np.min(corners@forward))-lower,upper-float(np.max(corners@forward)))
        paused=clearance<profile.push_table_inboard_margin_m and (self.previous_clearance is None or clearance<self.previous_clearance-1e-6)
        rotation=np.asarray(obs['tray_rotation']);actual_yaw=float(np.arctan2(rotation[1,0],rotation[0,0]))
        error=float(wrap_angle(self.goal_yaw-actual_yaw,np.pi))
        desired_yaw=self.goal_yaw+float(np.clip(error,-profile.push_axis_integral_limit_rad,profile.push_axis_integral_limit_rad))
        dyaw=float(np.clip(wrap_angle(desired_yaw-self.command_yaw),-profile.push_axis_step_rad,profile.push_axis_step_rad))
        command_yaw=self.command_yaw+dyaw
        command_rotation=rz(command_yaw-self.initial_yaw)@self.capture_rotation
        lead=float((self.tcp_reference-np.asarray(actual_tcp))@left)
        increment=0. if paused else min(profile.push_step_m,max(0.,remaining),max(0.,profile.push_reference_lead_m-lead))
        below=lower+profile.push_table_inboard_margin_m-float(np.min(corners@forward))
        above=float(np.max(corners@forward))-(upper-profile.push_table_inboard_margin_m)
        xerror=((below-above)/2 if below>0 and above>0 else below if below>0 else -above if above>0 else 0.)
        xstep=float(np.clip(xerror,-profile.push_forward_reference_step_m,profile.push_forward_reference_step_m))
        body=self.body_reference+increment*left+xstep*forward
        tcp=body+command_rotation@self.material_point
        for axis,cap in ((left,profile.push_reference_lead_m),(forward,profile.push_forward_reference_lead_m)):
            projected=float((tcp-actual_tcp)@axis)
            correction=(float(np.clip(projected,-cap,cap))-projected)*axis
            body+=correction;tcp+=correction
        tool=command_rotation@self.relative_tool
        return AxisProposal(body,tcp,tool,command_yaw,dyaw,body-self.body_reference,clearance,paused,error)

    def commit(self,proposal):
        self.body_reference=proposal.body_reference.copy();self.tcp_reference=proposal.tcp_reference.copy()
        self.command_yaw=proposal.command_yaw;self.previous_clearance=proposal.clearance

def predict_shadow_pose(controller,shadow,translation,yaw_delta):
    """Rotate/translate registered tray and passengers ONLY in own MjData.

    Payload rigid free joints and flex slide nodes share the actual tray pivot.
    No model mass/inertia/friction/geometry/control or live state is changed.
    """
    if shadow is controller.d:raise ValueError('private_prediction_requires_distinct_data')
    R=rz(float(yaw_delta));delta=np.asarray(translation,float)
    if delta.shape!=(3,) or not np.isfinite(delta).all() or not np.isfinite(yaw_delta):
        raise ValueError('finite_private_rigid_increment_required')
    pivot=controller.d.body(controller.p.tray_body).xpos.copy()
    moved=controller.tray|(controller.payload if controller.loaded else set())
    qrot=np.array([np.cos(yaw_delta/2),0.,0.,np.sin(yaw_delta/2)])
    for joint,body in enumerate(controller.m.jnt_bodyid):
        if int(body) not in moved or controller.m.jnt_type[joint]!=0:continue
        adr=int(controller.m.jnt_qposadr[joint]);point=shadow.qpos[adr:adr+3].copy()
        shadow.qpos[adr:adr+3]=pivot+R@(point-pivot)+delta
        quat=np.empty(4);controller.mj.mju_mulQuat(quat,qrot,shadow.qpos[adr+3:adr+7].copy())
        shadow.qpos[adr+3:adr+7]=quat
    if controller.loaded:
        for flex in controller.flexes:
            start=int(controller.m.flex_vertadr[flex]);count=int(controller.m.flex_vertnum[flex])
            for body in set(int(x) for x in controller.m.flex_vertbodyid[start:start+count]):
                actual=controller.d.body(body).xpos.copy();movement=pivot+R@(actual-pivot)+delta-actual
                basis=controller.d.body(body).xmat.reshape(3,3)
                for joint in range(controller.m.body_jntadr[body],controller.m.body_jntadr[body]+controller.m.body_jntnum[body]):
                    if controller.m.jnt_type[joint]==2:
                        world_axis=basis@controller.m.jnt_axis[joint]
                        shadow.qpos[int(controller.m.jnt_qposadr[joint])]+=float(world_axis@movement)
