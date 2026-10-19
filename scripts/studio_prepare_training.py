"""Resolve a frozen dataset selection into a new run; never mutate source data."""
import argparse
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.parallel_pickplace_training import freeze_pairs,verify_frozen,materialize_parallel_cache
from r1pro_teleop.vla.real_sim_data import write,sha


def prepare(run):
    inputs=json.loads((run/'inputs.pending.json').read_text());selection=json.loads((run/'selection.json').read_text())
    sims={k:v for k,v in selection.items() if v['domain']=='simulation/program_generated' and inputs['real_fraction']<1}
    if sims:
        if list(sims)==['isaac300_20261017']:
            registered=sims['isaac300_20261017'];frozen=verify_frozen(registered['frozenFile'])
            if frozen['complete_source_pairs']!=300:raise ValueError('registered_300_snapshot_changed')
            cache=Path(registered['cache']);manifest=json.loads((cache/'manifest.json').read_text())
            if manifest['source_manifest_sha256']!=sha(registered['frozenFile']):raise ValueError('registered_cache_source_changed')
            for name,h in json.loads((cache/'integrity.json').read_text()).items():
                if sha(cache/name)!=h:raise ValueError('registered_cache_changed')
            inputs.update(sim_cache=str(cache),frozen_manifest=registered['frozenFile'])
        else:
            batches=[]
            for entry in sims.values():
                if entry.get('frozenFile'):
                    frozen=verify_frozen(entry['frozenFile'])
                    rows=[p for p in frozen['files'] if p.endswith('/manifest.json') and '/dataset/batches/' in p]
                    if len(rows)!=entry['pairs']:raise ValueError('registered_batch_count_changed')
                    batches+=rows
                else:batches+=entry['batchManifests']
            parents=json.loads((Path(inputs['real_cache_root']).parents[1]/'real_isaac300_timeweighted_pi05_20261017_v1/parent_split_registry.json').read_text())
            for path in batches:
                row=json.loads(Path(path).read_text())['segments'][0];key=row['parent_scene_id'];split=row['split']
                if split!='train' or parents.get(key)!=split:raise ValueError('simulation_parent_split_conflict')
            expected=sum(e['pairs'] for e in sims.values())
            frozen=run/'frozen_simulation.json';manifest=freeze_pairs(batches,frozen,parents,minimum_sources=expected)
            frames=sum(s['frames'] for pair in manifest['pairs'] for s in pair['segments'])
            if shutil.disk_usage(run).free < frames*3*224*224*3+20*1024**3:raise ValueError('insufficient_space_for_new_cache_and_checkpoint')
            cache=run/'simulation_cache';materialize_parallel_cache(frozen,cache)
            inputs.update(sim_cache=str(cache),frozen_manifest=str(frozen))
    write(run/'inputs.json',inputs)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);prepare(p.parse_args().run)
