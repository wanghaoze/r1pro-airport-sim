"""Native, original-speed three-second Pick/Place visual benchmark."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    cfg=json.loads(a.config.read_text());out=Path(cfg['output']);out.mkdir(parents=True,exist_ok=False);record_cameras=cfg.get('record_cameras',True)
    def write(name,value):
        path=out/name;temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,indent=2));temp.replace(path)
    write('status.json',dict(stage='initializing',scope='fast_pickplace_benchmark',training_eligible=False,pid=__import__('os').getpid()))
    from isaacsim import SimulationApp
    app=SimulationApp(dict(headless=True,active_gpu=0,physics_gpu=0,multi_gpu=False,fast_shutdown=True))
    runtime=None;controller=None;error=None;rc=1;encoders={}
    try:
        from r1pro_teleop.real2sim.isaac_three_tray_runtime import NativeRuntime
        from r1pro_teleop.real2sim.isaac_fast_pickplace import FastPickPlace
        from r1pro_teleop.real2sim.isaac_lab_visuals import apply_lab_visuals
        from pxr import UsdGeom,Gf
        from isaacsim.sensors.camera import Camera
        runtime=NativeRuntime(cfg['scene_root'],out,seed=cfg['seed'],episode_id=cfg['case_id'],
            initial_pose_overrides={'tray_0':cfg['tray_pose']},interpolate_commands=cfg.get('interpolate_commands',False),
            restore_rubber_torsion=cfg.get('restore_rubber_torsion',False),record=record_cameras,
            exact_collision_footprint=cfg.get('exact_collision_footprint',False),camera_resolutions=cfg.get('camera_resolutions'),
            initial_base_world=cfg.get('initial_base_world'))
        if record_cameras:
            write('visual_translation.json',apply_lab_visuals(runtime.stage,cfg['lab_assets'],runtime.model))
            camera_path='/FastPresentationCamera';prim=UsdGeom.Camera.Define(runtime.stage,camera_path)
            prim.CreateHorizontalApertureAttr(36.);prim.CreateVerticalApertureAttr(20.25);prim.CreateFocalLengthAttr(23.);prim.CreateClippingRangeAttr(Gf.Vec2f(.03,30.))
            view=Gf.Matrix4d().SetLookAt(Gf.Vec3d(2.4,-2.3,1.85),Gf.Vec3d(.3,0.,1.),Gf.Vec3d(0.,0.,1.)).GetInverse()
            UsdGeom.Xformable(prim).AddTransformOp().Set(view)
            presentation_resolution=tuple(cfg.get('presentation_resolution',[1920,1080]))
            if len(presentation_resolution)!=2 or min(presentation_resolution)<=0 or not np.isclose(presentation_resolution[0]/presentation_resolution[1],16/9):raise ValueError('presentation_aspect_changed')
            camera=Camera(prim_path=camera_path,name='presentation',frequency=20,resolution=presentation_resolution);camera.initialize();runtime.cameras['presentation']=camera
            log=(out/'presentation_encoder.log').open('wb');path=out/'presentation.mp4'
            argv=['ffmpeg','-nostdin','-v','error','-n','-f','rawvideo','-pix_fmt','rgb24','-s',f'{presentation_resolution[0]}x{presentation_resolution[1]}','-r','20','-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf','16','-threads','2',str(path)]
            runtime.encoders['presentation']=(subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log),path,log)
            for _ in range(12):runtime.world.render()
            image=np.asarray(camera.get_rgba());write('render_diagnostics.json',dict(shape=list(image.shape),rgb_mean=image[:,:,:3].mean(axis=(0,1)).tolist(),rgb_std=image[:,:,:3].std(axis=(0,1)).tolist(),overbright_channel_fraction=float((image[:,:,:3]>250).mean()),presentation_not_training_camera=True))
        observer=SimpleNamespace(action=None,observe=lambda obs,frame:None)
        controller_type=FastPickPlace
        if cfg.get('diverse_preadjustment',False):
            from r1pro_teleop.real2sim.isaac_diverse_pickplace import DiversePickPlace
            controller_type=DiversePickPlace
        controller=controller_type(runtime,observer);controller.grasp_pitch_degrees=cfg.get('grasp_pitch_degrees',-30.);controller.contact_along_edge_offset_m=cfg.get('contact_along_edge_offset_m',0.);runtime.observer=observer
        write('status.json',dict(stage='native_fast_pickplace_running',scope='fast_pickplace_benchmark',training_eligible=False,pid=__import__('os').getpid()))
        controller.align_pad_normal=cfg.get('align_pad_normal',False)
        controller.gripper_preload_target_m=cfg.get('gripper_preload_target_m',.012)
        controller.fixed_base_world=cfg.get('fixed_base_world')
        controller.search_front_stations=cfg.get('search_front_stations',False)
        controller.base_initialized_before_episode=cfg.get('initial_base_world') is not None
        controller.reset_arms_after_preadjustment=cfg.get('reset_arms_after_preadjustment',False)
        controller.direct_grasp_only=cfg.get('direct_grasp_only',False)
        if controller.base_initialized_before_episode:
            if not np.allclose(cfg['initial_base_world'],cfg['fixed_base_world']):
                raise ValueError('initialized_station_must_match_fixed_action_station')
        controller.lift_height_m=cfg.get('lift_height_m',.18)
        controller.run();rc=0
    except Exception as exc:
        error=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc());write('failure.json',error)
    finally:
        if runtime is not None:
            try:encoders=runtime.close()
            except Exception as exc:rc=1;write('recording_failure.json',dict(error=repr(exc),traceback=traceback.format_exc()))
        if any(x['returncode'] for x in encoders.values()):rc=1
        spans=controller.spans if controller is not None else []
        complete=(rc==0 and len(spans)==2 and all(s['passed'] and s.get('core_motion_frames',s['frames'])==60 for s in spans))
        trace=out/'native_trace.npz';motion={};stability=None
        if trace.exists() and len(spans):
            with np.load(trace) as z:
                arms=np.r_[0:7,8:15]
                for span in spans:
                    lo,hi=span['start'],span['end'];v=np.diff(z['state'][lo:hi+1,:16],axis=0)*20;target=np.diff(z['raw_action'][lo:hi,:16],axis=0)*20
                    motion[span['prompt']]=dict(measured_joint_speed_rad_s_quantiles=np.quantile(abs(v[:,arms]),[.5,.9,.99,.999]).tolist(),target_joint_speed_rad_s_quantiles=np.quantile(abs(target[:,arms]),[.5,.9,.99,.999]).tolist(),maximum_raw_gripper_m=float(z['raw_action'][lo:hi,[7,15]].max()),actual_seconds=span['simulation_seconds'])
                from r1pro_teleop.real2sim.isaac_path_stability import path_stability
                stability=path_stability(z,spans,json.loads((out/'native_mapping.json').read_text()))
                write('path_stability.json',stability)
        scope=('fixed_base_pickplace_candidate_pending_independent_audit' if cfg.get('collection_scope')=='fixed_base_pickplace' else 'independent_fast_pickplace_not_full_three_tray_task') if record_cameras else 'physics_only_probe_not_video_demo'
        write('result.json',dict(schema='isaac_fast_pickplace_benchmark/1',scope=scope,passed=complete,video_demo_complete=complete and record_cameras,model_executed=False,teacher_collection=True,training_eligible=False,case=cfg,actions=spans,motion=motion,error=error,frames=runtime.frames if runtime else 0,raw_fps=20,playback_speed=1.,native_encoders=encoders,preparation_and_navigation_recorded_separately=True,physics='isaacsim_physx',unix=time.time()))
        write('status.json',dict(stage='complete' if complete else 'failed',passed=complete,training_eligible=False,error=error))
        app.close(exit_code=0 if complete else 1)


if __name__=='__main__':main()
