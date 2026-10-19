"""Private-clone escape proposal and opt-in adapter; never authorizes live motion.

Providers must query signed distance for every original pair at every sample,
even when MuJoCo drops that pair from its contact list. New nearby pairs must
also be enumerated. A shadow proposal alone cannot qualify an expert label.
"""
from dataclasses import dataclass
from typing import Mapping

import numpy as np


@dataclass(frozen=True)
class EscapeSample:
    base_world: np.ndarray
    joints: np.ndarray
    distances: Mapping[tuple[str, str], float]
    source: str = 'planning_shadow'
    physics_time: float | None = None
    transition_completed: bool = False
    original_guard_passed: bool = False


def pair_key(a, b):
    return tuple(sorted((a, b)))


def base_escape_candidates(base_world, outward_normals_xy, *, distances_m=(.002, .005, .01)):
    """Bounded translation proposals only, using table-to-robot outward normals.

    The caller must preserve arm targets/yaw and screen the complete reference
    before any private clone execution. Opposite/inward moves are not proposed.
    """
    base = np.asarray(base_world, dtype=float)
    normals = np.asarray(outward_normals_xy, dtype=float)
    if (base.shape != (3,) or normals.ndim != 2 or normals.shape[1] != 2
            or not len(normals) or not np.isfinite(base).all() or not np.isfinite(normals).all()
            or any(not np.isfinite(d) or not 0 < d <= .01 for d in distances_m)):
        raise ValueError('invalid_private_escape_geometry')
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(lengths < 1e-8):
        raise ValueError('private_escape_zero_normal')
    normals = normals / lengths[:, None]
    directions = [*normals]
    combined = normals.sum(axis=0)
    if np.linalg.norm(combined) > 1e-8:
        directions.append(combined / np.linalg.norm(combined))
    result = []
    for direction in directions:
        # Conflicting contact normals may have no translation-only escape.
        if np.any(normals @ direction < -1e-8):
            continue
        for distance in distances_m:
            candidate = base.copy(); candidate[:2] += direction * distance
            if not any(np.allclose(candidate, prior, atol=1e-10, rtol=0) for prior in result):
                result.append(candidate)
    return result


def qualify_private_escape(samples, *, original_pairs, source,
                           initial_penetration_cap_m=.00025, clearance_m=.001,
                           max_translation_m=.01, monotonic_tolerance_m=1e-7,
                           measured_tracking=False):
    """Reject new/renewed collisions; distinguish shadow vs real clone evidence.

    Only explicitly named initial robot/table pairs may start below the original
    planning margin. By default distance improves globally monotonically.
    The explicit measured-only candidate permits settling above the unchanged
    clearance after EACH original pair first clears, with actual yaw <=.01 rad.
    Shadows retain exact yaw and global monotonicity. All pairs must reach the
    unchanged clearance at the endpoint. This is an independent
    proposal qualifier, not a replacement for Runtime.guard or _target_valid.
    """
    pairs = frozenset(pair_key(*pair) for pair in original_pairs)
    if type(measured_tracking) is not bool:
        raise ValueError('private_escape_measured_tracking_requires_bool')
    tracking=measured_tracking and source=='measured_physics'
    if not pairs or not 2 <= len(samples) <= 256 or source not in ('planning_shadow', 'measured_physics'):
        raise ValueError('invalid_private_escape_evidence')
    if (not np.isfinite([initial_penetration_cap_m, clearance_m, max_translation_m,
                         monotonic_tolerance_m]).all() or not 0 < initial_penetration_cap_m <= .00025
            or clearance_m < .001 or not 0 < max_translation_m <= .01
            or not 0 <= monotonic_tolerance_m <= 1e-7):
        raise ValueError('invalid_private_escape_bounds')
    first = samples[0]
    previous = None
    best = None
    minimums = []
    yaw_errors=[];translations=[];first_clear={};settling=0.
    for index, sample in enumerate(samples):
        base, joints = np.asarray(sample.base_world), np.asarray(sample.joints)
        if (sample.source != source or base.shape != (3,) or joints.shape != (16,)
                or not np.isfinite(base).all() or not np.isfinite(joints).all()
                or not np.isfinite(list(sample.distances.values())).all()):
            raise ValueError('nonfinite_or_invalid_private_escape_sample')
        yaw_error=abs(float((base[2]-first.base_world[2]+np.pi)%(2*np.pi)-np.pi)) if tracking else abs(base[2]-first.base_world[2])
        translation=float(np.linalg.norm(base[:2]-first.base_world[:2]))
        if (yaw_error > (.01 if tracking else 1e-8)
                or np.linalg.norm(base[:2]-first.base_world[:2]) > max_translation_m+1e-10):
            raise ValueError('private_escape_exceeds_translation_or_changes_yaw')
        yaw_errors.append(yaw_error);translations.append(translation)
        # Geometry shadows must retain the arm pose. Physical joints may track
        # with servo lag; their safety still comes from unchanged actual guards.
        if source == 'planning_shadow' and not np.allclose(joints, first.joints, atol=1e-8, rtol=0):
            raise ValueError('private_escape_shadow_changes_arm_pose')
        distances = {pair_key(*key): value for key, value in sample.distances.items()}
        if not pairs <= distances.keys():
            raise ValueError('private_escape_initial_pair_distance_missing')
        current = np.asarray([distances[pair] for pair in sorted(pairs)])
        if index == 0 and (np.any(current < -initial_penetration_cap_m)
                           or np.any(current >= 0)):
            raise ValueError('private_escape_initial_contact_unqualified')
        if best is not None and np.any((best >= clearance_m) & (current < clearance_m)):
            raise ValueError('private_escape_cleared_pair_recontact')
        if best is not None:
            monotonic=best<clearance_m if tracking else np.ones(len(best),dtype=bool)
            if np.any(monotonic & (current < best-monotonic_tolerance_m)):
                raise ValueError('private_escape_contact_worsened')
            if tracking and np.any(~monotonic):
                settling=max(settling,float(np.max(np.maximum(best[~monotonic]-current[~monotonic],0))))
        if any(value < clearance_m for key, value in distances.items() if key not in pairs):
            raise ValueError('private_escape_new_collision_or_clearance_failure')
        if source == 'measured_physics':
            if (sample.physics_time is None or not np.isfinite(sample.physics_time)
                    or (index and (not sample.transition_completed or not sample.original_guard_passed
                                   or sample.physics_time <= samples[index-1].physics_time))):
                raise ValueError('private_escape_physics_interval_not_verified')
        previous = current
        best = current.copy() if best is None else np.maximum(best, current)
        for pair,value in zip(sorted(pairs),current):
            if value>=clearance_m:first_clear.setdefault('|'.join(pair),index)
        minimums.append(float(current.min()))
    if np.any(previous < clearance_m):
        raise ValueError('private_escape_endpoint_not_clear')
    return {'status': 'private_escape_qualified', 'source': source, 'samples': len(samples),
            'minimum_initial_pair_distance_by_sample_m': minimums,
            'planning_clearance_m': clearance_m, 'original_live_guards_unchanged': True,
            'expert_label_authorized': False, 'teacher_integration': False,
            'measured_tracking_enabled':tracking,
            'qualification_mode':'bounded_measured_tracking_after_clearance' if tracking else 'exact_yaw_global_monotonic',
            'maximum_actual_yaw_error_rad':max(yaw_errors),'actual_yaw_bound_rad':.01 if tracking else 1e-8,
            'maximum_actual_translation_m':max(translations),'actual_translation_bound_m':max_translation_m,
            'first_clear_sample_by_original_pair':first_clear,'maximum_post_clear_settling_m':settling,
            'qualification':'Private expert label qualification candidate only; not control improvement or task success'}


class RuntimeEscapeAdapter:
    """Private-clone-only translation screened without relaxing Runtime guards."""
    def __init__(self, runtime, *, measured_tracking=False):
        if type(measured_tracking) is not bool:raise ValueError('private_escape_measured_tracking_requires_bool')
        self.measured_tracking=measured_tracking
        self.r = runtime
        self.margin = max(.001, float(runtime.cfg.planner_margin_m))
        self.original = {}
        self.normals = []
        self.reference = np.asarray(runtime.sim.target).copy()
        self.start = np.asarray(runtime.sim.base_state()).copy()
        initial = self.distances(runtime.d)
        for pair, value in initial.items():
            ids = [runtime.m.geom(name).id for name in pair]
            bodies = [int(runtime.m.geom_bodyid[i]) for i in ids]
            robot_table = ((bodies[0] in runtime.robot_bodies and bodies[1] in runtime.table_bodies)
                           or (bodies[1] in runtime.robot_bodies and bodies[0] in runtime.table_bodies))
            if value < 0:
                if not robot_table or value < -.00025:
                    raise ValueError('private_escape_initial_pair_not_shallow_robot_table')
                self.original[pair] = value
                nearest = np.empty(6)
                runtime.mj.mj_geomDistance(runtime.m,runtime.d,*ids,1.,nearest)
                # Signed nearest-point differences invert under penetration.
                vector = nearest[3:5]-nearest[:2]
                if value < 0:vector = -vector
                if bodies[0] in runtime.robot_bodies:vector = -vector
                if np.linalg.norm(vector)<1e-8:
                    raise ValueError('private_escape_contact_normal_unresolved')
                self.normals.append(vector/np.linalg.norm(vector))
        if not self.original:raise ValueError('private_escape_no_actual_initial_robot_table_contact')

    def distances(self, data):
        r=self.r; result={}
        # Every original pair is re-queried even after its contact disappears.
        for pair in self.original:
            result[pair]=float(r.mj.mj_geomDistance(r.m,data,*[r.m.geom(n).id for n in pair],self.margin+.011,None))
        # Broadphase all active robot/environment and held-payload pairs, plus
        # contacts. Static robot/table pairs need explicit signed queries.
        active=np.flatnonzero((r.m.geom_contype!=0)|(r.m.geom_conaffinity!=0))
        moving=set(map(int,r.robot_geoms))
        if r.holding is not None:
            moving.update(int(i) for i in active if r.tray_bodies.get(int(r.m.geom_bodyid[i]))==r.holding)
        pairs=set()
        for a in moving:
            separation=np.linalg.norm(data.geom_xpos[active]-data.geom_xpos[a],axis=1)
            nearby=active[separation<r.m.geom_rbound[active]+r.m.geom_rbound[a]+self.margin]
            for b in nearby:
                b=int(b)
                ba,bb=int(r.m.geom_bodyid[a]),int(r.m.geom_bodyid[b])
                # Explicit signed queries supplement original robot/environment
                # screening, never manufacture compiled-out robot self contacts.
                # Actual robot self collisions still come from MuJoCo contacts.
                if ba in r.robot_bodies and bb in r.robot_bodies:continue
                if ba==bb or int(r.m.body_weldid[ba])==int(r.m.body_weldid[bb]):continue
                excluded=getattr(r.m,'exclude_signature',())
                signatures=[(min(x,y)<<16)+max(x,y) for x,y in
                    [(ba,bb),(int(r.m.body_weldid[ba]),int(r.m.body_weldid[bb]))]]
                if any(signature in excluded for signature in signatures):continue
                if a==b or r._pair_allowed(a,b):continue
                if not ((r.m.geom_contype[a]&r.m.geom_conaffinity[b]) or (r.m.geom_contype[b]&r.m.geom_conaffinity[a])):continue
                pairs.add(tuple(sorted((a,b))))
        for contact in data.contact:
            a,b=int(contact.geom1),int(contact.geom2)
            if not r._pair_allowed(a,b):pairs.add(tuple(sorted((a,b))))
        for a,b in pairs:
            key=pair_key(r.m.geom(a).name,r.m.geom(b).name)
            if key not in self.original:
                result[key]=float(r.mj.mj_geomDistance(r.m,data,a,b,self.margin+.001,None))
        return result

    def sample(self,data,*,source,completed=False):
        r=self.r
        base=np.asarray(r.sim.base_state()).copy() if source=='measured_physics' else self._proposed.copy()
        return EscapeSample(base,np.asarray(r.sim.state()).copy() if source=='measured_physics' else self.reference.copy(),
                            self.distances(data),source,float(data.time) if source=='measured_physics' else None,
                            completed,completed)

    def candidates(self):
        return base_escape_candidates(self.start,self.normals)

    def screen(self,target):
        samples=[]
        for u in np.linspace(0,1,21):
            self._proposed=self.start+u*(np.asarray(target)-self.start)
            data=self.r._shadow(self.reference,self._proposed)
            samples.append(self.sample(data,source='planning_shadow'))
        return qualify_private_escape(samples,original_pairs=self.original,source='planning_shadow',clearance_m=self.margin)

    def execute(self,target, *, audit=None):
        """Record genuine physical prefix with unchanged tick guards and targets."""
        r=self.r
        audit={} if audit is None else audit
        pre_reference=np.asarray(self.reference).copy()
        self.reference=np.asarray(pre_reference,np.float32)
        audit.update(status='planning_screening',teacher_integration=True,target_world=np.asarray(target).tolist(),
                     original_pairs=[list(p) for p in sorted(self.original)],
                     fixed_joint_reference=self.reference.tolist(),fixed_yaw_reference=float(self.start[2]),
                     measured_tracking_enabled=getattr(self,'measured_tracking',False),
                     amended_private_label_qualification_only=True,control_improvement_claimed=False,
                     actual_yaw_bound_rad=.01 if getattr(self,'measured_tracking',False) else 1e-8,
                     actual_translation_bound_m=.01,full_task_success_claimed=False)
        audit['reference_canonicalization']=dict(runtime_actuator_dtype='float32',
            pre_joint_dtype=str(pre_reference.dtype),canonical_joint_dtype=str(self.reference.dtype),
            pre_joint_reference=pre_reference.tolist(),canonical_joint_reference=self.reference.tolist(),
            joint_quantization_delta=(self.reference.astype(float)-pre_reference.astype(float)).tolist(),
            qualification='Existing Runtime.tick dtype conversion; bitexact canonical reference verification, no numeric tolerance relaxation')
        planning=self.screen(target)
        audit.update(status='private_physics_prefix',planning=planning,physics_times=[float(r.d.time)],
                     signed_pair_distances=[],initial_step=int(r.steps))
        samples=[self.sample(r.d,source='measured_physics')]
        audit['actual_base_world']=[samples[0].base_world.tolist()]
        origin=r.m.body_pos[r.m.body('base_link').id]
        yaw0=2*np.arctan2(r.m.body_quat[r.m.body('base_link').id][3],r.m.body_quat[r.m.body('base_link').id][0])
        expected_yaw=np.float32(self.start[2]-yaw0)
        audit['reference_canonicalization'].update(pre_local_yaw_reference=float(self.start[2]-yaw0),
            canonical_local_yaw_reference=float(expected_yaw),yaw_quantization_delta=float(expected_yaw-(self.start[2]-yaw0)))
        n=max(20,round(r.cfg.fps))
        for index in range(1,n+1):
            u=index/n; smooth=u*u*(3-2*u)
            command=self.start+smooth*(np.asarray(target)-self.start)
            expected_base=np.asarray(np.r_[command[:2]-origin[:2],expected_yaw],np.float32)
            r.sim.base_target=expected_base.copy()
            r.sim.target=self.reference.copy()
            before=float(r.d.time)
            try:r.tick()  # Original Runtime guards, cameras, force limits, recorder.
            except BaseException as exc:
                audit.update(status='private_prefix_rejected',failed_tick=index,error=repr(exc),
                             failed_sim_time=float(r.d.time),failed_step=int(r.steps))
                raise
            if float(r.d.time)<=before:raise ValueError('private_escape_tick_did_not_advance')
            actual_joint=np.asarray(r.sim.target);actual_base=np.asarray(r.sim.base_target)
            audit['reference_canonicalization'].update(actual_joint_dtype=str(actual_joint.dtype),actual_base_dtype=str(actual_base.dtype),
                last_expected_base_reference=expected_base.tolist(),last_actual_base_reference=actual_base.tolist())
            if (actual_joint.dtype!=np.float32 or actual_base.dtype!=np.float32 or
                    actual_joint.tobytes()!=self.reference.tobytes() or actual_base.tobytes()!=expected_base.tobytes()):
                audit.update(status='private_prefix_rejected',failed_tick=index,error='private_escape_fixed_reference_changed',
                             failed_sim_time=float(r.d.time),failed_step=int(r.steps))
                raise ValueError('private_escape_fixed_reference_changed')
            sample=self.sample(r.d,source='measured_physics',completed=True)
            samples.append(sample)
            audit['physics_times'].append(sample.physics_time)
            audit['signed_pair_distances'].append({'|'.join(k):v for k,v in sample.distances.items()})
            audit['actual_base_world'].append(sample.base_world.tolist())
        audit.update(maximum_actual_yaw_error_rad=max(abs(float((s.base_world[2]-self.start[2]+np.pi)%(2*np.pi)-np.pi)) for s in samples),
                     maximum_actual_translation_m=max(float(np.linalg.norm(s.base_world[:2]-self.start[:2])) for s in samples))
        try:
            evidence=qualify_private_escape(samples,original_pairs=self.original,source='measured_physics',clearance_m=self.margin,
                                            measured_tracking=getattr(self,'measured_tracking',False))
        except BaseException as exc:
            audit.update(status='private_prefix_qualification_rejected',qualification_error=repr(exc),final_step=int(r.steps))
            raise
        audit.update(status='private_prefix_qualified',measured=evidence,final_step=int(r.steps))
        return dict(planning=planning,measured=evidence,original_pairs=[list(p) for p in sorted(self.original)],
                    target_world=np.asarray(target).tolist(),fixed_joint_reference=self.reference.tolist(),
                    physics_times=[s.physics_time for s in samples],
                    signed_pair_distances=[{'|'.join(k):v for k,v in s.distances.items()} for s in samples],
                    qualification='Private expert prefix only; full skill and label guards must subsequently pass')
