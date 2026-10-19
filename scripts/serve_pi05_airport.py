"""Serve an actually saved airport pi0.5 fine-tune using official openpi.

Example: python scripts/serve_pi05_airport.py --training-status RUN/training_status.json
No fallback to pi05_base, guessed checkpoint names, or random model is allowed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.training import TrainingSpec, register_openpi_config


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_milestone_data(status, spec):
    """A saved update must belong to the complete, immutable train corpus."""
    dataset = Path(spec.dataset_root).resolve()
    cache = Path(spec.run_dir).resolve() / 'data_cache' / 'cache_manifest.json'
    if Path(status.get('cache_manifest', '')).resolve() != cache:
        raise ValueError('Milestone cache is outside the declared training run')
    acceleration = Path(spec.run_dir).resolve() / 'acceleration_spec.json'
    if Path(status.get('acceleration_spec', '')).resolve() != acceleration:
        raise ValueError('Milestone acceleration specification is outside its training run')
    paths = {
        'cache_manifest_sha256': cache,
        'acceleration_spec_sha256': acceleration,
        'dataset_training_manifest_sha256': dataset / 'airport_training_manifest.json',
        'dataset_source_manifest_sha256': dataset / 'whole_action_source_manifest.jsonl',
    }
    for key, file in paths.items():
        if not file.is_file() or status.get(key) != _file_hash(file):
            raise ValueError('Milestone training input hash disagrees: ' + key)
    manifest = json.loads(paths['dataset_training_manifest_sha256'].read_text(encoding='utf8'))
    if (manifest.get('dataset_ready') is not True or manifest.get('split') != 'train' or
            manifest.get('prompt_mode') != spec.prompt_mode or
            manifest.get('repo_id') != spec.dataset_repo_id or
            manifest.get('source_manifest_sha256') != status['dataset_source_manifest_sha256']):
        raise ValueError('Milestone requires the ready train split and matching language contract')
    if spec.prompt_mode == 'single_tray_action3_v1':
        cache_metadata = json.loads(cache.read_text(encoding='utf8'))
        for metadata in (status, manifest, cache_metadata):
            if (metadata.get('base_mode') != 'fixed_front' or
                    metadata.get('base_actuated') is not False or
                    metadata.get('model_action_mask') != [True] * 16 + [False] * 3):
                raise ValueError('Single-tray checkpoint/cache/dataset fixed-base mask disagreement')
    if spec.prompt_mode == 'three_table_single_tray_action3_v1':
        from r1pro_teleop.vla.training_cache import validate_three_table_metadata
        for metadata in (status, manifest, json.loads(cache.read_text(encoding='utf8'))):
            validate_three_table_metadata(metadata)
    return [{'path': str(file), 'sha256': status[key]} for key, file in paths.items()]


def verify_training_checkpoint(status_path):
    """Verify provenance and file content before importing/loading the model."""
    path = Path(status_path).resolve()
    status = json.loads(path.read_text(encoding='utf-8'))
    milestone = status.get('schema') == 'airport_pi05_training_milestone/1'
    required_state = 'milestone_checkpoint' if milestone else 'checkpoint_saved'
    if (status.get('status') != required_state or status.get('checkpoint_verified') is not True or
            status.get('model') != 'pi05' or status.get('fps') != 20 or
            status.get('action_semantics') != 'absolute_mobile19' or
            status.get('source') != 'simulation/program_generated'):
        raise ValueError('A completed, verified airport pi05 training status is required')
    steps = status.get('training_steps')
    if type(steps) is not int or steps <= 0:
        raise ValueError('Fine-tuned weights require positive completed training steps')
    spec = TrainingSpec(**status['spec'])
    from r1pro_teleop.vla.prompts import validate_prompt_mode
    validate_prompt_mode(spec.prompt_mode)
    if status.get('prompt_mode', 'legacy') != spec.prompt_mode:
        raise ValueError('Training prompt mode disagrees with its verified specification')
    checkpoint = Path(status['checkpoint']).resolve()
    expected = Path(spec.run_dir).resolve() / 'checkpoints' / spec.name / 'training'
    if checkpoint.parent != expected or not checkpoint.name.isdecimal():
        raise ValueError('Checkpoint is not inside the declared airport training run')
    checkpoint_step = int(checkpoint.name)
    # openpi saves zero-based iteration indices; step 0 is allowed only if an
    # actual one-step trainer completed, with train_state and checkpoint assets.
    if milestone:
        planned = status.get('planned_total_steps')
        completed = status.get('actual_completed_updates')
        if (type(planned) is not int or type(completed) is not int or
                type(spec.num_train_steps) is not int or
                planned != spec.num_train_steps or completed != steps or
                not 0 < completed <= planned or checkpoint_step != completed - 1):
            raise ValueError('Milestone completed updates and total training budget disagree')
        data_bindings = _verify_milestone_data(status, spec)
    if (status.get('checkpoint_step') != checkpoint_step or
            (not milestone and steps != spec.num_train_steps) or checkpoint_step >= steps):
        raise ValueError('Training and saved checkpoint steps disagree')
    if checkpoint == Path(spec.base_params).resolve():
        raise ValueError('Base pretrained weights cannot be advertised as fine-tuned')
    for item in ('params', 'train_state'):
        folder = checkpoint / item
        if not folder.is_dir() or not any(p.is_file() and p.stat().st_size for p in folder.rglob('*')):
            raise ValueError('Incomplete official training checkpoint: ' + item)
    norms = checkpoint / 'assets' / spec.dataset_repo_id / 'norm_stats.json'
    if not norms.is_file() or norms.stat().st_size == 0:
        raise ValueError('Checkpoint lacks its own training normalization assets')
    if milestone and status.get('norm_sha256') != _file_hash(norms):
        raise ValueError('Milestone checkpoint normalization hash disagrees')
    # Successful restore below is the definitive checkpoint completeness check.
    # This inventory binds identity to actual parameter bytes and their matching
    # normalization, rather than a caller-provided friendly name.
    files = sorted(p for p in (checkpoint / 'params').rglob('*') if p.is_file()) + [norms]
    inventory = [{'path': p.relative_to(checkpoint).as_posix(), 'sha256': _file_hash(p),
                  'bytes': p.stat().st_size} for p in files]
    identity_material = {'training_status_sha256': _file_hash(path), 'files': inventory}
    if milestone:
        # Bind optimizer/state bytes too. Milestones can be served after a clean
        # trainer exit, while retaining evidence for exact later restoration.
        identity_material['resume_state_files'] = [
            {'path': p.relative_to(checkpoint).as_posix(), 'sha256': _file_hash(p),
             'bytes': p.stat().st_size}
            for p in sorted((checkpoint / 'train_state').rglob('*')) if p.is_file()]
        identity_material['training_input_bindings'] = data_bindings
    digest = hashlib.sha256(json.dumps(identity_material, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    identity = {'checkpoint_id': 'sha256:' + digest, 'checkpoint_path': str(checkpoint),
                'prompt_mode': spec.prompt_mode,
                'training_status_path': str(path), 'training_steps': steps,
                'checkpoint_step': checkpoint_step, **identity_material}
    if milestone:
        identity.update(schema=status['schema'], actual_completed_updates=steps,
                        planned_total_steps=planned, training_complete=(steps == planned))
    return spec, checkpoint, identity


def load_airport_policy(status_path, *, denoising_steps=10):
    # The frozen official pi0.5 sampler defaults to ten Euler steps. Alternate
    # counts are explicit inference experiments, not new trained checkpoints.
    if type(denoising_steps) is not int or denoising_steps not in (10, 20, 30, 50):
        raise ValueError('denoising_steps must be one of 10, 20, 30, 50')
    spec, checkpoint, identity = verify_training_checkpoint(status_path)
    config = register_openpi_config(spec)
    from openpi.policies import policy_config
    # Official factory restores real params, checkpoint-local norm stats and
    # AirportInputs/AirportOutputs with model transforms (internal padding32).
    if denoising_steps == 10:
        policy = policy_config.create_trained_policy(config, checkpoint)
    else:
        policy = policy_config.create_trained_policy(
            config, checkpoint, sample_kwargs={'num_steps': denoising_steps})
        if getattr(policy, '_sample_kwargs', {}).get('num_steps') != denoising_steps:
            raise ValueError('Official policy did not retain the requested denoising steps')
    metadata = {'checkpoint_id': identity['checkpoint_id'], 'action_width': 19,
                'action_horizon': spec.action_horizon,
                'action_space': 'mobile19_absolute_v1', 'control_hz': 20, 'model': 'pi05',
                'fine_tuned': True, 'training_steps': identity['training_steps'],
                'checkpoint_step': identity['checkpoint_step'],
                'source': 'simulation/program_generated',
                'prompt_mode': spec.prompt_mode,
                'denoising_steps': denoising_steps, 'sampler': 'official_pi05_euler'}
    if spec.prompt_mode == 'single_tray_action3_v1':
        metadata.update(base_mode='fixed_front', base_actuated=False,
                        model_action_mask=[True] * 16 + [False] * 3,
                        action_space='fixed_front_arm16_zero_padded19',
                        control_mask_applied=True, raw_action_output_field='raw_actions')
    if spec.prompt_mode == 'three_table_single_tray_action3_v1':
        from r1pro_teleop.vla.data_three_table_single_tray import RULE_REVISION, FINAL_ORIENTATION_DEFINITION
        metadata.update(task_profile=spec.prompt_mode,task_rule_revision=RULE_REVISION,final_orientation_definition=FINAL_ORIENTATION_DEFINITION,base_mode='planar_mobile_table_front',base_actuated=True,
                        model_action_mask=[True]*19,action_space='mobile19_absolute_v1',
                        control_mask_applied=False,raw_action_output_field='raw_actions',
                        route_goal_observation_policy='fixed_registered_rear_to_front_left_route')
    if identity.get('schema') == 'airport_pi05_training_milestone/1':
        metadata.update(training_complete=identity['training_complete'],
                        actual_completed_updates=identity['actual_completed_updates'],
                        planned_total_steps=identity['planned_total_steps'],
                        checkpoint_status_schema=identity['schema'])
    return policy, metadata, identity


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--training-status', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--denoising-steps', type=int, choices=(10, 20, 30, 50), default=10,
                        help='Explicit official sampler count; affects inference latency, not weight identity')
    parser.add_argument('--identity-only', action='store_true', help='Hash verified files without loading a model or advertising a server')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('port must be in [1,65535]')
    if args.identity_only:
        _, _, identity = verify_training_checkpoint(args.training_status)
        print(json.dumps(identity, indent=2), flush=True)
        return
    policy, metadata, identity = load_airport_policy(args.training_status, denoising_steps=args.denoising_steps)
    print(json.dumps({'metadata': metadata, 'identity': identity}, indent=2), flush=True)
    from openpi.serving.websocket_policy_server import WebsocketPolicyServer
    WebsocketPolicyServer(policy=policy, host=args.host, port=args.port,
                          metadata=metadata).serve_forever()


if __name__ == '__main__':
    main()
