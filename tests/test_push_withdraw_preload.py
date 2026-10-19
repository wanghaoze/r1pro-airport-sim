"""An isolated endpoint compensation ablation, with unchanged defaults."""
import json
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.airport_fsm.contracts import Config
from r1pro_teleop.airport_fsm import primitives


@pytest.mark.parametrize('value', [0, 0., .75, 1.5])
def test_finite_preload_scale_in_closed_interval(value):
    assert Config(push_withdraw_preload_scale=value).validate().push_withdraw_preload_scale == value


@pytest.mark.parametrize('value', [-.001, 1.50001, float('nan'), float('inf'), -float('inf'), True, '0', None])
def test_invalid_preload_scale_rejected(value):
    with pytest.raises(ValueError, match='push_withdraw_preload_scale'):
        Config(push_withdraw_preload_scale=value).validate()


def test_missing_config_field_keeps_old_scale(tmp_path):
    path=tmp_path/'legacy.json';path.write_text('{}')
    assert Config.load(path).push_withdraw_preload_scale == 1.5
    path.write_text(json.dumps({'push_withdraw_preload_scale':0.}))
    assert Config.load(path).push_withdraw_preload_scale == 0.


@pytest.mark.parametrize('withdraw', [False, True])
@pytest.mark.parametrize('scale', [0., .75, 1.5])
def test_only_withdraw_endpoint_z_changes(withdraw, scale):
    cfg=Config(push_withdraw_preload_scale=scale,primitive_touchdown_preload_m=.003)
    body=SimpleNamespace(xpos=np.array([0.,0.,.8]),xmat=np.eye(3).ravel())
    command=SimpleNamespace(xpos=np.array([.1,0.,.9]),xmat=np.eye(3).ravel())
    measured=command.xpos.copy()
    captured=[]
    class PlanningReached(Exception): pass
    def cartesian(goals, **kwargs):
        captured.append(goals)
        raise PlanningReached
    runtime=SimpleNamespace(cfg=cfg,steps=0,primitive_deadline_step=None,
        primitive_lift_xy_shift_m=.06 if withdraw else 0.,
        sim=SimpleNamespace(target=np.zeros(16),tcp=lambda side:(measured.copy(),np.eye(3))),
        _shadow=lambda q:SimpleNamespace(site=lambda name:command),
        d=SimpleNamespace(body=lambda name:body),
        observation=lambda:{'tray_pose':np.array([[0.,0.,.8,1.,0.,0.,0.]])},cartesian=cartesian)
    machine=SimpleNamespace(r=runtime,c=cfg,g=SimpleNamespace(ids=['tray_0'],period=2*np.pi),
        log=SimpleNamespace(event=lambda *a,**kw:None))
    operation=SimpleNamespace(tray=0,destination=np.array([.1,0.,.8]),yaw=0.)
    with pytest.raises(PlanningReached):
        primitives.push(machine,operation,'right',np.eye(4),free_retreat=True)
    retained, orientation=captured[0]['right']
    assert retained[2] == pytest.approx(.9-(scale*.003 if withdraw else 0.))
    # Horizontal compensation retains the original withdraw-specific cap.
    compensation=min(cfg.primitive_push_compensation_m,.020) if withdraw else cfg.primitive_push_compensation_m
    np.testing.assert_allclose(retained[:2],[.2+compensation,0.])
    np.testing.assert_array_equal(orientation,np.eye(3))
    assert runtime.primitive_deadline_step is None
