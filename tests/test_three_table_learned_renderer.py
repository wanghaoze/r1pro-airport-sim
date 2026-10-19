"""Model RGB requires native camera initialization; physics defaults unchanged."""
from types import SimpleNamespace
import pytest
import r1pro_teleop.single_tray_3table.control as control


def test_native_renderer_opt_in_is_forwarded_and_teacher_default_stays_disabled(monkeypatch):
    calls=[]
    def parent(self,spec,xml,cfg,**kwargs):
        calls.append(kwargs)
        self.sim=object();self.g=SimpleNamespace(ids=[]);self.m=object();self.d=object();self.mj=object()
    monkeypatch.setattr(control.Runtime,'__init__',parent)
    monkeypatch.setattr(control,'Geometry',lambda spec,expected_trays:('geometry',expected_trays))
    monkeypatch.setattr(control,'RigidTrayEvidence',lambda *args:object())
    scene={'legacy_spec':{},'xml':'actual-scene.xml','payloads':[]};cfg=object()
    control.ThreeTableRuntime(scene,cfg)
    control.ThreeTableRuntime(scene,cfg,render=True)
    assert [call['render'] for call in calls]==[False,True]
    assert all(call['geometry']==('geometry',1) for call in calls)


def test_invalid_renderer_selection_rejects_before_model_or_physics_construction(monkeypatch):
    monkeypatch.setattr(control.Runtime,'__init__',lambda *a,**kw:pytest.fail('not constructed'))
    with pytest.raises(ValueError,match='render requires bool'):
        control.ThreeTableRuntime({},object(),render=1)
