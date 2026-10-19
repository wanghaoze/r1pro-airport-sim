"""Random tray yaw must not qualify short rims then execute long rims."""
from types import SimpleNamespace
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from r1pro_teleop.airport_fsm.contracts import Fault
from r1pro_teleop.airport_fsm.machine import Machine
from r1pro_teleop.airport_fsm.rim_affordances import RimCandidate, rim_pairs
from r1pro_teleop.airport_fsm.reachability_planner import alternate_candidate_lattice
from r1pro_teleop.single_tray_3table.control import ThreeTableMachine


def machine(yaw, table_id='rear'):
    m=ThreeTableMachine.__new__(ThreeTableMachine)
    q=Rotation.from_euler('z',yaw).as_quat()[[3,0,1,2]]
    m._poses=lambda:np.array([[0.,0.,.801,*q]])
    table=dict(table_id=table_id,center_world=[0.,0.,0.],
        dimensions_m=[1.2,.6,.8],yaw_world=np.pi/2)
    m.g=SimpleNamespace(sizes=np.array([[.56,.43,.105]]),
        tables={table_id:table},support_table=lambda p:table_id)
    m.c=SimpleNamespace(rim_inset_m=.01)
    m.grasp_stagger=0.
    m.r=SimpleNamespace(grasp_goals=lambda center,face,**kw:
        kw['rim_pair'].goals(center,x_offset=kw['x_offset'],sides=kw['sides']))
    return m


@pytest.mark.parametrize('yaw',[-1.3704311427,1.3239129912,0.,np.pi/2])
@pytest.mark.parametrize('table_id',['rear','front_left'])
def test_expanded_screen_pool_and_live_goals_use_same_opposed_long_edges(yaw,table_id):
    m=machine(yaw,table_id)
    normal=np.pi if table_id=='rear' else 0.
    pool=list(alternate_candidate_lattice([0,0,.801],m.g.sizes[0],yaw,
        normal,inset=.01))
    assert any(c.rim_pair.axis=='length' for c in pool)
    candidates=m._screen_candidate_list(0,pool)
    assert candidates
    center=np.array([0.,0.,.876])
    rotation=Rotation.from_euler('z',yaw).as_matrix()
    for c in candidates:
        assert c.rim_pair.axis=='width' and c[1]==c.rim_pair.face
        m.grasp_rim_pair=c.rim_pair
        private=c.rim_pair.goals(center,x_offset=c[2])
        live=m._grasp_goals(center,c[1],x_offset=c[2])
        for side in ('left','right'):
            np.testing.assert_allclose(live[side][0],private[side][0],atol=1e-12)
            np.testing.assert_allclose(live[side][1],private[side][1],atol=1e-12)
        points=np.array([(live[s][0]-center)@rotation for s in ('left','right')])
        np.testing.assert_allclose(np.sort(points[:,1]),[-.205,.205],atol=1e-12)
        assert abs(points[:,0]).max()<=.27+1e-12


def test_private_and_live_filter_keep_front_search_area_not_one_station():
    m=machine(.2)
    width,short=rim_pairs(m.g.sizes[0],.2,np.pi,inset=.01)
    bases=[[.55,-.2,np.pi],[.65,.2,2.8],[.55,.61,np.pi],[.299,0,np.pi],[-.55,0,0]]
    pool=[RimCandidate(np.array(b),short.face,.02,short) for b in bases]
    selected=m._screen_candidate_list(0,pool)
    assert len(selected)==2
    np.testing.assert_array_equal(selected[0][0],bases[0])
    np.testing.assert_array_equal(selected[1][0],bases[1])
    assert all(c.rim_pair.axis=='width' for c in selected)
    assert len(m._screen_candidate_list(0,pool+pool))==2


def test_live_rejects_unqualified_short_pair_instead_of_silent_substitution():
    m=machine(1.3)
    m.grasp_rim_pair=rim_pairs(m.g.sizes[0],1.3,np.pi,inset=.01)[1]
    with pytest.raises(Fault,match='private_live_grasp_geometry_mismatch'):
        m._grasp_goals(np.array([0.,0.,.876]),m.grasp_rim_pair.face)


def test_legacy_generic_candidate_hook_preserves_pool_object():
    generic=Machine.__new__(Machine)
    pool=[(np.array([.5,0.,0.]),0.,0.)]
    assert generic._screen_candidate_list(0,pool) is pool


def test_align_filters_appended_alternates_before_private_ik(monkeypatch):
    from r1pro_teleop.airport_fsm import reachability_planner
    from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
    m=machine(-1.3704311427)
    m.c=SimpleNamespace(reachability_screen_enabled=True,alternate_rim_enabled=True,
        rim_inset_m=.01,rim_x_jitter_m=.025,reachability_max_probes=24,
        reachability_max_qualified=2,max_candidate_count=12)
    m.pending_grasp_contact=None
    m.r.holding=None;m.r.retained_contact=None
    m.r.observation=lambda:dict(gripper_contact_force=np.zeros((1,2)))
    m.transition=lambda *a,**k:None
    m._inward_yaw=lambda p:np.pi
    m._candidate_list=lambda tray:[(np.array([.55,0.,np.pi]),np.pi,0.)]
    def checked(runtime,tray,pool,**kw):
        assert len(pool)>2
        for candidate in pool:
            assert candidate.rim_pair.axis=='width'
            assert candidate[1]==candidate.rim_pair.face
            assert not table_front_region_violation(m.g.tables['rear'],candidate[0])
        raise RuntimeError('private_pool_checked_before_any_live_navigation')
    monkeypatch.setattr(reachability_planner,'screen_candidates',checked)
    with pytest.raises(RuntimeError,match='private_pool_checked'):
        m.align(0,0)
