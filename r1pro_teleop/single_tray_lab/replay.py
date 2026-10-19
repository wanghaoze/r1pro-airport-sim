"""Continuous single-tray raw2 physics replay with payload-only environment journals."""
import json
from pathlib import Path
import h5py
import numpy as np

class SingleTrayReplay:
 def __init__(self,trace,xml,events):
  import mujoco as mj
  self.mj=mj;self.file=h5py.File(trace,'r');f=self.file
  self.source_schema=f.attrs.get('schema')
  if self.source_schema not in ('airport_single_tray_raw/2','airport_three_table_single_tray_raw/2'):raise ValueError('single_tray_raw2_required')
  self.meta=json.loads(f.attrs['metadata_json'])
  if (self.source_schema=='airport_three_table_single_tray_raw/2' or self.meta.get('task_profile')=='three_table_single_tray_action3_v1') and (self.meta.get('task_profile')!='three_table_single_tray_action3_v1' or self.meta.get('base_mode')!='planar_mobile_table_front' or self.meta.get('base_actuated') is not True or self.meta.get('model_action_mask')!=[True]*19 or self.meta.get('scene',{}).get('schema')!='airport_three_table_single_tray_scene/1'):raise ValueError('new_mobile_three_table_raw_contract_required')
  self.model=mj.MjModel.from_xml_path(str(xml))
  if self.meta.get('numeric_derivation')=='live_same_runtime_pre_action_observer':
   params=self.meta.get('source_model_parameters',{})
   caps=np.asarray(params.get('actuator_forcerange'),float);limited=np.asarray(params.get('actuator_forcelimited'))
   if params.get('schema')!='airport_recorded_initial_actuator_limits/1' or caps.shape!=(self.model.nu,2) or not np.isfinite(caps).all() or limited.shape!=(self.model.nu,) or not np.array_equal(limited,self.model.actuator_forcelimited):raise ValueError('actual_initial_actuator_limits_required')
   if np.any(caps[:,0]>caps[:,1]) or np.any(abs(caps[self.model.actuator_forcelimited.astype(bool)])>abs(self.model.actuator_forcerange[self.model.actuator_forcelimited.astype(bool)])):raise ValueError('recorded_limits_cannot_increase_xml_force_caps')
   unchanged=params.get('unchanged_xml_parameter_arrays',{})
   if set(unchanged)!=set(('actuator_gear','actuator_gainprm','actuator_biasprm','actuator_ctrlrange','cam_pos','cam_quat','cam_fovy','cam_ipd')):raise ValueError('complete_initial_unchanged_parameter_snapshot_required')
   for key,value in unchanged.items():
    actual=np.asarray(value,dtype=getattr(self.model,key).dtype)
    if actual.shape!=getattr(self.model,key).shape or not np.array_equal(actual,getattr(self.model,key)):raise ValueError('initial_parameter_differed_from_source_xml:'+key)
   self.model.actuator_forcerange[:]=caps
  self.data=mj.MjData(self.model)
  from r1pro_teleop.airport_fsm.contracts import sha256_file
  if sha256_file(xml)!=self.meta['scene_xml_sha256']:raise ValueError('source_xml_changed')
  self.spec=mj.mjtState(self.meta['integration_state_spec']);self.frames=len(f['qpos']);self.index=0;self.restores=1
  if not np.isfinite(f['integration_state'][0]).all():raise ValueError('nonfinite_initial_integration_state')
  mj.mj_setState(self.model,self.data,f['integration_state'][0],self.spec);mj.mj_forward(self.model,self.data)
  if self.meta.get('numeric_derivation')=='live_same_runtime_pre_action_observer':
   if 'qacc_warmstart' not in f:raise ValueError('actual_initial_warmstart_required')
   self.data.qacc_warmstart[:]=f['qacc_warmstart'][0]
  self.events={};self.errors={k:0. for k in ('qpos','qvel','time','terminal_qpos','terminal_qvel','terminal_time')}
  for row in [json.loads(line) for line in Path(events).read_text().splitlines() if line.strip()]:
   if row.get('event')=='passenger_payload_initialized':self.events.setdefault(row['frame'],[]).append(row['environment_evidence'])
 def environment(self,event):
  if event['schema']!='airport_passenger_environment_transition/1' or not event['physics_mass_inertia_contact_unchanged'] or not event['robot_tray_time_control_unchanged']:raise ValueError('unsupported_environment_mutation')
  m,d=self.model,self.data;allowed_q=[];allowed_v=[]
  payload_bodies=set();payload_flexes=set()
  for item in self.meta['scene']['payloads']:
   if item.get('kind') not in ('laptop','backpack','coat') or item.get('name')!='passenger_'+item['kind']:raise ValueError('unrecognized_source_payload_identity')
   kind=self.mj.mjtObj.mjOBJ_FLEX if item['flex'] else self.mj.mjtObj.mjOBJ_BODY
   identity=self.mj.mj_name2id(m,kind,item['name'])
   if identity<0:raise ValueError('declared_payload_missing_in_source_model')
   if item['flex']:
    payload_flexes.add(identity);payload_bodies.update(int(v) for v in m.flex_vertbodyid[m.flex_vertadr[identity]:m.flex_vertadr[identity]+m.flex_vertnum[identity]])
   else:payload_bodies.add(identity)
  for jid in range(m.njnt):
   body=m.jnt_bodyid[jid];name=self.mj.mj_id2name(m,self.mj.mjtObj.mjOBJ_BODY,int(body)) or ''
   if int(body) in payload_bodies:
    typ=m.jnt_type[jid];nq=7 if typ==0 else 4 if typ==1 else 1;nv=6 if typ==0 else 3 if typ==1 else 1
    allowed_q.extend(range(int(m.jnt_qposadr[jid]),int(m.jnt_qposadr[jid])+nq));allowed_v.extend(range(int(m.jnt_dofadr[jid]),int(m.jnt_dofadr[jid])+nv))
  qi=np.array(event['qpos_indices'],dtype=int);vi=np.array(event['qvel_indices'],dtype=int)
  if not set(qi).issubset(allowed_q) or not set(vi).issubset(allowed_v):raise ValueError('environment_changed_nonpayload_state')
  if not np.allclose(d.qpos[qi],event['qpos_before'],atol=1e-8,rtol=0) or not np.allclose(d.qvel[vi],event['qvel_before'],atol=1e-8,rtol=0):raise ValueError('environment_before_state_mismatch')
  d.qpos[qi]=event['qpos_after'];d.qvel[vi]=event['qvel_after']
  for change in event['model_visual_changes']:
   if change['kind'] not in ('geom_rgba','flex_rgba'):raise ValueError('nonvisual_model_mutation')
   array=getattr(m,change['kind']);idx=change['index']
   if change['kind']=='geom_rgba' and int(m.geom_bodyid[idx]) not in payload_bodies:raise ValueError('visual_mutation_not_payload')
   if change['kind']=='flex_rgba' and idx not in payload_flexes:raise ValueError('visual_mutation_not_payload')
   if not np.array_equal(array[idx],np.asarray(change['before'],dtype=array.dtype)):raise ValueError('visual_before_mismatch')
   array[idx]=change['after']
  self.mj.mj_forward(m,d)
 def before(self,index):
  if index!=self.index:raise ValueError('continuous_replay_only')
  for event in self.events.get(index,[]):self.environment(event)
  for key,target in [('qpos',self.data.qpos),('qvel',self.data.qvel),('time',self.data.time)]:
   source=self.file['sim_time' if key=='time' else key][index]
   if not np.isfinite(source).all() or not np.isfinite(target).all():raise ValueError('nonfinite_replay_state')
   error=float(np.max(np.abs(np.asarray(target)-source)));self.errors[key]=max(self.errors[key],error)
   if error>1e-7:raise ValueError('replay_prefix_'+key+':'+str(error))
 def advance(self):
  i=self.index;journal=self.file['ctrl_substeps'][i];executed=int(self.file['executed_substeps'][i])
  if journal.shape[1]!=self.model.nu or not 0<=executed<=len(journal) or not np.isfinite(journal[:executed]).all():raise ValueError('invalid_control_journal')
  for ctrl in journal[:executed]:
   self.data.ctrl[:]=ctrl;self.mj.mj_step(self.model,self.data)
   if self.meta.get('numeric_derivation')=='live_same_runtime_pre_action_observer':self.mj.mj_forward(self.model,self.data)
  self.index+=1
 def finish(self):
  if self.index!=self.frames:raise ValueError('complete_replay_required_for_terminal')
  for event in self.events.get(self.index,[]):self.environment(event)
  terminal=json.loads(self.file.attrs['terminal_snapshot_json'])
  for key in ('qpos','qvel','time'):
   if not np.isfinite(terminal[key]).all() or not np.isfinite(getattr(self.data,key)).all():raise ValueError('nonfinite_terminal_replay')
   error=float(np.max(np.abs(np.asarray(getattr(self.data,key))-terminal[key])));self.errors['terminal_'+key]=error
   if error>1e-7:raise ValueError('terminal_replay_'+key)
  return dict(errors=self.errors,initial_restore_count=self.restores,frames=self.index,environment_journal_replayed=True)
 def close(self):self.file.close()
