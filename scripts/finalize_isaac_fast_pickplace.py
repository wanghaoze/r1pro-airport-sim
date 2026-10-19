"""Audit closed native cases and concatenate original-speed action previews.

This reader never signals or restarts the native producer. It does not export
training data or change source result labels.
"""
import argparse
import fcntl
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_isaacsim_fast_pickplace import audit
from r1pro_teleop.vla.isaac_dataset import video_probe, sha


def atomic(path, value):
    temp = path.with_suffix(path.suffix + '.finalizer.tmp')
    temp.write_text(json.dumps(value, indent=2))
    temp.replace(path)


def checked_audit(case):
    report = audit(case)
    result = json.loads((case / 'result.json').read_text())
    arms = np.r_[0:7, 8:15]
    speeds = {}
    with np.load(case / 'native_trace.npz') as z:
        for span in result['actions']:
            lo, hi = span['start'], span['end']
            # Include the transition into the first command, not only later ones.
            rate = abs(np.diff(z['raw_action'][lo-1:hi, arms], axis=0)) * 20
            maximum = float(rate.max())
            speeds[span['prompt']] = maximum
            if maximum > 1.5 + 1e-7:
                report['errors'].append('actual_submitted_target_rate_exceeds_reference')
    report['maximum_target_rate_including_first_transition_rad_s'] = speeds
    report['passed'] = not report['errors']
    report['full_context_seconds'] = result['frames'] / 20
    report['preparation_seconds_before_pick'] = result['actions'][0]['start'] / 20
    report['initial_pose'] = result['case']['tray_pose']
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    planned = len(json.loads((run/'config.json').read_text())['cases'])
    lock = (run / 'finalizer.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stat = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()
    atomic(run / 'finalizer_identity.json', dict(pid=os.getpid(), start_ticks=stat[19],
           argv=Path('/proc/self/cmdline').read_text().split('\0')[:-1], cwd=str(Path.cwd())))
    reports = {}
    failures = {}
    try:
        while True:
            if not (run/'pipeline_status.json').exists():
                time.sleep(2)
                continue
            status = json.loads((run / 'pipeline_status.json').read_text())
            rows = json.loads((run / 'results.json').read_text()) if (run / 'results.json').exists() else []
            for row in rows:
                key = row['directory']
                if not row['passed'] or key in reports or failures.get(key,{}).get('attempt',0)>=3:
                    continue
                out = run / key / 'independent_audit_v2.json'
                if out.exists():
                    reports[key] = json.loads(out.read_text())
                    continue
                for attempt in range(3):
                    try:
                        report = checked_audit(run / key)
                        atomic(out, report)
                        reports[key] = report
                        break
                    except Exception as exc:
                        failures[key] = dict(error=repr(exc), attempt=attempt+1)
                        atomic(run / ('finalizer_' + key + '_attempt_' + str(attempt) + '.json'), failures[key])
                        time.sleep((2, 5, 10)[attempt])
            atomic(run / 'audit_summary.json', dict(stage='auditing' if status['stage'] not in ('complete', 'failed') else 'native_terminal',
                native_stage=status['stage'], source_cases=len(rows), raw_passed=sum(bool(r['passed']) for r in rows),
                independently_passed=sum(bool(r['passed']) for r in reports.values()), planned_cases=planned,
                reports={k: dict(passed=v['passed'], errors=v['errors'], actions=v['actions'], motion=v['motion'],
                            maximum_target_rate_including_first_transition_rad_s=v['maximum_target_rate_including_first_transition_rad_s'],
                            preparation_seconds_before_pick=v['preparation_seconds_before_pick']) for k,v in reports.items()},
                errors=failures, heartbeat_unix=time.time(), training_eligible=False, model_executed=False))
            if status['stage'] in ('complete', 'failed'):
                break
            time.sleep(10)
        accepted = [r for r in rows if reports.get(r['directory'], {}).get('passed') and r.get('overview')]
        products = {}
        for name, source in [('multi_pose_pickup', 'pick_up_the_tray_presentation.mp4'),
                             ('multi_pose_place', 'place_the_tray_presentation.mp4'),
                             ('multi_pose_audited_pair', 'presentation_6s.mp4')]:
            files = [run / r['overview'] for r in accepted]
            if source != 'presentation_6s.mp4':
                files = [p.parent / source for p in files]
            if not files:
                continue
            listing = run / (name + '.concat.txt')
            listing.write_text(''.join("file '" + str(p) + "'\n" for p in files))
            output = run / (name + '.mp4')
            if not output.exists():
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-n', '-f', 'concat', '-safe', '0',
                                '-i', str(listing), '-c', 'copy', str(output)], check=True)
            probe = video_probe(output)
            expected = len(files) * (120 if source == 'presentation_6s.mp4' else 60)
            if probe['frames'] != expected or probe['fps'] != 20:
                raise RuntimeError('montage_frame_count_or_rate_mismatch:' + name)
            products[name] = dict(path=str(output), sha256=sha(output), **probe, original_speed=True)
        summary = json.loads((run / 'audit_summary.json').read_text())
        summary.update(stage='complete', videos=products, actual_audited_cases=len(accepted),
                       all_planned_passed=len(accepted)==planned and status['stage']=='complete', heartbeat_unix=time.time())
        atomic(run / 'audit_summary.json', summary)
        text = '<!doctype html><meta charset="utf-8"><title>原速多位姿取放</title><style>body{font:17px sans-serif;background:#15191f;color:#eee;max-width:1200px;margin:32px auto}video{width:100%}a{color:#8dcaff}</style>'
        text += '<h1>Isaac：原速3秒夹起 / 3秒放下</h1><p>独立物理复核通过：' + str(len(accepted)) + '/'+str(planned)+'；不是VLA模型测试，也不是完整三托盘训练来源。</p>'
        text += '<p>每段从预备臂姿开始；站位、导航与臂部预备另计，完整视频保留。所有短片均原速，无时间压缩。目标关节变化率≤1.5 rad/s；不等于实际机械速度保证或真机安全验证。</p>'
        for name, label in [('multi_pose_pickup','多位姿夹起'), ('multi_pose_place','多位姿放下'), ('multi_pose_audited_pair','逐位姿夹起＋放下')]:
            if name in products:
                text += '<h2>'+label+'</h2><video controls preload="metadata" src="'+name+'.mp4"></video>'
        for row in rows:
            case = run / row['directory']
            result = json.loads((case/'result.json').read_text())
            audited = reports.get(row['directory'], {}).get('passed', False)
            text += '<h2>'+html.escape(row['case_id'])+' — '+('复核通过' if audited else '未通过或未闭合')+'</h2><p>初态：'+html.escape(str(result['case']['tray_pose']))+'</p>'
            if row.get('overview'):
                text += '<video controls preload="none" src="'+row['overview']+'"></video>'
            text += '<p><a href="'+row['directory']+'/presentation.mp4">完整预备过程</a> · <a href="'+row['directory']+'/result.json">真实结果</a> · <a href="'+row['directory']+'/independent_audit_v2.json">独立复核</a></p>'
        text += '<p><a href="audit_summary.json">总复核与速度统计</a> · <a href="real_train_motion_reference.json">真机train速度参考</a></p>'
        (run/'audited_viewer.html').write_text(text)
        atomic(run/'finalizer_exit.json', dict(returncode=0, unix=time.time(), actual_audited_cases=len(accepted)))
    except BaseException:
        atomic(run/'finalizer_exit.json', dict(returncode=1, unix=time.time(), error=traceback.format_exc()))
        raise


if __name__ == '__main__':
    main()
