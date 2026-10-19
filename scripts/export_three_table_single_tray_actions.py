"""New mobile/opposed three-table dataset export; no training or relabeling."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.data_three_table_lerobot import materialize
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--records',required=True);p.add_argument('--destination',required=True);p.add_argument('--repo-id',required=True);p.add_argument('--split',choices=('train','val','test'),required=True);a=p.parse_args();rows=[json.loads(x) for x in Path(a.records).read_text().splitlines() if x.strip()];rows=[r for r in rows if r['source']['split']==a.split];m=materialize(rows,a.destination,a.repo_id,split=a.split);print(json.dumps(dict(dataset_ready=m['dataset_ready'],training_started=False,episodes=len(m['episodes']))))
