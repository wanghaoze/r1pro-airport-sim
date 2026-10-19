"""Convert verified train spans to a new LeRobot v2 pi0.5 training dataset."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.data_lerobot import materialize_lerobot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--repo-id', required=True)
    parser.add_argument('--max-scenes', type=int)
    parser.add_argument('--include-reviewed-local', action='store_true')
    args = parser.parse_args()
    print(json.dumps(materialize_lerobot(args.manifest, args.destination, args.repo_id,
        max_scenes=args.max_scenes, include_reviewed_local=args.include_reviewed_local)))


if __name__ == '__main__':
    main()
