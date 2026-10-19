"""Loopback model process, separate from ROS's Python/ABI. NPZ, no pickle."""
import argparse
from http.server import BaseHTTPRequestHandler,HTTPServer
import io
import json
from pathlib import Path
import threading
import time
import hashlib
import numpy as np

class Adapter:
    def __init__(self,entry):
        self.entry=entry;self.config=entry.get('modelConfig',{});self.family=entry.get('family','pi05');self.clients={}
        if self.family=='pi05':
            from studio_mse import load_registered_policy
            self.policy=load_registered_policy(entry)
        elif self.family=='groot':
            from gr00t.policy.gr00t_policy import Gr00tPolicy
            from gr00t.data.embodiment_tags import EmbodimentTag
            self.policy=Gr00tPolicy(model_path=self.config['checkpointPath'],embodiment_tag=EmbodimentTag(self.config['embodimentTag']),device='cuda:0')
            self.modalities=self.policy.get_modality_config()
        elif self.family!='g05':raise ValueError('unsupported_model_family')
    def infer(self,sample,room):
        if self.family=='pi05':return np.asarray(self.policy.infer(sample)['actions'])
        c=self.config;s=np.asarray(sample['state']);unit=1250 if c['gripperUnit']=='percent80' else 1000 if c['gripperUnit']=='mm' else 1
        state={'left_arm':s[:7],'left_gripper':s[7:8]*unit,'right_arm':s[8:15],'right_gripper':s[15:16]*unit}
        if self.family=='g05':
            import msgpack
            from websockets.sync.client import connect
            def encode(a):
                if isinstance(a,np.ndarray):return {b'__ndarray__':True,b'data':a.tobytes(),b'dtype':a.dtype.str,b'shape':a.shape}
                if isinstance(a,np.generic):return a.item()
                raise TypeError(type(a).__name__)
            def decode(d):
                if b'__ndarray__' in d:return np.frombuffer(d[b'data'],dtype=d[b'dtype']).reshape(d[b'shape'])
                return d
            if room not in self.clients:
                ws=connect(f"ws://{c['host']}:{c['port']}",max_size=None,open_timeout=15);metadata=msgpack.unpackb(ws.recv(timeout=20),object_hook=decode,raw=False);self.clients[room]=ws
            ws=self.clients[room]
            request=dict(images={key:sample['image/'+cam].transpose(2,0,1) for cam,key in [('head_left','head_rgb'),('left_wrist','left_wrist_rgb'),('right_wrist','right_wrist_rgb')]},state=state,task=sample['prompt'],embodiment_type='galaxea_r1pro',frequency=20)
            ws.send(msgpack.packb(request,default=encode));reply=msgpack.unpackb(ws.recv(timeout=120),object_hook=decode,raw=False)
            if 'error' in reply:raise RuntimeError(reply['error'])
            actions={k:np.asarray(v).reshape(1,-1) for k,v in reply['action'].items()}
        else:
            # Explicit joint-key mapping. Relative-EEF checkpoints cannot use this adapter.
            sk=c['stateKeys'];ck=c['cameraKeys']
            obs={'video':{ck[k]:sample['image/'+k][None,None] for k in ck},'state':{sk[k]:v[None,None] for k,v in state.items()},'language':{'task':[[sample['prompt']]]}}
            result=self.policy.get_action(obs);raw=result[0] if isinstance(result,tuple) else result
            ak=c.get('actionKeys',sk);actions={k:np.asarray(raw[ak[k]])[0] for k in state}
        h=c['horizon'];result=np.zeros((h,19),dtype=np.float32)
        for part,start,width in [('left_arm',0,7),('left_gripper',7,1),('right_arm',8,7),('right_gripper',15,1)]:
            a=actions[part]
            if a.ndim!=2 or a.shape[0]<h or a.shape[1]!=width:raise ValueError('model_action_layout_mismatch:'+part)
            result[:,start:start+width]=a[:h]/(unit if 'gripper' in part else 1)
        return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--port',type=int,default=0);a=p.parse_args()
    entry=json.loads((a.run/'checkpoints.json').read_text())[0];adapter=Adapter(entry)
    request_config=json.loads((a.run/'request.json').read_text()).get('payload',{})
    limits=json.loads((Path(__file__).resolve().parents[1]/'gpu/robot_action_limits.json').read_text()) if request_config.get('actionSafetyMode')=='robot_limits' else None
    if adapter.family=='pi05' and request_config.get('runtimeProfile') in ('baseline','realtime'):
        began=time.monotonic()
        adapter.infer(dict(state=np.zeros(19,np.float32),prompt='Pick up the tray',**{'image/'+c:np.zeros((224,224,3),np.uint8) for c in ('head_left','left_wrist','right_wrist')}),'warmup_only')
        (a.run/'model_warmup.json').write_text(json.dumps(dict(seconds=time.monotonic()-began,executedActions=0,syntheticWarmupOnly=True)))
    (a.run/'checkpoint_action_contract.json').write_text(json.dumps(dict(checkpointId=entry['id'],actionSafetyMode=request_config.get('actionSafetyMode','strict'),limits=limits,weightsModified=False)))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path!='/health':self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps(dict(checkpointId=entry['id'],family=adapter.family,ready=True,simulationOnly=True)).encode())
        def do_POST(self):
            try:
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<=32*1024*1024:raise ValueError('invalid_observation_size')
                with np.load(io.BytesIO(self.rfile.read(size)),allow_pickle=False) as d:sample={k:d[k].copy() for k in d.files}
                room=str(sample.pop('_room'));sample['prompt']=str(sample['prompt'])
                if set(sample)!={'state','prompt','image/head_left','image/left_wrist','image/right_wrist'}:raise ValueError('invalid_observation_fields')
                began=time.monotonic();actions=adapter.infer(sample,room);latency=time.monotonic()-began
                with (a.run/'inference_events.jsonl').open('a') as log:log.write(json.dumps(dict(unix=time.time(),room=room,checkpointId=entry['id'],latency_seconds=latency,prompt=sample['prompt'],camera_sha256={k:hashlib.sha256(sample['image/'+k].tobytes()).hexdigest() for k in ('head_left','left_wrist','right_wrist')},state=sample['state'].tolist(),actions_sha256=hashlib.sha256(actions.tobytes()).hexdigest(),action_shape=list(actions.shape)))+'\n')
                if limits:
                    raw=actions.copy();actions=actions.astype(np.float64)
                    for side,offset in [('left',0),('right',8)]:
                        for j in range(7):actions[:,offset+j]=np.clip(actions[:,offset+j],*limits['mechanical']['ranges'][f'{side}_arm_joint{j+1}'])
                        actions[:,offset+7]=np.clip(actions[:,offset+7],*limits['gripper_range_m'])
                    with (a.run/'checkpoint_limit_events.jsonl').open('a') as log:log.write(json.dumps(dict(unix=time.time(),room=room,raw=raw.tolist(),bounded=actions.tolist(),checkpointId=entry['id']))+'\n')
                h=entry.get('modelConfig',{}).get('horizon',20)
                if actions.shape!=(h,19) or not np.isfinite(actions).all():raise ValueError('invalid_model_output')
                out=io.BytesIO();np.savez(out,actions=actions);self.send_response(200);self.end_headers();self.wfile.write(out.getvalue())
            except Exception as exc:self.send_response(500);self.end_headers();self.wfile.write(json.dumps({'error':repr(exc)}).encode())
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',a.port),Handler)
    (a.run/'model_http.ready.json').write_text(json.dumps(dict(port=server.server_port,checkpoint_id=entry['id'],family=entry.get('family','pi05'),actionSafetyMode=request_config.get('actionSafetyMode','strict'))))
    server.serve_forever()
if __name__=='__main__':main()
