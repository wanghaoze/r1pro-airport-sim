import numpy as np
import pytest
from r1pro_teleop.vla.flowdagger_single_tray import invert_verified_expert_chunk
from r1pro_teleop.vla.data_single_tray import PROFILE

def kwargs():
 actions=np.arange(20*19,dtype=np.float32).reshape(20,19)*.0001
 identity=dict(learner_state_sha256='a'*64,images_sha256={'head_left':'b'*64,'left_wrist':'c'*64,'right_wrist':'d'*64},prompt_sha256='e'*64)
 return dict(expert_actions=actions,observation_identity=identity,expert_provenance=dict(label_source='fresh_state_expert_replan',source='simulation/program_generated',split='train',task_profile=PROFILE,teacher_trace_verified=True,learner_state_sha256='a'*64),frozen_base_checkpoint_id='sha256:'+'f'*64,normalization_sha256='1'*64,action_label='pick_empty',verify_expert_artifact=lambda provenance,obs,actions:True,transform_target=lambda a:np.pad(a,((0,0),(0,13))),invert=lambda target,steps:target+2,sample_from_noise=lambda z,steps:z[:,:19]-2,reconstruction_tolerances=np.ones(19,dtype=np.float32)*1e-5)

def test_latent_and_expert_actions_remain_distinct_and_no_training_is_claimed():
 k=kwargs();result=invert_verified_expert_chunk(**k)
 assert result.latent.shape==(20,32) and result.reconstructed_actions.shape==(20,19)
 assert np.allclose(result.reconstructed_actions,k['expert_actions'],atol=1e-6)
 assert result.provenance['steering_trained'] is False and result.provenance['method']=='flowdagger_latent_inversion'
 assert result.provenance['latent_sha256']!=result.provenance['expert_actions_sha256']

@pytest.mark.parametrize('change,error',[
 (lambda k:k['expert_provenance'].update(split='test'),'fresh_state'),
 (lambda k:k.update(verify_expert_artifact=lambda *args:False),'artifact_verification'),
 (lambda k:k['expert_provenance'].update(learner_state_sha256='stale'),'fresh_state'),
 (lambda k:k.update(expert_actions=k['expert_actions'][:3]),'no_padding'),
 (lambda k:k.update(action_label='carry_position_1'),'three_action'),
 (lambda k:k.update(sample_from_noise=lambda z,steps:z[:,:19]),'does_not_reproduce'),
 (lambda k:k.update(invert=lambda t,steps:np.full(t.shape,np.nan)),'inversion_invalid'),
])
def test_invalid_expert_or_inversion_cannot_become_training_latent(change,error):
 k=kwargs();change(k)
 with pytest.raises(ValueError,match=error):invert_verified_expert_chunk(**k)
