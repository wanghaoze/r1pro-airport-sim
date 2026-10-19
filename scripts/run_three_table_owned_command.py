"""Run one explicit command with durable actual PID and exit evidence."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_3table.owned_command import run_command_receipt

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--options',required=True)
    a=p.parse_args();return run_command_receipt(a.options)

if __name__=='__main__':raise SystemExit(main())
