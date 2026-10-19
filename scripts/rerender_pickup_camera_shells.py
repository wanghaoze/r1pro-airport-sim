"""New video/data version of immutable pickup traces; renderer-only shell hide.

Recorded integration states are rendered frame by frame. This is not a new
physics rollout or evaluation. Model, camera and trajectory arrays stay intact.
"""
from __future__ import annotations
import argparse, importlib.util, json, os, shutil, subprocess, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get('VLA_CODE_ROOT', str(ROOT)))

def load_helper(name):
    spec=importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def write(path,value):
    p=Path(path);temporary=p.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,indent=2,allow_nan=False));temporary.replace(p)

def shell_ids(model):
    ids=[]
    for side in ('left','right'):
        body=model.body(side+'_realsense_link').id
        mesh=model.mesh(side+'_realsense_link').id
        matches=np.flatnonzero((model.geom_bodyid==body)&(model.geom_dataid==mesh)&(model.geom_group==1))
        if len(matches)!=1:raise ValueError('camera_shell_visual_not_unique')
        gid=int(matches[0])
        if model.geom_contype[gid] or model.geom_conaffinity[gid]:raise ValueError('camera_shell_selected_physical_geom')
        ids.append(gid)
    return ids

def hide_scene_shells(scene,ids,geom_type):
    hidden=[]
    for geom in scene.geoms[:scene.ngeom]:
        if geom.objtype==geom_type and geom.objid in ids:
            geom.rgba[3]=0.;hidden.append(int(geom.objid))
    if sorted(hidden)!=sorted(ids):raise ValueError('camera_shell_renderer_geometry_missing')

def collect(args,index):
    import h5py,mujoco
    from r1pro_teleop.airport_fsm.contracts import Config
    from r1pro_teleop.single_tray_3table.control import ThreeTableRuntime
    from r1pro_teleop.vla.observations import model_render_shape
    from openpi_client.image_tools import resize_with_pad
    helper=load_helper('generate_pickup_lerobot');video=load_helper('run_vla_fixed_scene')
    rows=[json.loads(line) for line in (Path(args.source)/'episodes.jsonl').read_text().splitlines()]
    row=rows[index];source=Path(row['source_case']);case=Path(args.output)/'cases'/f'episode_{index:06d}'
    case.mkdir(parents=True,exist_ok=False);(case/'videos').mkdir();(case/'attempt').mkdir()
    files=[source/'scene.json',source/'mobile.xml',source/'result.json',source/'attempt/trace.h5']
    before={str(p):helper.sha(p) for p in files}
    scene=json.loads(files[0].read_text());runtime=None;writers={}
    started=time.monotonic()
    try:
        with h5py.File(files[-1]) as trace:
            metadata=json.loads(trace.attrs['metadata_json']);cfg=Config.load(args.config)
            if json.loads(json.dumps(cfg.dump()))!=metadata['config']:raise ValueError('camera_rerender_source_config_changed')
            runtime=ThreeTableRuntime(scene,cfg,render=True);m,d=runtime.m,runtime.d
            if int(metadata['integration_state_spec'])!=int(runtime.integration_spec):raise ValueError('camera_rerender_state_spec_changed')
            ids=shell_ids(m)
            # Entire model numeric storage is snapshotted. Neither model alpha
            # nor physical arrays are edited; only the temporary MjvScene is.
            model_arrays={name:getattr(m,name).copy() for name in dir(m) if isinstance(getattr(m,name),np.ndarray)}
            renderers={}
            for camera in helper.CAMERAS:
                h,w,_=model_render_shape(runtime.sim.camera_shapes[camera],224)
                renderer=mujoco.Renderer(m,height=h,width=w)
                runtime.sim._camera_renderers[('shellless',camera)]=renderer;renderers[camera]=renderer
                writers[camera]=video.DiagnosticVideoWriter(case/'videos'/f'{camera}.mp4',(224,224,3))
            count=int(trace.attrs['num_frames'])
            if count!=row['frames']:raise ValueError('camera_rerender_source_frame_count_changed')
            for i in range(count):
                mujoco.mj_setState(m,d,np.asarray(trace['integration_state'][i]),runtime.integration_spec)
                mujoco.mj_forward(m,d)
                if not np.array_equal(d.qpos,trace['qpos'][i]) or not np.array_equal(d.qvel,trace['qvel'][i]):raise ValueError('camera_rerender_recorded_pose_mismatch')
                for camera,renderer in renderers.items():
                    renderer.update_scene(d,camera=camera,scene_option=runtime.sim.options)
                    for flag in (mujoco.mjtRndFlag.mjRND_SHADOW,mujoco.mjtRndFlag.mjRND_REFLECTION):renderer.scene.flags[flag]=False
                    hide_scene_shells(renderer.scene,ids,int(mujoco.mjtObj.mjOBJ_GEOM))
                    image=resize_with_pad(renderer.render().copy(),224,224)
                    writers[camera].write(image)
                    if i in (0,count//2,count-1):
                        from PIL import Image
                        Image.fromarray(image).save(case/f'{camera}_{i:04d}.png')
            if any(not np.array_equal(getattr(m,name),value) for name,value in model_arrays.items()):raise ValueError('camera_rerender_model_arrays_mutated')
        for writer in writers.values():writer.close()
        if before!={str(p):helper.sha(p) for p in files}:raise ValueError('camera_rerender_original_source_mutated')
        for original in files[:3]:shutil.copyfile(original,case/original.name)
        # Immutable original raw trace, not a synthesized/relabelled rollout.
        (case/'attempt/trace.h5').symlink_to(files[-1])
        result=json.loads(files[2].read_text());result['case']=str(case)
        receipt=dict(stage='rendered',episode_index=index,source_case=str(source),source_sha256=before,frames=count,
            hidden_visual_geom_ids=ids,hidden_visual_bodies=['left_realsense_link','right_realsense_link'],
            trajectory_changed=False,model_arrays_unchanged=True,gripper_shells_preserved=True,
            camera_pose_changed=False,physics_rollout=False,state_restores=count,physics_steps=0,
            wall_seconds=time.monotonic()-started)
        write(case/'render_receipt.json',receipt)
        return result
    finally:
        for writer in writers.values():writer.close()
        if runtime is not None:runtime.sim.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('source','output','config'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--worker',type=int);parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--limit',type=int,default=200);parser.add_argument('--render-only',action='store_true')
    args=parser.parse_args()
    if args.worker is not None:
        print(json.dumps(collect(args,args.worker)));return
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False);(out/'logs').mkdir();(out/'cases').mkdir()
    started=time.monotonic();results={}
    write(out/'status.json',dict(stage='rendering',rendered=0,target=args.limit,training_started=False))
    def run(index):
        argv=[sys.executable,str(Path(__file__).resolve()),'--source',args.source,'--output',args.output,'--config',args.config,'--worker',str(index)]
        with (out/'logs'/f'episode_{index:06d}.log').open('x') as log:
            proc=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            if proc.wait()!=0:raise RuntimeError('camera_rerender_worker_failed:'+str(index))
        original=json.loads((Path(args.source)/'episodes.jsonl').read_text().splitlines()[index])
        result=json.loads((Path(original['source_case'])/'result.json').read_text());result['case']=str(out/'cases'/f'episode_{index:06d}')
        return result
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures={pool.submit(run,i):i for i in range(args.limit)}
            for future in as_completed(futures):
                results[futures[future]]=future.result()
                write(out/'status.json',dict(stage='rendering',rendered=len(results),target=args.limit,elapsed_seconds=time.monotonic()-started,training_started=False))
        if args.render_only:
            write(out/'status.json',dict(stage='rendered_smoke',episodes=len(results)));return
        helper=load_helper('generate_pickup_lerobot');args.target=args.limit
        write(out/'status.json',dict(stage='exporting',rendered=len(results),target=args.limit,training_started=False))
        helper.export(args,[results[i] for i in range(args.limit)])
        import pandas as pd
        for i in range(args.limit):
            relative=Path(f'data/chunk-000/episode_{i:06d}.parquet')
            old=pd.read_parquet(Path(args.source)/'lerobot'/relative);new=pd.read_parquet(out/'lerobot'/relative)
            for key in old.columns:
                if not np.array_equal(np.stack(old[key]),np.stack(new[key])):raise ValueError('camera_rerender_export_trajectory_changed:'+key)
        write(out/'status.json',dict(stage='ready',episodes=args.limit,dataset=str(out/'lerobot'),trajectory_arrays_exactly_unchanged=True,
            gripper_shells_preserved=True,camera_pose_changed=False,elapsed_seconds=time.monotonic()-started,training_started=False))
    except BaseException as error:
        write(out/'status.json',dict(stage='failed_preserving_originals_and_prefix',error=repr(error),rendered=len(results),training_started=False));raise

if __name__=='__main__':main()
