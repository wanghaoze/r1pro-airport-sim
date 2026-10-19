"""Read-only progress for the new 300-pair collection and mixed BC."""
import argparse
import datetime
import json
from pathlib import Path
import time


def read(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def bar(n, total):
    fraction = min(1., max(0., n / total)) if total else 0.
    fill = int(25 * fraction)
    return '[' + '#' * fill + '-' * (25 - fill) + f'] {n}/{total} ({fraction:.1%})'


def report(root):
    production = root / 'runs/isaacsim_parallel_pickplace300_20261017_v1'
    training = root / 'runs/real_isaac300_timeweighted_pi05_20261017_v1'
    p = read(production / 'production_status.json')
    ready = read(production / 'data_ready.json')
    t = read(training / 'training_status.json')
    pipeline = read(training / 'pipeline_status.json')
    count = ready.get('source_pairs', p.get('qualified_pairs', 0))
    lines = [datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds'),
             'Collection: ' + str(p.get('stage', 'not_started')),
             'Qualified complete Pick/Place pairs ' + bar(count, 300),
             f'Action segments: {count * 2}; old 59 pairs excluded.']
    batch = p.get('batch')
    if batch:
        native = read(Path(batch) / 'native/status.json')
        lines += [f'Batch: {Path(batch).name}; shared native frames: {native.get("frames", "--")}; active rooms: {native.get("active_rooms", "--")}']
    catalogues = sorted(production.glob('batch_*/native/dataset_catalog.json'))
    seconds = sources = 0
    for catalogue in catalogues:
        c = read(catalogue)
        wall = c.get('producer_benchmark', {}).get('simulation_and_record_wall_seconds', 0) + c.get('export_wall_seconds', 0)
        if wall > 0:
            seconds += wall
            sources += c.get('complete_source_pairs', 0)
    if sources and seconds:
        rate = sources * 3600 / seconds
        lines += [f'Observed closed batches: {rate:.1f} pairs/hour (load/precheck excluded).',
                  f'Collection remaining at that rate: ~{max(0,300-count)/rate:.1f} h plus load/precheck; estimate only.']
    else:
        lines += ['Collection ETA: -- (no newly closed batch yet).']
    updates = t.get('actual_completed_updates', 0)
    phase = pipeline.get('stage', 'waiting_for_data')
    if phase.startswith('train_'):
        phase = t.get('stage', phase)
    lines += ['Mixed duration-weighted BC: ' + str(phase),
              'Verified updates ' + bar(updates, t.get('target_updates', 10000))]
    if updates == 0:
        lines += ['No gradient updates verified; waiting/initialization is not training.']
    if t.get('eta_seconds') is not None and t.get('stage') == 'training':
        lines += [f'Training ETA: {t["eta_seconds"]/60:.1f} min; {t.get("eta_scope", "active stage only")}.']
    if t.get('checkpoint'):
        lines += ['Checkpoint: ' + t['checkpoint']]
    for label, obj in [('production', read(production/'production_failure.json')), ('training', pipeline)]:
        error = obj.get('error', obj.get('last_error'))
        if error:
            lines += [label + ' last recorded error: ' + str(error)]
    return '\n'.join(lines + ['Ctrl+C exits this read-only monitor only.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('/home/michelle/haoze/r1pro-airport-sim'))
    parser.add_argument('--watch', type=float, default=0)
    args = parser.parse_args()
    try:
        while True:
            print(report(args.root), flush=True)
            if args.watch <= 0:
                break
            time.sleep(max(1., args.watch))
    except KeyboardInterrupt:
        pass
