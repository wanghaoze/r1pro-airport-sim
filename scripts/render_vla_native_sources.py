"""Replay frozen successful episodes into new, verified native four-camera video files."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,json,subprocess,os,sys,hashlib
BASE=Path('/home/michelle/haoze/r1pro-airport-sim')
SOURCE=BASE/'releases/robust_v64_20260930'
COLLECTION=SOURCE/'runs/v64_approximate_400/approximate_completion'
OUT=BASE/'runs/vla_20261001'
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def render(attempt):
 sys.path.insert(0,str(SOURCE))
 from r1pro_teleop.airport_fsm.exporter import Replay
 import av,numpy as np
 attempt=Path(attempt);result=json.loads((attempt/'result.json').read_text())
 if not result.get('task_completed') or result.get('diagnostic_only'):raise ValueError('not complete actual episode')
 scene=result['scene_id'];directory=OUT/'native'/scene/attempt.name
 directory.mkdir(parents=True,exist_ok=False)
 source={'trace':str(attempt/'trace.h5'),'scene_id':scene}
 writers={};streams={};references=[]
 try:
  with Replay(COLLECTION,source) as replay:
   for name,shape in replay.shapes.items():
    writer=av.open(str(directory/(name+'.mp4')),mode='w');stream=writer.add_stream('libx264',rate=20)
    stream.width=shape[1];stream.height=shape[0];stream.pix_fmt='yuv420p';stream.options={'crf':'18','preset':'fast','threads':'1'}
    writers[name]=writer;streams[name]=stream
   n=0
   for index,images in replay:
    for name,image in images.items():
     frame=av.VideoFrame.from_ndarray(image,format='rgb24');frame.pts=index
     for packet in streams[name].encode(frame):writers[name].mux(packet)
    n+=1
   for name in writers:
    for packet in streams[name].encode(None):writers[name].mux(packet)
    writers[name].close()
   writers.clear()
   trace_sha=digest(attempt/'trace.h5')
   for name in replay.shapes:
    references.append({'trace':str(attempt/'trace.h5'),'trace_sha256':trace_sha,'camera':name,'path':str(directory/(name+'.mp4')),'source_start_frame':0,'video_start_frame':0,'frames':n,'sha256':digest(directory/(name+'.mp4')),'native':True})
   manifest={'status':'complete','schema':'airport_vla_native_replay/1','purpose':'training_source_native_video','scene_id':scene,'split':result['split'],'attempt':attempt.name,'trace':str(attempt/'trace.h5'),'trace_sha256':trace_sha,'scene_xml_sha256':digest(COLLECTION/'scenes'/scene/'mobile.xml'),'base_qpos_indices':replay.runtime.base_qids.tolist(),'frames':n,'fps':20,'replay_max_qpos_error':replay.maximum_error,'camera_checks':replay.camera_checks,'references':references,'task_completed':True,'strict_success':result.get('strict_success',False),'source':'simulation/program_generated'}
   (directory/'manifest.json').write_text(json.dumps(manifest,indent=2))
   print(json.dumps({'scene':scene,'frames':n,'status':'complete','replay_error':replay.maximum_error}),flush=True)
 except BaseException as exc:
  for writer in writers.values():writer.close()
  (directory/'failure.json').write_text(json.dumps({'status':'failed','error':repr(exc)}))
  raise
 return references

def main():
 p=argparse.ArgumentParser();p.add_argument('--one');p.add_argument('--limit',type=int,default=16);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
 if a.one:render(a.one);return
 OUT.mkdir(parents=True,exist_ok=True)
 buckets={i:[] for i in range(4)}
 for scene in sorted((COLLECTION/'attempts').iterdir()):
  for f in sorted(scene.glob('a*/result.json')):
   result=json.loads(f.read_text())
   if result.get('task_completed') and result['split']=='train' and not result.get('diagnostic_only'):
    spec=json.loads((COLLECTION/'scenes'/scene.name/'scene.json').read_text());buckets[spec['front_count']].append(str(f.parent));break
 selected=[]
 while len(selected)<a.limit and any(buckets.values()):
  for values in buckets.values():
   if values and len(selected)<a.limit:selected.append(values.pop(0))
 plan=OUT/'native_plan.json'
 if plan.exists():raise FileExistsError(plan)
 plan.write_text(json.dumps({'source_collection':str(COLLECTION),'selected':selected,'split':'train','workers':a.workers},indent=2))
 env=dict(os.environ,MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
 def run_one(attempt):
  log=OUT/('render_'+Path(attempt).parent.name+'.log')
  with log.open('x') as f:return subprocess.run([sys.executable,__file__,'--one',attempt],env=env,stdout=f,stderr=subprocess.STDOUT).returncode
 with ThreadPoolExecutor(max_workers=a.workers) as pool:codes=list(pool.map(run_one,selected))
 refs=[];manifests=[]
 for f in sorted((OUT/'native').glob('*/*/manifest.json')):
  manifest=json.loads(f.read_text());refs.extend(manifest['references']);manifests.append(str(f))
 (OUT/'video_references.json').write_text(json.dumps(refs,indent=2))
 (OUT/'native_status.json').write_text(json.dumps({'status':'complete' if all(c==0 for c in codes) else 'partial','selected':len(selected),'rendered':len(manifests),'returncodes':codes,'video_references':str(OUT/'video_references.json'),'manifests':manifests},indent=2))
if __name__=='__main__':main()
