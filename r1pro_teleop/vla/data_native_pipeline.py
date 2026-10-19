"""Supervise a new immutable native-video training conversion on the server."""
from pathlib import Path
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--collection', required=True)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--scenes', type=int, default=16)
    parser.add_argument('--tag', default='native16', help='New immutable manifest/dataset/status suffix')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        raise ValueError('invalid_pipeline_tag')
    base, release = Path(args.base), Path(args.release)
    output = base / 'runs/vla_20261001'
    status_path = output / f'{args.tag}_conversion_status.json'
    manifest = output / f'segments_{args.tag}.jsonl'
    repo_id = f'airport/pi05_{args.tag}'
    destination = output / 'lerobot' / repo_id
    def status(stage, **details):
        record = {'stage': stage, 'pid': os.getpid(), 'updated_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'release': str(release), 'manifest': str(manifest), 'destination': str(destination), **details}
        temporary = status_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2), encoding='utf-8')
        temporary.replace(status_path)
        print(json.dumps(record), flush=True)
    env = dict(os.environ, HF_HOME=str(base / 'resources/hf_cache'),
               HF_LEROBOT_HOME=str(output / 'lerobot'), OPENPI_DATA_HOME=str(base / 'resources/openpi_cache'),
               OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    try:
        if manifest.exists() or destination.exists():
            raise FileExistsError('refuse_existing_manifest_or_dataset')
        status('waiting_native')
        while True:
            native_status = output / 'native_status.json'
            if native_status.exists():
                native = json.loads(native_status.read_text())
                if native.get('status') != 'complete' or native.get('rendered') != args.scenes or native.get('selected') != args.scenes:
                    raise ValueError('native_batch_not_complete:' + json.dumps(native))
                break
            time.sleep(30)
        references = output / 'video_references.json'
        refs = json.loads(references.read_text())
        if len(refs) != args.scenes * 4 or len({ref['trace'] for ref in refs}) != args.scenes:
            raise ValueError('native_reference_coverage_mismatch')
        status('preparing_manifest', native=native)
        subprocess.run([args.python, str(release / 'scripts/prepare_vla_dataset.py'),
            '--collection', args.collection, '--output', str(manifest),
            '--video-references', str(references), '--verify-videos'], cwd=release, env=env, check=True)
        status('converting_lerobot')
        subprocess.run([args.python, str(release / 'scripts/convert_vla_lerobot.py'),
            '--manifest', str(manifest), '--destination', str(destination),
            '--repo-id', repo_id, '--max-scenes', str(args.scenes)],
            cwd=release, env=env, check=True)
        training = json.loads((destination / 'airport_training_manifest.json').read_text())
        info = json.loads((destination / 'meta/info.json').read_text())
        scenes = {episode['scene_id'] for episode in training['episodes']}
        frames = sum(episode['frames'] for episode in training['episodes'])
        if len(scenes) != args.scenes or info['total_frames'] != frames or info['total_episodes'] != len(training['episodes']):
            raise ValueError('converted_dataset_totals_mismatch')
        encoding = training['training_video_encoding_verification']
        if encoding.get('verified') is not True or encoding.get('actual_codec') != 'h264':
            raise ValueError('converted_codec_not_verified')
        status('complete', scenes=sorted(scenes), frames=frames, episodes=len(training['episodes']),
               video_encoding=encoding, official_loader=training['official_loader_every_episode_first_last'])
    except BaseException as exc:
        status('failed', error=repr(exc), traceback=traceback.format_exc())
        raise


if __name__ == '__main__':
    main()
