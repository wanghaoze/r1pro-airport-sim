"""Validate native completed sources and freeze their three-action index.

This command never starts a trainer or turns diagnostic frames into data.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.isaac_dataset import freeze_corpus, export_action_clips, materialize_cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', required=True, type=Path)
    parser.add_argument('--episodes', type=Path,
                        help='JSON list of native closed episode directories')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--mode', choices=['freeze', 'clips', 'cache'], default='freeze')
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text())
    if args.mode == 'freeze':
        if args.episodes is None:
            parser.error('--episodes required for freeze')
        result = freeze_corpus(json.loads(args.episodes.read_text()), registry, args.output)
        result = {key: result[key] for key in ['full_sources', 'action_segments',
            'native_camera_files', 'counts', 'data_index_ready', 'training_cache_ready']}
    else:
        if args.manifest is None:
            parser.error('--manifest required for clips/cache')
        result = (export_action_clips if args.mode == 'clips' else materialize_cache)(
            args.manifest, registry, args.output)
        result = dict(stage=args.mode, completed=True, output=str(args.output))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
