import numpy as np
import pytest
import mujoco as mj
from r1pro_teleop.single_tray_lab.replay import SingleTrayReplay

def fixture():
 m=mj.MjModel.from_xml_string('<mujoco><worldbody><body name="robot"><joint type="slide"/><geom size=".1"/></body><body name="tray"><freejoint/><geom size=".1"/></body><body name="passenger_backpack"><freejoint/><geom size=".1" rgba="1 0 0 0"/></body></worldbody></mujoco>');d=mj.MjData(m);mj.mj_forward(m,d)
 replay=SingleTrayReplay.__new__(SingleTrayReplay);replay.mj=mj;replay.model=m;replay.data=d;replay.meta={'scene':{'payloads':[dict(kind='backpack',name='passenger_backpack',flex=False)]}}
 jid=m.body('passenger_backpack').jntadr[0];qa=int(m.jnt_qposadr[jid]);va=int(m.jnt_dofadr[jid]);gid=m.body('passenger_backpack').geomadr[0]
 event=dict(schema='airport_passenger_environment_transition/1',physics_mass_inertia_contact_unchanged=True,robot_tray_time_control_unchanged=True,qpos_indices=list(range(qa,qa+7)),qpos_before=d.qpos[qa:qa+7].tolist(),qpos_after=[.2,.3,.4,1,0,0,0],qvel_indices=list(range(va,va+6)),qvel_before=d.qvel[va:va+6].tolist(),qvel_after=[0]*6,model_visual_changes=[dict(kind='geom_rgba',index=int(gid),before=m.geom_rgba[gid].tolist(),after=[1,0,0,1])])
 return replay,event

def test_payload_journal_preserves_robot_tray_time_control_and_physics():
 r,event=fixture();before=r.data.qpos.copy();mass=r.model.body_mass.copy();ctrl=r.data.ctrl.copy();stamp=r.data.time;r.environment(event)
 assert np.array_equal(r.data.qpos[:8],before[:8]) and np.array_equal(r.model.body_mass,mass) and np.array_equal(r.data.ctrl,ctrl) and r.data.time==stamp
 assert np.array_equal(r.data.qpos[event['qpos_indices']],event['qpos_after'])

@pytest.mark.parametrize('change,error',[(lambda e:e.update(qpos_indices=[0],qpos_before=[0],qpos_after=[1]),'nonpayload'),(lambda e:e.update(physics_mass_inertia_contact_unchanged=False),'unsupported'),(lambda e:e['model_visual_changes'][0].update(index=0),'not_payload')])
def test_robot_or_physics_mutations_rejected(change,error):
 r,event=fixture();change(event)
 with pytest.raises(ValueError,match=error):r.environment(event)
