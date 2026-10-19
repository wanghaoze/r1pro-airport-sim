"""Actual unfiltered live-controller tray/table contact counts from raw2 replay."""
from pathlib import Path
import json,numpy as np
from .training_cache import file_sha
from .training_pipeline import write_atomic
from .data_single_tray import canonical_hash
from .data_three_table_single_tray import TABLE_IDS

def derive_table_contacts(source,output):
 from ..single_tray_lab.replay import SingleTrayReplay
 output=Path(output);receipt_path=output.with_suffix('.json')
 binding={k:source[k] for k in ('trace_sha256','scene_xml_sha256','events_sha256')}
 if any(file_sha(source[p])!=source[h] for p,h in (('trace','trace_sha256'),('scene_xml','scene_xml_sha256'),('events','events_sha256'))):raise ValueError('contact_projection_source_changed')
 if output.exists() and receipt_path.exists():
  receipt=json.loads(receipt_path.read_text())
  if receipt.get('verified') is not True or receipt.get('source_binding')!=binding or receipt.get('arrays_sha256')!=file_sha(output):raise ValueError('contact_projection_binding_changed')
  with np.load(output,allow_pickle=False) as f:return {k:f[k] for k in f.files},receipt
 replay=SingleTrayReplay(source['trace'],source['scene_xml'],source['events']);m,d=replay.model,replay.data
 def counts():
  result=np.zeros(3,np.int32)
  for c in d.contact:
   if min(c.geom)<0:continue
   ids=[int(m.geom_bodyid[g]) for g in c.geom];entities=[]
   for b in ids:
    entity=None
    while b:
     name=m.body(b).name
     if name=='tray' or name in TABLE_IDS:entity=name;break
     b=int(m.body_parentid[b])
    entities.append(entity)
   if 'tray' in entities:
    other=entities[1] if entities[0]=='tray' else entities[0]
    if other in TABLE_IDS:result[TABLE_IDS.index(other)]+=1
  return result
 frames=[];guards=[];output.parent.mkdir(parents=True,exist_ok=True)
 try:
  for i in range(replay.frames):
   replay.before(i);frames.append(counts());executed=int(replay.file['executed_substeps'][i])
   for ctrl in replay.file['ctrl_substeps'][i,:executed]:
    d.ctrl[:]=ctrl;replay.mj.mj_step(m,d)
    if replay.meta.get('numeric_derivation')=='live_same_runtime_pre_action_observer':replay.mj.mj_forward(m,d)
    guards.append(counts())
   replay.index+=1
   if i%100==0:write_atomic(output.with_suffix('.progress.json'),dict(stage='actual_continuous_contact_replay',heartbeat_unix=__import__('time').time(),frames=i+1,total_frames=replay.frames,guard_rows=len(guards),rendering=False,source_binding=binding))
  terminal=replay.finish()
  if any(v>1e-7 for v in terminal['errors'].values()):raise ValueError('contact_projection_replay_different_from_source')
  numeric=dict(table_contact_counts=np.asarray(frames),support_contact=np.asarray(frames).sum(axis=1).astype(np.int32),guard_table_contact_counts=np.asarray(guards))
  np.savez_compressed(output,**numeric)
  receipt=dict(schema='airport_live_table_contact_projection/1',verified=True,source_binding=binding,arrays_sha256=file_sha(output),arrays=str(output.resolve()),continuous_replay=terminal,table_contact_semantics='actual_mujoco_tray_table_contacts_without_force_cutoff_matching_loaded_bridge',controller_math_changed=False,original_raw_unchanged=True)
  write_atomic(receipt_path,receipt);return numeric,receipt
 finally:replay.close()
