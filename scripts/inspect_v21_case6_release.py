import pathlib,json
root=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/releases/robust_v21_20260929/runs/ablation/geometry');a=next((root/'attempts').glob('airport_0006_*/a000'))
es=[json.loads(x) for x in (a/'events.jsonl').read_text().splitlines()]
for e in es:
 if e['event'] in ['operation_selected','affordance_candidate','primitive_start','primitive_lift_path_selected','placement_arrival_base_correction','primitive_failed','contact_handoff_aborted'] or 'rim' in e['event']:print(json.dumps(e))
