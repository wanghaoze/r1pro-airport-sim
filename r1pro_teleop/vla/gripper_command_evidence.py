"""Read actual requested controls and MuJoCo's declared actuator clipping."""
import hashlib,json
from pathlib import Path
import numpy as np
from .data_single_tray import canonical_hash
from .training_cache import file_sha

def derive_submitted_gripper_evidence(source):
 import h5py,mujoco
 if file_sha(source['trace'])!=source['trace_sha256'] or file_sha(source['scene_xml'])!=source['scene_xml_sha256']:raise ValueError('submitted_control_source_identity_changed')
 model=mujoco.MjModel.from_xml_path(source['scene_xml']);names=['left_gripper_target','right_gripper_target'];ids=[int(model.actuator(n).id) for n in names]
 ranges=model.actuator_ctrlrange[ids].copy();limited=model.actuator_ctrllimited[ids].astype(bool)
 if ids!=[7,15] or not limited.all() or ranges.shape!=(2,2) or not np.isfinite(ranges).all():raise ValueError('actual_gripper_mapping_or_ctrllimited_required')
 with h5py.File(source['trace']) as f:
  meta=json.loads(f.attrs['metadata_json']);ctrl=np.asarray(f['ctrl_substeps'][:]);count=np.asarray(f['executed_substeps'][:]);raw=np.asarray(f['gripper_command_openings'][:])
  if meta.get('config',{}).get('substep_control_enabled') is not False or ctrl.shape!=(source['frames'],25,model.nu) or not np.all(count==25) or not np.all(f['transition_completed'][:]) or not np.isfinite(ctrl).all():raise ValueError('complete_actual_no_interpolation_control_journal_required')
 selected=np.ascontiguousarray(ctrl[:,:,ids]);first=selected[:,0,:]
 if not np.array_equal(selected,np.repeat(first[:,None,:],25,axis=1)):raise ValueError('actual_interval_gripper_controls_not_constant')
 effective=np.clip(selected,ranges[:,0],ranges[:,1]);opening=effective[:,0,:]*2
 proof=dict(shape=list(selected.shape),dtype=str(selected.dtype),sha256=hashlib.sha256(selected.tobytes()).hexdigest())
 evidence=dict(schema='airport_actual_gripper_actuator_command/1',scene_xml_sha256=source['scene_xml_sha256'],raw_control_journal_sha256=canonical_hash(proof),actuator_indices=ids,actuator_names=names,opening_multiplier=2,ctrlranges=ranges.tolist(),actuator_ctrllimited=limited.tolist(),control_range_semantics='mujoco_ctrllimited_internal_clamp',verified_actual_control_journal=True,raw_trace_sha256=source['trace_sha256'])
 audit=dict(verified=True,raw_reference_min_m=float(raw.min()),raw_reference_max_m=float(raw.max()),raw_control_min=float(selected.min()),raw_control_max=float(selected.max()),engine_clipped_control_count=int(np.count_nonzero(effective!=selected)),constant_substeps_verified=25,raw_commands_and_actions_unchanged=True,source_trace_sha256=source['trace_sha256'],evidence=evidence)
 return {'gripper_control_substeps':selected,'gripper_effective_command_openings':opening},evidence,audit
