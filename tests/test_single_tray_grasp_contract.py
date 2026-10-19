import pytest
from r1pro_teleop.single_tray_lab.grasp_contract import long_rim_contract,validate_long_rim_contract,validate_rim_assignments


def test_opposite_long_rims_and_changed_handover_rim_are_permitted_with_fixed_base():
    c=long_rim_contract();assert validate_long_rim_contract(c)==c
    assert c['base_placement']=='table_front_only' and c['base_actuated'] is False
    assert c['same_rim_required'] is False and c['handover_rim_change_allowed'] is True
    assert not c['declaration_is_actual_contact_evidence']
    assert validate_rim_assignments({'left':'local_y_positive','right':'local_y_negative'})
    assert validate_rim_assignments({'left':'local_y_negative'})


@pytest.mark.parametrize('rim',['local_x_positive','local_x_negative','unknown',None])
def test_short_or_unidentified_rim_is_not_an_allowed_assignment(rim):
    with pytest.raises(ValueError):validate_rim_assignments({'left':rim})


def test_contract_does_not_accept_base_motion_or_same_rim_restriction():
    c=long_rim_contract();c['base_actuated']=True
    with pytest.raises(ValueError):validate_long_rim_contract(c)
    c=long_rim_contract();c['same_rim_required']=True
    with pytest.raises(ValueError):validate_long_rim_contract(c)
