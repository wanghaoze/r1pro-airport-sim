"""Feedback-driven task state machine. The only live motion sink is Runtime.tick.

Planning failures may retry from the CURRENT state. A physics safety violation
terminates the attempt. Restarting an attempt creates a separate episode/seed;
there are no hidden resets inside an episode.
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import asdict
import json
import time
import traceback
import numpy as np
from .contracts import Config, Fault, State, CAMERAS, atomic_json, seed_for, wrap_angle, sha256_file, camera_shapes
from .geometry import Geometry, Scheduler, Operation, quat_yaw_tilt, rz, placement_ok, rectangle, overlap, push_overhang_kwargs
from .trace import Trace, segments_from_trace, events_from_trace


class Machine:
    def __init__(self, runtime, directory, *, attempt=0, seed=0):
        self.r = runtime
        self.c = runtime.cfg
        self.g = runtime.g
        self.directory = Path(directory)
        self.seed = seed_for(self.g.spec['scene_id'], seed, attempt)
        self.rng = np.random.default_rng(self.seed)
        self.attempt = attempt
        # Planning and physical verification must use the same centralized
        # placement contract.  A stricter hidden scheduler threshold caused
        # already-accepted trays to be selected and moved repeatedly.
        from .acceptance_profile import completion_criteria
        self.scheduler = Scheduler(self.g, completion_criteria(self.c), consistent_placement=self.c.consistent_placement,
            require_full_footprint=self.c.acceptance_profile=='strict',
            use_actual_gap=self.c.acceptance_profile=='completion_first',
            approximate_overlap_cap_m=(min(self.c.completion_collision_penetration_m,.02)
                if self.c.approximate_completion_enabled else 0.),
            allow_supported_overhang=bool(push_overhang_kwargs(self.c)))
        self.recovery_used = False
        self.operations = 0
        self.pending_grasp_contact = None
        self.grasp_rim_pair = None
        self.verified_final_trays = set()
        self.log = Trace(self.directory, {
            'scene_id': self.g.spec['scene_id'], 'scene': self.g.spec,
            'scene_xml_sha256': sha256_file(runtime.sim.scene), 'split': self.g.spec['split'],
            'attempt': attempt, 'seed': self.seed, 'config': self.c.dump(),
            'limits': runtime.limits, 'controller_source': 'program_generated',
            'environment_source': 'simulation', 'agent_uses_privileged_state': True,
            'privileged_observations_exported': False, 'cameras': list(camera_shapes(self.g.spec)),
            'initial_time': float(runtime.d.time), 'fps': self.c.fps,
            'physics_timestep_s': float(runtime.m.opt.timestep),
            'substeps_per_frame': int(runtime.sim.nstep),
            'base_model': 'simulation_ideal_planar_position_servo_v1',
            'real_robot_driver_available': False,
        })
        runtime.trace = self.log
        if self.c.reach_pull_enabled:
            from .task_dag import build_task_dag
            atomic_json(self.directory/'task_dag.json',build_task_dag(self.c.max_operations,self.c.max_local_retries))
        self.transition(State.SEARCH_TARGET, 'unknown')

    def transition(self, state, phase, *, tray=None, slot=None):
        r = self.r
        previous = (r.fsm_state.value, r.phase)
        r.fsm_state, r.phase = state, phase
        sequence=getattr(self,'transition_sequence',0)
        self.transition_sequence=sequence+1
        if tray is not None:
            r.allowed_tray = tray
        if slot is not None:
            r.target_slot = slot
        self.log.event('state_transition', previous=previous, state=state.value,
                       dag_node_id=f'transition_{sequence:06d}',
                       dag_predecessor=None if sequence==0 else f'transition_{sequence-1:06d}',
                       phase=phase, target_tray=r.allowed_tray,
                       target_slot=r.target_slot, recovery=r.recovery,
                       simulation_time=float(r.d.time))

    def _poses(self):
        return self.r.observation()['tray_pose'].copy()

    def _inward_yaw(self, position):
        table = self.g.support_table(position)
        if table is None:
            raise Fault('no_unambiguous_supported_table', np.asarray(position).tolist())
        # Into the front belt from the aisle; rear table has the opposite normal.
        inward = self.g.R[:, 1] * (-1. if table == 'rear' else 1.)
        return float(np.arctan2(inward[1], inward[0]))

    def _candidate_list(self, tray):
        pose = self._poses()[tray]
        yaw, _ = quat_yaw_tilt(pose[3:])
        normal = self._inward_yaw(pose[:3])
        # Rim grip is pi-symmetric irrespective of whether the placement task is.
        face = normal + float(wrap_angle(yaw-normal, np.pi))
        # Allow base and hand heading to differ. Tying them together fails for
        # sideways trays near the table edge. All candidates still need full IK.
        nominal_heading = normal + float(np.clip(wrap_angle(face-normal), -.25, .25))
        # First face the grasp axis itself.  This keeps both seven-DoF arms
        # away from opposite reach limits for trays with a large yaw offset.
        # Table-normal candidates remain as fallbacks near edges/obstacles.
        # Full segmented-path sweeps on the three-table scenes place the
        # reliable two-arm reach band at 0.60--0.70 m from the tray.  The old
        # 0.78--0.85 m values left both arms 4--6 cm short even though the
        # final-pose optimizer sometimes returned a superficially close fit.
        # Every candidate still passes chassis, arm, camera and path checks.
        nominal = [(face, .55, 0., 0.), (face, .58, 0., 0.),
                   (nominal_heading, .60, 0., 0.), (normal, .65, 0., 0.),
                   (normal, .62, 0., 0.), (nominal_heading, .68, .035, 0.),
                   (face, .60, 0., 0.), (face, .65, 0., 0.),
                   (face-.25, .60, 0., 0.), (face+.25, .60, 0., 0.)]
        candidates = []
        for i in range(self.c.max_candidate_count):
            if i < len(nominal) and self.attempt == 0 and not self.recovery_used:
                heading, distance, lateral, rim_x = nominal[i]
            else:
                heading = normal + float(self.rng.uniform(-.35, .35))
                distance = float(self.rng.uniform(.54, .69))
                lateral = float(self.rng.uniform(-.07, .07))
                rim_x = float(self.rng.uniform(-self.c.rim_x_jitter_m, self.c.rim_x_jitter_m))
            base_xy = pose[:2] - distance*np.array([np.cos(heading), np.sin(heading)])
            base_xy += lateral*np.array([-np.sin(heading), np.cos(heading)])
            candidates.append((np.r_[base_xy, heading], face, rim_x))
        return candidates

    def _screen_candidate_list(self, tray, candidates):
        """Task adapters may qualify the same geometry and region as live motion."""
        return candidates

    def align(self, tray, slot, *, forward_offset=0., allow_reach_pull=False, allow_alternate=True):
        self.transition(State.ALIGN_BASE, 'unknown', tray=tray, slot=slot)
        errors = []
        candidates = self._candidate_list(tray)
        self.grasp_rim_pair = None
        from .rim_affordances import RimCandidate
        screen_enabled = getattr(self.c, 'reachability_screen_enabled', False)
        screen_empty = (self.pending_grasp_contact is None and
                        self.r.holding is None and self.r.retained_contact is None and
                        np.max(self.r.observation()['gripper_contact_force']) <= .5) if screen_enabled else False
        if screen_enabled and not screen_empty:
            self.log.event('reachability_screen_skipped', reason='requires_empty_arms')
        if screen_enabled and screen_empty:
            from .reachability_planner import candidate_lattice, alternate_candidate_lattice, screen_candidates
            pose = self._poses()[tray]
            normal = self._inward_yaw(pose[:3])
            face = normal + float(wrap_angle(quat_yaw_tilt(pose[3:])[0]-normal, np.pi))
            # Preserve two historical candidates, then test decoupled chassis
            # poses without physically navigating through rejected candidates.
            pool = candidates[:2] + list(candidate_lattice(
                pose[:3], face, normal, rim_jitter=self.c.rim_x_jitter_m)) + candidates[2:]
            if getattr(self.c, 'alternate_rim_enabled', False) and allow_alternate:
                pool = candidates[:2] + list(alternate_candidate_lattice(pose[:3], self.g.sizes[tray],
                    quat_yaw_tilt(pose[3:])[0], normal, inset=self.c.rim_inset_m,
                    rim_jitter=self.c.rim_x_jitter_m)) + candidates[2:]
            if forward_offset:
                pool = [RimCandidate(np.r_[candidate[0][:2]+forward_offset*np.array([
                            np.cos(candidate[0][2]),np.sin(candidate[0][2])]),candidate[0][2]],
                            candidate[1],candidate[2],getattr(candidate,'rim_pair',None)) for candidate in pool]
            pool = self._screen_candidate_list(tray, pool)
            report = screen_candidates(self.r, tray, pool,
                max_probes=self.c.reachability_max_probes,
                max_qualified=self.c.reachability_max_qualified)
            self.log.event('reachability_screen', target_tray=tray,
                examined=report.examined, rejected=report.rejected,
                qualified=[{'base_world':c[0], 'face':c[1], 'rim_x':c[2],
                            'grasp_geometry':asdict(c.rim_pair) if getattr(c,'rim_pair',None) else None, **detail}
                           for c,detail in report.candidates],
                planning_wall_seconds=report.planning_wall_seconds,
                probe_budget=self.c.reachability_max_probes,
                qualified_budget=self.c.reachability_max_qualified,
                live_candidate_budget=self.c.max_candidate_count,
                alternate_rim_enabled=getattr(self.c, 'alternate_rim_enabled', False),
                alternate_rim_allowed=allow_alternate,
                exhausted=report.exhausted,
                qualification='shadow_only_live_replanning_required')
            if report.candidates:
                # Qualified bases already include the requested offset.
                # Keep old candidates as fallback after failed physical replay.
                selected = []
                for candidate, _ in report.candidates:
                    base, face, rim = candidate
                    base = base.copy()
                    base[:2] -= forward_offset*np.array([np.cos(base[2]),np.sin(base[2])])
                    selected.append(RimCandidate(base, face, rim, getattr(candidate, 'rim_pair', None)))
                candidates = selected + candidates
        for i, candidate in enumerate(candidates[:self.c.max_candidate_count]):
            base, face, rim_x = candidate
            self.grasp_rim_pair = getattr(candidate, 'rim_pair', None)
            base = base.copy()
            base[:2] += forward_offset*np.array([np.cos(base[2]), np.sin(base[2])])
            self.log.event('affordance_candidate', candidate=i, base_world=base,
                           rim_pair=('opposed_'+self.grasp_rim_pair.axis+'_axis_rims' if self.grasp_rim_pair else 'opposed_short_axis_rims'),
                           grasp_geometry=asdict(self.grasp_rim_pair) if self.grasp_rim_pair else None,
                           rim_local_z=self.c.rim_height_local_m,
                           rim_inset_m=self.c.rim_inset_m, rim_x_offset_m=rim_x,
                           hand_heading_world=face,
                           source='existing_validated_rim_template_scaled_by_declared_geometry',
                           qualification='candidate_only_until_collision_IK_and_contact_checks_pass')
            try:
                self.r.navigate(base)
                if (self.c.reach_pull_enabled and allow_reach_pull and
                        (self.grasp_rim_pair is None or self.grasp_rim_pair.axis == 'width')):
                    from .reach_pull import try_pull
                    if try_pull(self,tray,slot,face,rim_x):
                        return face,rim_x
                p = self._poses()[tray, :3]
                pre = p.copy(); pre[2] += self.c.rim_height_local_m + self.c.pregrasp_clearance_m
                # Preplanning belongs to cartesian(); an unexecuted IK candidate
                # failure is not labelled as a failed physical grasp.
                self.transition(State.APPROACH_TRAY, 'pregrasp')
                self.r.cartesian(self._grasp_goals(pre, face, x_offset=rim_x),
                                 speed=self.c.transit_tcp_speed, opening=self.c.gripper_open_m)
                return face, rim_x
            except Fault as exc:
                errors.append({'candidate': i, 'code': exc.code, 'detail': exc.detail})
                self.log.event('candidate_rejected', **errors[-1])
                if not exc.recoverable:
                    raise
                # If motion occurred, get to a checked clearance pose before
                # the next base route; no qpos reset or teleport is allowed.
                self.r.joints(self.r.tucked, minimum_seconds=.3)
                self.transition(State.ALIGN_BASE, 'unknown')
        self.grasp_rim_pair = None
        raise Fault('no_feasible_grasp_approach', errors, recoverable=True)

    def _grasp_goals(self, center, face, *, x_offset=0., sides=('left', 'right')):
        pair = getattr(self, 'grasp_rim_pair', None)
        if pair is None:
            return self.r.rim_goals(center, face, x_offset=x_offset, sides=sides)
        return self.r.grasp_goals(center, face, rim_pair=pair, x_offset=x_offset, sides=sides)

    def prepare_pick(self, tray, slot):
        if self.c.prefer_direct_grasp:
            try:
                face,rim_x=(self.align(tray,slot,allow_reach_pull=True) if self.c.reach_pull_enabled else self.align(tray,slot))
                if self.pending_grasp_contact is not None:
                    return face,rim_x
                contact=self._poses()[tray,:3].copy();contact[2]+=self.c.rim_height_local_m
                planned=self.r.cartesian(self._grasp_goals(contact,face,x_offset=rim_x),
                                         opening=self.c.gripper_open_m,wrist=True,preview_only=True)
                # Opening and closure must both clear neighbours and tables.
                # Intended own-tray fingertip contact is handled by collision().
                if getattr(self.c, 'reachability_screen_enabled', False):
                    from .reachability_planner import preview_contact_closure
                    closure = preview_contact_closure(self.r, planned[-1])
                    self.log.event('direct_grasp_contact_closure_preview', **closure)
                else:
                    for opening in np.linspace(self.c.gripper_open_m,self.c.gripper_close_m,21):
                        q=planned[-1].copy();q[[7,15]]=opening
                        if not self.r._target_valid(q,wrist=True):
                            raise Fault('direct_grasp_closure_blocked',recoverable=True)
                self.log.event('direct_grasp_preflight_passed',target_tray=tray,
                               qualification='planning_only_live_contact_still_required')
                return face,rim_x
            except Fault as exc:
                if not exc.recoverable:raise
                self.log.event('direct_grasp_preflight_rejected',reason=exc.code,detail=exc.detail)
                self.r.joints(self.r.tucked,minimum_seconds=.3)
        self.grasp_rim_pair = None
        self.separate_if_needed(tray)
        if self.pending_grasp_contact is not None:
            self.r.target_slot=slot
            return self.pending_grasp_contact['face'],self.pending_grasp_contact['rim_x']
        return self.align(tray,slot,allow_reach_pull=True) if self.c.reach_pull_enabled else self.align(tray,slot)

    def grasp(self, tray, face, rim_x):
        r = self.r
        p = self._poses()[tray, :3]
        contact = p.copy(); contact[2] += self.c.rim_height_local_m
        self.transition(State.APPROACH_TRAY, 'approach')
        retained=self.pending_grasp_contact
        if retained is not None:
            if retained['tray']!=tray:raise Fault('stale_handoff_tray')
            r.check_retained_contact()
            free='right' if retained['side']=='left' else 'left'
            errors=[]
            for height,shift in ((.014,0.),(.025,0.),(0.,0.),(.014,.025),(.014,-.025),(.025,.025),(.025,-.025)):
                candidate=contact.copy();candidate[2]+=height
                goals={free:self._grasp_goals(candidate,face,x_offset=rim_x+shift)[free]}
                try:
                    r.cartesian(goals,speed=self.c.contact_tcp_speed,opening=self.c.gripper_open_m,wrist=True,preview_only=True)
                    self.log.event('joining_grasp_candidate',side=free,height_offset_m=height,rim_x_shift_m=shift)
                    break
                except Fault as exc:
                    if not exc.recoverable:raise
                    errors.append({'height_offset_m':height,'rim_x_shift_m':shift,'reason':exc.code})
            else:raise Fault('joining_arm_path_unavailable',errors)
            self.log.event('separation_to_grasp_handoff',target_tray=tray,
                           retained_side=retained['side'],moving_side=free)
        else:
            goals=self._grasp_goals(contact,face,x_offset=rim_x)
        r.cartesian(goals,
                    speed=self.c.contact_tcp_speed, opening=self.c.gripper_open_m, wrist=True)
        self.transition(State.GRASP_TRAY, 'contact')
        r.wait(.10)
        self.transition(State.GRASP_TRAY, 'close')
        r.close_grippers_on_contact(self.c.gripper_close_m,sides=(free,) if retained else ('left','right'))
        bilateral = lambda e: bool(np.all(e['gripper_contact_force'][tray] > self.c.criteria.contact_n))
        if not r.wait(1., bilateral, .15):
            raise Fault('missing_bilateral_contact', r.observation()['gripper_contact_force'][tray].tolist(), recoverable=True)
        if retained:
            r.check_retained_contact()
            self.log.event('separation_to_grasp_handoff_complete',target_tray=tray,retained_side=retained['side'])
            r.retained_contact=None;self.pending_grasp_contact=None
        self.transition(State.GRASP_TRAY, 'load_transfer')
        # Use ACTUAL contact transforms, not independent left/right pose paths.
        r.remember_grasp(tray)
        if self.c.fixed_primitives:
            from .primitives import lift
            return lift(self,tray)
        # Close the loop on ACTUAL tray clearance.  Contact compliance means a
        # 5 cm hand command can initially produce only ~13 mm object motion.
        # Refreshing the measured contact transforms between bounded steps is
        # physical feedback, not an object teleport or welded constraint.
        e = None
        for requested_step in (.05, .015, .015, .015):
            test = self._poses()[tray, :3]; test[2] += requested_step
            r.object_motion(test, speed=min(self.c.contact_tcp_speed, .015))
            self.transition(State.GRASP_TRAY, 'lift')
            e = r.observation()
            clearance = float(e['min_z'][tray]-r.initial_bottom[tray])
            if not bilateral(e):
                raise Fault('test_lift_contact_lost', {
                    'bottom_clearance_m': clearance,
                    'gripper_contact_force_n': e['gripper_contact_force'][tray].tolist(),
                }, recoverable=True)
            if e['support_contact'][tray] == 0 and clearance >= self.c.criteria.lifted_m:
                break
            r.remember_grasp(tray)
        else:
            raise Fault('test_lift_failed', {
                'support_contacts': int(e['support_contact'][tray]),
                'bottom_clearance_m': float(e['min_z'][tray]-r.initial_bottom[tray]),
                'gripper_contact_force_n': e['gripper_contact_force'][tray].tolist(),
            }, recoverable=True)
        target = e['tray_pose'][tray, :3].copy()
        # Clearance derives from the highest table, not a fixed world z.  Four
        # centimetres of commanded clearance was insufficient once compliant
        # grasp sag and IK residual accumulated during base travel.  Ten
        # The configured clearance leaves measured headroom for a continuous
        # loaded base segment; collision-aware planning still rejects sweeps
        # through another tray.
        bottom_offset = target[2]-e['min_z'][tray]
        target[2] = max(target[2], max(t['dimensions_m'][2] for t in self.g.tables.values())+
                        self.c.carry_clearance_m+bottom_offset)
        carry_yaw, _ = quat_yaw_tilt(e['tray_pose'][tray, 3:])
        # Level the payload before base motion.  Preserving the compliant
        # pickup tilt makes it accumulate during navigation even with slow
        # acceleration.
        r.object_motion(target, carry_yaw, speed=self.c.carry_tcp_speed)
        self.transition(State.GRASP_TRAY, 'stabilize')
        if not r.wait(.75, lambda x: bilateral(x) and x['support_contact'][tray] == 0 and
                      quat_yaw_tilt(x['tray_pose'][tray, 3:])[1] <= np.deg2rad(5.), .2):
            raise Fault('unstable_lift')
        # Tabletop separation is checked before grasping, but compliant pickup
        # can pull the payload several centimetres back toward a neighbour.
        # Restore projected clearance while airborne, before any base motion.
        for correction in range(2):
            poses = self._poses()
            yaw, _ = quat_yaw_tilt(poses[tray, 3:])
            blockers = self.g.blockers(poses, tray, poses[tray, :3], yaw, .08)
            if not blockers:
                break
            away = sum((poses[tray, :2]-poses[index, :2] for index in blockers),
                       np.zeros(2, dtype=float))
            norm = np.linalg.norm(away)
            if norm < 1e-6:
                raise Fault('airborne_separation_direction_ambiguous', blockers, recoverable=True)
            target = poses[tray, :3].copy()
            target[:2] += .08*away/norm
            self.log.event('airborne_separation', iteration=correction,
                           blockers=blockers, measured_xy=poses[tray, :2],
                           command_xy=target[:2])
            r.object_motion(target, yaw, speed=self.c.contact_tcp_speed)
        poses = self._poses()
        yaw, _ = quat_yaw_tilt(poses[tray, 3:])
        if self.g.blockers(poses, tray, poses[tray, :3], yaw, .08):
            raise Fault('airborne_separation_clearance_not_met', recoverable=True)
        if retained:
            # Without realigning the base after separation the grasp is more
            # offset. Require measured clearance over neighbouring tray rims
            # before a base turn; commanded lift alone can hide servo sag.
            required=max(t['dimensions_m'][2] for t in self.g.tables.values())+float(self.g.sizes[:,2].max())+.025
            for correction in range(4):
                e=r.observation()
                if e['min_z'][tray]>=required:break
                if not bilateral(e):raise Fault('handoff_lift_contact_lost')
                # The loaded IK admits up to 22 mm residual. A correction
                # inside that band can return the same command indefinitely.
                # Request a bounded 35 mm step and stop on measured clearance.
                p=e['tray_pose'][tray,:3].copy();p[2]+=.035
                r.remember_grasp(tray)
                self.log.event('handoff_carry_clearance',target_tray=tray,required_bottom_z_m=required,
                               measured_bottom_z_m=float(e['min_z'][tray]),iteration=correction)
                r.object_motion(p,speed=self.c.contact_tcp_speed)
            if r.observation()['min_z'][tray]<required:raise Fault('handoff_carry_clearance_unreachable')

    def _place_location(self, operation):
        """Reserve release clearance instead of squeezing both hands into a gap."""
        if getattr(self.c, 'release_preflight_enabled', False):
            from .scheduler import release_location
            destination = release_location(self.g, self._poses(), operation, self.c)
            if np.linalg.norm(destination-operation.destination) > 1e-9:
                self.log.event('release_staging_reserved', position=destination, final=operation.destination)
            return destination
        pose = self._poses()
        destination = operation.destination.copy()
        if not self.g.blockers(pose, operation.tray, destination, operation.yaw, .065):
            return destination
        for sign in (1., -1.):
            staged = destination + self.g.R[:, 0]*sign*(self.c.staging_clearance_m+.025)
            if self.g.footprint_supported(staged, operation.yaw, self.g.sizes[operation.tray]) and not self.g.blockers(pose, operation.tray, staged, operation.yaw, .045):
                # The final supported pushing sweep must be free as well.
                predicted = pose.copy(); predicted[operation.tray, :3] = staged
                predicted[operation.tray, 3:] = [np.cos(operation.yaw/2), 0, 0, np.sin(operation.yaw/2)]
                if self.g.push_possible(predicted, operation.tray, destination, operation.yaw,
                                        self.c.push_max_distance_m, np.deg2rad(self.c.push_max_yaw_deg),
                                        **push_overhang_kwargs(self.c)):
                    self.log.event('release_staging_reserved', position=staged, final=destination)
                    return staged
        raise Fault('no_safe_release_clearance', recoverable=True)

    def _supported_staging_after_ik_failure(self, operation, staged, failure):
        """One private search; never retry a partly executed physical place."""
        from .arrival_replanning import zero_motion_place_failure
        r = self.r
        if (not self.c.completion_supported_staging_enabled or
                self.c.acceptance_profile != 'completion_first' or
                failure.code not in ('ik_unreachable', 'coupled_ik_unreachable') or
                not zero_motion_place_failure(r, operation.tray, failure)):
            raise failure
        from .supported_staging import screen_supported_staging
        # The failed reference preparation may have replaced command-relative
        # grasp transforms. Re-measure the two real contacts before screening.
        r.remember_grasp(operation.tray)
        alternate = screen_supported_staging(self, operation, staged)
        if alternate is None:
            raise failure
        self.log.event('completion_supported_staging_selected',
                       target_tray=operation.tray, original_staged=staged,
                       alternate_staged=alternate, trigger_failure=failure.code,
                       physical_retry_count=0)
        from .primitives import place
        return place(self, operation, alternate)

    def carry_place(self, operation, placement_proposal=None, *, skip_placement_screen=False):
        r = self.r; tray = operation.tray
        staged = self._place_location(operation)
        if placement_proposal is not None:
            from .buffer_serviceability import same_operation
            if (not same_operation(operation, placement_proposal['operation']) or
                    not np.array_equal(staged, placement_proposal['staged'])):
                raise Fault('temporary_buffer_proposal_stale')
        normal = self._inward_yaw(staged)
        self.transition(State.TRANSPORT_TRAY, 'transport')
        anchor=staged[:2].copy()
        if self.c.keep_place_contact:
            anchor=.5*(anchor+operation.destination[:2])
        base = np.r_[anchor - .57*np.array([np.cos(normal), np.sin(normal)]), normal]
        if getattr(self.c, 'carry_lateral_compensation_enabled', False):
            from .placement_planner import align_carried_lateral_offset
            nominal_base=base.copy()
            measured_base=r.sim.base_state().astype(float)
            measured_payload=r.observation()['tray_pose'][tray,:3].copy()
            base,lateral_offset=align_carried_lateral_offset(base,measured_base,measured_payload)
            self.log.event('carry_lateral_anchor',target_tray=tray,enabled=True,
                           measured_payload_position=measured_payload,measured_base=measured_base,
                           payload_lateral_offset_m=lateral_offset,nominal_base=nominal_base,
                           corrected_base=base,qualification='planning_goal_only_full_navigation_guards_required')
        else:
            self.log.event('carry_lateral_anchor',target_tray=tray,enabled=False,nominal_base=base)
        placement_nominal_base = base.copy()
        if placement_proposal is not None:
            base = np.asarray(placement_proposal['base'], float).copy()
        elif self.c.placement_screen_enabled and not skip_placement_screen:
            from .placement_reachability import carried_placement_candidates, screen_placement
            proposals = carried_placement_candidates(r, base, anchor, goal_tray_yaw=operation.yaw)
            screen = screen_placement(r, staged, operation.destination, operation.yaw, base,
                candidates=proposals, max_candidates=self.c.placement_max_probes, max_qualified=1)
            self.log.event('placement_reachability_screen',target_tray=tray,
                examined=screen.examined,probe_budget=self.c.placement_max_probes,
                qualified=screen.qualified,rejected=screen.rejected,nominal_base=base,
                fallback_to_nominal=not bool(screen.qualified),
                qualification='private_kinematics_only_live_navigation_and_replanning_required')
            if screen.qualified:
                base = np.asarray(screen.qualified[0]['base'], float).copy()
        r.navigate(base)
        carried_evidence = r.observation()
        if np.any(carried_evidence['gripper_contact_force'][tray] <= self.c.criteria.contact_n):
            raise Fault('preplace_bilateral_contact_missing',
                        carried_evidence['gripper_contact_force'][tray].tolist(), recoverable=True)
        # Contacts remain physical and can settle within the finger pads during
        # a long base carry.  Re-measure that ACTUAL relationship before
        # pre-place planning so stale pickup transforms do not pull an arm to
        # the edge of its workspace.  This changes no qpos or object pose.
        r.remember_grasp(tray)
        self.log.event('grasp_transform_refreshed', stage='before_preplace',
                       gripper_contact_force_n=carried_evidence['gripper_contact_force'][tray])
        if self.c.fixed_primitives:
            from .primitives import place
            try:
                return place(self, operation, staged)
            except Fault as original_failure:
                from .arrival_replanning import zero_motion_place_failure, alternative_bases
                if (not self.c.placement_arrival_rescreen_enabled or
                        not zero_motion_place_failure(r, tray, original_failure)):
                    return self._supported_staging_after_ik_failure(
                        operation, staged, original_failure)
                from .placement_reachability import carried_placement_candidates, screen_placement
                current_base = r.sim.base_state().astype(float)
                # Failed reference preparation may have installed command-relative
                # grasp transforms. Navigation needs the actual held relationship.
                r.remember_grasp(tray)
                proposals = alternative_bases(carried_placement_candidates(r,
                    placement_nominal_base, anchor, goal_tray_yaw=operation.yaw), current_base)
                screen = screen_placement(r, staged, operation.destination, operation.yaw,
                    placement_nominal_base, candidates=proposals,
                    max_candidates=self.c.placement_max_probes, max_qualified=1)
                selected = screen.qualified[0]['base'] if screen.qualified else None
                self.log.event('placement_arrival_reachability_screen', target_tray=tray,
                    examined=screen.examined, probe_budget=self.c.placement_max_probes,
                    qualified=screen.qualified, rejected=screen.rejected,
                    current_base=current_base, correction_selected=selected is not None,
                    trigger_failure=original_failure.code,
                    trigger_primitive=dict(original_failure.primitive_execution),
                    excluded_current_position_m=.001, excluded_current_yaw_rad=.001,
                    qualification='one_correction_after_zero_motion_original_primitive_planning_rejection')
                if selected is None:
                    return self._supported_staging_after_ik_failure(
                        operation, staged, original_failure)
                self.transition(State.TRANSPORT_TRAY, 'transport')
                correction_start = r.steps
                correction_time = float(r.d.time)
                r.navigate(np.asarray(selected, float).copy())
                carried_evidence = r.observation()
                forces = carried_evidence['gripper_contact_force'][tray]
                if not np.all(np.isfinite(forces)) or np.any(forces <= self.c.criteria.contact_n):
                    raise Fault('preplace_bilateral_contact_missing', forces.tolist(), recoverable=True)
                r.remember_grasp(tray)
                self.log.event('grasp_transform_refreshed', stage='after_arrival_base_correction',
                    gripper_contact_force_n=forces)
                self.log.event('placement_arrival_base_correction', target_tray=tray,
                    from_base=current_base, to_base=selected,
                    navigation_seconds=(r.steps-correction_start)/self.c.fps,
                    physical_navigation_seconds=float(r.d.time)-correction_time,
                    trigger_failure=original_failure.code,
                    counted_in_episode=True, excluded_from_primitive=True, maximum_corrections=1)
                # A failed corrected place gets no further base navigation.
                # Only a second pure, zero-motion IK rejection may enter the
                # private supported-staging screen at this measured base.
                try:
                    return place(self, operation, staged)
                except Fault as corrected_failure:
                    return self._supported_staging_after_ik_failure(
                        operation, staged, corrected_failure)
        table_top = max(table['dimensions_m'][2] for table in self.g.tables.values())
        lateral_sweep = float(np.linalg.norm(
            staged[:2]-carried_evidence['tray_pose'][tray, :2]))
        # Long lateral corrections need more measured clearance for compliant
        # grasp sag. Small corrections retain the lower reachable posture so
        # unnecessary lift does not rotate wrist cameras behind the fingers.
        _, arrival_tilt = quat_yaw_tilt(carried_evidence['tray_pose'][tray, 3:])
        required_clearance = (.04 if lateral_sweep > .06 and
                              arrival_tilt < np.deg2rad(3.) else .025)
        self.log.event('preplace_clearance_requirement', lateral_sweep_m=lateral_sweep,
                       arrival_tilt_deg=float(np.degrees(arrival_tilt)),
                       required_clearance_m=required_clearance)
        self.transition(State.GRASP_TRAY, 'lift')
        for correction in range(4):
            evidence = r.observation()
            if evidence['min_z'][tray] >= table_top+required_clearance:
                break
            position = evidence['tray_pose'][tray, :3].copy()
            yaw, _ = quat_yaw_tilt(evidence['tray_pose'][tray, 3:])
            bottom_offset = position[2]-evidence['min_z'][tray]
            position[2] = min(position[2]+.035, table_top+.08+bottom_offset)
            self.log.event('destination_clearance_restore', iteration=correction,
                           measured_bottom_z=float(evidence['min_z'][tray]),
                           command_center_z=float(position[2]))
            r.object_motion(position, yaw, speed=self.c.contact_tcp_speed)
            r.remember_grasp(tray)
        if r.observation()['min_z'][tray] < table_top+required_clearance:
            raise Fault('preplace_clearance_not_restored', {
                'bottom_clearance_m': float(r.observation()['min_z'][tray]-table_top),
            }, recoverable=True)
        actual_yaw, _ = quat_yaw_tilt(self._poses()[tray, 3:])
        final_yaw = actual_yaw + float(wrap_angle(operation.yaw-actual_yaw, self.g.period))
        carried = self._poses()[tray, :3].copy()
        pre = staged.copy(); pre[2] = carried[2]
        self.transition(State.PLACE_TRAY, 'preplace')
        r.object_motion(pre, final_yaw, speed=self.c.carry_tcp_speed)
        # The compliant dual-arm grasp and bounded IK may leave a few
        # centimetres of steady position error even though both TCP commands
        # are feasible.  Correct it while the tray is still supported by both
        # grippers.  The command is allowed to overshoot the nominal slot by a
        # bounded amount; measured tray pose, not the commanded pose, decides
        # when refinement is complete.
        for refinement in range(3):
            actual = self._poses()[tray]
            delta = staged[:2]-actual[:2]
            yaw, _ = quat_yaw_tilt(actual[3:])
            yaw_error = float(wrap_angle(operation.yaw-yaw, self.g.period))
            if np.linalg.norm(delta) <= .012 and abs(yaw_error) <= np.deg2rad(2.):
                break
            correction = delta * min(1., .04/max(np.linalg.norm(delta), 1e-9))
            command = pre.copy(); command[:2] += correction
            self.log.event('preplace_refinement', iteration=refinement,
                           measured_xy=actual[:2], error_xy_m=delta,
                           yaw_error_rad=yaw_error, command_xy=command[:2])
            r.object_motion(command, final_yaw+float(np.clip(yaw_error, -.06, .06)),
                            speed=self.c.contact_tcp_speed)
            pre = command
        # Let the tray contact the table; do not move the rigid object explicitly.
        e = r.observation(); offset = e['tray_pose'][tray, 2]-e['min_z'][tray]
        # Preserve the lateral command that compensated the measured grasp
        # error. Resetting it to the nominal slot here undoes refinement and
        # can release the tray over the table edge, making the next push fail.
        target = pre.copy(); target[2] = self.g.origin[2]+offset+.0005
        self.transition(State.PLACE_TRAY, 'descend')
        r.object_motion(target, final_yaw, speed=self.c.contact_tcp_speed)
        self.transition(State.PLACE_TRAY, 'support_contact')
        if not r.wait(1.2, lambda e: e['table_contact'][tray] > 0, .2):
            raise Fault('no_support_before_release', recoverable=True)
        self.transition(State.PLACE_TRAY, 'unload')
        r.wait(.2)
        # A release is allowed only after independent support evidence.
        r.holding = None; r.grasp_rel = None
        if (self.c.keep_place_contact and not self._operation_geometry_ready(operation) and
            self.g.push_possible(self._poses(),tray,operation.destination,operation.yaw,
                                 self.c.push_max_distance_m,np.deg2rad(self.c.push_max_yaw_deg),
                                 **push_overhang_kwargs(self.c))):
            return self.place_push_handoff(operation)
        self.transition(State.PLACE_TRAY, 'open')
        target = r.sim.target.copy(); target[[7, 15]] = self.c.gripper_open_m
        r.joints(target, minimum_seconds=.25, wrist=True, audit=False)
        if not r.wait(1., lambda e: e['table_contact'][tray] > 0 and np.max(e['gripper_contact_force'][tray]) <= .5, .15):
            raise Fault('release_not_observed', recoverable=True)
        self.retreat()
        if np.linalg.norm(staged[:2]-operation.destination[:2]) > .01:
            if self.c.consistent_placement and self._operation_geometry_ready(operation):
                self.log.event('redundant_postplace_push_skipped',target_tray=tray,
                               final_physical_verification_pending=True)
            else:
                return self.push(operation)

    def _operation_geometry_ready(self, operation):
        from .geometry import slot_geometry_ready
        from .acceptance_profile import completion_criteria
        expected=(self.scheduler.planning_destination(operation.slot) if
            getattr(getattr(self,'scheduler',None),'reservation_plan',None) is not None and operation.slot>=0 else
            self.g.goals[operation.slot])
        if not (operation.slot>=0 and
                np.linalg.norm(operation.destination-expected)<1e-6 and
                abs(wrap_angle(operation.yaw-self.g.goal_yaw[operation.slot],self.g.period))<1e-6):
            return False
        pose=self._poses();effective=completion_criteria(self.c)
        accepted=slot_geometry_ready(self.g,pose,self.scheduler.mapping,
                                      operation.tray,operation.slot,effective,
                                      require_full_footprint=self.c.acceptance_profile=='strict',
                                      use_actual_gap=self.c.acceptance_profile=='completion_first',
                                      **({'approximate_overlap_cap_m':min(self.c.completion_collision_penetration_m,.02)}
                                         if getattr(self.c,'approximate_completion_enabled',False) else {}),
                                      **({'reservation_positions':self._reservation_positions()}
                                         if getattr(getattr(self,'scheduler',None),'reservation_plan',None) is not None else {}))
        if accepted and effective is not self.c.criteria and not slot_geometry_ready(
                self.g,pose,self.scheduler.mapping,operation.tray,operation.slot,self.c.criteria):
            self.r.record_strict_deviation('operation_geometry_outside_strict_contract',
                {'tray':operation.tray,'slot':operation.slot,'pose':pose[operation.tray].tolist(),
                 'strict_criteria':asdict(self.c.criteria),'task_criteria':asdict(effective)})
        return bool(accepted)

    def place_push_handoff(self, operation):
        r=self.r;tray=operation.tray;pose=self._poses()
        sides=['left','right']
        direction=operation.destination[:2]-pose[tray,:2]
        # Keep the trailing hand: a leading hand can be trapped in the gap
        # that this very push is closing, even if it started far from a tray.
        sides.sort(key=lambda s:float(np.dot(r.sim.tcp(s)[0][:2]-pose[tray,:2],direction)))
        errors=[]
        for side,rise in ((sides[0],h) for h in (.08,.10,.13)):
            free='right' if side=='left' else 'left'
            p,R=r.sim.tcp(free);p[2]+=rise
            try:
                r.retained_contact=(tray,side);r.check_retained_contact()
                r.cartesian({free:(p,R)},opening=self.c.gripper_open_m,wrist=True,preview_only=True)
                break
            except Fault as exc:
                r.retained_contact=None
                if not exc.recoverable:raise
                errors.append({'retained_side':side,'rise_m':rise,'reason':exc.code})
        else:raise Fault('single_arm_release_path_unavailable',errors)
        r.retained_contact=(tray,side);r.check_retained_contact()
        self.log.event('place_to_push_handoff',target_tray=tray,retained_side=side,moving_side=free,
                       free_arm_rise_m=rise,rejected_paths=errors)
        self.transition(State.PLACE_TRAY,'open')
        target=r.sim.target.copy();target[7 if free=='left' else 15]=self.c.gripper_open_m
        r.joints(target,minimum_seconds=.25,wrist=True,audit=False)
        self.transition(State.PLACE_TRAY,'retreat')
        r.cartesian({free:(p,R)},opening=self.c.gripper_open_m,speed=self.c.transit_tcp_speed,wrist=True)
        r.check_retained_contact()
        return self.push(operation,retained_side=side)

    def retreat(self):
        self.transition(State.PLACE_TRAY, 'retreat')
        goals = {}
        for side in ('left', 'right'):
            p, R = self.r.sim.tcp(side); p[2] += .13
            goals[side] = (p, R)
        self.r.cartesian(goals, opening=self.c.gripper_open_m, speed=self.c.transit_tcp_speed)
        from .retreat_planner import tuck_minimum_seconds
        self.r.joints(self.r.tucked, minimum_seconds=tuck_minimum_seconds(self.r,self.c.retreat_joint_speed_scale))

    def push(self, operation, *, separation=False, retained_side=None, pull_context=None,
             free_precleared=False):
        """One-rim pinch plus supported translation/yaw; physical contact only."""
        r = self.r
        if free_precleared and (retained_side is None or separation or pull_context is not None or
                r.retained_contact != (operation.tray, retained_side) or
                getattr(r, '_handoff_clearance_monitor', None) !=
                    (operation.tray, 'right' if retained_side == 'left' else 'left') or
                not self.c.completion_handoff_clearance_enabled):
            raise Fault('handoff_clearance_context_invalid')
        if self.c.push_physical_preview_enabled and not free_precleared:
            from .physical_preview import eligible_push, preview_then_push
            if eligible_push(self,operation,separation=separation,retained_side=retained_side):
                return preview_then_push(self,operation,retained_side=retained_side)
        tray = operation.tray
        pose = self._poses()
        if separation:
            if not self._separation_path_valid(pose, tray, operation.destination):
                raise Fault('unsupported_separation_path', recoverable=True)
        elif not self.g.push_possible(pose, tray, operation.destination, operation.yaw,
                                       self.c.push_max_distance_m, np.deg2rad(self.c.push_max_yaw_deg),
                                       **push_overhang_kwargs(self.c)):
            raise Fault('push_affordance_not_feasible', recoverable=True)
        if retained_side is None:
            tray_yaw, _ = quat_yaw_tilt(pose[tray, 3:])
            forward_offset = (.04 if not separation and not self.g.footprint_supported(
                pose[tray, :3], tray_yaw, self.g.sizes[tray]) else 0.)
            if pull_context is None:
                face, rim_x = self.align(tray, operation.slot, forward_offset=forward_offset, allow_alternate=False)
            else:
                side,face,rim_x=pull_context
                from .reach_pull import supported_sweep
                if not supported_sweep(self.g,pose,tray,operation.destination):
                    raise Fault('reach_pull_sweep_invalid')
                self.log.event('reach_pull_single_hand_alignment',side=side)
            p = self._poses()[tray, :3]
            center = p.copy(); center[2] += self.c.rim_height_local_m+.014
            sides = ['left', 'right'] if pull_context is None else [pull_context[0]]
            # Pick the hand with the largest distance from neighbouring trays.
            goals = r.rim_goals(center, face, x_offset=rim_x)
            sides.sort(key=lambda s: -min(np.linalg.norm(goals[s][0][:2]-pose[j, :2]) for j in range(3) if j != tray))
            errors = []
            for side in sides:
                try:
                    self.transition(State.ADJUST_TRAY, 'approach')
                    r.cartesian({side: goals[side]}, speed=self.c.contact_tcp_speed,
                                opening=self.c.gripper_open_m, wrist=True)
                    break
                except Fault as exc:
                    if not exc.recoverable:
                        raise
                    errors.append({'side': side, 'code': exc.code, 'detail': exc.detail})
            else:
                raise Fault('no_free_single_rim', errors, recoverable=True)
            col = 7 if side == 'left' else 15
            self.transition(State.ADJUST_TRAY, 'close')
            r.close_grippers_on_contact(self.c.gripper_close_m, sides=(side,))
            if not r.wait(.8, lambda e: e['gripper_contact_force'][tray, sides_index(side)] > .5, .1):
                raise Fault('push_contact_missing', recoverable=True)
            if separation and self.c.keep_pick_contact:
                r.retained_contact=(tray,side);r.check_retained_contact()
        else:
            side=retained_side
            if r.retained_contact!=(tray,side):raise Fault('invalid_retained_push_contact')
            r.check_retained_contact()
            self.log.event('push_reuses_existing_contact',target_tray=tray,retained_side=side)
        col=7 if side=='left' else 15
        from .runtime import _homogeneous
        b = r.d.body(self.g.ids[tray])
        relation = np.linalg.inv(_homogeneous(b.xpos, b.xmat.reshape(3, 3))) @ _homogeneous(*r.sim.tcp(side))
        self.transition(State.ADJUST_TRAY, 'pull' if pull_context is not None else 'adjust')
        start_bottom = r.observation()['min_z'][tray]
        supported_center_z = float(self._poses()[tray, 2])
        commanded_xy = self._poses()[tray, :2].copy()
        commanded_yaw, _ = quat_yaw_tilt(self._poses()[tray, 3:])
        stagnant_steps = 0
        online_completed = False
        if self.c.fixed_primitives:
            from .primitives import push
            push(self,operation,side,relation,separation=separation,
                 free_retreat=retained_side is not None,
                 free_precleared=free_precleared)
            online_completed=True
        elif self.c.online_push:
            from .online_push import execute_push
            try:
                online_completed = execute_push(self, operation, side, relation, separation=separation)
                if not online_completed:
                    # Handoff occurs only after a jerk-limited stop. Refresh
                    # measured contact geometry; never pretend the tray stayed
                    # rigidly attached during the preceding tabletop push.
                    b=r.d.body(r.g.ids[tray])
                    relation=np.linalg.inv(_homogeneous(b.xpos,b.xmat.reshape(3,3)))@_homogeneous(*r.sim.tcp(side))
                    commanded_xy=self._poses()[tray,:2].copy()
                    commanded_yaw,_=quat_yaw_tilt(self._poses()[tray,3:])
            except Fault as exc:
                # A live reference may still have momentum. Do not start the
                # legacy rest-to-rest recovery from that moving reference.
                raise Fault(exc.code,exc.detail,recoverable=False) from exc
        for iteration in range(0 if online_completed else (min(5, self.c.push_iterations) if separation and not self.c.single_contact_separation else self.c.push_iterations)):
            actual = self._poses()[tray]
            yaw, _ = quat_yaw_tilt(actual[3:])
            delta = operation.destination[:2]-actual[:2]
            da = float(wrap_angle(operation.yaw-yaw, self.g.period))
            if (self.c.stop_push_at_contract or self.c.consistent_placement) and not separation and operation.slot>=0:
                if self._operation_geometry_ready(operation):
                    self.log.event('push_geometry_ready_for_release',target_tray=tray,target_slot=operation.slot,
                                   position_error_m=float(np.linalg.norm(delta)),final_physical_verification_pending=True)
                    break
            if np.linalg.norm(delta) < .006 and abs(da) < np.deg2rad(1.5):
                break
            # Never command an unbounded correction after slipping.
            distance = float(np.linalg.norm(delta))
            step_limit = .045
            if self.c.adaptive_push_distance and not separation:
                # Larger, fully preplanned corrections only away from the
                # target; separation near other trays keeps its old bound.
                step_limit = min(self.c.push_step_max_m, max(.045, .5*distance))
            step = delta * min(1., step_limit/max(distance, 1e-9))
            next_yaw = yaw + float(np.clip(da, -.08, .08))
            position = actual[:3].copy(); position[:2] += step
            if not separation or self.c.single_contact_separation:
                # Integrate measured placement error into the command. Merely
                # commanding actual+error repeats the same nominal goal after
                # every servo/contact offset and cannot remove steady error.
                commanded_xy += .5*step
                nominal_xy = actual[:2]+step
                excess = commanded_xy-nominal_xy
                commanded_xy = nominal_xy + excess*min(
                    1., .015/max(np.linalg.norm(excess), 1e-9))
                commanded_yaw += float(np.clip(da, -.08, .08))
                yaw_bias = float(wrap_angle(commanded_yaw-operation.yaw, self.g.period))
                next_yaw = commanded_yaw+float(np.clip(yaw_bias, -.08, .08))-yaw_bias
                position[:2] = commanded_xy
                position[2] = supported_center_z
            T = _homogeneous(position, rz(next_yaw)) @ relation
            before = actual.copy()
            r.cartesian({side: (T[:3, 3], T[:3, :3])}, speed=self.c.contact_tcp_speed,
                        opening=self.c.gripper_close_m, wrist=True)
            e = r.observation()
            self.log.event('push_feedback', iteration=iteration, separation=separation,
                           step_limit_m=step_limit, position_error_before_m=distance,
                           target_tray=tray, before_pose=before,
                           commanded_position=position,
                           measured_pose=e['tray_pose'][tray],
                           destination=operation.destination)
            # Contact solver micro-bounce at a table seam can leave a tray
            # tens of microns above support at the sampled frame. Stop and
            # require observed contact to return; do not classify zero contact
            # as support or continue driving an airborne tray.
            if (e['support_contact'][tray] <= 0 and
                    abs(e['min_z'][tray]-start_bottom) <= .002):
                self.log.event('push_support_settle', target_tray=tray,
                               bottom_delta_m=float(e['min_z'][tray]-start_bottom))
                r.wait(.3, lambda x: x['support_contact'][tray] > 0, .1)
                e = r.observation()
            if e['support_contact'][tray] <= 0 or e['min_z'][tray]-start_bottom > .015:
                raise Fault('push_lost_support')
            if separation:
                current = self._poses()
                if not self.g.blockers(current, tray, current[tray, :3],
                                       quat_yaw_tilt(current[tray, 3:])[0], (.085 if self.c.keep_pick_contact else .055)):
                    break
            if np.linalg.norm(e['tray_pose'][tray, :2]-before[:2]) < .0003 and abs(da) < .01:
                if separation and not self.c.single_contact_separation:
                    break
                stagnant_steps += 1
                if stagnant_steps >= 3:
                    raise Fault('push_no_progress', recoverable=True)
            else:
                stagnant_steps = 0
        if separation and self.c.keep_pick_contact:
            pose=self._poses();yaw,_=quat_yaw_tilt(pose[tray,3:])
            if not self.g.blockers(pose,tray,pose[tray,:3],yaw,.085):
                r.retained_contact=(tray,side);r.check_retained_contact()
                self.pending_grasp_contact={'tray':tray,'side':side,'face':face,'rim_x':rim_x}
                self.log.event('separation_contact_retained',target_tray=tray,retained_side=side)
                return
            raise Fault('separation_handoff_clearance_unmet')
        if retained_side is not None:
            r.check_retained_contact()
            self.log.event('retained_push_phase_end',target_tray=tray,retained_side=side,
                           physical_verification_pending=True)
            r.retained_contact=None
        target = r.sim.target.copy(); target[col] = self.c.gripper_open_m
        self.transition(State.ADJUST_TRAY, 'open')
        r.joints(target, minimum_seconds=.25, wrist=True, audit=False)
        try:
            self.retreat()
        except Fault as exc:
            if not exc.recoverable:
                raise
            # After release the tray is supported and a checked joint-space
            # return can recover from a Cartesian retreat at the workspace
            # edge without invalidating the completed separation motion.
            evidence = r.observation()
            if (evidence['support_contact'][tray] <= 0 or
                    np.max(evidence['gripper_contact_force'][tray]) > self.c.criteria.contact_n):
                raise
            self.log.event('supported_release_retreat_fallback', reason=exc.code,
                           target_tray=tray)
            r.joints(r.tucked, minimum_seconds=.4)
        if separation:
            pose = self._poses()
            if self.g.blockers(pose, tray, pose[tray, :3],
                               quat_yaw_tilt(pose[tray, 3:])[0], (.085 if self.c.keep_pick_contact else .055)):
                raise Fault('separation_clearance_not_met', recoverable=True)
            return
        if not self.verify_operation(operation):
            raise Fault('push_accuracy_not_met', recoverable=not self.c.fixed_primitives)
        return self.c.consistent_placement

    def _separation_path_valid(self, pose, tray, destination):
        table = self.g.support_table(pose[tray, :3])
        if table is None or not self.g.top_available(pose, tray):
            return False
        yaw, tilt = quat_yaw_tilt(pose[tray, 3:])
        if tilt > np.deg2rad(5) or np.linalg.norm(destination[:2]-pose[tray, :2]) > .12:
            return False
        for u in np.linspace(0., 1., 25):
            p = pose[tray, :3]*(1-u)+destination*u
            if self.g.support_table(p) != table:
                return False
            if any(j != tray and overlap(rectangle(p, yaw, self.g.sizes[tray]), self.g.footprint(pose, j), .001) for j in range(3)):
                return False
        return True

    def separate_if_needed(self, tray):
        moved = False
        for separation_pass in range(3):
            pose = self._poses()
            if not self.g.blockers(pose, tray, pose[tray, :3], quat_yaw_tilt(pose[tray, 3:])[0], (.085 if self.c.keep_pick_contact else .055)):
                return moved
            if not self.g.top_available(pose, tray):
                raise Fault('attempt_to_grasp_lower_stacked_tray')
            # A top stacked tray must be lifted, not dragged across its lower support.
            if self.r.observation()['table_contact'][tray] <= 0:
                return moved
            yaw, _ = quat_yaw_tilt(pose[tray, 3:])
            candidates = []
            candidates = self._separation_candidates(pose,tray,yaw)
            if not candidates:
                self.log.event('separation_unavailable', target_tray=tray, fallback='collision_checked_direct_grasp')
                return moved
            try:
                self.push(Operation(tray, -1, candidates[0], float(yaw), True), separation=True)
                moved = True
            except Fault as exc:
                if exc.code != 'separation_clearance_not_met':
                    raise
                moved = True
                self.log.event('separation_regrasp', pass_index=separation_pass,
                               reason=exc.code)
        raise Fault('separation_clearance_not_met', recoverable=True)

    def _separation_candidates(self, pose, tray, yaw):
        # Reserve the executed 55 mm clearance plus 20 mm tracking headroom;
        # the old 45 mm plan necessarily triggered another release/regrasp.
        clearance=.105 if self.c.keep_pick_contact else .075 if self.c.single_contact_separation else .045
        distances=(.115,) if self.c.keep_pick_contact else (.08,.10,.115) if self.c.single_contact_separation else (.06,.10)
        candidates=[]
        for direction in (self.g.R[:,0],-self.g.R[:,0],self.g.R[:,1],-self.g.R[:,1]):
            for distance in distances:
                p=pose[tray,:3]+direction*distance
                if self._separation_path_valid(pose,tray,p) and not self.g.blockers(pose,tray,p,yaw,clearance):
                    candidates.append(p)
        return candidates

    # 松爪后的几何和稳定性才是放置成功依据，避免弹性夹持造成误判。
    def _profile_final_acceptance(self):
        from .acceptance_profile import profile_placement_ok
        valid, report = profile_placement_ok(self.log.acceptance_arrays(),self.g,self.c)
        if valid and report.get('strict_accepted') is False:
            self.r.record_strict_deviation('final_physical_acceptance_failed',report['strict_report'])
        return valid, report

    def _record_completion_slot_deviations(self, pose):
        if getattr(self.c,'acceptance_profile','strict')=='strict':return
        from .acceptance_profile import completion_criteria
        from .geometry import slot_geometry_ready
        effective=completion_criteria(self.c)
        for slot,tray in enumerate(self.scheduler.mapping):
            def ready(criteria):
                valid=self.g.at_slot(pose,tray,slot,position_tol=criteria.position_m,
                    angle_tol=np.deg2rad(criteria.yaw_deg),tilt_tol=np.deg2rad(criteria.tilt_deg))
                return valid and (not self.c.consistent_placement or
                    slot_geometry_ready(self.g,pose,self.scheduler.mapping,tray,slot,criteria,
                        require_full_footprint=criteria is self.c.criteria,
                        use_actual_gap=criteria is not self.c.criteria,
                        **({'approximate_overlap_cap_m':min(self.c.completion_collision_penetration_m,.02)}
                            if self.c.approximate_completion_enabled and criteria is not self.c.criteria else {}),
                        **({'reservation_positions':self._reservation_positions()} if
                           criteria is not self.c.criteria and getattr(getattr(self,'scheduler',None),'reservation_plan',None) is not None else {})))
            if ready(effective) and not ready(self.c.criteria):
                self.r.record_strict_deviation('scheduler_slot_outside_strict_contract',
                    {'tray':tray,'slot':slot,'pose':pose[tray].tolist(),
                     'strict_criteria':asdict(self.c.criteria),'task_criteria':asdict(effective)})

    def verify_operation(self, operation):
        from .acceptance_profile import completion_criteria
        self.transition(State.VERIFY_PLACEMENT, 'verified', tray=operation.tray, slot=operation.slot)
        previous = None
        reservation_samples=[]
        effective=completion_criteria(self.c)
        def check(e):
            nonlocal previous
            if self.c.completion_adaptive_reservation_enabled:
                reservation_samples.append({key:np.array(e[key],copy=True) for key in
                    ('tray_pose','table_contact','gripper_contact_force')})
            p = e['tray_pose'][operation.tray]
            yaw, tilt = quat_yaw_tilt(p[3:])
            speed = np.inf if previous is None else np.linalg.norm(p[:3]-previous)*self.c.fps
            previous = p[:3].copy()
            def accepted(criteria):
                valid=bool(np.linalg.norm(p[:3]-operation.destination)<=criteria.position_m and
                    abs(wrap_angle(yaw-operation.yaw,self.g.period))<=np.deg2rad(criteria.yaw_deg) and
                    tilt<=np.deg2rad(criteria.tilt_deg) and speed<=.01 and
                    e['table_contact'][operation.tray]>0 and
                    np.max(e['gripper_contact_force'][operation.tray])<=.5)
                if valid and getattr(getattr(self,'scheduler',None),'reservation_plan',None) is not None and operation.slot>=0 and not operation.temporary:
                    from .reservation_plan import at_nominal
                    valid=at_nominal(self.g,e['tray_pose'],operation.tray,operation.slot,criteria)
                if valid and self.c.fixed_primitives and operation.slot>=0 and not operation.temporary:
                    from .geometry import slot_geometry_ready
                    reservation_kwargs={}
                    if criteria is not self.c.criteria and getattr(getattr(self,'scheduler',None),'reservation_plan',None) is not None:
                        reservation_kwargs['reservation_positions']=self._reservation_positions()
                    valid=slot_geometry_ready(self.g,e['tray_pose'],self.scheduler.mapping,
                                              operation.tray,operation.slot,criteria,
                        require_full_footprint=criteria is self.c.criteria,
                        use_actual_gap=criteria is not self.c.criteria,
                        **({'approximate_overlap_cap_m':min(self.c.completion_collision_penetration_m,.02)}
                            if self.c.approximate_completion_enabled and criteria is not self.c.criteria else {}),
                        **reservation_kwargs)
                return valid
            task_ok=accepted(effective)
            if task_ok and effective is not self.c.criteria and not accepted(self.c.criteria):
                self.r.record_strict_deviation('operation_outside_strict_contract',
                    {'tray':operation.tray,'slot':operation.slot,
                     'position_error_m':float(np.linalg.norm(p[:3]-operation.destination)),
                     'yaw_error_deg':float(np.degrees(abs(wrap_angle(yaw-operation.yaw,self.g.period)))),
                     'strict_criteria':asdict(self.c.criteria),'task_criteria':asdict(effective)})
            return task_ok
        valid=self.r.wait(2., check, self.c.criteria.stable_s)
        if not valid and self.c.completion_adaptive_reservation_enabled:
            from .reservation_plan import propose
            proposal=propose(self,operation,reservation_samples)
            if proposal is not None:
                self.scheduler.reservation_plan=proposal
                # Proposal checks the existing stable observations; it does not
                # authorize a future physical success or add hidden waiting.
                self.r.record_strict_deviation('adaptive_reservation_outside_strict_contract',
                    {'tray':operation.tray,'slot':operation.slot,'plan':proposal})
                valid=True
        return valid

    def _reservation_positions(self):
        from .reservation_plan import positions
        return positions(self.g,self.scheduler.mapping,self.scheduler.reservation_plan)

    def _complete_reservation(self):
        if getattr(self.scheduler,'reservation_plan',None) is not None:
            self.log.event('adaptive_reservation_completed',plan=self.scheduler.reservation_plan,
                qualification='actual_final_acceptance_against_original_nominal_goals')
            self.scheduler.reservation_plan=None

    def recover(self, fault):
        r = self.r
        self.recovery_used = True; r.recovery = True
        self.transition(State.RECOVER, 'recover')
        self.log.event('recovery_started', reason=fault.code, detail=fault.detail)
        if not fault.recoverable:
            raise fault
        tray = r.allowed_tray
        if tray is None:
            r.joints(r.tucked, minimum_seconds=.3)
            r.recovery = False
            return
        e = r.observation()
        if r.holding is not None and e['table_contact'][tray] <= 0:
            # Controlled placement on the CURRENT underlying table, never drop
            # or re-initialize an airborne tray to obtain a fresh retry.
            position = e['tray_pose'][tray, :3].copy()
            table = self.g.support_table(position)
            if table is None or self.g.blockers(e['tray_pose'], tray, position, quat_yaw_tilt(e['tray_pose'][tray, 3:])[0], .02):
                raise Fault('no_supported_airborne_recovery', fault.code)
            from .placement_planner import touchdown_position
            body_id = r.m.body(self.g.ids[tray]).id
            rotation = r.d.body(body_id).xmat.reshape(3, 3).copy()
            position = touchdown_position(position, r.evidence.local_vertices[body_id], rotation,
                table_height=self.g.tables[table]['dimensions_m'][2],
                preload=self.c.primitive_touchdown_preload_m)
            r.object_motion(position, speed=self.c.contact_tcp_speed)
            if not r.wait(1., lambda x: x['table_contact'][tray] > 0, .15):
                raise Fault('recovery_support_missing')
        if r.observation()['support_contact'][tray] <= 0:
            raise Fault('unsafe_recovery_without_support')
        r.holding = None; r.grasp_rel = None
        target = r.sim.target.copy(); target[[7, 15]] = self.c.gripper_open_m
        r.joints(target, minimum_seconds=.3, audit=False)
        if e['gripper_contact_force'][tray].max() <= self.c.criteria.contact_n:
            # A rejected pregrasp/approach still has the tray safely supported.
            # Return through the already collision-checked joint path; an extra
            # Cartesian retreat can itself be unreachable from a rejected IK
            # branch and must not consume the whole episode.
            r.joints(r.tucked, minimum_seconds=.3)
            r.recovery = False
            self.log.event('recovery_finished', qualification='retained_but_not_ordinary_BC_data')
            return
        self.retreat()
        r.recovery = False
        self.log.event('recovery_finished', qualification='retained_but_not_ordinary_BC_data')

    def run(self):
        r = self.r
        self.transition(State.SEARCH_TARGET, 'unknown')
        r.wait(2.)
        # Lift clearance is measured from the physically settled episode
        # state.  Formal preflight separately rejects scenes whose settled pose
        # drifts outside the scene contract, so this baseline cannot hide an
        # unstable source layout.
        r.initial_bottom = r.observation()['min_z'].copy()
        r.joints(r.tucked, minimum_seconds=.5)
        for _ in range(self.c.max_operations):
            self.transition(State.SEARCH_TARGET, 'unknown')
            if self.c.consistent_placement and self.operations:
                # Final physics acceptance outranks planning clearance margins.
                # Otherwise a completed arrangement can be regrasped solely
                # because release drift used part of a reserved future margin.
                valid,report=self._profile_final_acceptance()
                if valid:
                    self.log.event('final_acceptance_before_reschedule',operations=self.operations)
                    self._complete_reservation()
                    self.transition(State.TASK_COMPLETE,'verified');r.tick()
                    return report
            scheduling_pose=self._poses()
            op = self.scheduler.choose(scheduling_pose)
            self._record_completion_slot_deviations(scheduling_pose)
            if op is None:
                self.transition(State.VERIFY_PLACEMENT, 'verified')
                r.wait(self.c.criteria.stable_s+.15)
                valid, report = self._profile_final_acceptance()
                if valid:
                    self._complete_reservation()
                    self.transition(State.TASK_COMPLETE, 'verified')
                    r.tick()
                    return report
                # Geometry alone never promotes an episode to success. A
                # remaining small gap/pose error gets a bounded local repair.
                fatal = [reason for reason in report['reasons'] if reason not in ('pose_or_gap_outside_contract','not_stationary','tilt')]
                if fatal:
                    raise Fault('final_physical_acceptance_failed', report)
                pose = self._poses()
                mapping = self.scheduler.mapping
                slot = max(range(3), key=lambda s: np.linalg.norm(pose[mapping[s],:3]-self.g.goals[s]))
                if (getattr(self.scheduler,'reservation_plan',None) is not None and
                        mapping[slot] in self.scheduler.reservation_plan['protected_trays']):
                    raise Fault('adaptive_reservation_requires_protected_correction',report)
                op = Operation(mapping[slot], slot, self.scheduler.planning_destination(slot), self.g.goal_yaw[slot])
                self.log.event('final_feedback_correction', remaining_reasons=report['reasons'], target_slot=slot)
            prerequisite_context = None
            if getattr(self.c, 'release_preflight_enabled', False):
                from .scheduler import release_prerequisite
                requested_operation = op
                prerequisite_poses = self._poses().copy()
                op, prerequisite = release_prerequisite(self.g, prerequisite_poses, op,
                    self.scheduler.mapping, self.verified_final_trays, self.c,
                    **({'planning_destination':self.scheduler.planning_destination}
                       if getattr(self.scheduler,'reservation_plan',None) is not None else {}))
                if prerequisite is not None:
                    from .buffer_serviceability import prerequisite_context as make_prerequisite_context
                    prerequisite_context = make_prerequisite_context(requested_operation, op,
                        prerequisite_poses, self.scheduler.mapping, self.verified_final_trays,
                        prerequisite, self.operations+1)
                    self.log.event('release_precondition_selected', **prerequisite,
                        requested_operation=asdict(prerequisite_context.requested))
            from .general_buffer import capture_context, select_direct_buffer
            general_buffer_context = capture_context(self,op,scheduling_pose,prerequisite_context)
            self.operations += 1
            self.log.event('operation_selected', operation=asdict(op), operation_index=self.operations)
            completed = False
            for retry in range(self.c.max_local_retries):
                r.allowed_tray, r.target_slot = op.tray, op.slot
                try:
                    pose = self._poses()
                    if self.g.push_possible(pose, op.tray, op.destination, op.yaw,
                                             self.c.push_max_distance_m, np.deg2rad(self.c.push_max_yaw_deg),
                                             **push_overhang_kwargs(self.c)):
                        verified = self.push(op)
                    else:
                        face, rim_x = self.prepare_pick(op.tray, op.slot)
                        self.grasp(op.tray, face, rim_x)
                        placement_proposal = None
                        if general_buffer_context is not None:
                            op, placement_proposal = select_direct_buffer(self,op,general_buffer_context)
                        elif getattr(self.c, 'temporary_buffer_serviceability_enabled', False):
                            from .buffer_serviceability import select_buffer
                            op, placement_proposal = select_buffer(self, op, prerequisite_context)
                        if (placement_proposal is None and ((general_buffer_context is not None and general_buffer_context.screened) or
                                (prerequisite_context is not None and prerequisite_context.screened))):
                            verified = self.carry_place(op, skip_placement_screen=True)
                        elif placement_proposal is None:
                            verified = self.carry_place(op)
                        else:
                            verified = self.carry_place(op, placement_proposal=placement_proposal)
                    if not verified and not self.verify_operation(op):
                        raise Fault('placement_needs_correction', recoverable=not self.c.fixed_primitives)
                    if op.slot >= 0 and not op.temporary:
                        self.verified_final_trays.add(op.tray)
                    completed = True
                    break
                except Fault as exc:
                    if getattr(self.scheduler,'reservation_plan',None) is not None:
                        self.log.event('adaptive_reservation_invalidated',reason=exc.code,
                            plan=self.scheduler.reservation_plan)
                        self.scheduler.reservation_plan=None
                    if getattr(r,'retained_contact',None) is not None:
                        exc=Fault('contact_handoff_aborted',{'reason':exc.code,'detail':exc.detail})
                    self.log.event('operation_failed', retry=retry, reason=exc.code, detail=exc.detail,
                                   recoverable=exc.recoverable)
                    if not exc.recoverable or retry+1 >= self.c.max_local_retries:
                        raise exc
                    self.recover(exc)
            if not completed:
                raise Fault('local_retry_budget_exhausted')
        raise Fault('operation_budget_exhausted')

    def finish(self, success, acceptance=None, error=None):
        from .completion import completion_fields
        r = self.r
        result = {'scene_id': self.g.spec['scene_id'], 'split': self.g.spec['split'],
                  'attempt': self.attempt, 'seed': self.seed, 'physics_success': bool(success),
                  'recovery_used': self.recovery_used,
                  'failure_code': error.code if isinstance(error, Fault) else 'unexpected_exception' if error else None,
                  'error': str(error) if error else None, 'operations': self.operations,
                  'frames': self.log.count, 'simulation_seconds': r.steps/self.c.fps,
                  'physical_elapsed_seconds': float(r.d.time-r.physical_time_start),
                  'simulation_seconds_semantics': 'completed_20Hz_intervals; physical_elapsed_seconds also includes a failed substep prefix',
                  'wall_seconds': time.monotonic()-r.wall_start, 'acceptance': acceptance,
                  'peak_mechanical_abs_sum_power_w': r.peak_power,
                  'inverse_dynamics_calls': r.id_calls, 'inverse_dynamics_slowdowns': r.id_slowdowns,
                  'limits': r.limits, 'controller_source': ('vla_generated' if
                      getattr(self.c,'motion_backend','teacher')=='pi05' else 'program_generated'),
                  'environment_source': 'simulation', 'privileged_teacher':
                      getattr(self.c,'motion_backend','teacher')!='pi05',
                  'real_robot_validated': False, 'native_video_validation': 'pending_replay_export'}
        result.update(completion_fields(r, success))
        if getattr(self.c,'motion_backend','teacher')=='pi05':
            result['vla_servo_projection']=dict(self.executor.projection_stats)
            result['vla_reference_rate_limit']=dict(self.executor.rate_limit_stats)
        result['training_candidate'] = bool(getattr(self.c,'motion_backend','teacher')!='pi05' and success and not self.recovery_used and (
            not result['approximate_completion_enabled'] or result['strict_success']))
        result['strict_final_placement_passed'] = bool(success and (
            acceptance.get('strict_accepted', True) if isinstance(acceptance, dict) else False))
        self.log.close({'qpos': r.d.qpos, 'qvel': r.d.qvel, 'time': float(r.d.time)})
        atomic_json(self.directory/'result.json', result)
        if self.log.count:
            atomic_json(self.directory/'segments.json', segments_from_trace(self.directory/'trace.h5', self.g.spec, result))
            atomic_json(self.directory/'events.json', events_from_trace(self.directory/'trace.h5', self.g.spec, result))
        r.close()
        return result


def sides_index(side):
    return 0 if side == 'left' else 1


def run_attempt(spec, xml, cfg, directory, attempt=0, *, machine_observer=None):
    from .runtime import Runtime
    from .attempt_policy import effective_attempt_config, attempt_policy_fields
    runtime, machine = None, None
    try:
        cfg = effective_attempt_config(cfg, attempt)
        learned = getattr(cfg, 'motion_backend', 'teacher') == 'pi05'
        runtime = Runtime(spec, xml, cfg, **({'render': True} if learned else {}))
        runtime.attempt_controller_policy = attempt_policy_fields(cfg, attempt)
        engine = Machine
        if learned:
            from r1pro_teleop.vla.machine import VLAMachine
            engine = VLAMachine
        machine = engine(runtime, directory, attempt=attempt, seed=int(spec['seed']))
        if machine_observer is not None:
            machine_observer(machine)
        acceptance = machine.run()
        return machine.finish(True, acceptance)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            fault = Fault('interrupted', str(exc))
        else:
            fault = exc
        if machine is not None and not machine.log.closed:
            result = machine.finish(False, error=fault)
        else:
            if runtime is not None:
                runtime.close()
            directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
            result = {'scene_id': spec['scene_id'], 'split': spec['split'], 'attempt': attempt,
                      'physics_success': False, 'recovery_used': False, 'training_candidate': False,
                      'acceptance_profile': getattr(cfg, 'acceptance_profile', 'strict'),
                      'approximate_completion_enabled': bool(getattr(cfg, 'approximate_completion_enabled', False)),
                      'effective_acceptance_profile': ('approximate_completion' if
                          getattr(cfg, 'approximate_completion_enabled', False) else
                          getattr(cfg, 'acceptance_profile', 'strict')),
                      'task_completed': False, 'strict_success': False,
                      'acceptance_deviations': {'count': 0, 'by_code': {}, 'maxima': {}},
                      'failure_code': fault.code if isinstance(fault, Fault) else 'runtime_initialization_failed',
                      'error': str(fault), 'frames': 0,
                      'controller_source': 'vla_generated' if getattr(cfg,'motion_backend','teacher')=='pi05' else 'program_generated',
                      'motion_backend': getattr(cfg,'motion_backend','teacher'),
                      'physical_episode_started': False,
                      'environment_source': 'simulation'}
            result.update(attempt_policy_fields(cfg, attempt))
            atomic_json(directory/'result.json', result)
        (Path(directory)/'exception.txt').write_text(traceback.format_exc(), encoding='utf-8')
        return result





