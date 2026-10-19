"""Audit measured primitive timings; does not promote failed episodes."""
import argparse
import json
from pathlib import Path


def audit(directory):
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    result = json.loads((directory / 'result.json').read_text())
    pending = None
    actions = []
    problems = []
    for event in events:
        kind = event['event']
        if kind == 'primitive_start':
            if pending is not None:
                problems.append('nested_or_unfinished_primitive')
            pending = event
        elif kind in ('primitive_complete', 'primitive_failed'):
            if pending is None or pending['primitive'] != event['primitive']:
                problems.append('unmatched_primitive_end')
                continue
            row = dict(primitive=event['primitive'], start_frame=pending['frame'],
                       end_frame=event['frame'], duration_s=event['duration_s'],
                       success=kind == 'primitive_complete', parameters=pending['parameters'],
                       failure_reason=event.get('reason'),
                       planning_and_execution_wall_s=event.get('planning_and_execution_wall_s'))
            if event['duration_s'] > pending['limit_s'] + 1e-9:
                problems.append('primitive_exceeded_time_limit')
            if event['frame'] < pending['frame']:
                problems.append('invalid_frame_range')
            actions.append(row)
            pending = None
    if pending is not None:
        problems.append('unfinished_primitive')
    heights = [e['height_m'] for e in events if e['event'] == 'primitive_lift_measured']
    if any(not .15 <= height <= .20 for height in heights):
        problems.append('measured_lift_outside_15_20_cm')
    return dict(source=str(directory.resolve()), physics_success=result.get('physics_success'),
                training_candidate=result.get('training_candidate'),
                simulation_seconds=result.get('simulation_seconds'), failure_code=result.get('failure_code'),
                measured_lift_heights_m=heights, actions=actions, audit_problems=problems,
                all_completed_actions_within_3s=bool(actions) and all(a['duration_s'] <= 3. for a in actions),
                all_started_actions_succeeded=bool(actions) and pending is None and all(a['success'] for a in actions))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempts', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = dict(schema='fixed_primitives_audit/1',
                  timing='Simulation/control time. CPU planning wall time is separately reported.',
                  excluded_from_primitive_budget=['initial_grasp_acquisition', 'base_navigation',
                      'post_push_release_and_retreat', 'final_one_second_task_verification'],
                  transport_alignment='Explicit separate action with its own 3-second limit.',
                  attempts=[audit(path) for path in args.attempts])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
