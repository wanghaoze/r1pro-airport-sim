"""Local workstation model registration. Reads weights' metadata, never unpickles weights."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

def configure(data):
    root=Path(os.environ['AIRPORT_PROJECT']);path=Path(data.get('checkpointPath','')).expanduser()
    if not path.is_absolute() or not path.exists():raise ValueError('Checkpoint must be an existing absolute workstation path')
    path=path.resolve();family=data.get('family')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'gpu'))
    from studio_backend import checkpoints
    if family=='pi05':
        cp=next((c for c in checkpoints() if c.get('checkpoint') and Path(c['checkpoint']).resolve()==path),None)
        if not cp:raise ValueError('π0.5 path requires a closed registered training receipt and its own normalization assets')
        return dict(id=cp['id'],label=cp['label'],status='Registered π0.5 checkpoint; select it under Model checkpoint')
    if family not in ('g05','groot'):raise ValueError('Choose pi05, g05 or groot')
    config_path=root/'configs/studio_ros2_models.json';default=Path(__file__).resolve().parents[1]/'gpu/ros2_models.json'
    registry=json.loads((config_path if config_path.exists() else default).read_text())
    name=family+'_'+hashlib.sha256(str(path).encode()).hexdigest()[:16]
    base=dict(id=name,family=family,label=f'{"Galaxea G0.5" if family=="g05" else "GR00T"} · {path.parent.name}/{path.name}',checkpointPath=str(path),enabled=False,host='127.0.0.1',port=9085 if family=='g05' else 5555)
    if family=='g05':
        import yaml
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from r1pro_teleop.vla.g05_protocol import validate_shape_meta
        directory=path.parent if (path.parent/'.hydra/config.yaml').exists() else path.parent.parent
        required=[directory/'.hydra/config.yaml',directory/'dataset_stats.json',directory/'action_tokenizer.pt',directory/'hf_processor']
        if not all(p.exists() for p in required):raise ValueError('G0.5 requires neighboring .hydra/config.yaml, dataset_stats.json, action_tokenizer.pt and hf_processor')
        config=yaml.safe_load(required[0].read_text());shape=config['data']['processors']['galaxea_r1pro']['shape_meta']
        validate_shape_meta(shape)
        code=next((p/'code' for p in directory.parents if (p/'code/scripts/serve_policy_mem.py').exists()),None)
        base.update(horizon=1,actionSpace='joint_absolute',gripperUnit=data.get('gripperUnit','unconfirmed'),modelCode=str(code) if code else None,
            modelPython=data.get('modelPython') or str(code/'.venv/bin/python') if code else None,
            metadataSha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in required[:2]},
            status='Checkpoint metadata verified. Endpoint must load successfully before simulation.',enabled=bool(code) and data.get('gripperUnit') in ('mm','m','percent80'),trainingHz=30,simulationHz=20,temporalComparison='30 Hz training / 20 Hz diagnostic; not timing-matched',checkpointSize=path.stat().st_size,checkpointMtimeNs=path.stat().st_mtime_ns)
    else:
        contract=path/'studio_model.json'
        if not contract.exists():base.update(status='Path saved. Add studio_model.json with joint_absolute mapping, gripperUnit, horizon and modelPython; pretrained EEF output is unsupported.')
        else:
            metadata=json.loads(contract.read_text())
            if metadata.get('actionSpace')!='joint_absolute':raise ValueError('GR00T EEF output requires a separately approved controller; no implicit IK')
            for key in ('gripperUnit','horizon','cameraKeys','stateKeys','modelPython'):
                if key not in metadata:raise ValueError('Missing GR00T contract key: '+key)
                base[key]=metadata[key]
            base.update(actionSpace='joint_absolute',enabled=True,status='Joint checkpoint configured; native result not yet measured')
            base['actionKeys']=metadata.get('actionKeys',base['stateKeys']);base['embodimentTag']=metadata.get('embodimentTag','new_embodiment')
    if base.get('gripperUnit') not in (None,'mm','m','percent80','unconfirmed'):raise ValueError('Gripper mapping must be m, mm or percent80')
    if base.get('gripperUnit')=='unconfirmed':base['status']='Checkpoint path verified. Confirm gripper mapping before running.'
    registry['models']=[m for m in registry['models'] if m['id']!=name]+[base]
    config_path.parent.mkdir(parents=True,exist_ok=True);tmp=config_path.with_suffix('.tmp');tmp.write_text(json.dumps(registry,indent=2));tmp.replace(config_path)
    return base

if __name__=='__main__':
    try:print(json.dumps(configure(json.load(sys.stdin))))
    except Exception as exc:print(json.dumps({'error':str(exc)}));sys.exit(1)
