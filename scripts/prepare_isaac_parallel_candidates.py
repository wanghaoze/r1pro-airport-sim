"""CPU-only, finite private path registry; never marks physical data ready."""
import copy
import json
import math
import hashlib
import numpy as np
from pathlib import Path
import random
import subprocess
import sys
import time

B=Path('/home/michelle/haoze/r1pro-airport-sim')
CODE=B/'releases/isaacsim_parallel_live_20261016_code_v61'
ROOT=B/'runs/isaacsim_reachable_wide_station_candidates_20261016_v2'
SEED=2026101620
RANGES=dict(tray_x_m=[.84,.86],tray_y_m=[-.30,.30],base_distance_m=[.535,.565],
            base_lateral_relative_to_tray_m=[-.015,.015],base_yaw_degrees=[-4.,4.],
            tray_yaw_relative_to_base_degrees=[-2.,2.],lift_height_m=[.12,.18])


def save(path,data):
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(data,indent=2));temp.replace(path)


def main():
    ROOT.mkdir(exist_ok=False);(ROOT/'preflight').mkdir()
    old=json.loads((B/'runs/isaacsim_reachable_private_candidates_20261016_v2/config.json').read_text())
    template=old['cases'][0];rng=random.Random(SEED);accepted=[];registry=[]
    footprint_path=B/'runs/isaacsim_parallel_live_20261016_v2/native/rooms/room_000/tray_0_collision_footprint.json'
    footprint=json.loads(footprint_path.read_text());points=np.asarray(footprint['body_local_vertices_m'],float)
    if hashlib.sha256(points.tobytes()).hexdigest()!=footprint['vertices_sha256']:
        raise ValueError('native_footprint_sha_mismatch')
    scene_root=Path(old['scene_root']);validation=json.loads((scene_root/'control/validation.json').read_text())
    if footprint['validated_scene_sha256']!=validation['scene_sha256']:
        raise ValueError('native_footprint_scene_mismatch')
    inventory=json.loads((scene_root/'preparation/legacy_inventory.json').read_text())
    source=next(r for r in inventory['sources'] if r['parent_scene_id']==old['parent_scene_id'])
    parent=json.loads(Path(source['legacy_source']['scene_json']).read_text())
    table=next(t for t in parent['tables'] if t['table_id']=='front_left')
    angle=float(table['yaw_world']);table_R=np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])
    y_levels=[-.30+.60*i/31 for i in range(32)]
    def sample(key):return rng.uniform(*RANGES[key])
    save(ROOT/'registration.json',dict(scope='cpu_private_reachability_not_physical_data',
        seed=SEED,max_candidates=128,target_accepted=32,ranges=RANGES,
        parent_scene_id=old['parent_scene_id'],parent_split=old['parent_split'],
        source_code=str(CODE),source_template=str(B/'runs/isaacsim_reachable_private_candidates_20261016_v2/config.json'),
        fixed_base_during_entire_episode=True,old_data_unchanged=True))
    save(ROOT/'initial_support_contract.json',dict(table=table,native_footprint_source=str(footprint_path),
        native_footprint_sha256=footprint['vertices_sha256'],allowed_initial_overhang_m=0.,
        numerical_comparison_epsilon_m=1e-7,existing_during_action_5cm_gate_unchanged=True))
    for i in range(128):
        if i%32==0:rng.shuffle(y_levels)
        x=sample('tray_x_m');y=y_levels[i%32]+rng.uniform(-.003,.003)
        yaw=sample('base_yaw_degrees');relative=sample('tray_yaw_relative_to_base_degrees');tray_yaw=yaw+relative
        base=[x-sample('base_distance_m'),y+sample('base_lateral_relative_to_tray_m'),math.radians(yaw)]
        case=copy.deepcopy(template)
        case.update(case_id=f'wide_station_{SEED}_{i:03d}',seed=SEED+i,
            initial_base_world=base,fixed_base_world=base,
            tray_pose=[x,y,.801,math.cos(math.radians(tray_yaw)/2),0.,0.,math.sin(math.radians(tray_yaw)/2)],
            yaw_degrees=tray_yaw,xy_offset_m=[x-.85,y],lift_height_m=sample('lift_height_m'),
            sampling_registry=str(ROOT/'registration.json'),
            coverage_class='same_front_table_random_initial_station_and_tray_pose',
            private_path_available=False)
        cp=ROOT/'preflight'/f'candidate_{i:03d}.json';rp=cp.with_suffix('.result.json');save(cp,case)
        yaw_rad=math.radians(tray_yaw);R=np.array([[math.cos(yaw_rad),-math.sin(yaw_rad)],[math.sin(yaw_rad),math.cos(yaw_rad)]])
        world_xy=points[:,:2]@R.T+[x,y]
        local=(world_xy-np.asarray(table['center_world'][:2]))@table_R
        overhang=float((abs(local)-np.asarray(table['dimensions_m'][:2])/2).max())
        geometry=dict(full_initial_native_footprint_supported=overhang<=1e-7,
            maximum_signed_overhang_m=overhang,footprint_vertices=points.shape[0],
            vertices_sha256=footprint['vertices_sha256'],table_id=table['table_id'])
        save(cp.with_suffix('.geometry.json'),geometry)
        if not geometry['full_initial_native_footprint_supported']:
            registry.append(dict(candidate=str(cp),geometry=str(cp.with_suffix('.geometry.json')),
                private_path_available=False,reason='initial_footprint_outside_table_not_ik_tested'))
            save(ROOT/'registry.json',registry)
            continue
        with cp.with_suffix('.log').open('w') as log:
            result=subprocess.run([sys.executable,str(CODE/'scripts/probe_isaacsim_pad_station.py'),
                '--project',str(B),'--code',str(CODE),'--output',str(rp),
                '--aligned-legacy','--case-config',str(cp)],stdout=log,stderr=subprocess.STDOUT)
        report=json.loads(rp.read_text()) if rp.exists() else {}
        passed=result.returncode==0 and report.get('passed') is True
        registry.append(dict(candidate=str(cp),report=str(rp),geometry=str(cp.with_suffix('.geometry.json')),
            returncode=result.returncode,private_path_available=passed))
        if passed:
            # Original candidate record remains immutable; selection metadata is separate.
            selected=copy.deepcopy(case);selected.update(private_path_available=True,private_precheck_report=str(rp),
                initial_support_geometry=str(cp.with_suffix('.geometry.json')))
            accepted.append(selected)
        save(ROOT/'status.json',dict(stage='private_prechecking',tested=len(registry),accepted_candidates=len(accepted),
            target_candidates=32,complete_physical_sources=0,training_started=False,heartbeat_unix=time.time()))
        save(ROOT/'registry.json',registry)
        if result.returncode!=0 or not report:raise RuntimeError('private_probe_error_check_preserved_log')
        print(f'private {i+1}/128 accepted {len(accepted)}/32',flush=True)
        if len(accepted)>=32:break
    save(ROOT/'candidates.json',accepted)
    save(ROOT/'config.json',dict(scope='parallel_fixed_base_pickplace_candidate_registry',
        scene_root=old['scene_root'],lab_assets=old['lab_assets'],cases=accepted,
        parent_scene_id=old['parent_scene_id'],parent_split=old['parent_split'],
        seed=SEED,ranges=RANGES,training_eligible=False,physical_successes=0,
        source_code=str(CODE),native_collection_started=False))
    keys={'tray_x_m':[c['tray_pose'][0] for c in accepted],'tray_y_m':[c['tray_pose'][1] for c in accepted],
          'tray_yaw_degrees':[c['yaw_degrees'] for c in accepted],
          'base_x_m':[c['fixed_base_world'][0] for c in accepted],
          'base_y_m':[c['fixed_base_world'][1] for c in accepted],
          'base_yaw_degrees':[math.degrees(c['fixed_base_world'][2]) for c in accepted],
          'lift_height_m':[c['lift_height_m'] for c in accepted]}
    save(ROOT/'coverage.json',{k:[min(v),max(v)] for k,v in keys.items()} if accepted else {})
    save(ROOT/'status.json',dict(stage='candidate_registry_closed',tested=len(registry),accepted_candidates=len(accepted),
        target_candidates=32,complete_physical_sources=0,training_started=False,heartbeat_unix=time.time()))


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',type=int,required=True)
    args=p.parse_args();ROOT=args.output;SEED=args.seed;main()

