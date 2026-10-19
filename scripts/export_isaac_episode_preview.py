"""Export only a real fully-qualified source; this is not a training batch."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.isaac_dataset import export_episode_preview


def main():
    p=argparse.ArgumentParser();p.add_argument('--episode',required=True,type=Path)
    p.add_argument('--registry',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    result=export_episode_preview(a.episode,json.loads(a.registry.read_text()),a.output)
    print(json.dumps({k:v for k,v in result.items() if k!='segments'}))


if __name__=='__main__':main()
