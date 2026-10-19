"""Render immutable MSE figures from saved inference arrays; never runs a policy."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import time
import zipfile
import numpy as np

ORDER = [*range(7), *range(8, 15), 7, 15]
NAMES = [*[f'left_arm_{i}' for i in range(7)], *[f'right_arm_{i}' for i in range(7)], 'left_gripper', 'right_gripper']
COLORS = ['#0072B2', '#D55E00', '#8B5DA8', '#74852C']
STYLES = ['-', '--', '-.', ':']


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def write(path, data):
    path = Path(path); tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8'); tmp.replace(path)


def aligned_data(run):
    report = read(run/'report.json'); entries = read(run/'checkpoints.json'); arrays = []; labels = []
    if not 1 <= len(report['models']) <= 4: raise ValueError('plot_checkpoint_count')
    for model in report['models']:
        files = sorted((run/model['id']).glob('episode_*.npz'))
        if len(files) != len(model['byEpisode']): raise ValueError('plot_episode_coverage')
        chunks = []
        for path in files:
            with np.load(path, allow_pickle=False) as data:
                p, t, v = data['predicted'], data['truth'], data['valid']
                if p.shape != t.shape or p.ndim != 3 or p.shape[1:] != (20, 19) or v.shape != p.shape[:2] or v.dtype != bool:
                    raise ValueError('plot_array_contract')
                if not np.isfinite(p).all() or not np.isfinite(t).all(): raise ValueError('plot_nonfinite_output')
                chunks.append((p, t, v))
        pred, truth, valid = [np.concatenate([c[i] for c in chunks]) for i in range(3)]
        if len(pred) != report['frames'] or int(valid.sum()) != report['validTimesteps']: raise ValueError('plot_denominator_mismatch')
        if hashlib.sha256(truth.tobytes()).hexdigest() != model['truthSha256'] or hashlib.sha256(valid.tobytes()).hexdigest() != model['validMaskSha256']:
            raise ValueError('plot_source_hash_mismatch')
        if arrays:
            if model['contract'] != report['models'][0]['contract']: raise ValueError('plot_protocol_mismatch')
            np.testing.assert_array_equal(truth, arrays[0][1]); np.testing.assert_array_equal(valid, arrays[0][2])
        per = ((pred.astype(float)-truth.astype(float))**2)[valid].mean(axis=0)
        np.testing.assert_allclose(per[:16], model['perChannelMseRad2OrM2'], rtol=1e-8, atol=1e-12)
        arrays.append((pred, truth, valid, chunks, per))
        entry = next(e for e in entries if e['id'] == model['id'])
        source = 'Real-only' if Path(entry['run']).name == 'real_only_pi05_20261012_v1' else 'Mixed' if 'mixed' in entry.get('source', '') or 'real_isaac' in entry['run'] else 'Checkpoint'
        labels.append(f"{source} | {entry['updates']:,} updates | {model['id'][3:11]}")
    return report, arrays, labels


def render(run, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    out.mkdir(parents=True, exist_ok=True)
    if (out/'manifest.json').exists(): raise ValueError('plot_bundle_already_closed')
    report, arrays, labels = aligned_data(run)
    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':11, 'axes.spines.top':False, 'axes.spines.right':False,
                         'axes.grid':True, 'grid.alpha':.18, 'axes.axisbelow':True, 'savefig.facecolor':'white'})
    images = []; files = []
    total = 5 + len(arrays[0][3]); split = report['split'].upper()
    def save(fig, name, title, category):
        path = out/(name+'.png'); fig.savefig(path, dpi=135); plt.close(fig)
        images.append(dict(name=path.name, title=title, category=category)); files.append(path)
        write(out/'progress.json', dict(stage='rendering', completed=len(images), total=total, heartbeat_unix=time.time()))
    for name, title, ids, scale, root, unit in [
        ('joint_mse', 'Joint MSE', range(14), 1, False, 'rad²'),
        ('joint_mse_deg2', 'Joint MSE in degrees', range(14), (180/np.pi)**2, False, 'deg²'),
        ('joint_rmse_deg', 'Joint RMSE', range(14), (180/np.pi)**2, True, 'deg'),
        ('gripper_mse_mm2', 'Gripper MSE', range(14,16), 1e6, False, 'mm²'),
        ('gripper_rmse_mm', 'Gripper RMSE', range(14,16), 1e6, True, 'mm')]:
        ids = list(ids); x = np.arange(len(ids)); width = .75/len(arrays)
        fig, ax = plt.subplots(figsize=(16,6), layout='constrained')
        for k, a in enumerate(arrays):
            y = a[4][ORDER][ids]*scale
            if root: y = np.sqrt(y)
            ax.bar(x+(k-(len(arrays)-1)/2)*width, y, width, label=labels[k], color=COLORS[k], hatch=['','//','..','xx'][k])
        ax.set_xticks(x, [NAMES[i] for i in ids], rotation=40, ha='right'); ax.set_ylim(bottom=0)
        ax.set_ylabel(('RMSE' if root else 'MSE')+f' ({unit})'); ax.legend(fontsize=9)
        ax.set_title(f"{title} | real {split} | {report['frames']:,} frames · {report['validTimesteps']:,} valid H20 targets\nNo clipping; base channels and padded targets excluded")
        save(fig, name, title+f' ({unit})', 'summary')
    for ep, chunk in enumerate(arrays[0][3]):
        meta = report['models'][0]['byEpisode'][ep]; x = np.arange(len(chunk[0]))/20
        fig, axes = plt.subplots(4,4,figsize=(20,13),layout='constrained')
        for j, ax in enumerate(axes.flat):
            channel = ORDER[j]; scale = 1 if j < 14 else 1000
            ax.plot(x, chunk[1][:,0,channel]*scale, color='#333333', lw=1.8, label='Ground truth')
            for k, a in enumerate(arrays):
                ax.plot(x, a[3][ep][0][:,0,channel]*scale, color=COLORS[k], ls=STYLES[k], lw=1.2, label=labels[k])
            ax.set_title(NAMES[j]); ax.set_xlabel('Time (s)'); ax.set_ylabel('rad' if j<14 else 'mm')
        handles, legend_labels = axes.flat[0].get_legend_handles_labels()
        fig.legend(handles, legend_labels, loc='outside lower center', ncols=2, fontsize=10)
        title = f"Episode {ep:03d} · {meta['prompt']}"
        fig.suptitle(f'{title} | real {split} | first-step prediction at every 20 Hz frame\nIndependent channel scales; full values, no clipping; offline prediction only', fontsize=15)
        save(fig, f'episode_{ep:03d}_joints', title, 'episode')
    csv_path = out/'per_joint_mse.csv'
    with csv_path.open('w', newline='', encoding='utf8') as f:
        writer = csv.writer(f); writer.writerow(['checkpoint_id','checkpoint_label','dimension','mse','mse_unit','rmse','rmse_unit','mse_deg2','rmse_deg'])
        for k, a in enumerate(arrays):
            for j, channel in enumerate(ORDER):
                mse = a[4][channel]*(1 if j<14 else 1e6)
                writer.writerow([report['models'][k]['id'],labels[k],NAMES[j],mse,'rad^2' if j<14 else 'mm^2',np.sqrt(mse),'rad' if j<14 else 'mm',mse*(180/np.pi)**2 if j<14 else '',np.sqrt(mse)*180/np.pi if j<14 else ''])
    files.append(csv_path)
    provenance = dict(schema='studio_mse_figures/1', jobId=run.name, sourceReportSha256=hashlib.sha256((run/'report.json').read_bytes()).hexdigest(),
                      protocol=report['protocol'], checkpointIds=[m['id'] for m in report['models']], images=images,
                      frames=report['frames'], validTimesteps=report['validTimesteps'], noClipping=True,
                      units={'arms':'rad / rad² / deg² / deg','grippers':'mm / mm²'}, traces='first step at every 20 Hz frame',
                      notRobotSuccessRate=True, sourceArraysRemainOnGpu=True)
    write(out/'provenance.json', provenance); files.append(out/'provenance.json')
    with zipfile.ZipFile(out/'mse_figures.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in files: z.write(p,p.name)
    files.append(out/'mse_figures.zip')
    manifest = dict(provenance, files=[dict(name=p.name, bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files], createdAt=time.time())
    write(out/'manifest.json',manifest)
    write(out/'progress.json',dict(stage='completed',completed=len(images),total=total,heartbeat_unix=time.time()))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--run',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); render(args.run,args.output)
