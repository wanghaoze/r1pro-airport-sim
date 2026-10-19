"""Fresh frozen-v27 case60 episode, selected preflight and one worker only.

Execution requires the parent coordinator's explicit ready acknowledgement.
No private controller replacement, checkpoint, or existing collection writes.
"""
import argparse,json,os,pathlib,subprocess,sys,time


def main():
    p=argparse.ArgumentParser();p.add_argument('--release',type=pathlib.Path,required=True)
    p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--reference',type=pathlib.Path,required=True)
    p.add_argument('--confirmed-ready',action='store_true');args=p.parse_args()
    if not args.confirmed_ready:raise SystemExit('Parent server-core readiness confirmation required')
    release=args.release.resolve();output=args.output.resolve()
    if output.exists():raise SystemExit('Fresh output must not already exist')
    if release in output.parents:raise SystemExit('Diagnostic collection must be outside frozen release')
    config=release/'configs/airport_retiming_shortcut.json';baseline=release/'configs/airport_retiming_baseline.json'
    a=json.loads(baseline.read_text());b=json.loads(config.read_text())
    differing=[k for k in a.keys()|b.keys() if a.get(k)!=b.get(k)]
    if differing!=['empty_arm_shortcut_headroom_enabled'] or a[differing[0]] is not True or b[differing[0]] is not False:
        raise SystemExit('Frozen configuration pair is not a one-field timing ablation')
    if b['max_attempts_per_scene']!=1:raise SystemExit('Exactly one attempt required')
    reference=json.loads((args.reference/'collection.json').read_text())
    env=os.environ.copy();env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONPATH=str(release))
    env.setdefault('MUJOCO_GL','egl')
    commands=[];wall=time.monotonic();log=output.parent/(output.name+'.driver.log');log.parent.mkdir(parents=True,exist_ok=True)
    def run(parts):
        cmd=[sys.executable,'-m','r1pro_teleop.airport_fsm']+parts;start=time.monotonic()
        with log.open('a') as stream:
            stream.write(json.dumps({'command':cmd})+'\n');stream.flush()
            result=subprocess.run(cmd,cwd=release,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=2400)
        commands.append(dict(command=cmd,returncode=result.returncode,wall_s=time.monotonic()-start))
        print(json.dumps(commands[-1]),flush=True)
        if result.returncode:raise RuntimeError('Phase failed; preserve log and partial evidence')
    prepare=['prepare','--manifest',str(release/'resources/scenes/server_v7/manifest.json'),'--output',str(output),'--config',str(config)]
    if reference.get('half_turn_equivalent'):prepare.append('--half-turn-equivalent')
    try:
        run(prepare)
        rows=json.loads((output/'scenes/index.json').read_text());scene=next(x['scene_id'] for x in rows if int(x['scene_id'].split('_')[1])==60)
        run(['preflight','--root',str(output),'--workers','1','--scene-ids',scene])
        run(['generate','--root',str(output),'--workers','1','--scene-ids',scene])
        result=json.loads((output/'attempts'/scene/'a000/result.json').read_text())
        print(json.dumps({k:result.get(k) for k in ('scene_id','physics_success','failure_code','error','frames','simulation_seconds','operations')}),flush=True)
    finally:
        if output.exists():(output/'diagnostic_driver.json').write_text(json.dumps(dict(qualification='fresh_complete_episode_one_case_only_not_general_success_rate',config_pair_differences=differing,commands=commands,wall_s=time.monotonic()-wall),indent=2))

if __name__=='__main__':main()
