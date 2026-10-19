"""Verified latent-target boundary for the single-tray FlowDAgger integration.

The official sampler/inverter are supplied as callbacks. This module does not
label a rollout or train a steering model merely because inversion was attempted.
It keeps simulation expert actions and flow latents as distinct artifacts.
"""
from dataclasses import dataclass
import hashlib
import numpy as np
from .data_single_tray import LABELS,PROFILE,canonical_hash


def array_hash(value):
 value=np.asarray(value)
 return hashlib.sha256(str(value.dtype).encode()+str(value.shape).encode()+value.tobytes()).hexdigest()


@dataclass(frozen=True)
class LatentTarget:
 latent: np.ndarray
 reconstructed_actions: np.ndarray
 provenance: dict


def invert_verified_expert_chunk(*,expert_actions,observation_identity,expert_provenance,
 frozen_base_checkpoint_id,normalization_sha256,action_label,transform_target,invert,
 sample_from_noise,verify_expert_artifact,reconstruction_tolerances,denoising_steps=10,action_horizon=20):
 """Invert Hx19 real fresh-state actions, then verify with that same sampler.

 transform_target is the bound official data/model action transform (Hx32).
 invert accepts the transformed target; sample_from_noise returns raw Hx19.
 Both callbacks close over the same learner observation and frozen base model.
 Different normalization, denoising count or base checkpoint cannot be mixed.
 """
 if action_label not in LABELS:raise ValueError('new_three_action_label_required')
 if (expert_provenance.get('label_source')!='fresh_state_expert_replan' or
     expert_provenance.get('source')!='simulation/program_generated' or
     expert_provenance.get('split')!='train' or
     expert_provenance.get('task_profile')!=PROFILE or
     expert_provenance.get('teacher_trace_verified') is not True or
     expert_provenance.get('learner_state_sha256')!=observation_identity.get('learner_state_sha256')):
  raise ValueError('fresh_state_training_expert_provenance_required')
 for key in ('learner_state_sha256','images_sha256','prompt_sha256'):
  if not observation_identity.get(key):raise ValueError('learner_observation_identity_required:'+key)
 if not frozen_base_checkpoint_id.startswith('sha256:') or len(frozen_base_checkpoint_id)!=71 or len(normalization_sha256)!=64:
  raise ValueError('verified_base_and_normalization_identity_required')
 if type(denoising_steps) is not int or denoising_steps<=0 or type(action_horizon) is not int or action_horizon<=0:raise ValueError('invalid_sampler_shape_or_steps')
 if verify_expert_artifact(expert_provenance,observation_identity,expert_actions) is not True:
  raise ValueError('actual_teacher_artifact_verification_required')
 actions=np.asarray(expert_actions,dtype=np.float32)
 if actions.shape!=(action_horizon,19) or not np.isfinite(actions).all():raise ValueError('full_real_expert_chunk_required_no_padding')
 target=np.asarray(transform_target(actions.copy()),dtype=np.float32)
 if target.shape!=(action_horizon,32) or not np.isfinite(target).all():raise ValueError('official_normalized_model_target_required')
 latent=np.asarray(invert(target.copy(),denoising_steps),dtype=np.float32)
 if latent.shape!=target.shape or not np.isfinite(latent).all():raise ValueError('latent_inversion_invalid')
 reconstructed=np.asarray(sample_from_noise(latent.copy(),denoising_steps),dtype=np.float32)
 tolerances=np.asarray(reconstruction_tolerances,dtype=np.float32)
 if reconstructed.shape!=actions.shape or not np.isfinite(reconstructed).all() or tolerances.shape!=(19,) or not np.isfinite(tolerances).all() or (tolerances<=0).any():raise ValueError('raw_mobile19_reconstruction_and_declared_tolerance_required')
 errors=np.abs(reconstructed-actions);channel_max=errors.max(axis=0)
 if np.any(channel_max>tolerances):raise ValueError('latent_reconstruction_does_not_reproduce_expert_actions')
 provenance=dict(schema='airport_single_tray_flow_latent_target/1',method='flowdagger_latent_inversion',task_profile=PROFILE,action_label=action_label,frozen_base_checkpoint_id=frozen_base_checkpoint_id,normalization_sha256=normalization_sha256,denoising_steps=denoising_steps,action_horizon=action_horizon,observation_identity=dict(observation_identity),expert_provenance=dict(expert_provenance),expert_actions_sha256=array_hash(actions),normalized_target_sha256=array_hash(target),latent_sha256=array_hash(latent),reconstructed_actions_sha256=array_hash(reconstructed),channel_max_error=channel_max.tolist(),reconstruction_tolerances=tolerances.tolist(),steering_trained=False)
 provenance['target_identity']=canonical_hash(provenance)
 return LatentTarget(latent.copy(),reconstructed.copy(),provenance)
