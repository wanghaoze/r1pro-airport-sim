from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config, Fault
from r1pro_teleop.airport_fsm.reach_pull import estimate, supported_sweep, try_pull
from r1pro_teleop.airport_fsm.task_dag import build_task_dag
from test_airport_fsm_unit import spec_fixture, poses
from r1pro_teleop.airport_fsm.geometry import Geometry


def test_reach_estimate_rotation_and_translation_invariant():
    shoulders={'left':np.array([0.,.2,1.]),'right':np.array([0.,-.2,1.])}
    goals={'left':(np.array([.6,.2,1.]),np.eye(3)),
           'right':(np.array([.72,-.2,1.]),np.eye(3))}
    c=Config();before=estimate(goals,shoulders,c)
    R=np.array([[0.,-1,0],[1,0,0],[0,0,1]]);offset=np.array([3.,-2.,.5])
    after=estimate({s:(R@g[0]+offset,R) for s,g in goals.items()},
                   {s:R@p+offset for s,p in shoulders.items()},c)
    assert before['dual_likely_unreachable'] and before['single_candidates'][0]=='left'
    assert list(before['distances_m'].values())==pytest.approx(list(after['distances_m'].values()))


def test_pull_sweep_rejects_edge_and_obstacle():
    g=Geometry(spec_fixture());p=poses(g)
    dest=p[0,:3].copy();dest[0]-=.08
    # Near edge: COM remains over the tabletop but the FULL footprint leaves it.
    assert g.support_table(dest) is not None
    assert not supported_sweep(g,p,0,dest)
    dest=p[0,:3].copy();dest[1]=p[1,1]
    assert not supported_sweep(g,p,0,dest)


def test_bounded_graph_is_dag_with_explicit_pull_branch():
    graph=build_task_dag(18,3);ids={n['id'] for n in graph['nodes']}
    assert len(ids)==len(graph['nodes'])
    degree=dict.fromkeys(ids,0);children={n:[] for n in ids}
    for e in graph['edges']:
        assert e['from'] in ids and e['to'] in ids
        degree[e['to']]+=1;children[e['from']].append(e['to'])
    queue=[n for n,d in degree.items() if d==0];seen=[]
    while queue:
        n=queue.pop();seen.append(n)
        for child in children[n]:
            degree[child]-=1
            if degree[child]==0:queue.append(child)
    assert len(seen)==len(ids)
    assert any(e['from'].endswith('.pull') and e['to'].endswith('.join') for e in graph['edges'])


def test_used_pull_never_attempted_again():
    m=SimpleNamespace(reach_pull_used={0},r=None,c=Config(),g=None)
    assert not try_pull(m,0,0,0.,0.)


@pytest.mark.parametrize('kwargs',[
    {'reach_pull_distance_m':.13},
    {'reach_pull_min_progress_m':.09},
    {'reach_pull_dual_radius_m':.8},
    {'reach_pull_enabled':True}])
def test_invalid_pull_contract(kwargs):
    with pytest.raises(ValueError):replace(Config(),**kwargs).validate()


def test_new_profile_is_explicit_and_old_profile_unchanged():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    assert not Config.load(root/'configs/airport_primitives3.json').reach_pull_enabled
    assert Config.load(root/'configs/airport_reach_pull.json').reach_pull_enabled


@pytest.mark.parametrize('post_ik_fails',[False,True])
def test_pull_control_flow_single_hand_progress_and_nonrecoverable_failure(monkeypatch,post_ik_fails):
    """Mock control flow, not a physical-success benchmark."""
    from r1pro_teleop.airport_fsm import reach_pull
    monkeypatch.setattr(reach_pull,'supported_sweep',lambda *args:True)
    pose=np.array([[.70,0,.8,1,0,0,0.]])
    events=[];moves=[];pulled=[False]
    def goals(center,face,**kw):
        return {s:(center.copy(),np.eye(3)) for s in kw.get('sides',('left','right'))}
    def cartesian(goal,**kwargs):
        moves.append(tuple(goal))
        if pulled[0] and post_ik_fails:raise Fault('ik_unreachable',recoverable=True)
    c=Config(fixed_primitives=True,keep_pick_contact=True,reach_pull_enabled=True)
    r=SimpleNamespace(observation=lambda:{'table_contact':np.ones(1)},rim_goals=goals,
        d=SimpleNamespace(xanchor=np.array([[0,0,.9],[0,0,.9]]),body=lambda name:SimpleNamespace(xpos=np.zeros(3))),
        m=SimpleNamespace(joint=lambda name:SimpleNamespace(id=0 if name.startswith('left') else 1)),
        cartesian=cartesian)
    m=SimpleNamespace(r=r,c=c,g=SimpleNamespace(top_available=lambda *a:True),_poses=lambda:pose.copy(),
        log=SimpleNamespace(event=lambda name,**kw:events.append(name)))
    def push(op,**kwargs):
        assert kwargs['pull_context'][0]=='left'
        pose[0,:3]=op.destination;pulled[0]=True
    m.push=push
    if post_ik_fails:
        with pytest.raises(Fault,match='reach_pull_failed') as failure:try_pull(m,0,2,0.,0.)
        assert not failure.value.recoverable
    else:
        assert try_pull(m,0,2,0.,0.) and r.target_slot==2
        assert 'reach_pull_completed' in events
    assert m.reach_pull_used=={0}
    assert moves==[('left',),('left',),('right',)]
