"""Thread handoff for independent teachers sharing one main-thread PhysX engine.

No Isaac API is called here. Observations are actual, room-local snapshots supplied
by the main engine loop; private MuJoCo is used only for kinematics, never stepped.
"""
import copy
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import numpy as np
from .isaac_mobile import mobile_targets
from .isaac_three_tray_observer import NativeTaskFault
from .isaac_three_tray_runtime import NativeRuntime
from .isaac_front_drift import FRONT_FIELDS


def validate_actor_order(expected,actual,*,kind,native_actual=None):
    """Check row identity before any indexed pose or joint initialization.

    RigidPrim's public paths may describe USD discovery rather than backend
    tensor ordering. Pass backend prim_paths too when the SDK exposes them.
    This function never silently sorts, remaps, or writes physical actors.
    """
    expected=list(expected);actual=list(actual)
    if not expected or len(set(expected))!=len(expected):
        raise ValueError('parallel_expected_actor_paths_not_unique:'+kind)
    if actual!=expected:
        raise ValueError('parallel_actor_order_mismatch:'+kind)
    if native_actual is not None and list(native_actual)!=expected:
        raise ValueError('parallel_native_actor_order_mismatch:'+kind)
    return dict(kind=kind,expected_paths=expected,public_paths=actual,
                native_paths=None if native_actual is None else list(native_actual),
                native_tensor_order_verified=native_actual is not None)


class RoomExchange:
    """One outstanding command per room; only its owner supplies feedback."""
    def __init__(self):
        self.owner=threading.get_ident();self.condition=threading.Condition()
        self.request=None;self.response=None;self.error=None;self.done=False

    def submit(self,command):
        with self.condition:
            if self.error is not None:raise self.error
            if self.done:raise RuntimeError('room_worker_already_finished')
            if self.request is not None:raise RuntimeError('room_duplicate_pending_tick')
            self.request=np.asarray(command,float).copy();self.response=None
            self.condition.notify_all()
            self.condition.wait_for(lambda:self.response is not None or self.error is not None)
            if self.error is not None:raise self.error
            response=self.response;self.response=None
            return response

    def pending(self):
        self.assert_owner()
        with self.condition:
            return None if self.request is None else self.request.copy()

    def complete(self,response):
        self.assert_owner()
        with self.condition:
            if self.request is None:raise RuntimeError('feedback_without_pending_room_tick')
            self.request=None;self.response=copy.deepcopy(response);self.condition.notify_all()

    def abort(self,error):
        with self.condition:
            self.error=error if isinstance(error,BaseException) else RuntimeError(str(error))
            self.request=None
            self.condition.notify_all()

    def finish(self):
        with self.condition:
            if self.request is not None:raise RuntimeError('room_finished_with_pending_tick')
            self.done=True;self.condition.notify_all()

    def assert_owner(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('native_main_thread_required')


class ParallelRoomRuntime:
    def __init__(self,room_id,output,model_xml,parent,size,base_origin,source_base_q,
                 initial_observation,initial_command,*,boundary_footprints=None,
                 initial_time=0.,mujoco_module=None):
        if mujoco_module is None:
            import mujoco as mujoco_module
        self.mj=mujoco_module
        self.model=self.mj.MjModel.from_xml_path(str(model_xml))
        self.shadow=self.mj.MjData(self.model)
        self.shadow.qpos[:]=self.model.key_qpos[0] if self.model.nkey else self.model.qpos0
        self.room_id=room_id;self.output=Path(output);self.output.mkdir(parents=True,exist_ok=True)
        self.parent=copy.deepcopy(parent);self.tables=self.parent['tables']
        self.size=np.asarray(size,float).copy();self.tray_ids=[f'tray_{i}' for i in range(len(self.size))]
        self.base_origin=np.asarray(base_origin,float).copy();self.source_base_q=dict(source_base_q)
        self.command=np.asarray(initial_command,float).copy()
        if self.command.shape!=(19,) or not np.isfinite(self.command).all():raise ValueError('invalid_initial_room_command')
        self.fixed_episode_base_command=self.command[16:].copy()
        self.boundary_footprints=copy.deepcopy(boundary_footprints or {})
        self._actual=copy.deepcopy(initial_observation);self.world=SimpleNamespace(current_time=float(initial_time))
        self.loaded=np.asarray(initial_observation.get('loaded',np.zeros(len(self.size))),bool).copy()
        self.initial_bottom=np.asarray(initial_observation['tray_pose'])[:,2].copy()
        self.frames=0;self.observer=None;self.context=None;self.manipulating=False;self.events=[]
        self.exchange=RoomExchange();self.raw_arrays={};self._closed=False
        self.sync_planner()

    yaw=staticmethod(NativeRuntime.yaw)
    front_ok=NativeRuntime.front_ok

    def write(self,name,value):
        path=self.output/name;temp=path.with_suffix(path.suffix+'.tmp')
        temp.write_text(json.dumps(value,indent=2));temp.replace(path)

    def event(self,name,**data):
        row=dict(event=name,room_id=self.room_id,frame=self.frames,
                 sim_time=float(self.world.current_time),**data)
        self.events.append(row)
        with (self.output/'events.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')

    def observation(self,*,force=False):
        obs=copy.deepcopy(self._actual)
        ok=self.front_ok(obs['robot_position'])
        obs.update(command=self.command.copy(),front_region_ok=ok,**self._front_diagnostics)
        return obs

    def sync_planner(self,obs=None):
        obs=self.observation() if obs is None else obs
        names=tuple(mobile_targets(np.asarray(obs['state'])))
        measured=np.asarray(obs['joint_position'],float)
        if measured.shape!=(len(names),) or not np.isfinite(measured).all():
            raise ValueError('actual_room_joint_feedback_required')
        # All 18 measured articulation joints, including each actual finger.
        # Never split a total opening or substitute a requested joint target.
        for name,value in zip(names,measured):
            self.shadow.qpos[self.model.jnt_qposadr[self.model.joint(name).id]]=value
        for name,value in zip(('agent_base_x','agent_base_y','agent_base_yaw'),obs['state'][16:]):
            self.shadow.qpos[self.model.jnt_qposadr[self.model.joint(name).id]]=self.source_base_q[name]+value
        for index,name in enumerate(self.tray_ids):
            adr=int(self.model.jnt_qposadr[int(self.model.body(name).jntadr[0])])
            self.shadow.qpos[adr:adr+7]=obs['tray_pose'][index]
        self.mj.mj_forward(self.model,self.shadow)

    def refresh_joint_feedback(self,state,sampled_at):
        self.exchange.assert_owner()
        with self.exchange.condition:
            self._actual={**self._actual,'state':np.asarray(state).copy(),'measured_wall_time':sampled_at}

    def pending_command(self):return self.exchange.pending()
    def take_request(self):
        """Non-destructive poll; command stays pending until complete_tick."""
        return self.pending_command()

    def complete_tick(self,observation,sim_time,frame_record):
        """Main thread only, after exactly 25 actual shared physical steps."""
        self.exchange.assert_owner()
        if frame_record.get('completed_real_substeps')!=25:
            raise ValueError('parallel_room_real_substeps_must_equal_25')
        for key in ('submitted_control','finger_contact_force','table_force','penetration'):
            value=np.asarray(frame_record[key])
            if len(value)!=25 or not np.isfinite(value).all():
                raise ValueError('parallel_room_invalid_actual_substeps:'+key)
        if any(not np.isfinite(np.asarray(observation[key])).all() for key in ('state','tray_pose')):
            raise NativeTaskFault('nonfinite_native_physics')
        self.exchange.complete(dict(observation=observation,sim_time=float(sim_time),record=frame_record))

    def tick(self,command=None,*,raw_command=None):
        command=self.command if command is None else np.asarray(command,float)
        if command.shape!=(19,) or not np.isfinite(command).all():raise NativeTaskFault('nonfinite_or_invalid_native_command')
        raw=command if raw_command is None else np.asarray(raw_command,float)
        if raw.shape!=(19,) or not np.isfinite(raw).all():raise NativeTaskFault('nonfinite_or_invalid_native_raw_command')
        if not np.array_equal(command[16:],self.fixed_episode_base_command):raise NativeTaskFault('episode_fixed_base_command_changed')
        self.command=command.copy();before=self.observation();before_time=self.world.current_time
        result=self.exchange.submit(command);record=result['record']
        # Record real before/after feedback, never synthesize it from commands.
        self._actual=result['observation'];self.world.current_time=result['sim_time']
        if not np.isclose(self.world.current_time-before_time,.05,atol=2e-5,rtol=0):
            raise ValueError(f'parallel_room_actual_control_time_mismatch:{before_time}->{self.world.current_time}')
        frame=dict(time=before_time,state=before['state'],tray_pose=before['tray_pose'],
                   raw_action=raw.copy(),action=command.copy())
        for key in ('rigid_pose','long_edge_sign','payload_speed','payload_on_tray','boundary_ok',
                    'axis_error_rad','front_region_ok',*FRONT_FIELDS):
            if key in before:frame[key]=before[key]
        if 'loaded' in before:frame['payload_loaded']=before['loaded']
        if 'coat_positions' in before:frame['coat_positions']=before['coat_positions']
        for key in ('submitted_control','finger_contact_force','table_force','payload_rigid_support','penetration'):
            if key in record:frame[key]=record[key]
        for key,value in frame.items():self.raw_arrays.setdefault(key,[]).append(np.asarray(value).copy())
        with (self.output/'native_steps.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(frame=self.frames,completed_real_substeps=25,
                raw_action=raw.tolist(),applied_action=command.tolist(),sim_time=self.world.current_time,
                measured_state=np.asarray(before['state']).tolist(),
                submitted_control=np.asarray(record['submitted_control'])[-1].tolist()))+'\n')
        self.frames+=1;after=self.observation()
        if float(np.max(record['penetration']))>.02:
            self.event('native_hard_penetration',measured_m=float(np.max(record['penetration'])),existing_limit_m=.02)
            raise NativeTaskFault('native_hard_penetration_exceeded_2cm')
        if self.observer:self.observer.observe(after,self.frames)
        if self.manipulating and not after['front_region_ok']:
            if after['front_reference_strict'] and after['front_drift_m']>.05+1e-9:
                raise NativeTaskFault('native_base_drift_over_authorized_5cm')
            raise NativeTaskFault('native_table_side_manipulation')
        if self.frames%20==0:self.write('progress.json',dict(stage='native_parallel_room_running',
            room_id=self.room_id,frames=self.frames,sim_time=self.world.current_time,
            wall_unix=time.time(),action=self.observer.action if self.observer else None,training_started=False))
        return after

    def abort(self,error):self.exchange.abort(error)
    def worker_done(self):self.exchange.finish()

    def close_trace(self):
        """Call after worker completion; do not close the shared Isaac engine."""
        if self._closed:return
        if not self.exchange.done:raise RuntimeError('parallel_trace_close_before_worker_done')
        if self.raw_arrays:
            obs=self.observation()
            terminal=dict(time=self.world.current_time,state=obs['state'],tray_pose=obs['tray_pose'])
            for key in ('rigid_pose','long_edge_sign','payload_speed','payload_on_tray','boundary_ok',
                        'axis_error_rad','front_region_ok',*FRONT_FIELDS):
                if key in obs:terminal[key]=obs[key]
            if 'loaded' in obs:terminal['payload_loaded']=obs['loaded']
            for key,value in terminal.items():
                if key in self.raw_arrays:self.raw_arrays[key].append(np.asarray(value).copy())
            np.savez_compressed(self.output/'native_trace.npz',**{k:np.asarray(v) for k,v in self.raw_arrays.items()})
        self._closed=True


def run_room_controller(runtime,case):
    """Worker target. Physics and encoder completion remain main-thread owned."""
    import traceback
    from .isaac_diverse_pickplace import DiversePickPlace
    observer=SimpleNamespace(action=None,observe=lambda obs,frame:None)
    controller=None;error=None
    try:
        controller=DiversePickPlace(runtime,observer)
        controller.grasp_pitch_degrees=case.get('grasp_pitch_degrees',-30.)
        controller.contact_along_edge_offset_m=case.get('contact_along_edge_offset_m',0.)
        controller.align_pad_normal=case.get('align_pad_normal',True)
        controller.gripper_preload_target_m=case.get('gripper_preload_target_m',.008)
        controller.fixed_base_world=case['fixed_base_world']
        controller.search_front_stations=False
        controller.base_initialized_before_episode=True
        controller.reset_arms_after_preadjustment=case.get('reset_arms_after_preadjustment',False)
        controller.direct_grasp_only=case.get('direct_grasp_only',True)
        controller.lift_height_m=case.get('lift_height_m',.18)
        if case.get('initial_base_world')!=case['fixed_base_world']:
            raise ValueError('initialized_station_must_match_fixed_action_station')
        controller.run()
    except BaseException as exc:
        error=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
        runtime.write('failure.json',error)
    finally:
        spans=controller.spans if controller is not None else []
        complete=error is None and len(spans)==2 and all(s['passed'] and s.get('core_motion_frames',s['frames'])==60 for s in spans)
        runtime.worker_result=dict(schema='isaac_parallel_room_worker/1',passed=complete,
            scope='fixed_base_pickplace_pending_native_media_audit',room_id=runtime.room_id,
            model_executed=False,teacher_collection=True,training_eligible=False,
            case=copy.deepcopy(case),actions=copy.deepcopy(spans),error=error,
            frames=runtime.frames,raw_fps=20,playback_speed=1.,
            worker_completed=True,actual_child_wait=False,
            physics='isaacsim_physx_shared_single_engine',unix=time.time())
        runtime.write('worker_result.json',runtime.worker_result)
        runtime.worker_done()
    return runtime.worker_result
