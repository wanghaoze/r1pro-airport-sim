"""Launch a durable complete-source-gated training/evaluation chain."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.training_pipeline import pipeline

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--options',required=True);parser.add_argument('--launch',action='store_true');parser.add_argument('--recover',action='store_true')
 args=parser.parse_args();options=json.loads(Path(args.options).read_text())
 if not args.launch:raise ValueError('explicit --launch required')
 options['recover']=args.recover
 options['options_sha256']=hashlib.sha256(Path(args.options).read_bytes()).hexdigest()
 pipeline(options)
if __name__=='__main__':main()
