import mujoco
import numpy as np
from scipy.spatial.transform import Rotation
from r1pro_teleop.airport_fsm.camera_guard import self_view_hits


def scene():
    m=mujoco.MjModel.from_xml_string('<mujoco><worldbody><geom name="torso" type="box" pos="0 0 1" size=".15 .2 .4"/></worldbody></mujoco>')
    d=mujoco.MjData(m);mujoco.mj_forward(m,d)
    return m,d


def rotation_for(forward):
    z=-np.asarray(forward,dtype=float);z/=np.linalg.norm(z)
    x=np.cross([0,1,0],z);x/=np.linalg.norm(x)
    return np.column_stack((x,np.cross(z,x),z))


def test_downward_at_table_does_not_mean_facing_self():
    m,d=scene();before=m.geom_group.copy();q=d.qpos.copy()
    assert not self_view_hits(m,d,np.array([.6,0,.9]),rotation_for([-.28,0,-.96]),[0])
    np.testing.assert_array_equal(before,m.geom_group);np.testing.assert_array_equal(q,d.qpos)


def test_genuinely_facing_torso_is_rejected():
    m,d=scene()
    assert self_view_hits(m,d,np.array([.6,0,.9]),rotation_for([-1,0,.1]),[0])==[0]


def test_near_axis_body_is_rejected_by_cone():
    m,d=scene()
    # Camera just outside box width; central ray misses, cone hits the side.
    pos=np.array([.6,.23,.9]);rot=rotation_for([-1,0,0])
    assert not self_view_hits(m,d,pos,rot,[0],.01)
    assert self_view_hits(m,d,pos,rot,[0],5)==[0]
