import pytest
from r1pro_teleop.airport_fsm.contracts import Config


def test_direct_buffer_is_an_explicit_completion_candidate():
    assert not Config().completion_direct_buffer_enabled
    valid=dict(acceptance_profile='completion_first',
               retained_support_integer_clock_enabled=True,
               fixed_primitives=True,release_preflight_enabled=True,
               temporary_buffer_serviceability_enabled=True,
               completion_direct_buffer_enabled=True)
    assert Config(**valid).validate()
    for change in (dict(acceptance_profile='strict'),
                   dict(temporary_buffer_serviceability_enabled=False),
                   dict(completion_direct_buffer_enabled=1)):
        with pytest.raises(ValueError,match='completion_direct_buffer_enabled'):
            Config(**(valid|change)).validate()
