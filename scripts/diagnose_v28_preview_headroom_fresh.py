"""Authorized frozen v28 single-field headroom ablation, two fresh scenes."""
import argparse,json,os,pathlib,subprocess,sys,time,hashlib


def main():
 p=argparse.ArgumentParser();p.add_argument('--release',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--archive-sha',required=True);a=p.parse_args()
 release=a.release.resolve();output=a.output.resolve()
 if output.exists() or release in output.parents:raise ValueError('Must use new collection outside frozen release')
 original=release/'configs/airport_clock_step_preview.json';before=json.loads(original.read_text());after=dict(before);after['empty_arm_shortcut_headroom_enabled']=True
 differences={k:[before.get(k),after.get(k)] for k in before.keys()|after.keys() if before.get(k)!=after.get(k)}
 if differences!={'empty_arm_shortcut_headroom_enabled':[False,True]}:raise ValueError('Expected only explicit headroom switch')
 if after['max_attempts_per_scene']!=1:raise ValueError('Exactly one attempt required')
 config=output.parent/(output.name+'.config.json');config.parent.mkdir(parents=True,exist_ok=True)
 if config.exists():raise ValueError('Do not overwrite prior diagnostic config')
 config.write_text(json.dumps(after,indent=2))
 hashes={str(p.relative_to(release)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((release/'r1pro_teleop').rglob('*.py'))}
 record=dict(qualification='fresh_complete_episodes_two_cases_not_general_success_rate',release=str(release),archive_sha256=a.archive_sha,source_files_sha256=hashes,source_manifest_sha256=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(),config_difference=differences,original_config=str(original),original_config_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),external_config=str(config),commands=[])
 env=os.environ.copy();env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONPATH=str(release));env.setdefault('MUJOCO_GL','egl')
 log=output.parent/(output.name+'.driver.log');start=time.monotonic()
 def run(parts):
  command=[sys.executable,'-m','r1pro_teleop.airport_fsm']+parts;t=time.monotonic()
  with log.open('a') as f:
   f.write(json.dumps(command)+'\n');f.flush();done=subprocess.run(command,cwd=release,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=3600)
  row=dict(command=command,returncode=done.returncode,wall_s=time.monotonic()-t);record['commands'].append(row);print(json.dumps(row),flush=True)
  if done.returncode:raise RuntimeError('Phase returned nonzero; preserve failure evidence')
 try:
  reference=json.loads((release/'runs/ablation/step_preview/collection.json').read_text())
  parts=['prepare','--manifest',str(release/'resources/scenes/server_v7/manifest.json'),'--output',str(output),'--config',str(config)]
  if reference.get('half_turn_equivalent'):parts.append('--half-turn-equivalent')
  run(parts)
  rows=json.loads((output/'scenes/index.json').read_text());ids=[x['scene_id'] for x in rows if int(x['scene_id'].split('_')[1]) in (6,310)]
  if len(ids)!=2:raise ValueError('Exactly two selected scenes required')
  record['scene_ids']=ids
  run(['preflight','--root',str(output),'--workers','1','--scene-ids',*ids])
  run(['generate','--root',str(output),'--workers','1','--scene-ids',*ids])
  record['results']=[json.loads((output/'attempts'/scene/'a000/result.json').read_text()) for scene in ids]
  print(json.dumps([{k:r.get(k) for k in ('scene_id','physics_success','recovery_used','failure_code','frames','simulation_seconds')} for r in record['results']]),flush=True)
 finally:
  record['wall_s']=time.monotonic()-start
  if output.exists():(output/'diagnostic_driver.json').write_text(json.dumps(record,indent=2))

if __name__=='__main__':main()
