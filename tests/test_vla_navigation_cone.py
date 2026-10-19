from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config,State
from r1pro_teleop.airport_fsm.geometry import Operation
from r1pro_teleop.vla.machine import VLAMachine


def fixture(bearing=0.,distance=.55,mode='wide_target_cone'):
    m=VLAMachine.__new__(VLAMachine);m._inward_yaw=lambda _:0.
    # Chassis translation is along table normal; heading intentionally differs.
    r=SimpleNamespace(cfg=replace(Config(),vla_navigation_readiness_mode=mode),steps=0,
        sim=SimpleNamespace(base_state=lambda:np.array([0.,0.,-bearing])),
        observation=lambda:dict(tray_pose=np.array([[distance,0.,.8,1.,0.,0.,0.]])),
        d=SimpleNamespace(qvel=np.zeros(3)),base_dofs=np.arange(3))
    return m,r,Operation(0,0,np.array([distance,0.,.8]),0.)


def test_default_legacy_preserves_alternate_heading_but_reports_cone_false():
    m,r,op=fixture(np.pi/2,mode='legacy');r.cfg=replace(r.cfg,alternate_rim_enabled=True)
    assert m._navigation_ready(r,op)
    assert m.navigation_latest_metrics['legacy_ready']
    assert not m.navigation_latest_metrics['target_cone_ready']
    r.cfg=replace(r.cfg,vla_navigation_readiness_mode='wide_target_cone')
    assert not m._navigation_ready(r,op)
    assert Config().vla_navigation_readiness_mode=='legacy'


@pytest.mark.parametrize('bearing',[.5,-.5,.50147,-.49732,.11697])
def test_wide_cone_preserves_actual_teacher_oblique_handoffs(bearing):
    m,r,op=fixture(bearing)
    assert m._navigation_ready(r,op)
    assert m.navigation_latest_metrics['selected_ready']


def test_cone_adds_conditions_without_replacing_legacy_or_measured_velocity():
    m,r,op=fixture(.79708,.635713)
    assert not m._navigation_ready(r,op)
    m,r,op=fixture(.362943,.593677)
    assert m._navigation_ready(r,op)  # Explicitly does NOT solve v16 failure.
    r.d.qvel[0]=.031
    assert not m._navigation_ready(r,op)
    m,r,op=fixture(0.,.8)
    assert not m._navigation_ready(r,op)
    m,r,op=fixture(0.,.55);r.sim.base_state=lambda:np.array([0.,0.,np.nan])
    assert not m._navigation_ready(r,op)
    assert not m.navigation_latest_metrics['finite']
    assert m.navigation_latest_metrics['actual']['target_bearing_rad'] is None


@pytest.mark.parametrize('key,bad',[
    ('vla_navigation_readiness_mode','narrow'),('vla_navigation_target_bearing_max_rad',True),
    ('vla_navigation_target_bearing_max_rad',np.nan),('vla_navigation_target_bearing_max_rad',4.),
    ('vla_navigation_target_lateral_max_m',-.1),('vla_navigation_target_forward_min_m',.8),
    ('vla_navigation_stable_frames',False),('vla_navigation_stable_frames',0),
    ('vla_navigation_target_forward_min_m','0.4')])
def test_invalid_navigation_config_rejected(key,bad):
    with pytest.raises(ValueError):replace(Config(),**{key:bad}).validate()


@pytest.mark.parametrize('fail',[False,True])
def test_node_records_stable_actual_handoff_once_and_retains_failure(fail):
    m,r,op=fixture();m.r=r;m.c=r.cfg;m.operations=1
    m.g=SimpleNamespace(ids=['tray0'],spec={'slots':[{'slot_id':'slot0'}]})
    events=[];m.log=SimpleNamespace(event=lambda kind,**kw:events.append((kind,kw)))
    m.transition=lambda *a,**kw:None
    def run(op,prompt,predicate,**kw):
        assert not kw  # no motion correction, planner, or teacher fallback.
        for i in range(4):
            r.steps=i
            ready=predicate(r,op)
            assert predicate(r,op)==ready  # repeated query is not another tick.
        if fail:raise RuntimeError('physical guard failure')
        assert ready
    m.executor=SimpleNamespace(execute_operation=run)
    if fail:
        with pytest.raises(RuntimeError,match='physical guard'):
            m._node(op,'navigate_to_tray',State.ALIGN_BASE,m._navigation_ready,4)
    else:m._node(op,'navigate_to_tray',State.ALIGN_BASE,m._navigation_ready,4)
    record=m.navigation_handoffs[0]
    assert record['completed'] is (not fail)
    assert record['actual_stable_ticks']==record['required_stable_ticks']==4
    assert len([e for e,d in events if e=='vla_navigation_handoff_evaluated'])==1
    assert record['metrics']['actual']['target_forward_m']==pytest.approx(.55)


def test_cli_and_rollout_configuration_are_explicit_and_keep_task_acceptance(tmp_path,monkeypatch):
    import scripts.evaluate_pi05_airport as cli
    calls=[]
    monkeypatch.setattr(cli,'verified_server_metadata',lambda *a,**kw:{})
    monkeypatch.setattr(cli,'run_rollouts',lambda *a,**kw:calls.append(kw) or {'status':'completed'})
    assert cli.main(['--collection','src','--output','out','--indices','4','--navigation-readiness','wide_target_cone'])==0
    assert calls[0]['navigation_readiness']=='wide_target_cone'
    assert calls[0]['navigation_bearing_max']==.55 and calls[0]['navigation_stable_frames']==4
    from test_vla_rollout import source,metadata
    from r1pro_teleop.vla.rollout import run_rollouts
    collection,_=source(tmp_path)
    def runner(spec,xml,cfg,directory,**kw):
        assert cfg.vla_navigation_readiness_mode=='wide_target_cone'
        assert cfg.criteria==Config().criteria and not cfg.vla_grasp_base_hold_enabled
        directory.mkdir(parents=True)
        return dict(scene_id=spec['scene_id'],split=spec['split'],task_completed=False,inverse_dynamics_calls=0)
    report=run_rollouts(collection,tmp_path/'new',metadata(),indices=[4],navigation_readiness='wide_target_cone',attempt_runner=runner)
    assert report['config']['vla_navigation_target_lateral_max_m']==.28 and report['completed']==0
