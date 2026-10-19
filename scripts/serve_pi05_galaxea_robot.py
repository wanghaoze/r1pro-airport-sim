"""New workstation endpoint for unchanged Galaxea robot run.py."""
import argparse, dataclasses, hashlib, json, os, sys, time
from pathlib import Path
import numpy as np

ROOT = Path('/home/michelle/haoze/r1pro-airport-sim')
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(ROOT/'third_party/openpi/src'), str(ROOT/'third_party/openpi/packages/openpi-client/src')]
from r1pro_teleop.vla.galaxea_robot_adapter import observation, command


def main():
    p = argparse.ArgumentParser(); p.add_argument('--config', type=Path, required=True); args = p.parse_args()
    cfg = json.loads(args.config.read_text()); run = args.config.parent
    def permitted():
        control=json.loads(Path(cfg['control_file']).read_text())
        if control.get('stopped', True):
            raise RuntimeError('VLA command STOP latched; restart robot client after deliberate rearm')
        heartbeat=json.loads(Path(cfg['control_file']).with_name('operator_heartbeat.json').read_text())
        if not 0 <= time.time()-heartbeat['unix'] <= 1.0:
            raise RuntimeError('Operator keyboard heartbeat missing/stale; refusing command')
        return control['generation']
    import fcntl
    lock = (run/'server.lock').open('a'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    from r1pro_teleop.vla.training import TrainingSpec, build_openpi_config
    from r1pro_teleop.vla.training_accelerated import vision_parameter_filter
    from flax import nnx
    from openpi.policies import policy_config
    from openpi.serving.websocket_policy_server import WebsocketPolicyServer
    from openpi_client.image_tools import resize_with_pad
    status = json.loads(Path(cfg['training_status']).read_text())
    if status['stage'] != 'trained' or status['updates'] != 10000:
        raise ValueError('Expected verified completed 10000-update model')
    cp = Path(status['checkpoint']); spec = TrainingSpec(**status['spec'])
    config = build_openpi_config(spec)
    config = dataclasses.replace(config, freeze_filter=nnx.Any(config.freeze_filter, vision_parameter_filter))
    if cfg['gripper_range_mm'] != [0,80]:raise ValueError('Expected user-approved 0..80mm bounds')
    identity = dict(checkpoint=str(cp), updates=status['updates'], metadata_sha256=hashlib.sha256((cp/'_CHECKPOINT_METADATA').read_bytes()).hexdigest(), norm_sha256={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in (cp/'assets').rglob('*.json')}, model=cfg['model'], pid=os.getpid(), input_gripper_unit='mm', output_gripper_unit='mm', model_gripper_unit='m', gripper_range_mm=cfg['gripper_range_mm'],gripper_processing='user_authorized_saturation_not_rescaling',control_hz=20, executed_parts=['left_arm','left_gripper','right_arm','right_gripper'], teacher_fallback=False)
    model = policy_config.create_trained_policy(config, cp, sample_kwargs={'num_steps':10})
    # Compile using a recorded observation; never publish robot commands for warmup.
    from r1pro_teleop.vla.real_sim_data import Cache
    cache = Cache(Path(cfg['training_status']).parents[1]/'cache/test')
    sample = cache.get(0); model.infer({k:v for k,v in sample.items() if k!='actions'})
    count = 0
    class Adapter:
        def reset(self): self.chunk=None; self.cursor=0; self.task=None
        def infer(self, obs):
            nonlocal count
            generation=permitted()
            sample = observation(obs, resize_with_pad)
            if self.chunk is None or self.cursor >= cfg['execute_steps'] or self.task != sample['prompt']:
                self.chunk = np.asarray(model.infer(sample)['actions'])[:, :19]
                if self.chunk.shape != (20,19) or not np.isfinite(self.chunk).all(): raise ValueError('Invalid model chunk')
                self.cursor=0; self.task=sample['prompt']
                np.savez_compressed(run/f'raw_chunk_{count:08d}.npz', actions=self.chunk, state=sample['state'], prompt=self.task)
            if permitted()!=generation:
                self.reset()
                raise RuntimeError('Operator control changed during inference; refusing command')
            row = self.chunk[self.cursor].copy(); raw_command=command(row)
            action = command(row,cfg['gripper_range_mm']); self.cursor+=1; count+=1
            clipping={k:dict(raw_mm=raw_command[k].tolist(),submitted_mm=action[k].tolist(),clipped=bool(np.any(raw_command[k]!=action[k]))) for k in ['left_gripper','right_gripper']}
            with (run/'commands.jsonl').open('a') as f:
                f.write(json.dumps(dict(sequence=count,unix=time.time(),task=self.task,raw_action=row.tolist(),returned_action={k:v.tolist() for k,v in action.items()},gripper_clipping=clipping,robot_filter_expected_on_client=True))+'\n')
            return dict(action=action,gripper_clipping=clipping, need_obs=True, checkpoint_id=identity['metadata_sha256'], model=cfg['model'])
    adapter=Adapter();adapter.reset()
    class Server(WebsocketPolicyServer):
        busy=False
        async def _handler(self, websocket):
            if self.busy:
                await websocket.close(code=1013,reason='One robot client per model endpoint'); return
            self.busy=True;adapter.reset()
            try: await super()._handler(websocket)
            finally: adapter.reset();self.busy=False
    identity.update(stage='ready_operator_stop_latched',control_file=cfg['control_file'],ready_unix=time.time());(run/'server_status.json').write_text(json.dumps(identity,indent=2))
    print(json.dumps(identity),flush=True)
    Server(adapter,host=cfg['host'],port=cfg['port'],metadata=identity).serve_forever()


if __name__=='__main__': main()
