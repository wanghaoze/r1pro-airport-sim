"""Read frozen integration states; terminal replay uses recorded per-substep controls."""
import json,pathlib,sys,h5py,numpy as np
root=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/releases/robust_v19_20260929')
sys.path.insert(0,str(root))
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.registry import config_for
out=[]
for variant,case in [('alternate_align',218),('alternate_align',4)]:
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
  selected=next(e for e in reversed(events) if e['event']=='placement_arrival_reachability_screen')
  restore(selected['frame'])
 from r1pro_teleop.airport_fsm import placement_reachability as pr
 from r1pro_teleop.airport_fsm.contracts import Fault
 op=next(e['operation'] for e in reversed(events) if e['event']=='operation_selected' and e['frame']<=selected['frame'])
 place=next(e for e in reversed(events) if e['event']=='primitive_start' and e.get('primitive')=='place')
 r.holding=op['tray'];r.retained_contact=None;r.remember_grasp(op['tray'])
 probe=pr.loaded_planning_copy(r);plan_original=pr.plan;checked=[]
 def wrapped_plan(probe,*args,**kwargs):
  result=plan_original(probe,*args,**kwargs);metrics=[]
  for u in np.linspace(0,1,201):
   q=result[0].evaluate(u,result[1]/probe.cfg.fps)[0];metrics.append(probe.camera_metrics(probe._shadow(q)))
  checked.append(dict(frames=result[1],phase=probe.phase,min_camera_ahead_m={side:min(m[side]['camera_ahead_m'] for m in metrics) for side in ['left','right']},endpoint_camera=metrics[-1]))
  return result
 pr.plan=wrapped_plan
 try:
  prediction=pr.qualify_placement(probe,np.array(place['parameters']['staged']),np.array(op['destination']),op['yaw'],np.array(selected['qualified'][0]['base']));error=None
 except Fault as exc:prediction=None;error=dict(reason=exc.code,detail=exc.detail)
 pr.plan=plan_original
 out.append(dict(prediction=prediction,error=error,checked=checked,screen_frame=selected['frame'],variant=variant,case=case,margin_m=r.cfg.camera_front_margin_m,terminal_state='replayed final completed raw2 interval; not independently recorded endpoint',samples=samples,screen_events=[e for e in events if 'arrival' in e['event']]))
path=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/diagnostictools/support_forces_20260929_v1/v19_camera_prediction.json');path.write_text(json.dumps(out,indent=2,default=lambda x:x.tolist()));print(json.dumps([{k:v for k,v in x.items() if k not in ['screen_events','samples']} for x in out],default=lambda x:x.tolist()))
