"""Run a bounded outer guardian of an explicitly reviewed workflow process."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_3table.guardian import supervise_guardian
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--options',required=True);a=p.parse_args()
    supervise_guardian(a.options)
