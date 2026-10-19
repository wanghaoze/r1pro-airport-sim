"""Real MuJoCo environmental transition tests; no robot task success claims."""
import copy
from pathlib import Path
import mujoco
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from r1pro_teleop.airport_recording import AirportSimulation
from r1pro_teleop.single_tray_lab.scene import ROOT
from r1pro_teleop.single_tray_lab.three_table_scene import generate_three_table_scene,passenger_load_three_table


@pytest.fixture(scope='module')
def scene(tmp_path_factory):
    registry=ROOT/'resources/single_tray_three_table_v1/source_registry'
    return generate_three_table_scene(tmp_path_factory.mktemp('passenger_three_tables')/'scene',registry/'ordinary/airport_0004_20270920/scene.json',registry/'parent_manifest.json',202610061615,split_registry=registry/'canonical_split_registry.json')


def simulation(scene,yaw):
    sim=AirportSimulation(scene['xml'],render=False);m,d=sim.model,sim.data
    joint=m.joint('tray_free');a=int(m.jnt_qposadr[joint.id]);d.qpos[a:a+3]=[.85,.05,.801]
    d.qpos[a+3:a+7]=Rotation.from_euler('z',yaw).as_quat()[[3,0,1,2]]
    d.time=.123;d.qvel[:]=np.linspace(-.001,.001,m.nv);d.ctrl[:]=np.linspace(-.02,.02,m.nu)
    mujoco.mj_forward(m,d);return sim


def relative_payload(sim,scene):
    m,d=sim.model,sim.data;origin=d.body('tray').xpos;R=d.body('tray').xmat.reshape(3,3);values={}
    for item in scene['payloads']:
        if item['flex']:
            fid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_FLEX,item['name']);a=int(m.flex_vertadr[fid]);n=int(m.flex_vertnum[fid]);values[item['kind']]=dict(points=(d.flexvert_xpos[a:a+n]-origin)@R)
        else:
            body=d.body(item['name']);values[item['kind']]=dict(position=(body.xpos-origin)@R,rotation=R.T@body.xmat.reshape(3,3))
    return values


@pytest.mark.parametrize('yaw',[0.,np.pi])
def test_real_mujoco_rotates_reference_layout_including_all_cloth_nodes(scene,yaw):
    ref=simulation(scene,np.pi/2);sim=simulation(scene,yaw)
    try:
        a=passenger_load_three_table(ref,scene);b=passenger_load_three_table(sim,scene)
        ra=relative_payload(ref,scene);rb=relative_payload(sim,scene)
        assert set(ra)==set(rb)=={'backpack','coat','laptop'}
        for kind in ra:
            for key in ra[kind]:np.testing.assert_allclose(ra[kind][key],rb[kind][key],atol=1e-11,rtol=0)
        assert ra['coat']['points'].shape==(63,3)
        assert a['payload_mass_kg']==b['payload_mass_kg']
        assert b['actual_tray_yaw_rad']==pytest.approx(0 if yaw==0 else np.pi)
        assert b['layout_bound_to_actual_tray_horizontal_frame']
    finally:ref.close();sim.close()


def apply_journal(sim,journal):
    m,d=sim.model,sim.data
    np.testing.assert_array_equal(d.qpos[journal['qpos_indices']],journal['qpos_before'])
    np.testing.assert_array_equal(d.qvel[journal['qvel_indices']],journal['qvel_before'])
    d.qpos[journal['qpos_indices']]=journal['qpos_after'];d.qvel[journal['qvel_indices']]=journal['qvel_after']
    for event in journal['model_visual_changes']:
        arr=m.geom_rgba if event['kind']=='geom_rgba' else m.flex_rgba
        np.testing.assert_allclose(arr[event['index']],event['before'],atol=0,rtol=0);arr[event['index']]=event['after']
    mujoco.mj_forward(m,d)


@pytest.mark.parametrize('yaw',[0.,np.pi])
def test_complete_journal_preserves_protected_state_and_replays_continuously(scene,yaw):
    original=simulation(scene,yaw);replay=simulation(scene,yaw)
    try:
        m,d=original.model,original.data;beforeq=d.qpos.copy();beforev=d.qvel.copy();beforectrl=d.ctrl.copy();stamp=d.time
        physics={k:getattr(m,k).copy() for k in ('body_mass','body_inertia','geom_contype','geom_conaffinity','geom_friction','flex_elem','flex_edge')}
        journal=passenger_load_three_table(original,scene)
        qmask=np.ones(m.nq,bool);qmask[journal['qpos_indices']]=False;vmask=np.ones(m.nv,bool);vmask[journal['qvel_indices']]=False
        np.testing.assert_array_equal(d.qpos[qmask],beforeq[qmask]);np.testing.assert_array_equal(d.qvel[vmask],beforev[vmask]);np.testing.assert_array_equal(d.ctrl,beforectrl);assert d.time==stamp
        for k,expected in physics.items():np.testing.assert_array_equal(getattr(m,k),expected)
        assert journal['training_eligible'] is False and journal['action']=='passenger_load'
        assert len(set(journal['qpos_indices']))==len(journal['qpos_indices'])
        apply_journal(replay,journal)
        np.testing.assert_array_equal(replay.data.qpos,d.qpos);np.testing.assert_array_equal(replay.data.qvel,d.qvel)
        # Same real integration in two models, one after function and one from
        # journal application, proves the endpoint is sufficient for replay.
        for _ in range(25):mujoco.mj_step(m,d);mujoco.mj_step(replay.model,replay.data)
        np.testing.assert_array_equal(replay.data.qpos,d.qpos);np.testing.assert_array_equal(replay.data.qvel,d.qvel);assert replay.data.time==d.time
    finally:original.close();replay.close()
