"""Real ROS 2 topic transport for simulation only; no hardware topic aliases.

Gateway: native NPZ -> Image/JointState/request topics -> correlated action NPZ.
Adapter: topic observations -> loopback model service -> action topic.
Use --external-policy to connect your own policy node instead of the adapter.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import time
import urllib.request
import numpy as np

CAMERAS=('head_left','left_wrist','right_wrist')
NAMES=[*(f'left_joint_{i}' for i in range(1,8)),'left_gripper_m',*(f'right_joint_{i}' for i in range(1,8)),'right_gripper_m','base_dx_m','base_dy_m','base_dyaw_rad']

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--external-policy',action='store_true');a=p.parse_args()
    if os.environ.get('ROS_DOMAIN_ID')!='86':raise ValueError('Simulation transport requires isolated ROS_DOMAIN_ID=86')
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import Image,JointState
    from std_msgs.msg import String
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy
    run=a.run.resolve();directory=run/'policy';directory.mkdir(exist_ok=True)
    entry=json.loads((run/'checkpoints.json').read_text())[0];h=entry.get('modelConfig',{}).get('horizon',20)
    request_config=json.loads((run/'request.json').read_text())['payload'];ids=request_config['roomIds'];timeout=request_config.get('inferenceTimeoutSeconds',150)
    def status(data):
        tmp=run/'inference_status.tmp';tmp.write_text(json.dumps(data));tmp.replace(run/'inference_status.json')
    prefix='/r1pro_sim/job_'+run.name.replace('-','_');qos=QoSProfile(depth=16,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.VOLATILE)
    rclpy.init();pool=ThreadPoolExecutor(max_workers=1);node=Node('studio_gateway_'+run.name.replace('-','_')[:50]);pending={};sent=set();received=set();pubs={};last_heartbeat=0
    def action(msg):
        try:
            d=json.loads(msg.data);key=d['requestId'];ctx=pending.get(key)
            if not ctx or key in received or d.get('roomId')!=ctx['roomId'] or d.get('checkpointId')!=entry['id']:return
            if time.monotonic()-ctx['sentAt']>timeout:raise ValueError('stale_policy_action')
            if d.get('error'):raise ValueError(d['error'])
            actions=np.asarray(d['actions'],dtype=np.float32)
            if actions.shape!=(h,19) or not np.isfinite(actions).all():raise ValueError('invalid_ros2_action_chunk')
            target=directory/(key+'.reply.npz');tmp=target.with_suffix('.tmp')
            with tmp.open('wb') as f:np.savez(f,actions=actions)
            tmp.replace(target);received.add(key);pending.pop(key,None)
        except Exception as exc:
            if 'key' in locals() and key in pending:(directory/(key+'.error.json')).write_text(json.dumps({'error':str(exc)}));pending.pop(key,None)
    for room in ids:
        base=f'{prefix}/room_{room:03d}'
        pubs[room]={'state':node.create_publisher(JointState,base+'/joint_states',qos),'request':node.create_publisher(String,base+'/request',qos),**{cam:node.create_publisher(Image,base+'/camera/'+cam+'/image_raw',qos) for cam in CAMERAS}}
        node.create_subscription(String,base+'/actions',action,qos)
    adapter=None
    if not a.external_policy:
        adapter=Node('studio_policy_adapter_'+run.name.replace('-','_')[:40]);cache={};requests={};active=set();outputs={}
        port=json.loads((run/'model_http.ready.json').read_text())['port']
        def maybe(key):
            if key in active or key not in requests or not all(k in cache.get(key,{}) for k in ('state',*CAMERAS)):return
            active.add(key);req=requests.pop(key);obs=cache.pop(key)
            def infer():
                result=dict(requestId=key,roomId=req['roomId'],checkpointId=entry['id'])
                began=time.time();status(dict(stage='inferring',requestId=key,startedAt=began,roomId=req['roomId'],checkpointId=entry['id']))
                try:
                    buf=io.BytesIO();np.savez(buf,state=obs['state'],prompt=req['prompt'],_room=run.name+':'+str(req['roomId']),**{'image/'+cam:obs[cam] for cam in CAMERAS})
                    request=urllib.request.Request(f'http://127.0.0.1:{port}/infer',data=buf.getvalue(),method='POST')
                    with urllib.request.urlopen(request,timeout=timeout) as response:
                        with np.load(io.BytesIO(response.read()),allow_pickle=False) as d:result['actions']=d['actions'].tolist()
                except Exception as exc:result['error']='model_inference_failed:'+repr(exc)
                status(dict(stage='error' if 'error' in result else 'reply_received',requestId=key,startedAt=began,finishedAt=time.time(),latencySeconds=time.time()-began,error=result.get('error'),roomId=req['roomId'],checkpointId=entry['id']))
                with (run/'inference_events.jsonl').open('a') as log:log.write(json.dumps(dict(unix=time.time(),latency_seconds=time.time()-began,requestId=key,error=result.get('error')))+'\n')
                msg=String();msg.data=json.dumps(result);outputs[req['roomId']].publish(msg)
            pool.submit(infer)
        def state(msg):
            key=msg.header.frame_id
            if list(msg.name)!=NAMES or len(msg.position)!=19:return
            cache.setdefault(key,{})['state']=np.asarray(msg.position,dtype=np.float32);maybe(key)
        def image(msg,cam):
            if msg.encoding!='rgb8' or msg.step!=msg.width*3:return
            key=msg.header.frame_id;cache.setdefault(key,{})[cam]=np.frombuffer(bytes(msg.data),dtype=np.uint8).reshape(msg.height,msg.width,3).copy();maybe(key)
        def request(msg):
            d=json.loads(msg.data)
            if d.get('checkpointId')!=entry['id'] or d.get('roomId') not in ids:return
            requests[d['requestId']]=d;maybe(d['requestId'])
        for room in ids:
            base=f'{prefix}/room_{room:03d}';outputs[room]=adapter.create_publisher(String,base+'/actions',qos)
            adapter.create_subscription(JointState,base+'/joint_states',state,qos)
            adapter.create_subscription(String,base+'/request',request,qos)
            for cam in CAMERAS:adapter.create_subscription(Image,base+'/camera/'+cam+'/image_raw',lambda msg,c=cam:image(msg,c),qos)
    def scan():
        nonlocal last_heartbeat
        if time.monotonic()-last_heartbeat>2:
            (run/'ros2.heartbeat.json').write_text(json.dumps(dict(heartbeat_unix=time.time(),requests=len(sent),responses=len(received),namespace=prefix,domain=86,pid=os.getpid())));last_heartbeat=time.monotonic()
        for key,ctx in list(pending.items()):
            if time.monotonic()-ctx['sentAt']>timeout:
                (directory/(key+'.error.json')).write_text(json.dumps({'error':'ROS2 action timeout; no fallback'}));pending.pop(key)
        for path in sorted(directory.glob('*.request.npz')):
            key=path.name.removesuffix('.request.npz')
            if key in sent:continue
            room=int(key.split('_')[0].removeprefix('room'))
            if room not in pubs:continue
            # Wait for subscribers so first observation cannot disappear during DDS discovery.
            if not all(pub.get_subscription_count() for pub in pubs[room].values()):continue
            with np.load(path,allow_pickle=False) as d:sample={k:d[k].copy() for k in d.files}
            stamp=node.get_clock().now().to_msg();j=JointState();j.header.stamp=stamp;j.header.frame_id=key;j.name=NAMES;j.position=np.asarray(sample['state'],dtype=float).tolist();pubs[room]['state'].publish(j)
            for cam in CAMERAS:
                arr=sample['image/'+cam];im=Image();im.header.stamp=stamp;im.header.frame_id=key;im.height=arr.shape[0];im.width=arr.shape[1];im.encoding='rgb8';im.step=im.width*3;im.data=arr.tobytes();pubs[room][cam].publish(im)
            msg=String();msg.data=json.dumps(dict(requestId=key,roomId=room,checkpointId=entry['id'],prompt=str(sample['prompt']),horizon=h,actionSpace='mobile19_absolute_v1',baseActuatorMask='fixed_episode_base'))
            pending[key]={'roomId':room,'sentAt':time.monotonic()};sent.add(key);pubs[room]['request'].publish(msg)
    node.create_timer(.02,scan);executor=MultiThreadedExecutor(num_threads=2);executor.add_node(node)
    if adapter:executor.add_node(adapter)
    (directory/'ready.json').write_text(json.dumps(dict(checkpoint_id=entry['id'],horizon=h,transport='ros2',namespace=prefix,domain=86)))
    (run/'ros2_topics.json').write_text(json.dumps(dict(namespace=prefix,domain=86,rooms=ids,observationTopics=['joint_states',*[f'camera/{c}/image_raw' for c in CAMERAS],'request'],actionTopic='actions',correlation='header.frame_id=requestId, roomId, checkpointId',stamp='ROS system clock at observation publication',units='joints rad, gripper full opening m, base m/m/rad',horizon=h),indent=2))
    try:
        while not (directory/'stop').exists():executor.spin_once(timeout_sec=.2)
    finally:executor.shutdown();pool.shutdown(wait=False,cancel_futures=True);node.destroy_node();adapter.destroy_node() if adapter else None;rclpy.shutdown()
if __name__=='__main__':main()
