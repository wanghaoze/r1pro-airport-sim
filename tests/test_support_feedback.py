from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.support_feedback import measure_support_force


def fixture_contacts(reverse=False):
    # The tabletop contact normal points up. For reversed geom ordering it
    # points down, and MuJoCo's geom2 force must be negated to recover tray load.
    up=np.array([[0,0,1], [1,0,0], [0,1,0]],float)
    down=np.array([[0,0,-1], [1,0,0], [0,-1,0]],float)
    contacts=[SimpleNamespace(geom1=1 if reverse else 0,geom2=0 if reverse else 1,
                              frame=down if reverse else up),
              SimpleNamespace(geom1=2,geom2=1,frame=up)]
    model=SimpleNamespace(nbody=4,geom_bodyid=np.array([1,2,3]))
    data=SimpleNamespace(ncon=2,contact=contacts)
    def force(model,data,index,out):
        out[:3]=[12,0,0] if index==0 else [100,0,0]
    return model,data,force


@pytest.mark.parametrize('reverse',[False,True])
def test_support_force_uses_body_order_and_excludes_fingers(reverse):
    model,data,force=fixture_contacts(reverse)
    result=measure_support_force(model,data,2,{1},contact_force=force)
    np.testing.assert_allclose(result.resultant_world_n,[0,0,12])
    assert result.load_n==12
    assert result.pair_count==result.qualifying_contact_count==1
    assert result.tangent_world_n==(0.,0.,0.)


def test_contact_frame_transpose_and_friction_are_preserved():
    model,data,_=fixture_contacts()
    def force(model,data,index,out):out[:3]=[12,3,-4]
    result=measure_support_force(model,data,2,{1},contact_force=force)
    np.testing.assert_allclose(result.resultant_world_n,[3,-4,12])
    np.testing.assert_allclose(result.tangent_world_n,[3,-4,0])
    assert result.signed_normal_n==12


def test_sensor_reports_no_support_without_inventing_weight_or_contacts():
    model,data,force=fixture_contacts()
    result=measure_support_force(model,data,2,set(),contact_force=force)
    assert result.load_n==0
    assert result.qualifying_contact_count==result.pair_count==0


def test_subthreshold_force_is_continuous_measurement_not_contact_authorization():
    model,data,_=fixture_contacts()
    def force(model,data,index,out):out[0]=.04
    result=measure_support_force(model,data,2,{1},contact_force=force)
    assert result.load_n==pytest.approx(.04)
    assert result.qualifying_contact_count==0
    assert result.pair_count==1


def test_physical_resting_body_load_matches_weight_without_mutating_state():
    import mujoco
    m=mujoco.MjModel.from_xml_string('''<mujoco><option timestep=".002"/><worldbody>
      <body name="table"><geom type="plane" size="1 1 .1"/></body>
      <body name="tray" pos="0 0 .05"><freejoint/><geom type="sphere" size=".05" mass="1.2"/></body>
    </worldbody></mujoco>''')
    d=mujoco.MjData(m);mujoco.mj_step(m,d,nstep=1000)
    initial={name:getattr(d,name).copy() for name in ('qpos','qvel','ctrl','qacc_warmstart')}
    t=d.time
    result=measure_support_force(m,d,m.body('tray').id,{m.body('table').id})
    assert result.load_n==pytest.approx(1.2*9.81,rel=1e-4)
    assert result.qualifying_contact_count>0
    assert d.time==t
    for name,value in initial.items():np.testing.assert_array_equal(getattr(d,name),value)


@pytest.mark.parametrize('normal',[(0,0,0),(float('nan'),0,1),(0,1)])
def test_invalid_normal_rejected(normal):
    model,data,force=fixture_contacts()
    with pytest.raises(ValueError):measure_support_force(model,data,2,{1},normal=normal,contact_force=force)


def test_self_support_is_rejected():
    model,data,force=fixture_contacts()
    with pytest.raises(ValueError):measure_support_force(model,data,2,{2},contact_force=force)
