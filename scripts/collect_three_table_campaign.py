"""Plan or explicitly collect new complete three-table sources, never train."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_3table.campaign import build_plan, execute, atomic_json
from r1pro_teleop.single_tray_3table.campaign_recovery import execute_recoverable


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--selection',required=True,help='JSON: schema airport_three_table_campaign_selection/1, variants [{parent_scene_id, variant_seed}]')
    p.add_argument('--inventory',required=True)
    p.add_argument('--parent-manifest',required=True)
    p.add_argument('--split-registry',required=True)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--scene-options',help='Explicit generator options JSON; cannot alter split, route or task')
    p.add_argument('--execute',action='store_true',help='Actually run physics; default only writes a nontraining plan')
    p.add_argument('--recover',action='store_true',help='Adopt unchanged registered campaign and actual owned child receipts')
    p.add_argument('--release',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--sim-python',default=sys.executable)
    p.add_argument('--config')
    p.add_argument('--push-reference-scene')
    p.add_argument('--workers',type=int,default=1)
    a=p.parse_args()
    if a.recover and not a.execute:p.error('--recover requires --execute; a plan is not a running campaign')
    if a.execute and (not a.config or not a.push_reference_scene):
        p.error('--execute requires --config and --push-reference-scene')
    selection=json.loads(Path(a.selection).read_text())
    options=json.loads(Path(a.scene_options).read_text()) if a.scene_options else None
    plan=build_plan(selection,a.inventory,a.parent_manifest,a.split_registry,scene_options=options)
    if a.execute:
        result=execute_recoverable(plan,a.output,release=a.release,sim_python=a.sim_python,config=a.config,
                       reference=a.push_reference_scene,workers=a.workers,recover=a.recover)
    else:
        a.output.mkdir(parents=True,exist_ok=False)
        atomic_json(a.output/'plan.json',plan)
        result=dict(status='planned_not_executed',selected=plan['selected'],physical_jobs_started=0,
                    task_profile=plan['task_profile'],dataset_ready=False,training_started=False,
                    plan=str((a.output/'plan.json').resolve()))
        atomic_json(a.output/'planning_receipt.json',result)
    print(json.dumps(result,allow_nan=False))


if __name__=='__main__':
    main()
