"""Explicit fresh three-table/mobile/opposed task pipeline. No old-task reuse."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.three_table_single_tray_pipeline import supervise
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--options',required=True);p.add_argument('--recover',action='store_true');p.add_argument('--data-only',action='store_true');a=p.parse_args();options=json.loads(Path(a.options).read_text())
 if a.data_only:options['data_only']=True
 supervise(options,recover=a.recover)
