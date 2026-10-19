import importlib.util,pathlib
import mujoco
import numpy as np
p=pathlib.Path(__file__).with_name('diagnostic_contact_kinematics.py');spec=importlib.util.spec_from_file_location('diagnostic_contact_kinematics',p);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def test_point_velocity_world_translation_rotation_and_read_only():
 m=mujoco.MjModel.from_xml_string('<mujoco><worldbody><body name="tray"><freejoint/><geom type="sphere" size=".1" mass="1"/></body></worldbody></mujoco>');d=mujoco.MjData(m)
 d.qvel[:]=[1,2,3,0,0,2];mujoco.mj_forward(m,d)
 before=(d.qpos.copy(),d.qvel.copy(),d.qacc_warmstart.copy(),d.ctrl.copy())
 v,w=mod.point_velocity(mujoco,m,d,m.body('tray').id,np.array([1.,0,0]))
 np.testing.assert_allclose(v,[1,4,3]);np.testing.assert_allclose(w,[0,0,2])
 for a,b in zip(before,(d.qpos,d.qvel,d.qacc_warmstart,d.ctrl)):np.testing.assert_array_equal(a,b)
