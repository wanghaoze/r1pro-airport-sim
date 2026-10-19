"""Launch only owned model/ROS children; native evaluator manages this service."""
import json
import os
from pathlib import Path
import subprocess
import socket
import signal
import sys
import time

def serve(run):
    def interrupted(*_):raise KeyboardInterrupt('owned service shutdown')
    signal.signal(signal.SIGTERM,interrupted)
    run=Path(run);code=Path(__file__).resolve().parent;children=[];logs=[]
    env={**os.environ,'ROS_DOMAIN_ID':'86','ROS_LOCALHOST_ONLY':'1','ROS_AUTOMATIC_DISCOVERY_RANGE':'LOCALHOST'}
    # Never inherit the hardware discovery-server profile.
    for key in ('FASTRTPS_DEFAULT_PROFILES_FILE','FASTDDS_DEFAULT_PROFILES_FILE','ROS_DISCOVERY_SERVER'):env.pop(key,None)
    entry=json.loads((run/'checkpoints.json').read_text())[0];config=entry.get('modelConfig',{})
    def start(name,argv,cwd=None,extra=None):
        log=(run/(name+'.log')).open('ab');logs.append(log);p=subprocess.Popen(argv,cwd=cwd or code.parent,env={**env,**(extra or {})},stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT);children.append((name,p));return p
    request=json.loads((run/'request.json').read_text())['payload']
    shared=None
    if request.get('liveEvaluation'):
        from studio_reuse_service import find_service
        from studio_mse import ROOT
        shared=find_service(ROOT,entry)
        if shared and shared.get('actionSafetyMode','strict')!=request.get('actionSafetyMode','strict'):shared=None
        if shared:(run/'model_http.ready.json').write_text(json.dumps(shared))
    try:
        if not shared and entry.get('family')=='g05':
            cp=Path(config['checkpointPath'])
            if cp.stat().st_size!=config['checkpointSize'] or cp.stat().st_mtime_ns!=config['checkpointMtimeNs']:raise ValueError('G0.5 checkpoint changed since registration')
            with socket.socket() as sock:
                if sock.connect_ex((config['host'],config['port']))==0:raise ValueError('G0.5 port already occupied; refusing an unverified server')
            model_code=Path(config['modelCode'])
            upstream=start('g05_server',[config['modelPython'],str(model_code/'scripts/serve_policy_mem.py'),'--ckpt_path',str(cp),'--host','127.0.0.1','--port',str(config['port']),'--device','cuda:0','--action_steps','5','eval_embodiment=galaxea_r1pro'],cwd=model_code,extra={'PYTHONPATH':':'.join(str(model_code/x) for x in ('src','scripts','.')),'WANDB_MODE':'offline','MPLBACKEND':'Agg','OMP_NUM_THREADS':'4'})
            deadline=time.monotonic()+1200
            while True:
                if upstream.poll() is not None:raise RuntimeError('G0.5 checkpoint load failed; inspect g05_server.log')
                with socket.socket() as sock:
                    if sock.connect_ex((config['host'],config['port']))==0:break
                if time.monotonic()>deadline:raise TimeoutError('G0.5 initialization timeout')
                time.sleep(1)
        model_python=config.get('modelPython') if entry.get('family')=='groot' else sys.executable
        model=None if shared else start('model_http',[model_python,str(code/'studio_model_http.py'),'--run',str(run)])
        deadline=time.monotonic()+1200
        while not (run/'model_http.ready.json').exists():
            if model is not None and model.poll() is not None:raise RuntimeError('ROS2 model service initialization failed')
            if time.monotonic()>deadline:raise TimeoutError('model initialization timeout')
            time.sleep(1)
        ros_python=os.environ.get('STUDIO_ROS_PYTHON','/home/michelle/miniconda3/envs/galaxea_ros_jazzy312/bin/python')
        # Source only the existing ROS environment; install nothing into system Python.
        start('ros2',['bash','-c','source /opt/ros/jazzy/setup.bash; exec "$1" "$2" --run "$3"','studio-ros2',ros_python,str(code/'studio_ros2_transport.py'),str(run)])
        while not (run/'policy/stop').exists():
            if any(p.poll() is not None for _,p in children):raise RuntimeError('ROS2 service child exited')
            time.sleep(.5)
    finally:
        for name,p in reversed(children):
            if p.poll() is None:p.terminate()
            try:rc=p.wait(timeout=15)
            except subprocess.TimeoutExpired:p.kill();rc=p.wait()
            (run/(name+'.exit.json')).write_text(json.dumps(dict(returncode=rc,actual_child_wait=True,pid=p.pid,endedAt=time.time())))
        for log in logs:log.close()
