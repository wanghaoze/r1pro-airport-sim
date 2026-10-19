"""Paired held-out simulation Pick/Place; direct model controls, no fallback."""
import argparse,dataclasses,hashlib,html,json,os,subprocess,sys,time,traceback
from pathlib import Path
import numpy as np

CODE=Path(__file__).resolve().parents[1]
ROOT=Path('/home/michelle/haoze/r1pro-airport-sim')
sys.path[:0]=[str(CODE),str(CODE/'scripts'),str(ROOT/'third_party/openpi/src'),str(ROOT/'third_party/openpi/packages/openpi-client/src')]
from r1pro_teleop.vla.real_sim_data import write,sha,PROMPTS,CAMERAS
MODELS={'real_only':ROOT/'runs/real_only_pi05_20261012_v1','mixed':ROOT/'runs/real_sim_pickplace_20261009_v3'}
SIM=ROOT/'runs/three_actions_gripper_preserved_20261007_v4/data_batch_v1'
VIDEO_CAMERAS=('head_left','head_right','left_wrist','right_wrist')


def forbid_solver(*args,**kwargs):
    raise RuntimeError('forbidden_teacher_IK_or_inverse_dynamics_call')


def prepare(run):
    rows=[json.loads(l) for l in (SIM/'source_records.jsonl').read_text().splitlines()]
    test=[e for e in rows if e['source']['split']=='test']
    train_parents={e['source']['parent_scene_id'] for e in rows if e['source']['split']=='train'}
    assert len(test)==10
    cases=[]
    for e in test:
        s=e['source'];assert s['parent_scene_id'] not in train_parents and s['parent_split']=='test'
        for key in ['trace','scene_json','scene_xml','result']:
            assert sha(s[key])==s[key+'_sha256'],key
        for seg in e['plan']['segments'][:2]:
            t=seg['task_index'];assert t in (0,1)
            cases.append(dict(case_id=f'case_{len(cases):03d}',source=s,start_frame=seg['start_frame'],task=t,prompt=PROMPTS[t]))
    assert [sum(c['task']==t for c in cases) for t in (0,1)]==[10,10]
    write(run/'frozen_cases.json',dict(cases=cases,source_manifest_sha256=sha(SIM/'source_records.jsonl'),
        seed_formula='20261012 + case_index*10000 + control_frame',fps=20,frames=1000,execute_steps=5,
        scope='independent_Pick_and_Place_not_whole_task',video='224x224 live observation previews; full physics traces retained'))


def model(run,name):
    import mujoco,h5py
    from flax import nnx
    from openpi.policies import policy_config
    from openpi_client.image_tools import resize_with_pad
    from r1pro_teleop.vla.training import TrainingSpec,build_openpi_config
    from r1pro_teleop.vla.training_accelerated import vision_parameter_filter
    from r1pro_teleop.vla.observations import model_render_shape
    from r1pro_teleop.airport_fsm.contracts import Config
    from r1pro_teleop.airport_fsm.trace import Trace
    from r1pro_teleop.single_tray_3table.control import ThreeTableRuntime
    from r1pro_teleop.single_tray_3table.learned import contact_snapshot,opposed_contact,place_completion
    from r1pro_teleop.single_tray_3table.observer import table_front_region_violation
    from run_vla_fixed_scene import restore_stage,advance_interval,DiagnosticVideoWriter
    status=json.loads((MODELS[name]/'pi05/training_status.json').read_text());assert status['stage']=='trained' and status['updates']==10000
    spec=TrainingSpec(**status['spec']);cfg=build_openpi_config(spec);cfg=dataclasses.replace(cfg,freeze_filter=nnx.Any(cfg.freeze_filter,vision_parameter_filter))
    cp=Path(status['checkpoint']);out=run/name;out.mkdir(exist_ok=False)
    write(out/'identity.json',dict(checkpoint=str(cp),metadata_sha256=sha(cp/'_CHECKPOINT_METADATA'),norms={str(p):sha(p) for p in (cp/'assets').rglob('*.json')},updates=10000,cases_sha256=sha(run/'frozen_cases.json')))
    policy=policy_config.create_trained_policy(cfg,cp)
    mujoco.mj_inverse=forbid_solver
    cases=json.loads((run/'frozen_cases.json').read_text())['cases'];results=[]
    for number,item in enumerate(cases):
        case=out/item['case_id'];case.mkdir();(case/'videos').mkdir();s=item['source'];scene=json.loads(Path(s['scene_json']).read_text());task=item['task']
        result=dict(case_id=item['case_id'],scene_id=s['scene_id'],parent_scene_id=s['parent_scene_id'],action=item['prompt'],success=False,frames=0,inference_calls=0,
            teacher_fallback_calls=0,ik_calls=0,inverse_solver_calls=0,online_state_resets=0,checkpoint=str(cp),initial_source_frame=item['start_frame'],
            scope='independent_action_from_recorded_physical_initial_state_not_full_task',video_resolution=[224,224],failure_reason='action_budget_exhausted')
        runtime=None;trace=None;writers={};started=time.monotonic();diagnostics=[]
        try:
            with h5py.File(s['trace']) as f:meta=json.loads(f.attrs['metadata_json'])
            write(case/'scene.json',scene);write(case/'config.json',meta['config'])
            runtime=ThreeTableRuntime(scene,Config.load(case/'config.json'),render=True)
            origin,_,initial_state=restore_stage(runtime,s['trace'],item['start_frame']);runtime.solve_pair=forbid_solver;runtime._inverse_ratio=forbid_solver
            result['initial_integration_sha256']=hashlib.sha256(initial_state.tobytes()).hexdigest();result['base_origin']=origin.tolist()
            trace=Trace(case/'attempt',dict(config=runtime.cfg.dump(),scene=scene,integration_state_spec=int(runtime.integration_spec),source_model_parameters=meta.get('source_model_parameters'),
                source='simulation/program_generated',controller_source='vla_generated',checkpoint=str(cp),fps=20,initial_source=s['trace'],initial_frame=item['start_frame'],base_origin=origin.tolist()))
            trace.file.attrs['image_storage']='Live PRE-action four-camera RGB videos at224; exact camera pose/FOV preserved; not native-resolution export'
            initial=float(runtime.observation()['min_z'][0]);held=0;seen=opposed_contact(contact_snapshot(runtime,scene),scene['tray']['size']);chunk=None;cursor=0;renderers={}
            for c in VIDEO_CAMERAS:
                h,w,_=model_render_shape(runtime.sim.camera_shapes[c],224);renderer=mujoco.Renderer(runtime.m,height=h,width=w)
                runtime.sim._camera_renderers[('paired_eval',c)]=renderer;renderers[c]=renderer;writers[c]=DiagnosticVideoWriter(case/'videos'/f'{c}.mp4',(224,224,3))
            for frame in range(1000):
                images={}
                for c,renderer in renderers.items():
                    renderer.update_scene(runtime.d,camera=c,scene_option=runtime.sim.options);images[c]=resize_with_pad(renderer.render().copy(),224,224)
                if chunk is None or cursor==5:
                    state=np.r_[runtime.sim.state(),runtime.sim.base_joint_state()-origin].astype(np.float32)
                    noise=np.random.default_rng(20261012+number*10000+frame).standard_normal((20,32)).astype(np.float32)
                    chunk=np.asarray(policy.infer(dict(state=state,prompt=item['prompt'],**{'image/'+c:images[c] for c in CAMERAS}),noise=noise)['actions'])
                    if chunk.shape!=(20,19) or not np.isfinite(chunk).all():raise ValueError('nonfinite_or_invalid_model_output')
                    cursor=0;result['inference_calls']+=1
                    np.savez_compressed(case/f'decision_{frame:04d}.npz',raw_actions=chunk,state=state,noise_seed=20261012+number*10000+frame)
                for c in VIDEO_CAMERAS:writers[c].write(images[c])
                row,error=advance_interval(runtime,chunk[cursor],origin,frame);trace.append(row);cursor+=1;result['frames']=trace.count
                if error:raise error
                obs=runtime.observation();contact=contact_snapshot(runtime,scene);opposed=opposed_contact(contact,scene['tray']['size']);seen=seen or opposed
                table_id=scene['source_table'] if task==0 else scene['target_table']
                table=next(t for t in scene['tables'] if t['table_id']==table_id) if isinstance(scene['tables'],list) else scene['tables'][table_id]
                side=bool(table_front_region_violation(table,runtime.d.body('base_link').xpos))
                if task==0:valid=bool(opposed and np.all(obs['gripper_contact_force'][0]>runtime.cfg.criteria.contact_n) and obs['table_contact'][0]==0 and obs['floor_contact'][0]==0 and obs['min_z'][0]-initial>=runtime.cfg.criteria.lifted_m and not side)
                else:valid=place_completion(contact,obs,scene,opposed_seen=seen,released=bool(np.all(obs['gripper_contact_force'][0]<runtime.cfg.criteria.contact_n)),front_violation=side)
                diagnostic=dict(frame=frame,opposed=bool(opposed),opposed_seen=bool(seen),front_violation=side,endpoint_valid=bool(valid),table_contact=int(obs['table_contact'][0]),floor_contact=int(obs['floor_contact'][0]),lift_m=float(obs['min_z'][0]-initial),gripper_forces=np.asarray(obs['gripper_contact_force'][0]).tolist())
                diagnostics.append(diagnostic);held=held+1 if valid else 0
                if frame%20==0:write(out/'progress.json',dict(stage='closed_loop',case_index=number,completed=len(results),total=20,current_case=item['case_id'],frames=frame+1,heartbeat_unix=time.time()))
                if held>=20:result.update(success=True,failure_reason=None);break
            result['final_diagnostic']=diagnostics[-1] if diagnostics else None
            if not result['success']:
                result['failure_reason']='tray_floor_contact' if diagnostics and diagnostics[-1]['floor_contact'] else 'no_stable_opposed_lift' if task==0 else 'no_stable_target_support_release_alignment'
        except Exception as error:
            result.update(error=repr(error),failure_reason='execution_error',infrastructure_error=True);(case/'exception.txt').write_text(traceback.format_exc())
        finally:
            for writer in writers.values():writer.close()
            if trace:trace.close(dict(qpos=runtime.d.qpos,qvel=runtime.d.qvel,time=float(runtime.d.time)))
            if runtime:result['inverse_solver_calls']=int(runtime.id_calls);runtime.sim.close()
            assert result['inverse_solver_calls']==0
            result['wall_seconds']=time.monotonic()-started
            write(case/'diagnostics.json',diagnostics);write(case/'result.json',result);results.append(result)
            cards=''.join(f'<h3>{c}</h3><video controls preload="metadata" width="480" src="videos/{c}.mp4"></video>' for c in VIDEO_CAMERAS)
            (case/'viewer.html').write_text('<!doctype html><meta charset="utf-8"><h1>'+html.escape(name+' / '+item['prompt'])+'</h1><p>'+html.escape(json.dumps(result))+'</p>'+cards)
            write(out/'progress.json',dict(stage='closed_loop',completed=len(results),total=20,successes=sum(x['success'] for x in results),heartbeat_unix=time.time()))
    write(out/'summary.json',dict(cases=results,groups={p:dict(tested=sum(x['action']==p for x in results),successes=sum(x['action']==p and x['success'] for x in results)) for p in PROMPTS[:2]},infrastructure_failures=sum(x.get('infrastructure_error',False) for x in results),whole_task_success_not_measured=True))


def supervise(run):
    import fcntl
    run.mkdir(parents=True,exist_ok=True);lock=(run/'pipeline.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    prepare(run);(run/'logs').mkdir()
    for name in MODELS:
        argv=[sys.executable,str(Path(__file__).resolve()),'--run',str(run),'--mode',name]
        with (run/'logs'/f'{name}.log').open('x') as f:p=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
        write(run/'logs'/f'{name}.launch.json',dict(pid=p.pid,argv=argv,cwd=str(ROOT),start_ticks=Path(f'/proc/{p.pid}/stat').read_text().rsplit(')',1)[1].split()[19]))
        while p.poll() is None:write(run/'pipeline_status.json',dict(stage=name,pid=os.getpid(),active_pid=p.pid,heartbeat_unix=time.time()));time.sleep(5)
        code=p.wait();write(run/'logs'/f'{name}.exit.json',dict(returncode=code))
        if code:write(run/'pipeline_status.json',dict(stage='failed',failed_stage=name,returncode=code));return
    summaries={n:json.loads((run/n/'summary.json').read_text()) for n in MODELS}
    for a,b in zip(summaries['real_only']['cases'],summaries['mixed']['cases']):assert a.get('initial_integration_sha256')==b.get('initial_integration_sha256') and a['case_id']==b['case_id']
    write(run/'comparison_summary.json',summaries)
    cards=['<!doctype html><meta charset="utf-8"><h1>π0.5 paired simulation: real-only vs mixed</h1><p>10 test scenes × Pick/Place per model; independent action initializations, not whole-task success. 20Hz, 50s maximum; no teacher/IK fallback. Live camera previews at224; traces contain all actual controls.</p>']
    for n,s in summaries.items():
        cards.append('<h2>'+n+'</h2><pre>'+html.escape(json.dumps(s['groups'],indent=2))+'</pre>')
        for c in s['cases']:cards.append(f'<p><a href="{n}/{c["case_id"]}/viewer.html">{c["case_id"]} {c["action"]} — {"SUCCESS" if c["success"] else "FAIL: "+str(c["failure_reason"])}</a></p>')
    (run/'index.html').write_text('\n'.join(cards));write(run/'pipeline_status.json',dict(stage='complete',active_pid=None,heartbeat_unix=time.time()))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--mode',choices=['supervise',*MODELS],required=True);a=p.parse_args()
    if a.mode=='supervise':supervise(a.run)
    else:model(a.run,a.mode)
