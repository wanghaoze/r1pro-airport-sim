"""Independent physical planning copies; previews never constitute actual success.

Machine.push invokes this only under its default-off final-placement switch.
The selected policy still executes normally with every actual physical guard.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass, replace, fields, is_dataclass
from enum import Enum
import hashlib
from pathlib import Path
import pickle
import re
import time
import traceback
import numpy as np
from mujoco import mjtState
from .contracts import Fault, atomic_json


CONTROL_FIELDS = frozenset({
    'loaded_command_reference_enabled', 'loaded_command_reference_scope',
    'push_yaw_feedback_enabled', 'push_yaw_feedback_scope',
    'push_yaw_feedback_additive_fallback_enabled',
})
_RUNTIME_OWNED = {'mj', 'cfg', 'spec', 'g', 'sim', 'm', 'd', 'shadow',
                  'inverse', 'evidence', 'trace'}
_SIM_OWNED = {'model', 'data', 'ik_data', 'renderer', 'options', '_camera_renderers'}
_MACHINE_OWNED = {'r', 'c', 'g', 'log', 'directory', 'scheduler'}


@dataclass(frozen=True)
class PushCandidate:
    name: str
    overrides: tuple[tuple[str, object], ...] = ()

    def config(self, original):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,47}',self.name):
            raise ValueError('Preview candidate name must be a safe path component')
        changes = dict(self.overrides)
        if len(changes) != len(self.overrides) or not changes.keys() <= CONTROL_FIELDS:
            raise ValueError('Preview candidates may change only declared control fields')
        return replace(original, **changes).validate()


@dataclass(frozen=True)
class PushSelection:
    candidate: PushCandidate
    preview_verified: bool
    summaries: tuple[dict, ...]
    wall_seconds: float


def _plain_fields(obj, excluded):
    fields = {key: value for key, value in vars(obj).items() if key not in excluded}
    for key,value in fields.items():_validate_context_value(value,key)
    return fields


def _validate_context_value(value, path):
    """Reject external trees/I/O/callback objects, including nested references."""
    if value is None or isinstance(value,(bool,int,float,str,bytes,Path,Enum,np.generic,mjtState)):
        return
    if isinstance(value,np.ndarray):
        if value.dtype.hasobject:raise ValueError('Cannot clone object array context: '+path)
        return
    if isinstance(value,np.random.Generator):return
    if isinstance(value,dict):
        for key,item in value.items():
            _validate_context_value(key,path+'.key')
            _validate_context_value(item,path+'.'+str(key))
        return
    if isinstance(value,(list,tuple,set,frozenset)):
        for item in value:_validate_context_value(item,path+'[]')
        return
    if is_dataclass(value) and type(value).__module__.startswith('r1pro_teleop.airport_fsm.'):
        for field in fields(value):_validate_context_value(getattr(value,field.name),path+'.'+field.name)
        return
    raise ValueError('Cannot clone external controller object or callback: '+path+' ('+type(value).__name__+')')


def _integration(runtime):
    value = np.empty(runtime.integration_size)
    runtime.mj.mj_getState(runtime.m, runtime.d, value, runtime.integration_spec)
    return value


def context_digest(machine):
    """Digest physical state and every copied Python control field, excluding I/O."""
    r = machine.r
    machine_fields = _plain_fields(machine, _MACHINE_OWNED)
    machine_fields.pop('_physical_preview_active', None)
    payload = (_integration(r), r.d.qacc_warmstart.copy(),
               _plain_fields(r, _RUNTIME_OWNED),
               _plain_fields(r.sim, _SIM_OWNED), machine_fields,
               {k: v for k, v in vars(machine.scheduler).items() if k != 'g'})
    return hashlib.sha256(pickle.dumps(payload, protocol=5)).hexdigest()


def clone_machine(source, directory, candidate=PushCandidate('original')):
    """Copy a direct live boundary into independent models/data/controller state.

    No remember_grasp, no live reset, no new grace timers or refreshed deadlines.
    The original wall_start is copied, so preview overhead consumes attempt time.
    """
    from .runtime import Runtime
    from .machine import Machine
    a = source.r
    if getattr(a.cfg, 'retained_support_integer_clock_enabled', False):
        a.validate_retained_clock_state()
    source_fields=_plain_fields(source,_MACHINE_OWNED)
    _plain_fields(a,_RUNTIME_OWNED)
    _plain_fields(a.sim,_SIM_OWNED)
    cfg = candidate.config(a.cfg)
    b = Runtime(copy.deepcopy(a.spec), a.sim.scene, cfg, render=False)
    try:
        # Copy the effective model as well: _limits must not be reapplied to a
        # shared model, nor may runtime model changes silently disappear.
        b.m = copy.copy(a.m)
        b.sim.model = b.m
        b.d = a.mj.MjData(b.m)
        b.sim.data = b.d
        b.shadow = a.mj.MjData(b.m)
        b.inverse = a.mj.MjData(b.m)
        b.sim.ik_data = a.mj.MjData(b.m)
        for key, value in _plain_fields(a, _RUNTIME_OWNED).items():
            setattr(b, key, copy.deepcopy(value))
        for key, value in _plain_fields(a.sim, _SIM_OWNED).items():
            setattr(b.sim, key, copy.deepcopy(value))
        for dest, src in ((b.d, a.d), (b.shadow, a.shadow),
                          (b.inverse, a.inverse), (b.sim.ik_data, a.sim.ik_data)):
            a.mj.mj_copyData(dest, b.m, src)
        if getattr(b.cfg, 'retained_support_integer_clock_enabled', False):
            b.validate_retained_clock_state()
        b.evidence = copy.copy(a.evidence)
        b.evidence.sim = b.sim
        for key, value in vars(a.evidence).items():
            if key != 'sim':setattr(b.evidence, key, copy.deepcopy(value))
        machine=object.__new__(type(source))
        for key,value in source_fields.items():
            setattr(machine,key,copy.deepcopy(value))
        # Preserve class-defined experimental behavior without rerunning its
        # constructor and resetting experiment/controller context.
        Machine.__init__(machine,b,directory)
        for key, value in source_fields.items():
            setattr(machine, key, copy.deepcopy(value))
        machine.scheduler = copy.deepcopy(source.scheduler)
        machine.scheduler.g = machine.g
        for key in ('fsm_state', 'phase', 'allowed_tray', 'target_slot'):
            setattr(b, key, copy.deepcopy(getattr(a, key)))
        if context_digest(source) != context_digest(machine):
            raise Fault('physical_preview_context_mismatch')
        machine._physical_preview_active = True
        machine.log.file.attrs['physical_preview'] = True
        machine.log.file.attrs['actual_episode_success_eligible'] = False
        machine.log.event('physical_preview_source', preview=True,
                          actual_episode_success_eligible=False,
                          source_step=a.steps, source_time=float(a.d.time),
                          candidate=candidate.name, controls=dict(candidate.overrides))
        return machine
    except BaseException:
        if b.trace is not None:b.trace.close()
        b.close()
        raise


def default_candidates():
    return (
        PushCandidate('original'),
        PushCandidate('command_reference', (
            ('loaded_command_reference_enabled', True),
            ('loaded_command_reference_scope', 'push'))),
        PushCandidate('yaw_feedback', (('push_yaw_feedback_enabled', True),)),
    )


def _check_attempt_budget(runtime):
    if (runtime.steps >= round(runtime.cfg.max_episode_seconds*runtime.cfg.fps)
            or time.monotonic()-runtime.wall_start > runtime.cfg.max_attempt_wall_seconds):
        if getattr(runtime.cfg, 'approximate_completion_enabled', False):
            recorder = getattr(runtime, 'record_strict_deviation', None)
            if recorder is not None:
                recorder('episode_budget_exhausted', {
                    'elapsed_physics_s': runtime.steps/runtime.cfg.fps,
                    'elapsed_wall_s': time.monotonic()-runtime.wall_start,
                    'qualification': 'diagnostic_only_approximate_completion_no_time_failure'})
            return
        raise Fault('episode_budget_exhausted')


def _save_terminal(runtime, directory):
    # Raw/1 trace rows precede the action; preserve an exact terminal failed
    # prefix as well, without pretending that an incomplete interval completed.
    np.savez_compressed(Path(directory)/'terminal_state.npz',
        integration_state=_integration(runtime),ctrl=runtime.d.ctrl.copy(),
        qacc_warmstart=runtime.d.qacc_warmstart.copy(),
        target=runtime.sim.target.copy(),base_target=runtime.sim.base_target.copy(),
        steps=np.int64(runtime.steps),physical_time=np.float64(runtime.d.time))


def eligible_push(machine, operation, *, separation, retained_side):
    return (not getattr(machine, '_physical_preview_active', False)
            and machine.c.fixed_primitives and not separation
            and not operation.temporary and operation.slot >= 0
            and retained_side in ('left', 'right')
            and machine.r.retained_contact == (operation.tray, retained_side)
            and machine.r.holding is None
            and getattr(machine.r, 'primitive_deadline_step', None) is None)


def choose_push_candidate(machine, operation, *, retained_side, directory,
                          candidates=None, max_candidates=3):
    """Select first fully verified private continuation, at most three policies.

    This function never executes or changes controls on the original Runtime.
    Actual execution must still use Machine.push and all normal final checks.
    """
    if not eligible_push(machine, operation, separation=False, retained_side=retained_side):
        raise ValueError('Physical preview requires retained final-placement push boundary')
    if type(max_candidates) is not int or not 1 <= max_candidates <= 3:
        raise ValueError('Physical preview candidate budget must be 1..3')
    proposals = tuple(default_candidates() if candidates is None else candidates)
    if (not proposals or proposals[0] != PushCandidate('original') or len(proposals) > 3
            or len({p.name for p in proposals})!=len(proposals)):
        raise ValueError('Original candidate must be first; at most three declared candidates')
    # Validate every declaration before running even the original candidate.
    configs = [p.config(machine.c) for p in proposals]
    start = time.monotonic();summaries=[];seen=set();fingerprint=context_digest(machine)
    selected=proposals[0];verified=False
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    for candidate,cfg in zip(proposals,configs):
        if len(summaries)>=max_candidates:break
        key=tuple((name,getattr(cfg,name)) for name in sorted(CONTROL_FIELDS))
        if key in seen:continue
        seen.add(key);_check_attempt_budget(machine.r)
        probe=None;t=time.monotonic();cpu=time.process_time()
        summary={'candidate':candidate.name,'overrides':dict(candidate.overrides),
                 'preview':True,'actual_episode_success_eligible':False,
                 'source_step':machine.r.steps,'source_time':float(machine.r.d.time)}
        try:
            probe=clone_machine(machine,directory/candidate.name,candidate)
            summary['clone_wall_seconds']=time.monotonic()-t
            result=probe.push(copy.deepcopy(operation),retained_side=retained_side)
            # Machine.push returning means its original released verification
            # passed, even when consistent_placement makes the return False.
            summary.update(outcome='verified_local_push',return_value=bool(result))
            selected=candidate;verified=True
        except Fault as exc:
            summary.update(outcome='failed',failure=exc.code,detail=exc.detail)
        except Exception as exc:
            summary.update(outcome='error',failure=type(exc).__name__,detail=str(exc))
            (directory/(candidate.name+'_exception.txt')).write_text(traceback.format_exc(),encoding='utf-8')
            raise
        finally:
            if probe is not None:
                r=probe.r
                summary.update(executed_frames=r.steps-machine.r.steps,
                               physical_seconds=float(r.d.time-machine.r.d.time))
                _save_terminal(r,probe.directory)
                probe.log.event('physical_preview_result',**summary)
                probe.log.close({'qpos':r.d.qpos,'qvel':r.d.qvel,'time':float(r.d.time)})
                r.close()
            summary.update(wall_seconds=time.monotonic()-t,cpu_seconds=time.process_time()-cpu)
            summaries.append(summary)
            atomic_json(directory/(candidate.name+'_summary.json'),summary)
            if context_digest(machine)!=fingerprint:
                raise Fault('physical_preview_modified_live_state')
        _check_attempt_budget(machine.r)
        if verified:break
    result=PushSelection(selected,verified,tuple(summaries),time.monotonic()-start)
    atomic_json(directory/'selection.json',{
        'selected':selected.name,'overrides':dict(selected.overrides),
        'preview_verified':verified,'actual_episode_success_eligible':False,
        'wall_seconds':result.wall_seconds,'candidate_count':len(summaries),
        'actual_execution_pending':True})
    return result


def preview_then_push(machine, operation, *, retained_side):
    """Run previews, then call the unchanged actual push exactly once.

    Recursion marker bypasses only this selector, never physical guards. Restore
    config references afterward, without restoring any executed physical state.
    """
    sequence=getattr(machine,'_physical_preview_sequence',0)
    machine._physical_preview_sequence=sequence+1
    directory=machine.directory/'physical_previews'/f'push_{sequence:04d}_{machine.r.steps:08d}'
    machine.log.event('physical_push_preview_start',target_tray=operation.tray,
        target_slot=operation.slot,max_candidates=machine.c.push_physical_preview_max_candidates,
        source_step=machine.r.steps,source_time=float(machine.r.d.time),directory=str(directory),
        scope='retained_final_placement',wall_time_counts_in_attempt=True)
    selection=choose_push_candidate(machine,operation,retained_side=retained_side,directory=directory,
                                    max_candidates=machine.c.push_physical_preview_max_candidates)
    machine.log.event('physical_push_preview_selected',candidate=selection.candidate.name,
        overrides=dict(selection.candidate.overrides),preview_verified=selection.preview_verified,
        candidate_count=len(selection.summaries),wall_seconds=selection.wall_seconds,
        actual_execution_pending=True,actual_episode_success_eligible=False,
        summaries=list(selection.summaries))
    original_c,original_cfg=machine.c,machine.r.cfg
    previous_active=getattr(machine,'_physical_preview_active',False)
    machine.c=machine.r.cfg=selection.candidate.config(original_c)
    machine._physical_preview_active=True
    try:
        result=machine.push(operation,retained_side=retained_side)
        machine.log.event('physical_push_preview_actual_result',candidate=selection.candidate.name,
            outcome='verified_local_push',whole_episode_success_pending=True)
        if selection.preview_verified:
            with np.load(directory/selection.candidate.name/'terminal_state.npz') as expected:
                matched=(np.array_equal(_integration(machine.r),expected['integration_state'])
                         and np.array_equal(machine.r.d.ctrl,expected['ctrl']))
            machine.log.event('physical_push_preview_terminal_comparison',matched=matched,
                candidate=selection.candidate.name,qualification='terminal_comparison_not_substep_certificate')
        return result
    except Fault as exc:
        machine.log.event('physical_push_preview_actual_result',candidate=selection.candidate.name,
            outcome='failed',failure=exc.code,detail=exc.detail,no_physical_retry=True)
        raise
    finally:
        machine.c,machine.r.cfg=original_c,original_cfg
        machine._physical_preview_active=previous_active
