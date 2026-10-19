"""Eight action goals for whole-task-success derivatives; old six mode stays intact."""
from copy import deepcopy
import re

PROFILE = 'task_complete_action8_v1'
ACTION_VOCABULARY = [
    dict(action_label='initialize_posture', base_skill='initialize_posture',
         language_prompt='Move both arms to the initial tucked posture.'),
    dict(action_label='navigate_to_tray', base_skill='navigate_to_tray',
         language_prompt='Navigate to the selected tray.'),
    dict(action_label='push_adjust_tray', base_skill='push_adjust_tray',
         language_prompt='Push and align the selected tray.'),
    dict(action_label='grasp_lift_tray', base_skill='grasp_lift_tray',
         language_prompt='Grasp and lift the selected tray.'),
    *[dict(action_label=f'carry_to_position_{i}', base_skill='carry_tray',
           language_prompt=f'Carry the tray to position {i}.', target_slot_id=f'slot_{i-1}')
      for i in (1, 2, 3)],
    dict(action_label='place_release_tray', base_skill='place_release_tray',
         language_prompt='Place the tray and release the grippers.'),
]
_BY_LABEL = {row['action_label']: row for row in ACTION_VOCABULARY}


def final_slot_index(value):
    if type(value) is int and value in (0, 1, 2):
        return value
    if isinstance(value, str) and re.fullmatch(r'slot_[012]', value):
        return int(value[-1])
    raise ValueError('unknown_final_slot_for_carry')


def label_complete_action(row):
    """Return (training row, excluded row). Never relabel a temporary carry."""
    out = deepcopy(row)
    base_skill = row['skill']
    if base_skill == 'carry_tray':
        operation = row.get('operation') or {}
        if row.get('temporary') or operation.get('temporary'):
            out['training_eligible'] = False
            out['exclusion_reason'] = 'temporary_carry_preserved_in_full_task_only'
            return None, out
        recorded_slot = row.get('target_slot_id')
        operation_slot = operation.get('slot')
        if recorded_slot is None and operation_slot is None:
            raise ValueError('missing_final_carry_destination')
        index = final_slot_index(recorded_slot if recorded_slot is not None else operation_slot)
        if operation_slot is not None and final_slot_index(operation_slot) != index:
            raise ValueError('carry_destination_evidence_disagrees')
        label = f'carry_to_position_{index+1}'
        out['destination_position'] = index + 1
        out['destination_slot_id'] = f'slot_{index}'
    else:
        label = base_skill
    if label not in _BY_LABEL:
        raise ValueError('unsupported_complete_action_label')
    out.update(base_skill=base_skill, action_label=label,
               source_language_prompt=row.get('language_prompt'),
               language_prompt=_BY_LABEL[label]['language_prompt'],
               language_profile=PROFILE, training_eligible=True)
    if 'prompt_mode' in out:
        out['source_prompt_mode'] = out.pop('prompt_mode')
    return out, None
