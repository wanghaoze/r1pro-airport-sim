"""Snapshot-initialized physics FIXTURE, never a training episode or full-task success."""
import argparse,json
from pathlib import Path
from types import SimpleNamespace
import h5py,numpy as np
from r1pro_teleop.airport_fsm.contracts import Config,State,Fault,atomic_json
from r1pro_teleop.airport_fsm.runtime import Runtime,_homogeneous
from r1pro_teleop.airport_fsm.geometry import Operation
from r1pro_teleop.airport_fsm import primitives

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source',type=Path,required=True);p.add_argument('--scene',type=Path,required=True)
p.add_argument('--config',type=Path,required=True);p.add_argument('--kind',choices=['lift','push','place','handoff_push'],required=True)
p.add_argument('--occurrence',type=int,default=0)
p.add_argument('--chain-push',action='store_true',help='Also validate retained-hand push after place; remains diagnostic-only')
p.add_argument('--output',type=Path,required=True)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
events=[json.loads(x) for x in (a.source/'events.jsonl').read_text().splitlines()]
phase='load_transfer' if a.kind=='lift' else 'adjust'
if a.kind=='place':
 entries=[x for x in events if x['event']=='grasp_transform_refreshed' and x.get('stage')=='before_preplace']
 entry=entries[a.occurrence].copy()
 previous=[x for x in events if x['event']=='state_transition' and x['frame']<=entry['frame']][-1]
 entry.update(target_tray=previous['target_tray'],target_slot=previous['target_slot'])
elif a.kind=='handoff_push':
 entry=[x for x in events if x['event']=='push_reuses_existing_contact'][a.occurrence].copy()
 entry['target_slot']=[x for x in events if x['event']=='operation_selected' and x['frame']<=entry['frame']][-1]['operation']['slot']
else:entry=[x for x in events if x['event']=='state_transition' and x.get('phase')==phase][a.occurrence]
frame=entry['frame'];tray=entry['target_tray'];cfg=Config.load(a.config)
r=Runtime(json.loads((a.scene/'scene.json').read_text()),a.scene/'mobile.xml',cfg)
saved=[];rows=[]
log=SimpleNamespace(event=lambda kind,**kw:saved.append({'event':kind,'frame':r.steps,**kw}),append=rows.append)
def transition(state,phase,**kw):r.fsm_state=state;r.phase=phase
m=SimpleNamespace(r=r,c=cfg,g=r.g,log=log,transition=transition,retreat=lambda:None)
result={'diagnostic_only':True,'training_candidate':False,'snapshot_initialized':True,'source':str(a.source),'source_frame':frame,'primitive':a.kind}
try:
 with h5py.File(a.source/'trace.h5') as f:
  n=len(f['integration_state'])
  if frame==n:
   if not f['transition_completed'][n-1]:raise ValueError('Cannot restore an incomplete terminal interval')
   r.mj.mj_setState(r.m,r.d,f['integration_state'][n-1],r.integration_spec)
   r.sim.target=f['action'][n-1].copy();r.sim.base_target=f['base_action'][n-1].copy()
   r.mj.mj_forward(r.m,r.d);r.sim.apply_target()
   for _ in range(r.sim.nstep):r.mj.mj_step(r.m,r.d);r.mj.mj_forward(r.m,r.d)
   terminal=json.loads(f.attrs['terminal_snapshot_json'])
   error=float(np.max(abs(r.d.qpos-np.array(terminal['qpos']))))
   result['terminal_restore_qpos_error']=error
   if error>cfg.replay_tolerance:raise ValueError('Terminal fixture replay mismatch')
  else:
   r.mj.mj_setState(r.m,r.d,f['integration_state'][frame],r.integration_spec)
   r.sim.target=f['action'][max(0,frame-1)].copy();r.sim.base_target=f['base_action'][frame].copy()
  r.initial_bottom=f['min_z'][0].copy()
 r.mj.mj_forward(r.m,r.d);r.allowed_tray=tray;r.target_slot=entry['target_slot'];r.trace=log
 selected_lifts=[x for x in events if x['event']=='primitive_lift_path_selected' and x['frame']<=frame]
 r.primitive_lift_xy_shift_m=abs(selected_lifts[-1]['inward_m']) if selected_lifts else 0.
 transition(State.GRASP_TRAY if a.kind=='lift' else State.ADJUST_TRAY,phase)
 initial=r.observation()
 if a.kind=='lift':
  r.remember_grasp(tray);primitives.lift(m,tray)
 elif a.kind=='place':
  r.remember_grasp(tray)
  selected=[x for x in events if x['event']=='operation_selected' and x['frame']<=frame][-1]['operation']
  op=Operation(selected['tray'],selected['slot'],np.array(selected['destination']),selected['yaw'],selected.get('temporary',False))
  staged=op.destination.copy()
  reserves=[x for x in events if x['event']=='release_staging_reserved' and x['frame']<=frame]
  if reserves and np.linalg.norm(np.array(reserves[-1]['final'])-op.destination)<1e-8:staged=np.array(reserves[-1]['position'])
  def stop_after_place(operation,retained_side=None):
   if a.chain_push and retained_side:
    transition(State.ADJUST_TRAY,'adjust')
    b=r.d.body(r.g.ids[tray])
    relation=np.linalg.inv(_homogeneous(b.xpos,b.xmat.reshape(3,3)))@_homogeneous(*r.sim.tcp(retained_side))
    primitives.push(m,operation,retained_side,relation,free_retreat=True)
   return True
  m.push=stop_after_place
  primitives.place(m,op,staged)
 else:
  if a.kind=='handoff_push':
   selected=[x for x in events if x['event']=='operation_selected' and x['frame']<=frame][-1]['operation']
   destination=selected['destination']
  else:destination=next(x for x in events if x['event']=='push_feedback' and x['frame']>=frame)['destination']
  from r1pro_teleop.airport_fsm.geometry import quat_yaw_tilt
  yaw,_=quat_yaw_tilt(initial['tray_pose'][tray,3:]);side='right'
  r.retained_contact=(tray,side)
  b=r.d.body(r.g.ids[tray]);relation=np.linalg.inv(_homogeneous(b.xpos,b.xmat.reshape(3,3)))@_homogeneous(*r.sim.tcp(side))
  op=Operation(tray,entry['target_slot'] if a.kind=='handoff_push' else -1,np.array(destination),selected['yaw'] if a.kind=='handoff_push' else yaw,a.kind!='handoff_push')
  primitives.push(m,op,side,relation,separation=a.kind!='handoff_push',free_retreat=a.kind=='handoff_push')
 result['passed']=True
except Fault as exc:result.update(passed=False,failure_code=exc.code,detail=exc.detail)
finally:
 result['duration_s']=r.steps/cfg.fps
 result['events']=saved
 result['final_tray_pose']=r.observation()['tray_pose'][tray]
 result['final_gripper_force']=r.observation()['gripper_contact_force'][tray]
 result['measured_lift_m']=float(r.observation()['min_z'][tray]-initial['min_z'][tray]) if 'initial' in locals() else None
 if rows:
  result['table_zero_frames']=sum(x['table_contact'][tray]==0 for x in rows)
  result['maximum_action_step']=float(np.max(abs(np.diff(np.array([x['action'] for x in rows]),axis=0)))) if len(rows)>1 else 0.
 atomic_json(a.output/'fixture.json',result);r.close()
 print(json.dumps({k:v for k,v in result.items() if k!='events'},default=lambda x:x.tolist() if hasattr(x,'tolist') else str(x)))
