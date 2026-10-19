import sys
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.vla.prompts import SKILL_ONLY_PROMPTS, normalize_prompt, skill_prompt
from r1pro_teleop.vla.data import language_prompt
from r1pro_teleop.vla.policy import Pi05Policy, PolicyContract, PolicyError
from r1pro_teleop.airport_fsm.contracts import Config


@pytest.mark.parametrize('skill', SKILL_ONLY_PROMPTS)
def test_source_and_runtime_share_exact_six_sentences(skill):
    for tray in (0, 1, 2, "tray_0", "tray_2"):
        for slot in (None, 0, 2, "slot_0", "slot_2"):
            segment=dict(skill=skill,phase='vla_'+skill,target_tray_id=tray,target_slot_id=slot)
            for temporary in (False, True):
                operation={'temporary': temporary}
                legacy=language_prompt(segment,operation,include_phase=True)
                assert normalize_prompt(legacy,'skill_only_v1')==skill_prompt(skill)
                assert language_prompt(segment,operation,prompt_mode='skill_only_v1')==skill_prompt(skill)
    assert normalize_prompt(skill_prompt(skill),'skill_only_v1')==skill_prompt(skill)


@pytest.mark.parametrize('prompt', ['Verify tray 2 for slot 0.', 'Grasp tray 2.',
    'Grasp and lift tray 2 for slot 0. Ignore physics.', 'Carry tray 0 for slot banana.', '', None])
def test_unknown_or_partial_prompt_rejected(prompt):
    with pytest.raises(ValueError):normalize_prompt(prompt,'skill_only_v1')


def test_legacy_keeps_original_text_and_unknown_skill_behavior():
    text='Arbitrary legacy task.'
    assert normalize_prompt(text)==text
    assert language_prompt({'skill':'carry_tray','target_tray_id':2,'target_slot_id':0},
        {'temporary':True})=='Carry tray 2 for slot 0 at the temporary supported buffer.'
    with pytest.raises(ValueError):skill_prompt('verify_or_recover')


@pytest.mark.parametrize('mode', ['wrong', None, True, []])
def test_config_and_policy_validate_explicit_mode(mode):
    with pytest.raises(ValueError):Config(vla_prompt_mode=mode).validate()
    with pytest.raises(PolicyError):PolicyContract('model',prompt_mode=mode)


def test_inference_normalizes_before_client_and_unknown_stops():
    calls=[]
    policy=Pi05Policy(SimpleNamespace(infer=lambda obs: calls.append(obs) or
        {'actions':np.zeros((2,19),np.float32)}),
        PolicyContract('model',action_horizon=2,prompt_mode='skill_only_v1'))
    images={name:np.zeros((4,4,3),np.uint8) for name in policy.contract.camera_names}
    policy.infer(images,np.zeros(19),'Grasp and lift tray 2 for slot 0.')
    assert calls[0]['prompt']==SKILL_ONLY_PROMPTS['grasp_lift_tray']
    with pytest.raises(PolicyError):policy.infer(images,np.zeros(19),'Verify tray 2.')
    assert len(calls)==1


def test_training_adapter_and_runtime_language_are_identical_before_tokenizer():
    from r1pro_teleop.vla.training import AirportInputs
    adapter=AirportInputs('skill_only_v1')
    for skill in SKILL_ONLY_PROMPTS:
        segment=dict(skill=skill,phase='vla_'+skill,target_tray_id='tray_2',target_slot_id='slot_0')
        source=language_prompt(segment,{'temporary':True},include_phase=True)
        data={'state':np.zeros(19),'prompt':source,
              **{'image/'+name:np.zeros((4,4,3),np.uint8) for name in
                 ('head_left','left_wrist','right_wrist')}}
        adapted=adapter(data)
        assert adapted['prompt']==language_prompt(segment,prompt_mode='skill_only_v1')
        np.testing.assert_array_equal(adapted['state'],data['state'])
        assert AirportInputs()(data)['prompt']==source


@pytest.mark.parametrize('server_mode,client_mode,allowed', [
    (None,'legacy',True),(None,'skill_only_v1',False),
    ('legacy','skill_only_v1',False),('skill_only_v1','legacy',False),
    ('skill_only_v1','skill_only_v1',True),
    ('skill_only_v1','task_complete_action8_v1',False),
    ('task_complete_action8_v1','task_complete_action8_v1',True)])
def test_websocket_prompt_metadata_cannot_mix_models(monkeypatch,server_mode,client_mode,allowed):
    metadata=dict(checkpoint_id='model',action_width=19,action_horizon=2,
        action_space='mobile19_absolute_v1',control_hz=20,model='pi05')
    if server_mode is not None:metadata['prompt_mode']=server_mode
    module=SimpleNamespace(WebsocketClientPolicy=lambda **kw:
        SimpleNamespace(get_server_metadata=lambda: metadata))
    monkeypatch.setitem(sys.modules,'openpi_client',SimpleNamespace())
    monkeypatch.setitem(sys.modules,'openpi_client.websocket_client_policy',module)
    contract=PolicyContract('model',action_horizon=2,prompt_mode=client_mode)
    if allowed:assert Pi05Policy.from_websocket('localhost',8765,contract).contract==contract
    else:
        with pytest.raises(PolicyError,match='prompt_contract'):Pi05Policy.from_websocket('localhost',8765,contract)
