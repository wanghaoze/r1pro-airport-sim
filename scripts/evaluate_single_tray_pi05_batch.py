"""Explicit new-task milestone protocol; GPU execution requires --execute."""
from pathlib import Path
import argparse,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_lab.evaluation_batch import run_batch


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('spec','milestone','protocol','out'):p.add_argument('--'+key,required=True,type=Path)
    p.add_argument('--model-python',default=sys.executable);p.add_argument('--sim-python',default=sys.executable)
    p.add_argument('--gpu-uuid');p.add_argument('--egl-device',type=int,choices=(0,1),default=1)
    p.add_argument('--port',type=int,default=8013);p.add_argument('--startup-timeout',type=float,default=600)
    p.add_argument('--execute-steps',type=int,default=5);p.add_argument('--max-action-steps',type=int,default=3600)
    p.add_argument('--execute',action='store_true');run_batch(p.parse_args())


if __name__=='__main__':main()

