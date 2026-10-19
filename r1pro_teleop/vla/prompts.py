"""Explicit language contracts shared by dataset transforms and live inference.

Skill-only language deliberately carries no target identity. DAG/source metadata
still identifies objects, but that metadata is not a policy observation.
"""
import re

PROMPT_MODES = ('legacy', 'skill_only_v1', 'task_complete_action8_v1', 'single_tray_action3_v1', 'three_table_single_tray_action3_v1')
SKILL_ONLY_PROMPTS = {
    'initialize_posture': 'Move both arms to the initial tucked posture.',
    'navigate_to_tray': 'Navigate to the selected tray.',
    'push_adjust_tray': 'Push and align the selected tray.',
    'grasp_lift_tray': 'Grasp and lift the selected tray.',
    'carry_tray': 'Carry the tray to the target position.',
    'place_release_tray': 'Place the tray and release the grippers.',
}
_VERBS = {'navigate_to_tray': 'Move the base toward',
          'push_adjust_tray': 'Push and align', 'grasp_lift_tray': 'Grasp and lift',
          'carry_tray': 'Carry', 'place_release_tray': 'Place and release'}


def validate_prompt_mode(mode):
    if not isinstance(mode, str) or mode not in PROMPT_MODES:
        raise ValueError('unknown_vla_prompt_mode')
    return mode


def skill_prompt(skill):
    try:
        return SKILL_ONLY_PROMPTS[skill]
    except (KeyError, TypeError) as exc:
        raise ValueError('unknown_skill_only_prompt_skill') from exc


def normalize_prompt(prompt, prompt_mode='legacy'):
    """Normalize only complete, known source sentences; never guess a class."""
    validate_prompt_mode(prompt_mode)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('invalid_vla_prompt')
    if prompt_mode == 'legacy':
        return prompt
    if prompt_mode in ('single_tray_action3_v1', 'three_table_single_tray_action3_v1'):
        from .data_single_tray import ACTION_VOCABULARY
        if prompt not in {row['language_prompt'] for row in ACTION_VOCABULARY}:
            raise ValueError('unknown_single_tray_three_action_prompt')
        return prompt
    if prompt_mode == 'task_complete_action8_v1':
        from .data_task_labels import ACTION_VOCABULARY, label_complete_action
        if prompt in {row['language_prompt'] for row in ACTION_VOCABULARY}:
            return prompt
        target = r'(?:tray (?:tray_)?[0-9]+|the selected tray)'
        carry = re.fullmatch(r'Carry ' + target +
            r' for slot (?:slot_)?([012])\.(?: Current phase: [A-Za-z0-9_]+\.)?', prompt)
        if carry:
            labeled, _ = label_complete_action(dict(skill='carry_tray', target_slot_id=int(carry[1])))
            return labeled['language_prompt']
        # Five non-carry actions share the existing fixed vocabulary. The six
        # mode's generic/temporary carry must never erase an eight-mode goal.
        normalized = normalize_prompt(prompt, 'skill_only_v1')
        if normalized == SKILL_ONLY_PROMPTS['carry_tray']:
            raise ValueError('eight_action_carry_requires_final_destination')
        return normalized
    if prompt in SKILL_ONLY_PROMPTS.values():
        return prompt
    target = r'(?:tray (?:tray_)?[0-9]+|the selected tray)'
    suffix = r'(?: for slot (?:slot_)?[0-9]+)?(?: at the temporary supported buffer)?\.(?: Current phase: [A-Za-z0-9_]+\.)?'
    for skill, verb in _VERBS.items():
        if re.fullmatch(re.escape(verb) + ' ' + target + suffix, prompt):
            return skill_prompt(skill)
    raise ValueError('unknown_skill_only_source_prompt')
