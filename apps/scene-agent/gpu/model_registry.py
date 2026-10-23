import hashlib
from pathlib import Path
from studio_backend import ROOT,read

def registry_path():return ROOT/'configs/studio_ros2_models.json'

def models():return read(registry_path(),read(Path(__file__).with_name('ros2_models.json'))).get('models',[])

def entries():
    result=[]
    for m in models():
        if not m.get('enabled'):continue
        if m.get('family') not in ('g05','groot') or m.get('actionSpace')!='joint_absolute':raise ValueError('Unsupported model action space; no implicit IK')
        if m.get('gripperUnit') not in ('mm','m','percent80') or type(m.get('horizon'))!=int or not 1<=m['horizon']<=40:raise ValueError('Explicit model units and horizon required')
        if m.get('host') not in ('127.0.0.1','localhost') or type(m.get('port'))!=int:raise ValueError('Model server must be on the workstation loopback')
        result.append(dict(id=m['id'],label=m['label'],updates=0,source='external_model_endpoint',closed=True,family=m['family'],modelConfig=m,modelConfigSha256=hashlib.sha256(__import__('json').dumps(m,sort_keys=True).encode()).hexdigest()))
    return result

def summary():return [dict(id=m['id'],family=m['family'],label=m['label'],configured=m.get('enabled',False),status=m.get('status','Configured; simulation not yet measured')) for m in models()]
