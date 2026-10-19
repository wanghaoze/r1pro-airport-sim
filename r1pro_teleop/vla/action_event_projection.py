"""Reconcile recorder field names/duplicate bridge annotations, retaining sources."""
from .data_single_tray import canonical_hash

def project_action_events(events,result):
 spans=result.get('action_spans',[])
 if [s.get('action_label') for s in spans]!=['pick_empty','place_empty','push_loaded'] or any(s.get('verified') is not True for s in spans):raise ValueError('three_actual_verified_result_spans_required')
 chosen=[];identities=[]
 for span in spans:
  label=span['action_label'];a=span['start_frame'];b=span['end_frame'];endpoint=span['measured_endpoint_frame']
  starts=[(i,e) for i,e in enumerate(events) if e.get('event')=='action_start' and e.get('action_label')==label]
  ends=[(i,e) for i,e in enumerate(events) if e.get('event')=='action_complete' and e.get('action_label')==label]
  if not starts or not ends or any(e.get('frame')!=a for _,e in starts) or any(e.get('start_frame')!=a or e.get('end_frame',e.get('end_frame_exclusive'))!=b or e.get('measured_endpoint_frame')!=endpoint or e.get('verified') is not True for _,e in ends):raise ValueError('action_recorder_duplicates_do_not_match_actual_spans')
  authoritative=[(i,e) for i,e in starts if e.get('task_rule_revision')]
  if len(authoritative)!=1:raise ValueError('actual_observer_action_start_required')
  final=[(i,e) for i,e in ends if e.get('end_frame')==b]
  if len(final)!=1:raise ValueError('actual_observer_action_completion_required')
  i,start=authoritative[0];j,end=final[0];new=dict(end,end_frame_exclusive=b)
  chosen.extend([(i,start),(j,new)]);identities.append(dict(action_label=label,original_start_rows=[canonical_hash(e) for _,e in starts],original_complete_rows=[canonical_hash(e) for _,e in ends],actual_result_span_sha256=canonical_hash(span)))
 ordinary=[(i,e) for i,e in enumerate(events) if e.get('event') not in ('action_start','action_complete')]
 projected=[e for _,e in sorted(ordinary+chosen,key=lambda row:row[0])]
 return projected,dict(schema='airport_actual_action_event_projection/1',verified=True,original_events_sha256=canonical_hash(events),projected_events_sha256=canonical_hash(projected),action_proofs=identities,original_events_unchanged=True)
