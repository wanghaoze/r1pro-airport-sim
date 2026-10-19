"""Launch the independent new single-tray three-action data/BC pipeline."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.single_tray_pipeline import supervise

def main():
 p=argparse.ArgumentParser();p.add_argument('--options',required=True);p.add_argument('--launch',action='store_true');a=p.parse_args()
 if not a.launch:raise ValueError('explicit launch required')
 supervise(json.loads(Path(a.options).read_text()))
if __name__=='__main__':main()
