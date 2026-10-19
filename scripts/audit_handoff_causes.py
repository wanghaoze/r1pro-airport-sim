"""Read-only nested failure audit using small result/event JSON, never HDF5."""
import argparse
from collections import Counter
import json
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
if a.output.exists():raise ValueError('Use a new diagnostic output')
rows=[];total=0
for result_path in sorted((a.root/'attempts').glob('*/*/result.json')):
    result=json.loads(result_path.read_text());total+=1
    if result.get('failure_code')!='contact_handoff_aborted':continue
    events=[json.loads(line) for line in (result_path.parent/'events.jsonl').read_text().splitlines()]
    terminal=next((e for e in reversed(events) if e.get('event')=='operation_failed'),{})
    nested=terminal.get('detail',{});chain=[];detail=nested
    while isinstance(detail,dict) and isinstance(detail.get('reason'),str):
        chain.append(detail['reason']);detail=detail.get('detail')
    primitive_failed=next((e for e in reversed(events) if e.get('event')=='primitive_failed'),{})
    starts=[e for e in events if e.get('event')=='primitive_start']
    start=starts[-1] if starts else {}
    start_frame=start.get('frame');end_frame=terminal.get('frame')
    elapsed_frames=end_frame-start_frame if isinstance(start_frame,int) and isinstance(end_frame,int) else None
    recent=[e for e in events if start_frame is not None and e.get('frame',-1)>=start_frame]
    reference=[e for e in recent if e.get('event')=='primitive_reference']
    transitions=[e for e in events if e.get('event')=='state_transition']
    phase=transitions[-1] if transitions else {}
    active_primitive=start.get('primitive') if primitive_failed.get('frame')==terminal.get('frame') else None
    if active_primitive is None:
        start_frame=phase.get('frame');elapsed_frames=end_frame-start_frame if isinstance(start_frame,int) and isinstance(end_frame,int) else None
        recent=[e for e in events if start_frame is not None and e.get('frame',-1)>=start_frame]
        reference=[e for e in recent if e.get('event')=='primitive_reference']
    operation=next((e for e in reversed(events) if e.get('event')=='operation_selected'),{})
    root_reason=chain[-1] if chain else primitive_failed.get('reason','unknown')
    if elapsed_frames==0 and not reference:category='zero_motion_planning_or_precondition'
    elif root_reason in ('retained_contact_lost','bilateral_contact_lost','support_contact_lost'):category='physical_contact_during_execution'
    elif root_reason=='primitive_postcondition_failed':category='postcondition_after_execution'
    else:category='other_executed_or_context_failure'
    path_candidates=detail.get('candidates',[]) if isinstance(detail,dict) else []
    rows.append(dict(scene_id=result['scene_id'],attempt=result.get('attempt'),nested_chain=chain,root_reason=root_reason,
        root_detail=detail,primitive=active_primitive,primitive_parameters=start.get('parameters') if active_primitive else None,primitive_failure=primitive_failed,
        phase_transition=phase,operation=operation,primitive_start_frame=start_frame,failure_frame=end_frame,
        elapsed_frames=elapsed_frames,reference_count=len(reference),references=reference,category=category,
        candidate_reasons=dict(Counter(e.get('reason','unknown') for e in path_candidates)),
        compliance_reference=next((e for e in reversed(recent) if e.get('event')=='primitive_push_compliance_reference'),None),
        feedforward=next((e for e in reversed(recent) if e.get('event')=='primitive_push_feedforward'),None)))
def count(key):return dict(Counter(row[key] for row in rows))
summary=dict(completed_results=total,handoff_failures=len(rows),root_reasons=count('root_reason'),
             categories=count('category'),primitives=count('primitive'),
             zero_motion=sum(row['elapsed_frames']==0 for row in rows),
             nonzero_motion=sum(isinstance(row['elapsed_frames'],int) and row['elapsed_frames']>0 for row in rows),
             root_primitive_counts=dict(Counter(f"{row['root_reason']}|{row['primitive']}" for row in rows)))
physical=[row for row in rows if row['root_reason']=='retained_contact_lost']
paths=[row for row in rows if row['root_reason']=='primitive_path_infeasible']
summary['push_zero_motion']=sum(row['primitive']=='push' and row['elapsed_frames']==0 for row in rows)
summary['physical_contact_signatures']=dict(Counter(f"table_zero={row['root_detail']['table_contact']==0}|grip_below_threshold={row['root_detail']['force_n']<=.5}|side={row['root_detail']['side']}" for row in physical))
summary['physical_previous_phase']=dict(Counter('|'.join(row['phase_transition']['previous']) for row in physical))
summary['path_candidate_reason_sets']=dict(Counter('|'.join(sorted(row['candidate_reasons'])) for row in paths))
payload=dict(root=str(a.root),summary=summary,rows=rows)
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(payload,indent=2))
print(json.dumps(summary,indent=2))
