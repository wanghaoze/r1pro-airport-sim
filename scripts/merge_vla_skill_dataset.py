"""Create a new skill-contiguous derivative without rewriting source data."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.data_skill_merge import materialize_skill_dataset


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source-dataset',required=True)
    p.add_argument('--destination',required=True)
    p.add_argument('--repo-id',required=True)
    p.add_argument('--manifest-output',required=True)
    p.add_argument('--scene-id',action='append',help='Explicit fixture/subset only; default all source scenes')
    args=p.parse_args()
    print(json.dumps(materialize_skill_dataset(args.source_dataset,args.destination,args.repo_id,
                                               args.manifest_output,scene_ids=args.scene_id)))


if __name__=='__main__':main()
