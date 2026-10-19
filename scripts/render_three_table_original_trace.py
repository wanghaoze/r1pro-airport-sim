"""Native four-camera continuous replay of original raw Trace diagnostics."""
from pathlib import Path
import argparse,json,sys,os,subprocess,xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_3table.replay import ThreeTableTraceReplay
from r1pro_teleop.airport_fsm.contracts import sha256_file

class NativeWriter:
 def __init__(self,path,shape):
  import av
  self.av=av;self.closed=False;self.container=av.open(str(path),'w');self.stream=self.container.add_stream('libx264',rate=20);self.stream.width=shape[1];self.stream.height=shape[0];self.stream.pix_fmt='yuv420p';self.stream.options={'crf':'18','preset':'fast','threads':'1'}
 def write(self,image):
  for packet in self.stream.encode(self.av.VideoFrame.from_ndarray(image,format='rgb24')):self.container.mux(packet)
 def close(self):
  if self.closed:return
  for packet in self.stream.encode():self.container.mux(packet)
  self.container.close();self.closed=True

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',required=True);p.add_argument('--output',required=True);p.add_argument('--audit-only',action='store_true');a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
 replay=ThreeTableTraceReplay(a.case,render=not a.audit_only);source={k:sha256_file(v) for k,v in replay.source_files.items()};writers={};gpu=[];frames=0
 try:
  if not a.audit_only:
   writers={camera:NativeWriter(out/(camera+'.mp4'),shape) for camera,shape in replay.shapes.items()}
  for frame,images in replay:
   frames+=1
   if not a.audit_only:
    for camera,image in images.items():writers[camera].write(image)
    if frames==1:
     doc=ET.fromstring(subprocess.check_output(['nvidia-smi','-q','-x'],text=True))
     gpu=[dict(pid=os.getpid(),gpu_uuid=g.findtext('uuid'),type=p.findtext('type'),used_memory=p.findtext('used_memory')) for g in doc.findall('gpu') for p in g.findall('./processes/process_info') if p.findtext('pid')==str(os.getpid())]
  for writer in writers.values():writer.close()
  if source!={k:sha256_file(v) for k,v in replay.source_files.items()}:raise ValueError('original_source_changed_during_replay')
  receipt=dict(schema='airport_three_table_original_trace_native_replay/1',task_profile='three_table_single_tray_action3_v1',source_schema=replay.schema,diagnostic_only=True,task_completed=False,training_eligible=False,training_ready=False,source='simulation/program_generated',frames=frames,source_files=replay.source_files,source_sha256=source,errors=replay.errors,terminal_checked=replay.terminal_checked,initial_restore_count=1,pose_resets_during_replay=0,teacher_calls=0,inverse_solver_calls=0,environment_event_count=replay.environment_event_count,camera_checks=replay.camera_checks,actual_own_gpu_rows=gpu,audit_only=a.audit_only)
  (out/'manifest.json').write_text(json.dumps(receipt,indent=2,allow_nan=False));print(json.dumps(receipt))
 finally:
  for writer in writers.values():writer.close()
  replay.close()
if __name__=='__main__':main()
