"""Render a new raw2 replay; failed prefixes remain nontraining evidence."""
import argparse,json,sys,os,subprocess,hashlib,time,xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def main():
 p=argparse.ArgumentParser();p.add_argument('--case',required=True);p.add_argument('--output',required=True);p.add_argument('--max-frames',type=int);p.add_argument('--expected-profile');a=p.parse_args()
 import av,mujoco
 from r1pro_teleop.single_tray_lab.replay import SingleTrayReplay
 case=Path(a.case);out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
 def progress(stage,**values):
  target=out/'progress.json';temp=out/'progress.json.tmp';temp.write_text(json.dumps(dict(stage=stage,pid=os.getpid(),heartbeat_unix=time.time(),**values)));temp.replace(target)
 progress('initializing_continuous_native_replay',completed_frames=0)
 def filehash(path):
  h=hashlib.sha256()
  with Path(path).open('rb') as stream:
   while chunk:=stream.read(8*1024*1024):h.update(chunk)
  return h.hexdigest()
 scene_doc=json.loads((case/'scene/scene.json').read_text());xml=Path(scene_doc['xml'])
 if a.expected_profile and scene_doc.get('task_profile')!=a.expected_profile:raise ValueError('renderer_scene_profile_mismatch')
 source_files={'trace':case/'attempt/trace.h5','events':case/'attempt/events.jsonl','scene_xml':xml,'scene_json':case/'scene/scene.json','result':case/'result.json'}
 source_hashes={key:filehash(path) for key,path in source_files.items()}
 replay=SingleTrayReplay(case/'attempt/trace.h5',xml,case/'attempt/events.jsonl')
 if a.expected_profile and replay.meta.get('task_profile')!=a.expected_profile:raise ValueError('renderer_raw_profile_mismatch')
 gpu_rows=[]
 def capture_gpu():
  doc=ET.fromstring(subprocess.check_output(['nvidia-smi','-q','-x'],text=True))
  for gpu in doc.findall('gpu'):
   for proc in gpu.findall('./processes/process_info'):
    if proc.findtext('pid')==str(os.getpid()):
     row=dict(pid=os.getpid(),gpu_uuid=gpu.findtext('uuid'),type=proc.findtext('type'),used_memory=proc.findtext('used_memory'))
     if row not in gpu_rows:gpu_rows.append(row)
 cameras={'head_left':(1920,1536),'head_right':(1920,1536),'left_wrist':(1280,720),'right_wrist':(1280,720)}
 containers={};renderers={};streams={}
 try:
  for camera,(w,h) in cameras.items():
   renderers[camera]=mujoco.Renderer(replay.model,height=h,width=w);container=av.open(str(out/(camera+'.mp4')),'w');stream=container.add_stream('libx264',rate=20);stream.width=w;stream.height=h;stream.pix_fmt='yuv420p';stream.options={'crf':'18'};containers[camera]=container;streams[camera]=stream
  count=min(replay.frames,a.max_frames) if a.max_frames else replay.frames
  for i in range(count):
   replay.before(i)
   for camera,renderer in renderers.items():
    renderer.update_scene(replay.data,camera=camera);frame=av.VideoFrame.from_ndarray(renderer.render(),format='rgb24')
    for packet in streams[camera].encode(frame):containers[camera].mux(packet)
   if i==0:capture_gpu()
   replay.advance()
   if i%50==0:progress('rendering_original_native_four_views',completed_frames=i+1,total_frames=count,actual_own_gpu_rows=gpu_rows,sim_time=float(replay.data.time))
  receipt=replay.finish() if count==replay.frames else dict(errors=replay.errors,frames=count,terminal_checked=False)
  if source_hashes!={key:filehash(path) for key,path in source_files.items()}:raise ValueError('source_changed_during_replay')
  receipt.update(schema='airport_single_tray_native_replay/1',source_files={key:str(path) for key,path in source_files.items()},source_sha256=source_hashes,native_camera_contract={key:dict(width=size[0],height=size[1],fps=20) for key,size in cameras.items()},training_ready=False,source_schema=replay.source_schema,task_profile=replay.meta.get('task_profile'),actual_own_gpu_rows=gpu_rows,environment_event_count=sum(len(events) for events in replay.events.values()));(out/'manifest.json').write_text(json.dumps(receipt,indent=2));progress('replay_verified_waiting_encoder_flush',completed_frames=count,total_frames=count,six_errors=replay.errors)
 finally:
  for camera in containers:
   for packet in streams[camera].encode():containers[camera].mux(packet)
   containers[camera].close();renderers[camera].close()
  replay.close()
if __name__=='__main__':main()
