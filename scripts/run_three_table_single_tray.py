"""First continuous legacy opposed-pick/place diagnostic; not training data."""
from pathlib import Path
import sys,json,argparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_3table.control import empty_motion_diagnostic
from r1pro_teleop.airport_fsm.contracts import Config,json_default
parser=argparse.ArgumentParser();parser.add_argument('--scene',required=True);parser.add_argument('--output',required=True)
parser.add_argument('--grasp-stagger',type=float,choices=(0.,.12,.16),default=0.)
parser.add_argument('--approximate-planning',action='store_true')
parser.add_argument('--config',help='Actual source Config JSON; used unchanged, without teacher_config overrides')
args=parser.parse_args();manifest=json.loads(Path(args.scene).read_text())
result=empty_motion_diagnostic(manifest,Path(args.output),cfg=Config.load(args.config) if args.config else None,
    grasp_stagger=args.grasp_stagger,approximate_planning=args.approximate_planning)
print(json.dumps({k:v for k,v in result.items() if k!='final_observation'},default=json_default))
