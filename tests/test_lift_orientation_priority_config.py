from dataclasses import replace
import pytest
from r1pro_teleop.airport_fsm.contracts import Config


def test_default_preserves_existing_lift_order():
    assert Config().completion_lift_strict_orientation_first_enabled is False


@pytest.mark.parametrize('value',[0,1,None,'true'])
def test_orientation_priority_requires_real_boolean(value):
    with pytest.raises(ValueError,match='completion_lift_strict_orientation_first_enabled must be boolean'):
        replace(Config(),completion_lift_strict_orientation_first_enabled=value).validate()


def test_priority_only_completion_profile():
    with pytest.raises(ValueError,match='requires completion_first'):
        replace(Config(),completion_lift_strict_orientation_first_enabled=True).validate()
    cfg=replace(Config(),acceptance_profile='completion_first',retained_support_integer_clock_enabled=True,
        completion_lift_strict_orientation_first_enabled=True,completion_held_ik_orientation_tolerance_rad=.12)
    assert cfg.validate() is cfg
