"""Explicit nonproduction pi05 checkpoint serving for diagnostic physics smoke.

Formal evaluation's fine-tuned metadata verifier deliberately rejects this server.
"""
from pathlib import Path
import argparse,hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.training import TrainingSpec,register_openpi_config


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def verify_diagnostic_checkpoint(status_path):
    status_path=Path(status_path).resolve();status=json.loads(status_path.read_text())
    if (status.get('schema')!='airport_pi05_training_diagnostic/1' or status.get('status')!='diagnostic_checkpoint' or
        status.get('checkpoint_verified') is not True or status.get('training_complete') is not False or
        status.get('prompt_mode')!='task_complete_action8_v1' or status.get('model')!='pi05' or
        status.get('fps')!=20 or status.get('action_semantics')!='absolute_mobile19' or
        status.get('source')!='simulation/program_generated'):
        raise ValueError('Explicit saved diagnostic-only airport checkpoint required')
    updates=status.get('actual_completed_updates')
    if type(updates) is not int or updates<=0 or status.get('checkpoint_step')!=updates-1:
        raise ValueError('Diagnostic actual completed update identity differs')
    spec=TrainingSpec(**status['spec']);checkpoint=Path(status['checkpoint']).resolve()
    if (spec.prompt_mode!='task_complete_action8_v1' or
        checkpoint!=Path(spec.run_dir).resolve()/'checkpoints'/spec.name/'training'/str(updates-1)):
        raise ValueError('Diagnostic checkpoint path/spec differs')
    inventory=[]
    for folder in ('params','train_state'):
        files=sorted(p for p in (checkpoint/folder).rglob('*') if p.is_file())
        if not files or not any(p.stat().st_size for p in files):raise ValueError('Incomplete diagnostic '+folder)
        inventory.extend(dict(path=p.relative_to(checkpoint).as_posix(),sha256=sha(p),bytes=p.stat().st_size) for p in files)
    norms=checkpoint/'assets'/spec.dataset_repo_id/'norm_stats.json'
    if sha(norms)!=status.get('norm_sha256'):raise ValueError('Diagnostic normalization differs')
    cache=Path(status['cache_manifest'])
    if sha(cache)!=status['cache_manifest_sha256']:raise ValueError('Diagnostic train-cache provenance changed')
    inventory.append(dict(path=norms.relative_to(checkpoint).as_posix(),sha256=sha(norms),bytes=norms.stat().st_size))
    material=dict(training_status_sha256=sha(status_path),checkpoint_files=inventory,
        cache_manifest_sha256=status['cache_manifest_sha256'],diagnostic=True)
    checkpoint_id='sha256:'+hashlib.sha256(json.dumps(material,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return spec,checkpoint,dict(checkpoint_id=checkpoint_id,actual_completed_updates=updates,
        checkpoint_step=updates-1,training_status=str(status_path),**material)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnostic-status',required=True);parser.add_argument('--identity-output',required=True)
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8767)
    args=parser.parse_args(argv)
    spec,checkpoint,identity=verify_diagnostic_checkpoint(args.diagnostic_status)
    config=register_openpi_config(spec)
    from openpi.policies import policy_config
    policy=policy_config.create_trained_policy(config,checkpoint)
    metadata=dict(checkpoint_id=identity['checkpoint_id'],action_width=19,action_horizon=spec.action_horizon,
        action_space='mobile19_absolute_v1',control_hz=20,model='pi05',prompt_mode=spec.prompt_mode,
        fine_tuned=False,diagnostic=True,formal_evaluation_eligible=False,training_complete=False,
        actual_completed_updates=identity['actual_completed_updates'],training_steps=identity['actual_completed_updates'],
        checkpoint_step=identity['checkpoint_step'],source='simulation/program_generated')
    with Path(args.identity_output).open('x') as stream:json.dump(dict(identity=identity,metadata=metadata),stream,indent=2)
    print(json.dumps(metadata),flush=True)
    from openpi.serving.websocket_policy_server import WebsocketPolicyServer
    WebsocketPolicyServer(policy,host=args.host,port=args.port,metadata=metadata).serve_forever()


if __name__=='__main__':main()
