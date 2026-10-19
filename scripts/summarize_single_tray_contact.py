"""Audit complete-task counts and the new single-tray 3mm/5mm contact gate."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_lab.contact_summary import summarize_cases

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',type=Path,action='append',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.output.exists():raise FileExistsError(a.output)
 report=summarize_cases(a.case);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,allow_nan=False));print(json.dumps({k:v for k,v in report.items() if k!='rows'}))
if __name__=='__main__':main()
