"""Compact read-only completed-result comparison; never infer partial success."""
import argparse
import json
from collections import Counter
from pathlib import Path


def summarize(root, groups, cases):
    report=[]
    for group in groups:
        collection=root/group
        for case in cases:
            matches=sorted((collection/'attempts').glob(f'airport_{case:04d}_*/a*/result.json'))
            if not matches:
                report.append(dict(group=group,case=case,status='no_completed_result'))
                continue
            for path in matches:
                result=json.loads(path.read_text())
                events=[json.loads(line) for line in (path.parent/'events.jsonl').read_text().splitlines() if line.strip()]
                failures=[e for e in events if e['event'] in ('primitive_failed','operation_failed')]
                first=failures[0] if failures else None
                relevant=[e for e in events if first is None or e['frame']<=first['frame']]
                transitions=[e for e in relevant if e['event']=='state_transition']
                operations=[e for e in relevant if e['event']=='operation_selected']
                report.append(dict(group=group,case=case,status='completed',result=result,
                    first_failure=first,last_transition=transitions[-1] if transitions else None,
                    operation=operations[-1] if operations else None,
                    completed_primitives=[dict(primitive=e['primitive'],duration_s=e.get('duration_s'))
                        for e in events if e['event']=='primitive_complete']))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    p.add_argument('--groups',nargs='+',default=['baseline','command','command_substep'])
    p.add_argument('--cases',nargs='+',type=int,default=[4,5,8,16]);p.add_argument('--output',type=Path)
    args=p.parse_args();rows=summarize(args.root,args.groups,args.cases)
    if args.output:
        if args.output.exists():raise ValueError('Refuse to overwrite report')
        args.output.write_text(json.dumps(rows,indent=2))
    for row in rows:
        r=row.get('result',{});first=row.get('first_failure') or {};transition=row.get('last_transition') or {}
        detail=first.get('detail') or {};candidates=detail.get('candidates',[]) if isinstance(detail,dict) else []
        print(json.dumps(dict(group=row['group'],case=row['case'],status=row['status'],
            physics_success=r.get('physics_success'),failure=first.get('reason'),
            seconds=first.get('frame',0)/20 if first else r.get('simulation_seconds'),
            phase=transition.get('phase'),primitive=first.get('primitive'),
            path_available_s=detail.get('available_s') if isinstance(detail,dict) else None,
            path_rejections=dict(Counter(c['reason'] for c in candidates)),
            smallest_duration_rejection_s=min((c['required_s'] for c in candidates if c.get('reason')=='duration'),default=None),
            completed_pushes=sum(e['primitive']=='push' for e in row.get('completed_primitives',[])))))
