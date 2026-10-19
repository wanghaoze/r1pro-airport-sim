"""Two independent native replay workers, immutable source/reuse, no training."""
import datetime,hashlib,importlib.util,json,os,signal,subprocess,sys,time,traceback
from pathlib import Path
BASE=Path('/home/michelle/haoze/r1pro-airport-sim');ROOT=BASE/'runs/vla_20261001'
OUTPUT=ROOT/'native32_v4';OLD=ROOT/'native32_v2';RELEASE=BASE/'releases/vla_v13_20261001'
PYTHON='/home/michelle/miniconda3/envs/r1pro-vla/bin/python';PLAN=ROOT/'candidate_native32_source_plan.json'
CAMERAS={'head_left','head_right','left_wrist','right_wrist'}
OLD_SCRIPT=BASE/'diagnostictools/native32_v2_pipeline.py'
def load_old():
 spec=importlib.util.spec_from_file_location('native32_v2_definitions',OLD_SCRIPT);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
shared=load_old();digest=shared.digest;gpu=shared.gpu;dump=shared.dump

def verify_native(scene,path):
 m=json.loads(Path(path).read_text())
 if (m['status']!='complete' or m['trace_sha256']!=scene['trace_sha256'] or m['scene_xml_sha256']!=scene['scene_xml_sha256']
     or m['frames']!=scene['frames_native_replay'] or m['fps']!=20 or m['split']!='train'
     or set(m['camera_checks'])!=CAMERAS or m.get('replay_max_qpos_error',1)>1e-6):raise RuntimeError('reuse_native_identity:'+scene['scene_id'])
 if path.is_relative_to(OLD) or path.is_relative_to(OUTPUT):
  a=m['replay_velocity_time_audit']
  if not a['continuous_physical_replay'] or not a['no_frame_state_resets'] or a['initial_state_restores']!=1 or any(a[k]>1e-6 for k in ('per_frame_qvel_max_error','per_frame_sim_time_max_error','terminal_qvel_max_error','terminal_sim_time_error')):raise RuntimeError('reuse_native_replay_audit')
 if {r['camera']for r in m['references']}!=CAMERAS:raise RuntimeError('reuse_camera_reference_coverage')
 for r in m['references']:
  check=m['camera_checks'][r['camera']]
  if check['frames']!=m['frames'] or check['blank_frames'] or r['trace_sha256']!=scene['trace_sha256'] or digest(r['path'])!=r['sha256']:raise RuntimeError('reuse_native_video_hash_or_blank')
  measured=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=width,height,avg_frame_rate,nb_read_frames','-of','json',r['path']],text=True))['streams'][0]
  numerator,denominator=map(int,measured['avg_frame_rate'].split('/'))
  if (int(measured['nb_read_frames'])!=m['frames'] or numerator/denominator!=20 or
      (measured['height'],measured['width'],3)!=tuple(check['shape'])):raise RuntimeError('reuse_native_ffprobe_mismatch')
 return m

def main():
 plan=json.loads(PLAN.read_text());scenes=plan['scenes'];ids={s['scene_id']for s in scenes};collection=Path(plan['source_collection'])
 status=dict(stage='waiting_v3_remaining_renderer_natural_completion',pid=os.getpid(),output=str(OUTPUT),workers=2,training_started=False,training_ready=False,rendered_new=0,reused_original=0,reused_v2=0,source_plan_sha256=digest(PLAN),source_collection=str(collection),source='simulation/program_generated',egl_enum=1,physical_gpu_required=0)
 def persist(stage=None,**data):
  if stage:status['stage']=stage
  status.update(data,updated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat());dump(OUTPUT/'status.json',status)
  print(json.dumps(status),flush=True)
 env=dict(os.environ,MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID='1',CUDA_VISIBLE_DEVICES='0',HF_HOME=str(BASE/'resources/hf_cache'),HF_LEROBOT_HOME=str(ROOT/'lerobot'),OPENPI_DATA_HOME=str(BASE/'resources/openpi_cache'),OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
 def execute(cmd,log,stage):
  persist(stage,command=cmd)
  with (OUTPUT/log).open('x')as f:
   proc=subprocess.Popen(cmd,cwd=RELEASE,env=env,stdout=f,stderr=subprocess.STDOUT);persist(process_pid=proc.pid);code=proc.wait()
  if code:raise RuntimeError(stage+'_exit_'+str(code))
 active={}
 try:
  migration=json.loads((OUTPUT/'migration.json').read_text());sid=migration['scene_id'];current=next(s for s in scenes if s['scene_id']==sid)
  current_manifest=OLD/'native'/sid/current['attempt']/'manifest.json';persist(current_old_renderer_pid=migration['current_renderer_pid'],current_scene=sid)
  while True:
   stat=Path('/proc')/str(migration['current_renderer_pid'])/'stat'
   if not stat.exists() or stat.read_text().split()[2]=='Z':break
   time.sleep(10)
  natural=verify_native(current,current_manifest)
  migration.update(status='remaining_v3_renderer_completed_naturally',old_renderer_manifest=str(current_manifest),old_renderer_manifest_sha256=digest(current_manifest),old_renderer_qpos_error=natural['replay_max_qpos_error'],old_renderer_velocity_time_audit=natural['replay_velocity_time_audit'],old_renderer_signalled=False,output_routing_fix='set_shared_OUTPUT_not_unused_OUT')
  dump(OUTPUT/'migration.json',migration)
  if len(ids)!=32 or digest(plan['source_manifest'])!=plan['source_manifest_sha256'] or json.loads((collection/'collection.json').read_text())['fingerprint']!=plan['collection_fingerprint']:raise RuntimeError('source_plan_identity_changed')
  references=[];remaining=[];reuse=[]
  for s in scenes:
   for path,sha in ((s['trace'],s['trace_sha256']),(Path(s['trace']).with_name('result.json'),s['result_sha256']),(collection/'scenes'/s['scene_id']/'scene.json',s['scene_json_sha256']),(collection/'scenes'/s['scene_id']/'mobile.xml',s['scene_xml_sha256'])):
    if digest(path)!=sha:raise RuntimeError('source_hash_changed:'+str(path))
   original=ROOT/'native'/s['scene_id']/s['attempt']/'manifest.json';previous=OLD/'native'/s['scene_id']/s['attempt']/'manifest.json'
   if s['native_four_ready']:path=original;key='reused_original'
   elif previous.exists() and json.loads(previous.read_text()).get('status')=='complete':path=previous;key='reused_v2'
   else:remaining.append(s);continue
   manifest=verify_native(s,path);references.extend(manifest['references']);status[key]+=1
   reuse.append(dict(scene_id=s['scene_id'],manifest=str(path),manifest_sha256=digest(path),trace_sha256=s['trace_sha256'],scene_xml_sha256=s['scene_xml_sha256']))
  dump(OUTPUT/'source_plan.json',plan);dump(OUTPUT/'reused_sources.json',reuse)
  persist('rendering_native',remaining_scene_ids=[s['scene_id']for s in remaining],reused_sources_sha256=digest(OUTPUT/'reused_sources.json'))
  pending=list(remaining)
  while pending or active:
   resources=gpu()
   while pending and len(active)<2 and resources[0]['free_mib']>6144:
    s=pending.pop(0);attempt=collection/'attempts'/s['scene_id']/s['attempt'];command=['nice','-n','10',PYTHON,str(Path(__file__).resolve()),'--one',str(attempt)]
    log=(OUTPUT/('render_'+s['scene_id']+'.log')).open('x');proc=subprocess.Popen(command,cwd=RELEASE,env=env,stdout=log,stderr=subprocess.STDOUT)
    active[proc.pid]=dict(process=proc,scene=s,log=log,gpu_seen=False,command=command)
    persist(active_workers=[dict(pid=pid,scene_id=v['scene']['scene_id'],command=v['command'])for pid,v in active.items()]);resources=gpu()
   for pid,job in list(active.items()):
    matches=[(g['index'],p)for g in resources for p in g['processes']if p['pid']==pid]
    if matches:
     if any(index!=0 for index,_ in matches):job['process'].terminate();job['process'].wait(timeout=15);raise RuntimeError('own_native_worker_wrong_gpu')
     job['gpu_seen']=True
    code=job['process'].poll()
    if code is None:continue
    job['log'].close()
    if code or not job['gpu_seen']:raise RuntimeError('native_worker_failed_or_gpu_unobserved:'+str(pid))
    s=job['scene'];path=OUTPUT/'native'/s['scene_id']/s['attempt']/'manifest.json';m=verify_native(s,path);references.extend(m['references']);del active[pid]
    persist('native_case_complete',rendered_new=status['rendered_new']+1,case_manifest=str(path),active_workers=[dict(pid=p,scene_id=v['scene']['scene_id'])for p,v in active.items()],gpu0_free_mib=resources[0]['free_mib'])
   if pending and not active and resources[0]['free_mib']<=6144:persist('waiting_gpu0_headroom',gpu0_free_mib=resources[0]['free_mib'])
   if pending or active:time.sleep(10)
  if len(references)!=128:raise RuntimeError('final_native_reference_count')
  refs=OUTPUT/'video_references.json';dump(refs,references);dump(OUTPUT/'native_status.json',dict(status='complete',selected=32,references=str(refs),references_sha256=digest(refs),source_plan_sha256=digest(PLAN),new_scenes=status['rendered_new'],reused_v2=status['reused_v2'],reused_original=status['reused_original']))
  inventory=OUTPUT/'inventory_all400.jsonl';execute([PYTHON,str(RELEASE/'scripts/prepare_vla_dataset.py'),'--collection',str(collection),'--output',str(inventory),'--video-references',str(refs),'--verify-videos'],'prepare.log','preparing_verified_inventory')
  selected=OUTPUT/'segments_native32_v3.jsonl'
  with selected.open('x')as target:
   for line in inventory.open():
    if json.loads(line)['scene_id']in ids:target.write(line)
  sys.path.insert(0,str(RELEASE));from r1pro_teleop.vla.data_quality_audit import audit_manifest
  audit=audit_manifest(selected)
  if audit['scene_count']!=32 or not audit['all_scenes_initialize']or not audit['all_source_lifts_qualified']or audit['qualified_lift_operations']!=113:raise RuntimeError('qualification_audit_failed')
  dump(OUTPUT/'quality_audit.json',audit)
  destination=ROOT/'lerobot/airport/pi05_native32_v3'
  execute([PYTHON,str(RELEASE/'scripts/convert_vla_lerobot.py'),'--manifest',str(selected),'--destination',str(destination),'--repo-id','airport/pi05_native32_v3'],'convert.log','converting_lerobot')
  training=json.loads((destination/'airport_training_manifest.json').read_text());info=json.loads((destination/'meta/info.json').read_text());frames=sum(e['frames']for e in training['episodes'])
  if {e['scene_id']for e in training['episodes']}!=ids or any(e['split']!='train'for e in training['episodes'])or info['total_frames']!=frames or not training['official_loader_every_episode_first_last']or training['training_video_encoding_verification'].get('verified')is not True:raise RuntimeError('final_training_contract')
  audit_path=OUTPUT/'source_superset_audit.json'
  command=[PYTHON,'-m','r1pro_teleop.vla.data_lineage','--parent-dataset',str(ROOT/'lerobot/airport/pi05_native16_v3'),'--child-dataset',str(destination),'--output',str(audit_path)]
  persist('auditing_source_superset',command=command)
  with (OUTPUT/'source_superset_audit.log').open('x')as f:
   code=subprocess.call(command,cwd=BASE/'diagnostictools/model_observation_candidate',env=env,stdout=f,stderr=subprocess.STDOUT)
  if code:raise RuntimeError('source_superset_audit_failed')
  lineage=json.loads(audit_path.read_text())
  if not lineage['verified'] or lineage['datasets'][0]['scene_count']!=16 or lineage['datasets'][1]['scene_count']!=32:raise RuntimeError('source_superset_final_contract')
  persist('complete',dataset=str(destination),frames=frames,episodes=len(training['episodes']),verified_native_streams=128,qualified_lifts=113,all_initializations=32,official_loader_verified=True,codec_verification=training['training_video_encoding_verification'],source_superset_audit=str(audit_path),source_superset_audit_sha256=digest(audit_path),source_manifest_sha256=digest(selected),training_manifest_sha256=digest(destination/'airport_training_manifest.json'),training_ready=True)
 except BaseException as exc:
  persist('failed',error=repr(exc),traceback=traceback.format_exc(),training_ready=False,remaining_active_worker_pids=list(active));raise
if __name__=='__main__':
 if '--one' in sys.argv:
  attempt=Path(sys.argv[sys.argv.index('--one')+1]).resolve()
  if Path.cwd()!=RELEASE or not attempt.is_relative_to(BASE/'releases/robust_v64_20260930/runs/v64_approximate_400/approximate_completion/attempts'):
   raise RuntimeError('native_worker_route_cwd_or_source_invalid')
  shared.OUTPUT=OUTPUT
  if shared.OUTPUT!=OUTPUT:raise RuntimeError('native_worker_output_owner_invalid')
  expected=OUTPUT/'native'/attempt.parent.name/attempt.name/'manifest.json'
  if expected.parent.exists():raise RuntimeError('native_worker_output_must_be_exclusive')
  shared.worker(str(attempt))
  if not expected.is_file():raise RuntimeError('native_worker_expected_output_missing')
  manifest=json.loads(expected.read_text())
  if any(not Path(ref['path']).resolve().is_relative_to(expected.parent.resolve())for ref in manifest['references']):raise RuntimeError('native_worker_video_route_invalid')
  manifest['worker_output_routing_audit']=dict(expected_output_root=str(OUTPUT),actual_manifest=str(expected),actual_cwd=str(Path.cwd()),actual_argv=sys.argv,delegated_worker_module=str(OLD_SCRIPT),delegated_worker_module_sha256=digest(OLD_SCRIPT),routing_attribute='OUTPUT',source_attempt=str(attempt))
  dump(expected,manifest)
 elif '--launch' in sys.argv:
  if (OUTPUT/'status.json').exists():raise RuntimeError('refuse_existing_v3_supervisor')
  log=(OUTPUT/'pipeline.log').open('x');proc=subprocess.Popen(['nice','-n','10',PYTHON,str(Path(__file__).resolve())],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,cwd=BASE);print(proc.pid,flush=True)
 else:main()
