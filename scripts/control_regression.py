"""Fresh server control evaluation on the unchanged 400-scene source and split."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from r1pro_teleop.airport_fsm.contracts import atomic_json, Config
from r1pro_teleop.airport_fsm.registry import load_sources, preflight_coverage
from r1pro_teleop.airport_fsm.completion import outcome_counts


def summarize_results(results, source_ids, attempt_budget, *, selected_ids=None,
                      acceptance_profile=None, successes_per_scene=1):
    source_ids=set(source_ids)
    selected_ids=source_ids if selected_ids is None else set(selected_ids)
    if not selected_ids<=source_ids:raise ValueError('Selected scene is not in the registered source')
    if isinstance(attempt_budget,bool) or not isinstance(attempt_budget,int) or attempt_budget<1:
        raise ValueError('Attempt budget must be a positive integer')
    results=[r for r in results if not r.get('diagnostic_only')]
    identities=set();per_scene={sid:[] for sid in sorted(source_ids)}
    for result in results:
        sid=result['scene_id'];attempt=result.get('attempt',0)
        if sid not in source_ids:raise ValueError('Result scene is not in the registered source')
        if isinstance(attempt,bool) or not isinstance(attempt,int) or not 0<=attempt<attempt_budget:
            raise ValueError('Result attempt is outside the declared budget')
        if (sid,attempt) in identities:raise ValueError('Duplicate scene/attempt result')
        identities.add((sid,attempt));per_scene[sid].append(attempt)
    for attempts in per_scene.values():
        if sorted(attempts)!=list(range(len(attempts))):raise ValueError('Attempt sequence contains a gap')
    attempted={r['scene_id'] for r in results}
    if not attempted<=source_ids:
        raise ValueError('Result scene is not in the registered source')
    clean=[r for r in results if r.get('physics_success') and not r.get('recovery_used')
           and not r.get('diagnostic_only')]
    successes={r['scene_id'] for r in clean}
    complete=attempted==source_ids
    outcomes = outcome_counts(results)
    completed_ids={r['scene_id'] for r in results if r.get('task_completed',r.get('physics_success',False))}
    closures={sid:dict(attempts=sorted(attempts),task_completed=sid in completed_ids,
        budget_closed=sid in completed_ids or len(attempts)==attempt_budget,
        closure_reason=('task_completed' if sid in completed_ids else
                        'attempt_budget_exhausted' if len(attempts)==attempt_budget else 'pending'))
        for sid,attempts in per_scene.items()}
    budget_closed=all(c['budget_closed'] for c in closures.values())
    for sid,closure in closures.items():
        scene_results=[r for r in results if r['scene_id']==sid]
        profile=acceptance_profile or next((r.get('acceptance_profile') for r in scene_results if r.get('acceptance_profile')),'strict')
        stops=(closure['task_completed'] if profile=='completion_first' else
               sum(bool(r.get('physics_success') and not r.get('recovery_used') and not r.get('export_rejected')) for r in scene_results)>=successes_per_scene)
        closure['stopping_budget_closed']=bool(stops or len(closure['attempts'])==attempt_budget)
    selected_closed=all(closures[s]['budget_closed'] for s in selected_ids)
    selected_completed=len(completed_ids & selected_ids)
    return {**outcomes, 'source_scene_count':len(source_ids),'attempted_scenes':len(attempted),
        'selected_scene_count':len(selected_ids),'selected_budget_closed':selected_closed,
        'selected_task_completed_scenes':selected_completed,
        'selected_task_completion_rate':selected_completed/len(selected_ids) if selected_ids else None,
        'selected_rate_is_final':selected_closed,
        'selected_rate_qualification':'Selected development subset only; not the full-source success rate.' if selected_ids!=source_ids else 'Full registered source.',
        'stopping_budget_closed':all(c['stopping_budget_closed'] for c in closures.values()),
        'selected_stopping_budget_closed':all(closures[s]['stopping_budget_closed'] for s in selected_ids),
        'total_simulation_seconds':sum(float(r.get('simulation_seconds',0)) for r in results),
        'total_physical_elapsed_seconds':sum(float(r.get('physical_elapsed_seconds',r.get('simulation_seconds',0))) for r in results),
        'total_attempt_wall_seconds':sum(float(r.get('wall_seconds',0)) for r in results),
        'cost_records_missing_wall_seconds':sum('wall_seconds' not in r for r in results),
        'cost_records_missing_simulation_seconds':sum('simulation_seconds' not in r for r in results),
        'budget_closed':budget_closed,'budget_closed_scenes':sum(c['budget_closed'] for c in closures.values()),
        'per_scene_attempts':closures,
        'first_attempt_task_completion_rate':outcomes['first_attempt_task_completed_scenes']/len(source_ids) if source_ids else None,
        'first_attempt_rate_is_final':complete,
        'budget_task_completion_rate':outcomes['task_completed_scenes']/len(source_ids) if source_ids and budget_closed else None,
        'task_completion_rate_is_final':budget_closed,
        'completed_attempts':len(results),'clean_complete_attempts':len(clean),
        'clean_complete_successes':len(successes),
        'full_source_success_rate':len(successes)/len(source_ids) if source_ids else None,
        'attempted_scene_success_rate':len(successes)/len(attempted) if attempted else None,
        'all_400_attempted':len(source_ids)==400 and complete,
        'target_70_percent_reached':len(source_ids)==400 and budget_closed and len(successes)>=280,
        'task_completion_rate': outcomes['task_completed_scenes']/len(source_ids) if source_ids else None,
        'strict_clean_success_rate': outcomes['strict_clean_successful_scenes']/len(source_ids) if source_ids else None,
        'task_completion_target_70_percent_reached': len(source_ids)==400 and budget_closed and outcomes['task_completed_scenes']>=280,
        'strict_target_70_percent_reached': len(source_ids)==400 and budget_closed and outcomes['strict_clean_successful_scenes']>=280,
        'attempt_budget':attempt_budget,'simulation_only':True,
        'qualification':'Task completion uses the recorded acceptance profile and includes physical recovery; strict clean success excludes deviations and recovery. Legacy clean counters use the recorded profile. Partial-source rate is coverage, not an estimated full-source result.',
        'primitive_budget_exclusions':['initial_grasp','navigation','push_release_retreat','final_stability','cpu_planning'],
        'episode_time_includes_all_physical_motion':True}


def select_indices(rows, indices, all_scenes=False):
    if all_scenes:return [r['scene_id'] for r in rows]
    requested=set(indices)
    if not requested:raise ValueError('Requested scene selection is empty')
    selected=[r['scene_id'] for r in rows if int(r['scene_id'].split('_')[1]) in requested]
    if len(selected)!=len(requested):raise ValueError('Requested scene index missing or ambiguous')
    return selected


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument('--config', required=True)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--all', action='store_true')
    p.add_argument('--indices', nargs='+', type=int, default=[1,4,5,6,7,8,16,25,218,310])
    a = p.parse_args(argv)
    if not (Path(sys.prefix)/'conda-meta').is_dir() or (Path(sys.prefix)/'condabin').exists():
        raise RuntimeError('Use non-base Conda')
    if a.workers < 1:
        raise ValueError('workers must be positive')
    manifest=ROOT/'resources/scenes/server_v7/manifest.json'
    # Reject bad requests before even spawning prepare; registration itself still
    # covers the full manifest, split and all immutable source checksums.
    registered=load_sources(manifest,Config.load(a.config).expected_scenes)
    selected=select_indices(registered,a.indices,a.all)
    root = Path(a.output).resolve()
    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    def run(*args):
        subprocess.run([sys.executable, '-m', 'r1pro_teleop.airport_fsm', *map(str,args)],
                       cwd=ROOT, env=env, check=True)
    run('prepare','--manifest',manifest,
        '--config',a.config,'--output',root,'--half-turn-equivalent')
    preflight_args=['preflight','--root',root,'--workers',a.workers]
    if not a.all:preflight_args+=['--scene-ids',*selected]
    run(*preflight_args)
    # Existing collection source hashes are checked by generate before resuming.
    args = ['generate','--root',root,'--workers',a.workers]
    if not a.all:
        args += ['--scene-ids', *selected]
    run(*args)
    results = [json.loads(f.read_text()) for f in root.glob('attempts/*/a*/result.json')]
    source_rows=json.loads((root/'scenes/index.json').read_text())
    run_config=json.loads((root/'collection.json').read_text())['config']
    summary=summarize_results(results,
        [r['scene_id'] for r in source_rows],
        run_config['max_attempts_per_scene'],selected_ids=selected,
        acceptance_profile=run_config.get('acceptance_profile','strict'),
        successes_per_scene=run_config.get('successes_per_scene',1))
    summary['primitive_budget_seconds']=run_config['primitive_seconds']
    summary['preflight_coverage']=preflight_coverage(root,source_rows,selected)
    summary['runner_complete']=True
    summary['selected_scene_ids']=selected
    atomic_json(root/'evaluation_summary.json',summary)


if __name__ == '__main__':
    main()
