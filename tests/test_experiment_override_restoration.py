import pytest
from r1pro_teleop.experiments.adapter import ExperimentMachine
from r1pro_teleop.airport_fsm.machine import Machine
from r1pro_teleop.airport_fsm.physical_preview import _plain_fields
from r1pro_teleop.airport_fsm.contracts import Fault


class ClassMethodRuntime:
    phase='approach'

    def cartesian(self,goals,**kwargs):
        return ('class_method',goals,kwargs)


@pytest.mark.parametrize('existing_override',[False,True])
@pytest.mark.parametrize('fail',[False,True])
def test_full_approach_override_restores_dictionary_shape(monkeypatch,existing_override,fail):
    runtime=ClassMethodRuntime()
    existing=lambda goals,**kwargs:('existing_override',goals,kwargs)
    if existing_override:runtime.cartesian=existing
    before=dict(vars(runtime))
    machine=object.__new__(ExperimentMachine)
    machine.experiment={'strategy':'full_approach_preview'}
    machine.r=runtime
    fault=Fault('diagnostic_alignment_failure')
    def align(self,tray,slot,**kwargs):
        assert 'cartesian' in vars(runtime)
        assert runtime.cartesian is not existing
        result=runtime.cartesian('goals',wrist=True)
        assert result[0]==('existing_override' if existing_override else 'class_method')
        if fail:raise fault
        return result
    monkeypatch.setattr(Machine,'align',align)
    if fail:
        with pytest.raises(Fault) as caught:machine.align(0,0)
        assert caught.value is fault
    else:
        result=machine.align(0,0)
        assert result[1:] == ('goals',{'wrist':True})
    assert vars(runtime)==before
    if existing_override:
        assert runtime.cartesian is existing
        # A preexisting external callback remains rejected, never sanitized.
        with pytest.raises(ValueError,match='external controller object'):
            _plain_fields(runtime,set())
    else:
        assert 'cartesian' not in vars(runtime)
        assert runtime.cartesian.__self__ is runtime
        assert runtime.cartesian.__func__ is ClassMethodRuntime.cartesian
        assert _plain_fields(runtime,set())=={}
