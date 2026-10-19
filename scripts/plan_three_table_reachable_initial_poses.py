"""Explicit bounded random-initial-pose qualification; never starts physics/training."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_3table.initial_pose_preflight import collect_plan

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--options', required=True)
    a = p.parse_args()
    raise SystemExit(0 if collect_plan(json.loads(Path(a.options).read_text())) else 2)
