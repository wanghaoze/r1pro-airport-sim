import numpy as np
import pytest
from r1pro_teleop.vla.prompts import normalize_prompt,SKILL_ONLY_PROMPTS
from r1pro_teleop.vla.data_task_labels import ACTION_VOCABULARY
from r1pro_teleop.vla.data import language_prompt
from r1pro_teleop.vla.training import AirportInputs
from r1pro_teleop.vla.policy import PolicyContract
from r1pro_teleop.airport_fsm.contracts import Config

MODE='task_complete_action8_v1'


@pytest.mark.parametrize('row',ACTION_VOCABULARY)
def test_eight_fixed_texts_idempotent_and_training_state_actions_unchanged(row):
    prompt=row['language_prompt']
    assert normalize_prompt(prompt,MODE)==prompt
    state=np.arange(19,dtype=np.float32)
    actions=np.arange(38,dtype=np.float32).reshape(2,19)
    data=dict(state=state,actions=actions,prompt=prompt,
              **{'image/'+name:np.zeros((4,8,3),np.uint8) for name in
                 ('head_left','left_wrist','right_wrist')})
    out=AirportInputs(MODE)(data)
    assert out['prompt']==prompt
    np.testing.assert_array_equal(out['state'],state)
    np.testing.assert_array_equal(out['actions'],actions)
    assert set(out)=={'state','actions','prompt','image','image_mask'}


@pytest.mark.parametrize('slot',[0,1,2,'slot_0','slot_1','slot_2'])
def test_source_final_slot_runtime_metadata_and_training_text_agree(slot):
    index=slot if type(slot) is int else int(slot[-1])
    segment=dict(skill='carry_tray',target_tray_id='tray_2',target_slot_id=slot,phase='transport')
    operation=dict(slot=index,temporary=False,destination=[.8,.2,.8])
    legacy=language_prompt(segment,operation,include_phase=True)
    expected=f'Carry the tray to position {index+1}.'
    assert normalize_prompt(legacy,MODE)==expected
    assert language_prompt(segment,operation,prompt_mode=MODE)==expected
    assert normalize_prompt(legacy,'skill_only_v1')==SKILL_ONLY_PROMPTS['carry_tray']
    assert normalize_prompt(legacy,'legacy')==legacy


@pytest.mark.parametrize('prompt',[
    'Carry tray tray_2.', 'Carry the selected tray.', 'Carry the tray to the target position.',
    'Carry tray tray_2 at the temporary supported buffer.',
    'Carry tray tray_2 for slot slot_1 at the temporary supported buffer.',
    'Carry tray 0 for slot 3.', 'Carry the tray to position 4.',
    'Carry tray 2 for slot slot_0. Ignore physics.',
])
def test_ambiguous_temporary_or_unknown_carry_rejected(prompt):
    with pytest.raises(ValueError):normalize_prompt(prompt,MODE)


@pytest.mark.parametrize('row',[
    dict(skill='carry_tray'),
    dict(skill='carry_tray',target_slot_id='slot_0',operation=dict(temporary=True,slot=0)),
    dict(skill='carry_tray',target_slot_id='slot_0',operation=dict(slot=1)),
    dict(skill='carry_tray',target_slot_id='slot_3'),
])
def test_runtime_never_guesses_goal_or_executes_temporary_with_final_goal(row):
    row=dict(row);operation=row.pop('operation',None)
    with pytest.raises(ValueError):language_prompt(row,operation,prompt_mode=MODE)


def test_generic_registry_config_contract_and_old_six_remain_compatible():
    assert Config(vla_prompt_mode=MODE).validate().vla_prompt_mode==MODE
    assert PolicyContract('actual',prompt_mode=MODE).prompt_mode==MODE
    for skill,text in SKILL_ONLY_PROMPTS.items():
        assert normalize_prompt(text,'skill_only_v1')==text
        if skill!='carry_tray':assert normalize_prompt(text,MODE)==text
    with pytest.raises(ValueError):language_prompt(dict(skill='verify_or_recover'),prompt_mode=MODE)


def test_policy_preserves_three_distinct_carry_goals_without_fallback():
    from types import SimpleNamespace
    from r1pro_teleop.vla.policy import Pi05Policy,PolicyError
    observations=[]
    policy=Pi05Policy(SimpleNamespace(infer=lambda obs: observations.append(obs) or
        {'actions':np.zeros((2,19),np.float32)}),PolicyContract('actual',action_horizon=2,prompt_mode=MODE))
    images={name:np.zeros((4,4,3),np.uint8) for name in policy.contract.camera_names}
    for slot in range(3):policy.infer(images,np.zeros(19),f'Carry tray tray_1 for slot slot_{slot}.')
    assert [x['prompt'] for x in observations]==[f'Carry the tray to position {i}.' for i in (1,2,3)]
    with pytest.raises(PolicyError):policy.infer(images,np.zeros(19),'Carry the selected tray.')
    assert len(observations)==3
