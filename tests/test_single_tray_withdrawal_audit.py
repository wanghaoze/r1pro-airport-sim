import json
from dataclasses import asdict
import h5py,numpy as np,pytest,mujoco
from r1pro_teleop.single_tray_lab.withdrawal_audit import audit_place_withdrawal
from r1pro_teleop.single_tray_lab.control import ControlProfile
from r1pro_teleop.single_tray_lab.contact_summary import sha

def fixture(tmp_path,height):
 xml=tmp_path/'scene.xml';xml.write_text(f'<mujoco><worldbody><body name="tray" pos=".85 -.24 .8"><geom type="sphere" size=".01"/></body><site name="left_tcp" pos=".85 -.24 {height}"/><site name="right_tcp" pos=".85 -.24 {height}"/></worldbody></mujoco>')
 scene=tmp_path/'scene.json';scene.write_text('{}');result=tmp_path/'result.json';p=asdict(ControlProfile());result.write_text(json.dumps(dict(control_profile=p)))
 trace=tmp_path/'trace.h5';model=mujoco.MjModel.from_xml_path(str(xml))
 with h5py.File(trace,'w') as f:
  f.attrs.update(schema='airport_single_tray_raw/2',metadata_json=json.dumps(dict(control_profile=p,scene_xml_sha256=sha(xml))));f['qpos']=np.zeros((1,model.nq))
 source={k:str(v) for k,v in [('trace',trace),('scene_xml',xml),('scene_json',scene),('result',result)]}
 source.update({k+'_sha256':sha(v) for k,v in [('trace',trace),('scene_xml',xml),('scene_json',scene),('result',result)]})
 return source,dict(action_label='place_empty',start_frame=0,end_frame=1,measured_endpoint_frame=0)

def test_actual_fk_clear_and_source_unchanged(tmp_path):
 source,span=fixture(tmp_path,1.2);before=sha(source['trace']);e=audit_place_withdrawal(source,span)
 assert e['verified'] and e['mj_steps']==0 and e['inverse_solver_calls']==0 and e['tcp_positions']['left'][2]==1.2
 assert sha(source['trace'])==before

def test_low_tcp_cannot_count_release_as_withdrawal(tmp_path):
 source,span=fixture(tmp_path,.85)
 with pytest.raises(ValueError,match='not_withdrawn'):audit_place_withdrawal(source,span)

def test_missing_measured_endpoint_and_source_mutation_rejected(tmp_path):
 source,span=fixture(tmp_path,1.2);span.pop('measured_endpoint_frame')
 with pytest.raises(ValueError,match='endpoint_frame_required'):audit_place_withdrawal(source,span)
 span['measured_endpoint_frame']=0;open(source['scene_json'],'a').write(' ')
 with pytest.raises(ValueError,match='source_identity_changed'):audit_place_withdrawal(source,span)
