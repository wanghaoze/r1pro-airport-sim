"""Read-only measured-qpos FK audit of a recorded place withdrawal endpoint."""
import json
import inspect
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from .placement_clearance import grippers_clear_of_tray
from .contact_summary import sha

def audit_place_withdrawal(source,span):
 import h5py,mujoco
 trace=Path(source['trace']);xml=Path(source['scene_xml']);scene_path=Path(source['scene_json']);result_path=Path(source['result'])
 for path,key in ((trace,'trace_sha256'),(xml,'scene_xml_sha256'),(scene_path,'scene_json_sha256'),(result_path,'result_sha256')):
  if sha(path)!=source[key]:raise ValueError('withdrawal_source_identity_changed:'+key)
 if span.get('action_label')!='place_empty':raise ValueError('actual_place_endpoint_required')
 frame=span.get('measured_endpoint_frame');a=span.get('start_frame');b=span.get('end_frame')
 if type(frame) is not int or type(a) is not int or type(b) is not int or not a<=frame<b:raise ValueError('recorded_place_endpoint_frame_required')
 result=json.loads(result_path.read_text());profile=result.get('control_profile')
 if not isinstance(profile,dict):raise ValueError('actual_control_profile_required')
 model=mujoco.MjModel.from_xml_path(str(xml));data=mujoco.MjData(model)
 with h5py.File(trace,'r') as f:
  metadata=json.loads(f.attrs['metadata_json'])
  if f.attrs.get('schema')!='airport_single_tray_raw/2' or metadata.get('scene_xml_sha256')!=source['scene_xml_sha256'] or json.dumps(profile,sort_keys=True)!=json.dumps(metadata.get('control_profile'),sort_keys=True):raise ValueError('raw_place_model_profile_identity_changed')
  if not 0<=frame<len(f['qpos']):raise ValueError('actual_place_endpoint_frame_missing')
  qpos=np.asarray(f['qpos'][frame],float)
  if qpos.shape!=(model.nq,) or not np.isfinite(qpos).all():raise ValueError('actual_endpoint_qpos_invalid')
 data.qpos[:]=qpos;mujoco.mj_forward(model,data)
 body=data.body(profile['tray_body']);position=body.xpos.copy();rotation=body.xmat.reshape(3,3).copy();size=np.asarray(profile['tray_dimensions'],float)
 corners=np.array([[x,y,z] for x in (-size[0]/2,size[0]/2) for y in (-size[1]/2,size[1]/2) for z in (0,size[2])])@rotation.T+position
 sites={side:int(model.site(side+'_tcp').id) for side in ('left','right')};tcp={side:data.site(sid).xpos.copy() for side,sid in sites.items()}
 adapter=SimpleNamespace(p=SimpleNamespace(front_normal=profile['front_normal']),sim=SimpleNamespace(tcp=lambda side:(tcp[side],None)))
 verified=grippers_clear_of_tray(adapter,dict(tray_corners=corners))
 if not verified:raise ValueError('measured_place_grippers_not_withdrawn')
 return dict(schema='airport_single_tray_place_withdrawal_fk/1',method='private_mjdata_recorded_qpos_mj_forward_no_step_no_ik',qualifier_sha256=sha(Path(inspect.getsourcefile(grippers_clear_of_tray))),verified=True,measured_endpoint_frame=frame,source_action_span={k:span[k] for k in ('action_label','start_frame','end_frame','measured_endpoint_frame')},source_trace_sha256=source['trace_sha256'],source_scene_xml_sha256=source['scene_xml_sha256'],source_scene_json_sha256=source['scene_json_sha256'],source_result_sha256=source['result_sha256'],qpos_sha256=__import__('hashlib').sha256(qpos.tobytes()).hexdigest(),tray_body_id=int(model.body(profile['tray_body']).id),tcp_site_ids=sites,tcp_positions={s:tcp[s].tolist() for s in sites},tray_corners=corners.tolist(),front_normal=profile['front_normal'],vertical_clearance_m=.03,front_clearance_m=.08,mj_steps=0,inverse_solver_calls=0,source_modified=False)
