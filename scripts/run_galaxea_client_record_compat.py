"""New robot entry; preserves original run/scheduler/filter/recorder files."""
import argparse
import json
import runpy
import sys
import subprocess
import shutil
import time
import os
import threading
from collections import deque
from pathlib import Path
import numpy as np


def json_value(x):
    if isinstance(x, np.ndarray): return json_value(x.tolist())
    if isinstance(x, np.generic): return json_value(x.item())
    if isinstance(x,float) and not np.isfinite(x):return str(x)
    if isinstance(x, dict): return {k:json_value(v) for k,v in x.items()}
    if isinstance(x, (list, tuple)): return [json_value(v) for v in x]
    return x


def arrays(values):
    return None if values is None else {k:np.asarray(v) for k,v in values.items()}


def save_video(recorder, tag):
    import cv2
    first=next((s['images'] for s in recorder._steps if s['images'] is not None),None)
    if first is None:return
    keys=sorted(first);height=max(img.shape[1] for img in first.values());writer=None;last=None;opencv=not bool(shutil.which('ffmpeg'))
    try:
        for step in recorder._steps:
            if step['images'] is not None:
                panels=[]
                for key in keys:
                    image=np.transpose(step['images'][key],(1,2,0))
                    if image.shape[0]!=height:image=cv2.resize(image,(int(image.shape[1]*height/image.shape[0]),height))
                    panels.append(image)
                last=np.concatenate(panels,axis=1)
            if last is None:continue
            frame=last.copy();text=step.get('extra',{}).get('cot_text','')
            if text:recorder._overlay_text(frame,text)
            if writer is None:
                h,w,_=frame.shape
                if opencv:
                    writer=cv2.VideoWriter(str(recorder.save_dir/f'{tag}.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),recorder.fps,(w,h))
                    if not writer.isOpened():raise RuntimeError('OpenCV video encoder unavailable')
                else:writer=subprocess.Popen(['ffmpeg','-v','error','-n','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}','-r',str(recorder.fps),'-i','pipe:0','-an','-c:v','libx264','-crf','23','-pix_fmt','yuv420p',str(recorder.save_dir/f'{tag}.mp4')],stdin=subprocess.PIPE)
            if opencv:writer.write(cv2.cvtColor(frame,cv2.COLOR_RGB2BGR))
            else:writer.stdin.write(np.ascontiguousarray(frame).tobytes())
    finally:
        if writer:
            if opencv:writer.release()
            else:
                writer.stdin.close()
                if writer.wait()!=0:raise RuntimeError('FFmpeg recording failed; retain JSON/failure evidence')


def main():
    root=Path(__file__).resolve().parent
    if not (root/'run.py').exists():
        raise RuntimeError('Deploy this new entry beside the original robot run.py')
    sys.path.insert(0,str(root))
    import toml
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--config','-c',default='config.toml')
    args,_=p.parse_known_args();cfg=toml.load(args.config)
    from utils import episode_recorder
    from scheduler import scheduler
    recorders=[];bridges=[];filters=[]
    original_recorder=episode_recorder.EpisodeRecorder
    original_bridge=scheduler.Ros2Bridge
    original_filter=scheduler.JointCommandFilter
    class CompatibleRecorder(original_recorder):
        def __init__(self, save_dir, fps=None):
            super().__init__(save_dir, fps=int(cfg['basic']['control_frequency']) if fps is None else fps)
            recorders.append(self)
        def add_step(self, images=None, gt_action=None, pred_action=None, extra=None):
            extra=json_value(extra or {})
            extra['submitted_action']=json_value(pred_action)
            if filters:extra['joint_filter_diagnostic']=json_value(filters[-1].last_diagnostic)
            super().add_step(images,arrays(gt_action),arrays(pred_action),extra)
        def _save_video(self,tag):save_video(self,tag)
        def stop_and_save(self):
            # Save controls even if media encoding fails.
            if self.active and self._steps:
                self.save_dir.mkdir(parents=True,exist_ok=True)
                self._save_json(f'episode_{self._episode_idx:04d}')
            super().stop_and_save()
    class TrackedBridge(original_bridge):
        def __init__(self,*a,**kw):
            self.sdk_lock=threading.Lock();self.sdk_history=deque(maxlen=2048)
            super().__init__(*a,**kw);bridges.append(self)
        def state_callback(self,msg,_stack=None,state_name='None'):
            if state_name in ('left_arm','right_arm'):
                entry=dict(kind='sdk_feedback',part=state_name,unix=time.time(),
                           stamp_seconds=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
                           position=list(msg.position),velocity=list(msg.velocity),effort=list(msg.effort))
                with self.sdk_lock:self.sdk_history.append(entry)
            return super().state_callback(msg,_stack=_stack,state_name=state_name)
        def publish_action(self,action):
            entry=dict(kind='ros_publish_attempt',unix=time.time(),intervention_active=self._intervention_active,
                       positions={k:list(v.position) for k,v in vars(action).items() if v is not None and hasattr(v,'position')})
            with self.sdk_lock:self.sdk_history.append(entry)
            result=super().publish_action(action)
            entry['publish_api_returned']=True
            return result
        def sdk_snapshot(self):
            with self.sdk_lock:return [dict(row) for row in self.sdk_history]
    class DiagnosticFilter(original_filter):
        def __init__(self,*a,**kw):
            super().__init__(*a,**kw);self.last_diagnostic={};self.diagnostic_sequence=0;filters.append(self)
        def step(self,action,measured_state,observation_age):
            self.diagnostic_sequence+=1
            d=dict(sequence=self.diagnostic_sequence,unix=time.time(),observation_age=observation_age,
                   measured_state=json_value(measured_state),raw_target=json_value(action),
                   previous_filtered_target=json_value(self.previous),limits=json_value(self.limits))
            # Convert infinite optional bounds to text for strict JSON evidence.
            d['limits']={arm:{k:('unconfigured' if k in ['lower','upper'] and not np.isfinite(v).all() else json_value(v)) for k,v in values.items()} for arm,values in self.limits.items()}
            if self.previous is not None:
                d['feedback_minus_previous_rad']={arm:(np.asarray(measured_state[arm])-np.asarray(self.previous[arm])).tolist() for arm in ['left_arm','right_arm']}
            try:
                result=super().step(action,measured_state,observation_age)
                d.update(status='accepted',filtered_action=json_value(result));return result
            except Exception as error:
                d.update(status='rejected',error=repr(error))
                # Copy the high-rate stream before cleanup; original fault remains latched.
                if bridges:d['sdk_pre_fault_history']=bridges[-1].sdk_snapshot()
                raise
            finally:
                self.last_diagnostic=d
                destination=recorders[-1].save_dir if recorders else root/'recordings/filter_diagnostics'
                destination.mkdir(parents=True,exist_ok=True)
                with (destination/'joint_filter_diagnostics.jsonl').open('a') as f:
                    f.write(json.dumps(json_value(d),allow_nan=False)+'\n')
                    if d.get('status')=='rejected':f.flush();os.fsync(f.fileno())
    episode_recorder.EpisodeRecorder=CompatibleRecorder
    scheduler.Ros2Bridge=TrackedBridge
    scheduler.JointCommandFilter=DiagnosticFilter
    try:
        runpy.run_path(str(root/'run.py'),run_name='__main__')
    finally:
        for bridge in bridges:
            try:
                if filters and filters[-1].last_diagnostic.get('status')=='rejected':
                    # Passive post-fault observation only; no hold/reset/recovery commands.
                    time.sleep(1.0)
                    destination=recorders[-1].save_dir if recorders else root/'recordings/filter_diagnostics'
                    destination.mkdir(parents=True,exist_ok=True)
                    with (destination/'sdk_fault_window.json').open('w') as f:
                        json.dump(json_value(dict(fault=filters[-1].last_diagnostic,
                            sdk_history=bridge.sdk_snapshot(),automatic_recovery=False)),f,allow_nan=False,indent=2)
                        f.flush();os.fsync(f.fileno())
            except Exception as error:print('SDK diagnostic save failed:',repr(error),file=sys.stderr)
            try: bridge.destroy()
            except Exception as error: print('Bridge cleanup failed:',repr(error),file=sys.stderr)
        for recorder in recorders:
            try: recorder.stop_and_save()
            except Exception as error: print('Recording closure failed:',repr(error),file=sys.stderr)
        episode_recorder.EpisodeRecorder=original_recorder
        scheduler.Ros2Bridge=original_bridge
        scheduler.JointCommandFilter=original_filter


if __name__=='__main__':main()
