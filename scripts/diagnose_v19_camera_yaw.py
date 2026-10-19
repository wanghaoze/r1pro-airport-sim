"""Read frozen integration states; terminal replay uses recorded per-substep controls."""
import json,pathlib,sys,h5py,numpy as np
root=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/releases/robust_v19_20260929')
sys.path.insert(0,str(root))
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.registry import config_for
out=[]
for variant,case in [('alternate_align',218),]:
 source=root/'runs/ablation'/variant;scene=next((source/'scenes').glob(f'airport_{case:04d}_*'));a=source/'attempts'/scene.name/'a000'
 events=[json.loads(x) for x in (a/'events.jsonl').read_text().splitlines()];r=Runtime(json.loads((scene/'scene.json').read_text()),scene/'mobile.xml',config_for(source),render=False)
 alignment=[e for e in events if e['event']=='primitive_start' and e.get('primitive')=='transport_align'][-1]
 res=json.loads((a/'result.json').read_text());end=res['frames'];samples=[]
 with h5py.File(a/'trace.h5') as h:
  def restore(i):
   index=min(i,len(h['integration_state'])-1);r.mj.mj_setState(r.m,r.d,h['integration_state'][index],r.integration_spec);r.mj.mj_forward(r.m,r.d);r.d.qacc_warmstart[:]=h['qacc_warmstart'][index]
   if i==len(h['integration_state']):
    assert bool(h['transition_completed'][index])
    if str(h.attrs['schema'])=='airport_fsm_raw/2':
     assert int(h['executed_substeps'][index])==r.sim.nstep;controls=h['ctrl_substeps'][index]
    else:
     assert str(h.attrs['schema'])=='airport_fsm_raw/1';r.sim.target=h['action'][index].copy();r.sim.base_target=h['base_action'][index].copy();r.sim.apply_target();controls=np.repeat(r.d.ctrl[None,:],r.sim.nstep,axis=0)
    for ctrl in controls:r.d.ctrl[:]=ctrl;r.mj.mj_step(r.m,r.d);r.mj.mj_forward(r.m,r.d)
   r.sim.target=h['action'][i-1].copy();r.allowed_tray=int(h['target_tray'][index])
  for i in sorted(set([alignment['frame'],*range(max(alignment['frame'],end-10),end+1)])):
   restore(i);actual=r.camera_metrics();s=r._shadow(r.sim.target);command=r.camera_metrics(s)
   samples.append(dict(frame=i,time_s=float(r.d.time),actual=actual,command=command,tcp_deflection_m={side:float(np.linalg.norm(r.d.site(side+'_tcp').xpos-s.site(side+'_tcp').xpos)) for side in ['left','right']}))
 from r1pro_teleop.airport_fsm.placement_reachability import loaded_planning_copy,qualify_placement
 from r1pro_teleop.airport_fsm.contracts import Fault
 from r1pro_teleop.airport_fsm.geometry import Operation
 op=next(e['operation'] for e in reversed(events) if e['event']=='operation_selected')
 placement=next(e for e in reversed(events) if e['event']=='primitive_start' and e.get('primitive')=='place')
 tray=op['tray'];r.holding=tray;r.retained_contact=None;r.remember_grasp(tray)
 b=r.sim.base_state().astype(float);trials=[]
 for delta in [0.,.05,-.05,.10,-.10]:
  goal=b.copy();goal[2]+=delta;probe=loaded_planning_copy(r)
  try: result=qualify_placement(probe,np.array(placement['parameters']['staged']),np.array(op['destination']),op['yaw'],goal);record=dict(delta_yaw=delta,qualified=True,result=result)
  except Fault as exc:record=dict(delta_yaw=delta,qualified=False,reason=exc.code,detail=exc.detail)
  trials.append(record)
 out.append(dict(trials=trials,variant=variant,case=case,margin_m=r.cfg.camera_front_margin_m,terminal_state='replayed final completed raw2 interval; not independently recorded endpoint',samples=samples,screen_events=[e for e in events if 'arrival' in e['event']]))
path=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/diagnostictools/support_forces_20260929_v1/v19_camera_yaw_candidates.json');path.write_text(json.dumps(out,indent=2,default=lambda x:x.tolist()));print(json.dumps([dict(case=x['case'],trials=x['trials']) for x in out],default=lambda x:x.tolist()))
