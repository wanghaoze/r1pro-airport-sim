"""Append-only numeric source episodes, bounded memory, explicit transition timing."""
from __future__ import annotations
from pathlib import Path
import json
import os
import time
import h5py
import numpy as np
from .contracts import atomic_json, json_default, State


class Trace:
    def __init__(self, directory, attributes):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.file = h5py.File(self.directory / "trace.partial.h5", "x")
        self.file.attrs["schema"] = "airport_fsm_raw/1"
        self.file.attrs["metadata_json"] = json.dumps(attributes, default=json_default, allow_nan=False)
        self.file.attrs["observation_semantics"] = "state[t] and images[t] BEFORE accepted action[t]; action held through next 1/fps interval"
        if attributes.get('config', {}).get('substep_control_enabled', False):
            self.file.attrs['schema'] = 'airport_fsm_raw/2'
            self.file.attrs['observation_semantics'] = (
                'state[t] and images[t] BEFORE action interval; action[t] is end-of-frame joint reference; '
                'ctrl_substeps[t,k] is the exact actuator control applied for physics substep k; '
                'executed_substeps records the real prefix on failed intervals')
        self.file.attrs["image_storage"] = "Native RGB encoded once into official LeRobot video shards during deterministic replay; see media_reference.json"
        self.count = 0
        self.closed = False
        self.events = open(self.directory / "events.jsonl", "x", encoding="utf-8", buffering=1)

    def event(self, kind, **details):
        row = {"frame": self.count, "event": kind, **details}
        self.events.write(json.dumps(row, ensure_ascii=False, default=json_default, allow_nan=False)+"\n")
        self.events.flush()

    def append(self, row):
        if self.closed:
            raise RuntimeError("Trace closed")
        for key, value in row.items():
            if isinstance(value, (str, State)):
                value = str(value.value if isinstance(value, State) else value)
                if key not in self.file:
                    self.file.create_dataset(key, shape=(0,), maxshape=(None,), chunks=(128,), dtype=h5py.string_dtype("utf-8"))
            else:
                value = np.asarray(value)
                # Zero-actuation-state MuJoCo models have act.shape == (0,).
                # HDF5 chunk dimensions must be positive. Save the absent field
                # explicitly as metadata, rather than creating a zero chunk.
                if value.size == 0:
                    self.file.attrs['empty_shape:'+key] = json.dumps(list(value.shape))
                    continue
                if key not in self.file:
                    self.file.create_dataset(key, shape=(0,)+value.shape, maxshape=(None,)+value.shape, chunks=(128,)+value.shape, dtype=value.dtype, compression="lzf")
                if self.file[key].shape[1:] != value.shape:
                    raise ValueError("Trace shape drift: "+key)
            ds = self.file[key]
            ds.resize(self.count+1, axis=0)
            ds[self.count] = value
        self.count += 1
        if self.count % 100 == 0:
            self.file.flush()

    def arrays(self, *, include=None):
        self.file.flush()
        return {key: ds[:] for key, ds in self.file.items()
                if isinstance(ds, h5py.Dataset) and (include is None or key in include)}

    def acceptance_arrays(self):
        # The full-episode gate needs every violation/pose sample, but not the
        # much larger actuator journal or integration snapshots.
        return self.arrays(include={'qpos','qvel','action','base_action','tray_pose',
            'floor_contact','illegal_collision','max_penetration','wrist_violation',
            'transition_completed','table_contact','gripper_contact_force','state'})

    def close(self, terminal=None):
        if self.closed:
            return
        self.file.attrs["num_frames"] = self.count
        if terminal is not None:
            try:
                self.file.attrs["terminal_snapshot_json"] = json.dumps(terminal, default=json_default, allow_nan=False)
            except ValueError:
                self.file.attrs["terminal_snapshot_json"] = json.dumps({'invalid':True,'reason':'nonfinite_terminal_state'})
        self.file.flush()
        self.file.close()
        self.events.flush()
        os.fsync(self.events.fileno())
        self.events.close()
        os.replace(self.directory/"trace.partial.h5", self.directory/"trace.h5")
        self.closed = True


def strings(array):
    return [x.decode("utf-8") if isinstance(x, bytes) else str(x) for x in array]


# 片段引用原 Episode 半开帧区间，不能复制视频或推断未知标签。
def segments_from_trace(path, spec, result):
    """Controller intent supplies phase; contact evidence verifies outcomes separately.

    Never assert a grasp occurred just because GRASP_TRAY was requested.
    Bad attempt spans and recovery are not ordinary successful BC supervision.
    """
    with h5py.File(path, "r") as f:
        n = len(f["timestamp"])
        states, phases = strings(f["fsm_state"][:]), strings(f["phase"][:])
        tray, slot = f["target_tray"][:], f["target_slot"][:]
        recovery = f["recovery"][:].astype(bool)
        force = f["gripper_contact_force"][:]
        support = f["support_contact"][:]
        bottom = f["min_z"][:]
        table = f["table_contact"][:]
        pose = f["tray_pose"][:]
        state = f["state"][:]
        labels = list(zip(states, phases, tray, slot, recovery))
        starts = [0]+[i for i in range(1, n) if labels[i] != labels[i-1]]+[n] if n else [0]
        segments = []
        eid = Path(path).parent.name
        for start, end in zip(starts[:-1], starts[1:]):
            st, phase, t, sl, rec = labels[start]
            if st == State.ALIGN_BASE.value:
                skill, category = "navigate_to_tray", None
            elif st == State.ADJUST_TRAY.value:
                skill, category = "push_adjust_tray", "adjust"
            elif st in (State.APPROACH_TRAY.value, State.GRASP_TRAY.value):
                skill, category = "grasp_lift_tray", "pick"
            elif st == State.TRANSPORT_TRAY.value:
                skill, category = "carry_tray", "place"
            elif st == State.PLACE_TRAY.value:
                skill, category = "place_release_tray", "place"
            else:
                skill, category = "verify_or_recover", None
            evidence, needs = {}, False
            if t >= 0:
                evidence = {"bilateral_contact_observed": bool(np.any(np.all(force[start:end, t] > .5, axis=1))), "table_support_observed": bool(np.any(table[start:end, t] > 0)), "max_lift_from_episode_initial_m": float(np.max(bottom[start:end, t])-bottom[0, t])}
                if phase in ("lift", "stabilize", "transport"):
                    verified = bool(np.all(force[start:end, t] > .5) and np.all(support[start:end, t] == 0))
                    needs = not verified
                elif phase == "support_contact":
                    needs = not evidence["table_support_observed"]
                elif phase in ("adjust", "pull"):
                    movement = np.linalg.norm(pose[end-1, t, :2]-pose[start, t, :2])
                    needs = not (movement > .001 and np.any(force[start:end, t] > .5))
            if st == State.RECOVER.value:
                needs = True
            successful = bool(result.get("physics_success") and not needs and not rec)
            training_candidate = bool(successful and not result.get("recovery_used") and
                (not result.get("approximate_completion_enabled", False) or
                 result.get("strict_success", False)) and
                result.get("training_candidate", True))
            segments.append({"segment_id": f"{spec['scene_id']}_{eid}_{start:06d}", "episode_id": f"{spec['scene_id']}/{eid}", "scene_id": spec["scene_id"], "split": spec["split"], "start_frame": start, "end_frame": end, "interval": "half-open", "state": st, "skill": skill, "phase": phase, "primary_class": category, "target_tray_id": None if t < 0 else spec["trays"][int(t)]["tray_id"], "target_slot_id": None if sl < 0 else spec["slots"][int(sl)]["slot_id"], "success": successful, "recovery": bool(rec), "failure_reason": result.get("failure_code") if not successful else None, "needs_review": needs, "training_candidate": training_candidate, "controller_source": result.get("controller_source", "program_generated"), "environment_source": "simulation", "annotation_source": "fsm_intent_plus_simulation_contact_evidence", "annotation_version": "airport_fsm_events/1", "evidence": evidence})
        for segment in segments:
            segment['acceptance_profile'] = result.get('acceptance_profile', 'strict')
            segment['episode_task_completed'] = result.get('task_completed', result.get('physics_success', False))
            segment['episode_strict_success'] = result.get('strict_success', result.get('physics_success', False))
        return segments


def events_from_trace(path, spec, result):
    """Evidence events are distinct from FSM intent/state-transition logs."""
    with h5py.File(path) as f:
        n = len(f['timestamp']); force = f['gripper_contact_force'][:]
        support, table, bottom = f['support_contact'][:], f['table_contact'][:], f['min_z'][:]
        floor, pose = f['floor_contact'][:], f['tray_pose'][:]
        state, target, times = f['state'][:], f['target_tray'][:], f['timestamp'][:]
        complete = f['transition_completed'][:]
        rows = []
        def emit(i, event, tray=None, **extra):
            rows.append({'episode_id': spec['scene_id']+'/'+Path(path).parent.name,
                         'scene_id': spec['scene_id'], 'frame': int(i), 'timestamp': float(times[i]),
                         'event': event, 'target_tray_id': None if tray is None else spec['trays'][tray]['tray_id'],
                         'controller_source': result.get('controller_source', 'program_generated'), 'environment_source': 'simulation',
                         'annotation_source': 'simulation_contact_and_pose',
                         'annotation_version': 'airport_fsm_events/1', **extra})
        contact = np.any(force > .5, axis=2); both = np.all(force > .5, axis=2)
        lifted = (support == 0) & (bottom-bottom[:1] > .02) & both
        ever_lifted = np.zeros(3, bool)
        for i in range(n):
            for t in range(3):
                previous = i > 0
                if contact[i,t] and (not previous or not contact[i-1,t]): emit(i,'gripper_contact',t)
                if both[i,t] and np.all(state[i,[7,15]] < .035) and (not previous or not both[i-1,t]): emit(i,'bilateral_grasp_observed',t)
                if lifted[i,t] and (not previous or not lifted[i-1,t]):
                    emit(i,'lift_above_2cm',t); ever_lifted[t] = True
                if previous and ever_lifted[t] and table[i,t] > 0 and table[i-1,t] <= 0: emit(i,'table_support_restored',t)
                if previous and both[i-1,t] and not both[i,t] and support[i,t] == 0: emit(i,'bilateral_contact_loss_in_air',t)
                if previous and contact[i-1,t] and not contact[i,t] and support[i,t] > 0 and np.all(state[i,[7,15]] > .06): emit(i,'open_release',t)
                if floor[i,t] and (not previous or not floor[i-1,t]): emit(i,'dropped_to_floor',t)
                if previous and table[i,t] > 0 and contact[i,t] and np.linalg.norm(pose[i,t,:2]-pose[i-1,t,:2])*20 > .015:
                    if i == 1 or np.linalg.norm(pose[i-1,t,:2]-pose[i-2,t,:2])*20 <= .015: emit(i,'table_push_or_rotate',t)
            if not complete[i]: emit(i,'incomplete_control_interval', failure_reason=result.get('failure_code'))
        if n and result.get('physics_success'): emit(n-1,'task_complete_physically_verified')
        return rows
