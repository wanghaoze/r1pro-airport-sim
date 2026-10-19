"""Export the new single-tray three-action demonstrations; never starts training."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.data_single_tray import materialize_action_split

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--records',required=True);parser.add_argument('--destination',required=True)
 parser.add_argument('--repo-id',required=True);parser.add_argument('--split',choices=['train','val','test'],required=True)
 args=parser.parse_args()
 records=[json.loads(line) for line in Path(args.records).read_text().splitlines() if line.strip()]
 records=[row for row in records if row['source']['split']==args.split]
 manifest=materialize_action_split(records,args.destination,args.repo_id,split=args.split)
 print(json.dumps(dict(dataset=args.destination,split=args.split,scenes=len(records),episodes=len(manifest['episodes']),dataset_ready=manifest['dataset_ready'],training_started=False)))
if __name__=='__main__':main()
