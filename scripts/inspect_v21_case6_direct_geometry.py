import pathlib,json,sys,h5py,numpy as np
root=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/releases/robust_v21_20260929');sys.path.insert(0,str(root))
from r1pro_teleop.airport_fsm.runtime import Runtime
from r1pro_teleop.airport_fsm.registry import config_for
source=root/'runs/ablation/geometry';scene=next((source/'scenes').glob('airport_0006_*'));a=source/'attempts'/scene.name/'a000'
es=[json.loads(x) for x in (a/'events.jsonl').read_text().splitlines()];op=next(e['operation'] for e in es if e['event']=='operation_selected');r=Runtime(json.loads((scene/'scene.json').read_text()),scene/'mobile.xml',config_for(source),render=False)
with h5py.File(a/'trace.h5') as h:
 i=542;r.mj.mj_setState(r.m,r.d,h['integration_state'][i],r.integration_spec);r.mj.mj_forward(r.m,r.d);r.d.qacc_warmstart[:]=h['qacc_warmstart'][i];r.sim.target=h['action'][i-1].copy();r.sim.base_target=h['base_action'][i-1].copy();r.allowed_tray=op['tray'];r.remember_grasp(op['tray']);e=r.observation()
 out=dict(frame=i,operation=op,poses=e['tray_pose'].tolist(),tcp={side:r.sim.tcp(side)[0].tolist() for side in ['left','right']},blockers0=r.g.blockers(e['tray_pose'],op['tray'],np.array(op['destination']),op['yaw'],0),blockers65mm=r.g.blockers(e['tray_pose'],op['tray'],np.array(op['destination']),op['yaw'],.065))
 from r1pro_teleop.airport_fsm.placement_reachability import loaded_planning_copy,qualify_placement
 from r1pro_teleop.airport_fsm.contracts import Fault
 try:out['direct_prediction']=qualify_placement(loaded_planning_copy(r),np.array(op['destination']),np.array(op['destination']),op['yaw'],r.sim.base_state())
 except Fault as ex:out['direct_prediction_failure']=dict(code=ex.code,detail=ex.detail)
 outpath=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/diagnostictools/support_forces_20260929_v1/v21_case6_direct_geometry.json');outpath.write_text(json.dumps(out,default=lambda x:x.tolist(),indent=2));print(json.dumps(out,default=lambda x:x.tolist()))
