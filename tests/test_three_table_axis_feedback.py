import math
from dataclasses import replace
from types import SimpleNamespace
import mujoco
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.geometry import rz
from r1pro_teleop.single_tray_3table.axis_feedback import PushAxisReference,predict_shadow_pose
from r1pro_teleop.single_tray_3table.loaded_bridge import LoadedBridgeController,LoadedBridgeProfile
from r1pro_teleop.single_tray_lab.control import SingleTrayController


def profile():
    return replace(LoadedBridgeProfile(),push_command_reference=True,push_lead_frame='measured_tcp',push_axis_feedback_enabled=True)


def observation(yaw=-.04,x=.85):
    R=rz(yaw);p=np.array([x,0,.8]);corners=np.array([[a,b,z] for a in (-.28,.28) for b in (-.215,.215) for z in (0,.105)])@R.T+p
    return {'tray_position':p,'tray_rotation':R,'tray_corners':corners}


def state():
    return PushAxisReference([.85,0,.8],np.eye(3),[.85,.205,.885],np.eye(3),[1,0,0])


def test_captured_material_point_and_tool_rotation_move_together_without_actual_tcp_reset():
    s=state();material=s.material_point.copy();before=s.tcp_reference.copy();obs=observation(-.05,x=.84)
    p=s.propose(obs,np.array([.85,.205,.88]),profile(),.2)
    assert p.yaw_delta==pytest.approx(math.radians(.5)) and p.paused_y
    assert p.body_reference[1]==0.  # no new left-axis force accumulation
    R=rz(p.command_yaw-s.initial_yaw)@s.capture_rotation
    np.testing.assert_allclose(p.tcp_reference,p.body_reference+R@material)
    np.testing.assert_allclose(p.tool_rotation,R@s.relative_tool)
    np.testing.assert_array_equal(s.tcp_reference,before)
    np.testing.assert_array_equal(s.material_point,material)
    assert p.tcp_reference[2]==pytest.approx(.885)  # commanded preload persists


def test_reference_force_lead_caps_and_unoriented_forward_target_are_preserved():
    s=PushAxisReference([.85,0,.8],rz(np.pi),[.85,.205,.885],np.eye(3),[1,0,0])
    assert s.goal_yaw==pytest.approx(np.pi)
    actual=np.array([.84,.19,.88]);obs=observation(np.pi-.2)
    p=s.propose(obs,actual,profile(),.2)
    assert abs(p.yaw_delta)<=math.radians(.5)+1e-12
    assert abs((p.tcp_reference-actual)@np.array([0,1,0]))<=.04+1e-12
    assert abs((p.tcp_reference-actual)@np.array([1,0,0]))<=.02+1e-12


def test_disabled_bridge_delegates_exact_original_reference_methods(monkeypatch):
    c=LoadedBridgeController.__new__(LoadedBridgeController);c.p=LoadedBridgeProfile();c.pending_axis_proposal=None
    calls=[]
    monkeypatch.setattr(SingleTrayController,'_next_tcp_push_reference',lambda self,*args:calls.append(('next',args)) or ('old','tcp'))
    monkeypatch.setattr(SingleTrayController,'_push_reference_move',lambda self,*args:calls.append(('submit',args)) or 'oldresult')
    ref=np.array([1.,2.,3.])
    assert c._next_tcp_push_reference(ref,'right',.2)==('old','tcp')
    assert c._push_reference_move(ref,'right')=='oldresult'
    assert calls[0][1][0] is ref and calls[1][1][0] is ref


def test_discarded_right_proposal_does_not_commit_yaw_anchor_or_target():
    c=LoadedBridgeController.__new__(LoadedBridgeController);c.p=profile();s=state()
    c.axis_references={'right':s};c.pending_axis_proposal=None
    c.push_anchor=('right',np.array([.85,0,.8]),np.array([.85,.205,.885]),np.eye(3))
    c.observation=lambda:observation(-.05,x=.84);target=np.arange(16,dtype=float)
    c.sim=SimpleNamespace(tcp=lambda side:(np.array([.85,.205,.88]),np.eye(3)),target=target.copy())
    c.event=lambda *a,**k:None
    anchor=tuple(x.copy() if isinstance(x,np.ndarray) else x for x in c.push_anchor)
    proposed=c._next_tcp_push_reference(np.array([.85,0,.8]),'right',.2)
    assert c.pending_axis_proposal is not None and s.command_yaw==0.
    np.testing.assert_array_equal(s.body_reference,[.85,0,.8]);np.testing.assert_array_equal(c.sim.target,target)
    for old,new in zip(anchor,c.push_anchor):
        if isinstance(old,np.ndarray):np.testing.assert_array_equal(old,new)
    assert proposed[1][0]!=pytest.approx(.85)  # coupled yaw changed proposed TCP only


def test_private_coupled_pose_moves_tray_rigid_payload_and_flex_without_live_or_mass_writes():
    xml='''<mujoco><worldbody><body name="tray" pos=".85 0 .8"><freejoint/><geom type="box" size=".28 .215 .02" mass="1.2"/></body><body name="bag" pos=".9 .1 .86"><freejoint/><geom size=".02" mass=".2"/></body><flexcomp name="coat" type="grid" count="2 2 1" spacing=".03 .03 .03" dim="2" pos=".9 -.1 .9" mass=".1" radius=".0025"/></worldbody></mujoco>'''
    m=mujoco.MjModel.from_xml_string(xml);d=mujoco.MjData(m);mujoco.mj_forward(m,d)
    c=SimpleNamespace(m=m,d=d,mj=mujoco,p=SimpleNamespace(tray_body='tray'),tray={m.body('tray').id},payload={m.body('bag').id},loaded=True,flexes={0})
    shadow=mujoco.MjData(m);shadow.qpos[:]=d.qpos
    q=d.qpos.copy();v=d.qvel.copy();mass=m.body_mass.copy();ctrl=d.ctrl.copy();pivot=d.body('tray').xpos.copy()
    vertices=set(int(x) for x in m.flex_vertbodyid);before={b:d.body(b).xpos.copy() for b in vertices}
    shift=np.array([.002,.003,0.]);angle=math.radians(.5)
    predict_shadow_pose(c,shadow,shift,angle);mujoco.mj_forward(m,shadow)
    np.testing.assert_allclose(shadow.body('bag').xpos,pivot+rz(angle)@(d.body('bag').xpos-pivot)+shift)
    for b in vertices:np.testing.assert_allclose(shadow.body(b).xpos,pivot+rz(angle)@(before[b]-pivot)+shift)
    np.testing.assert_array_equal(d.qpos,q);np.testing.assert_array_equal(d.qvel,v)
    np.testing.assert_array_equal(d.ctrl,ctrl);np.testing.assert_array_equal(m.body_mass,mass)
    with pytest.raises(ValueError,match='distinct_data'):predict_shadow_pose(c,d,shift,angle)
