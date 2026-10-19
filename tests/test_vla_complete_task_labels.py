import copy
import pytest
from r1pro_teleop.vla.data_task_labels import ACTION_VOCABULARY, label_complete_action


def test_three_carry_destinations_preserve_base_action_and_source():
    for index in range(3):
        source = dict(skill='carry_tray', target_slot_id=f'slot_{index}',
                      operation=dict(slot=index, temporary=False, destination=[1, 2, 3]),
                      language_prompt='Carry the tray to the target position.', prompt_mode='skill_only_v1',
                      start_frame=70, end_frame=100)
        old = copy.deepcopy(source)
        labeled, excluded = label_complete_action(source)
        assert excluded is None and source == old
        assert labeled['language_prompt'] == f'Carry the tray to position {index+1}.'
        assert labeled['base_skill'] == 'carry_tray'
        assert (labeled['start_frame'], labeled['end_frame']) == (70, 100)
        assert 'prompt_mode' not in labeled


def test_temporary_carry_is_not_mislabeled_as_a_final_destination():
    row = dict(skill='carry_tray', target_slot_id=None, temporary=True,
               operation=dict(slot=-1, temporary=True), start_frame=10, end_frame=50)
    labeled, excluded = label_complete_action(row)
    assert labeled is None and excluded['end_frame'] == 50
    assert excluded['training_eligible'] is False


@pytest.mark.parametrize('slot', [None, -1, 3, True, 'slot_3', 'slot_0;guess'])
def test_unknown_destinations_are_not_guessed(slot):
    with pytest.raises(ValueError):
        label_complete_action(dict(skill='carry_tray', target_slot_id=slot))


def test_destination_fields_must_agree():
    with pytest.raises(ValueError, match='disagrees'):
        label_complete_action(dict(skill='carry_tray', target_slot_id='slot_0', operation=dict(slot=2)))


def test_vocabulary_has_exactly_eight_distinct_goals():
    assert len(ACTION_VOCABULARY) == 8
    assert len({r['language_prompt'] for r in ACTION_VOCABULARY}) == 8
