"""Collect a fresh observed three-table task; no training/model launch."""
from pathlib import Path
import sys,argparse,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_3table.collect import collect
from r1pro_teleop.airport_fsm.contracts import json_default
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scene',required=True);p.add_argument('--config',required=True);p.add_argument('--push-reference-scene',required=True);p.add_argument('--confirmation-rule');p.add_argument('--no-axis-feedback',action='store_true');p.add_argument('--output',required=True);a=p.parse_args()
r=collect(a.scene,a.config,a.push_reference_scene,a.output,disable_axis_feedback=a.no_axis_feedback,confirmation_rule=json.loads(Path(a.confirmation_rule).read_text()) if a.confirmation_rule else None);print(json.dumps(r,default=json_default));raise SystemExit(0 if r['task_completed'] else 2)
