"""Diagnostic-only native4 continuous replay; never counts as task evaluation."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_3table.free_run_native import render

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',required=True);p.add_argument('--output',required=True);p.add_argument('--audit-only',action='store_true');a=p.parse_args()
    print(json.dumps(render(a.case,a.output,audit_only=a.audit_only)))

if __name__=='__main__':main()
