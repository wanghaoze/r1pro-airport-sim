"""Project cache and bounded milestone training; no automatic evaluation service."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.training import TrainingSpec
from r1pro_teleop.vla.training_cache import compute_train_only_norm,build_cache
from r1pro_teleop.vla.training_accelerated import train_to_milestone

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--spec',required=True);parser.add_argument('--parent-status',required=True)
 parser.add_argument('--prepare-cache',action='store_true');parser.add_argument('--stop-after',type=int)
 parser.add_argument('--resume',action='store_true');parser.add_argument('--diagnostic-smoke',action='store_true')
 args=parser.parse_args();spec=TrainingSpec(**json.loads(Path(args.spec).read_text()))
 if args.prepare_cache:
  print(json.dumps(compute_train_only_norm(spec,diagnostic_fixture=args.diagnostic_smoke)),flush=True)
  print(json.dumps(build_cache(spec,Path(spec.run_dir)/'data_cache',diagnostic_fixture=args.diagnostic_smoke)),flush=True)
 else:
  if args.stop_after is None:parser.error('--stop-after is required for actual training')
  print(json.dumps(train_to_milestone(spec,parent_status=args.parent_status,stop_after=args.stop_after,resume=args.resume,diagnostic_smoke=args.diagnostic_smoke),default=str),flush=True)
if __name__=='__main__':main()
