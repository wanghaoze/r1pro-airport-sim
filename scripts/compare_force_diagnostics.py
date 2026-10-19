"""Compare all variants over the same elapsed interval, never full-run averages."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np

p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();result={}
for label,folder in [('baseline','local_full_push_v11case5_force_baseline'),('feedback','local_full_push_v11case5_force_feedback_v2'),('zero_gain','local_full_push_v11case5_force_zero_gain')]:
    root=a.root/folder
    summary=json.loads((root/'summary.json').read_text());events=json.loads((root/'events.json').read_text())
    updates=[x for x in events if x['event']=='diagnostic_force_feedback_update']
    force=[x for x in csv.DictReader((root/'forces.csv').open()) if float(x['time_s'])<=2463/20+2.7+1e-7]
    missing=longest=0
    for row in force:
        missing=missing+1 if int(row['table_contacts'])==0 else 0;longest=max(longest,missing)
    result[label]=dict(comparison_elapsed_s=2.7,physics_samples=len(force),
        support_fraction=float(np.mean([int(x['table_contacts'])>0 for x in force])),
        mean_normal_n=float(np.mean([float(x['table_normal_n']) for x in force])),
        peak_normal_n=max(float(x['table_normal_n']) for x in force),longest_missing_s=longest*.002,
        minimum_height_m=min(float(x['bottom_z']) for x in force),maximum_height_m=max(float(x['bottom_z']) for x in force),
        requested_updates=len(updates),accepted_updates=sum(x['accepted'] for x in updates),
        offsets_m=[x['request']['offset_m'] for x in updates if x['request'] is not None],
        update_planning_wall_s=sum(x['planning_wall_s'] for x in updates),
        total_wall_s=summary['rollout_wall_s'],total_elapsed_s=summary['elapsed_s'],failure=summary['failure'],
        final_position_error_m=summary['final_position_error_m'],final_yaw_deg=float(np.degrees(summary['final_yaw_rad'])),
        primitive_completes=[x for x in events if x['event']=='primitive_complete'])
a.output.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
