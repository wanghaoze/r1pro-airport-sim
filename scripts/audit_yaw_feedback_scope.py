"""Read-only stage audit of completed production feedback experiments."""
import argparse
import json
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();rows=[]
for mode in ('baseline','feedback','command_feedback'):
    for case in (4,5,8,16):
        attempts=list((a.root/mode/'attempts').glob(f'airport_{case:04d}_*/a000'))
        if not attempts:continue
        attempt=attempts[0]
        if not (attempt/'result.json').exists():
            rows.append(dict(mode=mode,case=case,status='incomplete'));continue
        result=json.loads((attempt/'result.json').read_text())
        events=[json.loads(line) for line in (attempt/'events.jsonl').read_text().splitlines()]
        pushes=[]
        for index,start in enumerate(events):
            if start['event']!='primitive_start' or start.get('primitive')!='push':continue
            stop=next((i for i in range(index+1,len(events)) if events[i]['event'] in ('primitive_complete','primitive_failed') and events[i].get('primitive')=='push'),len(events)-1)
            segment=events[index:stop+1]
            prior=events[:index]
            operation=next((x for x in reversed(prior) if x['event']=='operation_selected'),{})
            lift=next((x for x in reversed(prior) if x['event']=='primitive_lift_path_selected'),{})
            retained=next((x for x in segment if x['event']=='primitive_push_compliance_reference'),None)
            feedback=[x for x in segment if x['event'] in ('push_yaw_feedback_suffix','push_yaw_feedback_skipped')]
            pushes.append(dict(start_frame=start['frame'],operation_index=operation.get('operation_index'),
                operation=operation.get('operation'),separation=start.get('parameters',{}).get('separation'),
                free_retreat=retained is not None,withdraw_free=retained is not None and abs(lift.get('inward_m',0))>.005,
                retained_side=retained.get('side') if retained else None,last_lift=lift,
                feedback=feedback,end_event=events[stop],feedforward=next((x for x in segment if x['event']=='primitive_push_feedforward'),None)))
        rows.append(dict(mode=mode,case=case,status='complete',physics_success=result.get('physics_success'),
                         failure=result.get('failure_code'),simulation_seconds=result.get('simulation_seconds'),pushes=pushes))
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(dict(root=str(a.root),rows=rows),indent=2))
for row in rows:
    print(json.dumps({k:v for k,v in row.items() if k!='pushes'}))
    for push in row.get('pushes',[]):
        print(json.dumps(dict(start=push['start_frame'],op=push['operation_index'],separation=push['separation'],free_retreat=push['free_retreat'],withdraw=push['withdraw_free'],feedback=push['feedback'],end=push['end_event'])))
