"""Detach externally once; this durable workflow waits for actual sources."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_3table.workflow import supervise

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--options',required=True)
    p.add_argument('--recover',action='store_true');a=p.parse_args()
    supervise(a.options,recover=a.recover)
