import pathlib,json,hashlib,xml.etree.ElementTree as ET,h5py,numpy as np
B=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/releases');roots=[B/'coverage_v4_20260928/runs/firstpass',B/'robust_v24b_20260929/runs/fresh_verification/baseline'];out=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/diagnostictools/support_forces_20260929_v1/v4_v24b_regression_audit');report=json.loads((out/'audit.json').read_text());rows=[];assets={}
for case in report['historical_success_cases']:
 models=[];specs=[]
 for root in roots:
  scene=next((root/'scenes').glob(f'airport_{case:04d}_*'));xml=ET.parse(scene/'mobile.xml')
  for e in xml.iter():
   if 'file' in e.attrib:
    file=(scene/e.attrib['file']).resolve();key=str(file)
    if key not in assets:assets[key]=hashlib.sha256(file.read_bytes()).hexdigest()
    e.attrib['file']=file.name+':sha256:'+assets[key]
  models.append(ET.tostring(xml.getroot()));spec=json.loads((scene/'scene.json').read_text());spec.pop('xml_sha256',None);specs.append(spec)
 rows.append(dict(case=case,normalized_xml_and_asset_bytes_equal=models[0]==models[1],scene_except_xml_sha_equal=specs[0]==specs[1]))
result=dict(normalized_scenes=rows,asset_files_hashed=len(assets),case60_aligned={})
left=next((roots[0]/'attempts').glob('airport_0060_*'))/'a000/trace.h5';right=next((roots[1]/'attempts').glob('airport_0060_*'))/'a000/trace.h5'
with h5py.File(left) as a,h5py.File(right) as b:
 for label,x,y in [('pregrasp_entry',158,158),('pregrasp_endpoint',194,218),('contact_approach_entry',276,324),('close_entry',331,379),('push_entry',377,425),('push_1s',397,445),('push_1_5s',407,455)]:
  record=dict(old_frame=x,new_frame=y)
  for key in ('qpos','qvel','action','tray_pose','gripper_contact_force','table_contact'):
   if key in a and key in b:record[key+'_max_diff']=float(np.max(abs(a[key][x]-b[key][y])))
  record['old_tray2_table']=int(a['table_contact'][x][2]);record['new_tray2_table']=int(b['table_contact'][y][2]);result['case60_aligned'][label]=record
(out/'provenance_and_aligned.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
