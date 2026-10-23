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
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.real2sim.robot_action_filter import load_limits, contract_id, bound_actions, configured_limits

class Adapter:
    def __init__(self,entry):
        self.entry=entry;self.config=entry.get('modelConfig',{});self.family=entry.get('family','pi05')
        if self.family=='pi05':
            from studio_mse import load_registered_policy
            self.policy=load_registered_policy(entry)
        elif self.family=='groot':
            from gr00t.policy.gr00t_policy import Gr00tPolicy
            from gr00t.data.embodiment_tags import EmbodimentTag
            self.policy=Gr00tPolicy(model_path=self.config['checkpointPath'],embodiment_tag=EmbodimentTag(self.config['embodimentTag']),device='cuda:0')
            self.modalities=self.policy.get_modality_config()
        elif self.family=='g05':
            from r1pro_teleop.vla.g05_protocol import G05Client
            self.g05=G05Client(self.config)
        elif self.family!='g05':raise ValueError('unsupported_model_family')
    def close(self):
        if self.family=='g05':self.g05.close()
    @property
    def protocol_evidence(self):
        return self.g05.last_evidence if self.family=='g05' else None
    def infer(self,sample,room):
        if self.family=='pi05':return np.asarray(self.policy.infer(sample)['actions'])
        if self.family=='g05':self.g05.last_evidence=None
        c=self.config;s=np.asarray(sample['state']);unit=1250 if c['gripperUnit']=='percent80' else 1000 if c['gripperUnit']=='mm' else 1
        state={'left_arm':s[:7],'left_gripper':s[7:8]*unit,'right_arm':s[8:15],'right_gripper':s[15:16]*unit}
        if self.family=='g05':
            request=dict(images={key:sample['image/'+cam].transpose(2,0,1) for cam,key in [('head_left','head_rgb'),('left_wrist','left_wrist_rgb'),('right_wrist','right_wrist_rgb')]},state=state,task=sample['prompt'],embodiment_type='galaxea_r1pro',frequency=20)
            actions=self.g05.infer(request,room)
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
    limits=configured_limits(request_config.get('filterSettings'));filter_id=contract_id(limits)
    if adapter.family=='pi05' and request_config.get('runtimeProfile') in ('baseline','realtime'):
        began=time.monotonic()
        adapter.infer(dict(state=np.zeros(19,np.float32),prompt='Pick up the tray',**{'image/'+c:np.zeros((224,224,3),np.uint8) for c in ('head_left','left_wrist','right_wrist')}),'warmup_only')
        (a.run/'model_warmup.json').write_text(json.dumps(dict(seconds=time.monotonic()-began,executedActions=0,syntheticWarmupOnly=True)))
    (a.run/'checkpoint_action_contract.json').write_text(json.dumps(dict(checkpointId=entry['id'],inferenceGpu=request_config.get('inferenceGpu',0),actionSafetyMode='robot_limits',actionFilterContract=filter_id,limits=limits,weightsModified=False)))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path!='/health':self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps(dict(checkpointId=entry['id'],family=adapter.family,ready=True,simulationOnly=True,actionFilterContract=filter_id)).encode())
        def do_POST(self):
            room=None;began=None;inference_started=False
            try:
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<=32*1024*1024:raise ValueError('invalid_observation_size')
                with np.load(io.BytesIO(self.rfile.read(size)),allow_pickle=False) as d:sample={k:d[k].copy() for k in d.files}
                room=str(sample.pop('_room'));sample['prompt']=str(sample['prompt'])
                if set(sample)!={'state','prompt','image/head_left','image/left_wrist','image/right_wrist'}:raise ValueError('invalid_observation_fields')
                began=time.monotonic();inference_started=True
                try:actions=adapter.infer(sample,room);latency=time.monotonic()-began
                finally:
                    protocol=getattr(adapter,'protocol_evidence',None)
                    if protocol is not None:
                        with (a.run/'g05_protocol_events.jsonl').open('a',encoding='utf8') as log:
                            log.write(json.dumps(dict(unix=time.time(),requestId=self.headers.get('X-Inference-Request-Id'),checkpointId=entry['id'],**protocol),allow_nan=False)+'\n')
                with (a.run/'inference_model_events.jsonl').open('a') as log:log.write(json.dumps(dict(schema='inference_timing_event/1',stage='model_adapter',requestId=self.headers.get('X-Inference-Request-Id'),unix=time.time(),room=room,checkpointId=entry['id'],latency_seconds=latency,prompt=sample['prompt'],camera_sha256={k:hashlib.sha256(sample['image/'+k].tobytes()).hexdigest() for k in ('head_left','left_wrist','right_wrist')},state=sample['state'].tolist(),actions_sha256=hashlib.sha256(actions.tobytes()).hexdigest(),action_shape=list(actions.shape)))+'\n')
                h=entry.get('modelConfig',{}).get('horizon',20)
                raw=actions.copy();actions=bound_actions(raw,limits,h)
                with (a.run/'checkpoint_limit_events.jsonl').open('a') as log:
                    log.write(json.dumps(dict(unix=time.time(),room=room,raw=raw.tolist(),bounded=actions.tolist(),checkpointId=entry['id'],actionFilterContract=filter_id),allow_nan=False)+'\n')
                out=io.BytesIO();np.savez(out,actions=actions,raw_actions=raw);self.send_response(200);self.end_headers();self.wfile.write(out.getvalue())
            except Exception as exc:
                error={'error':repr(exc),'details':getattr(exc,'details',None)}
                with (a.run/'model_error_events.jsonl').open('a',encoding='utf8') as log:
                    log.write(json.dumps(dict(unix=time.time(),room=room,requestId=self.headers.get('X-Inference-Request-Id'),checkpointId=entry['id'],inferenceStarted=inference_started,**error),allow_nan=False)+'\n')
                self.send_response(500);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(error).encode())
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',a.port),Handler)
    (a.run/'model_http.ready.json').write_text(json.dumps(dict(port=server.server_port,checkpoint_id=entry['id'],family=entry.get('family','pi05'),inferenceGpu=request_config.get('inferenceGpu',0),actionSafetyMode='robot_limits',actionFilterContract=filter_id)))
    try:server.serve_forever()
    finally:
        server.server_close()
        close=getattr(adapter,'close',None)
        if close is not None:close()
if __name__=='__main__':main()
