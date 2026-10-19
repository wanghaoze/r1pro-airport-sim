"""Scene-frame geometry and support-aware task ordering; no hardcoded tray order."""
from __future__ import annotations
from dataclasses import dataclass
from itertools import permutations
import math
import numpy as np
from .contracts import Criteria, Fault, wrap_angle


def rz(yaw: float) -> np.ndarray:
    c, s = np.cos(yaw), np.sin(yaw)
    return np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])


def rectangle(center, yaw, size, margin=0.) -> np.ndarray:
    hx, hy = np.asarray(size[:2]) / 2 + margin
    return np.array([[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]]) @ rz(yaw)[:2, :2].T + np.asarray(center[:2])


def carried_pose_at_base(position, orientation, current_base, proposed_base):
    """Predict a rigid carry from measured pose; used only in private planning data."""
    current_base, proposed_base = np.asarray(current_base), np.asarray(proposed_base)
    turn = rz(float(wrap_angle(proposed_base[2]-current_base[2])))
    offset = np.asarray(position)-np.r_[current_base[:2], 0.]
    return turn @ offset + np.r_[proposed_base[:2], 0.], turn @ np.asarray(orientation)


def overlap(a, b, clearance=0.) -> bool:
    """SAT for convex rectangle footprints; touching is not penetrating."""
    a, b = np.asarray(a), np.asarray(b)
    for p in (a, b):
        for i in (0, 1):
            edge = p[(i+1) % 4] - p[i]
            axis = np.array([-edge[1], edge[0]])
            norm = np.linalg.norm(axis)
            if norm < 1e-12:
                raise ValueError("Degenerate footprint")
            axis /= norm
            aa, bb = a @ axis, b @ axis
            if aa.max() + clearance <= bb.min() or bb.max() + clearance <= aa.min():
                return False
    return True


def footprint_boundary_distance(a, b):
    """Euclidean edge distance for disjoint rectangles; None means SAT overlap."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if overlap(a, b):
        return None
    distance = np.inf
    for vertices, edges in ((a, b), (b, a)):
        for i in range(4):
            start, end = edges[i], edges[(i+1)%4]
            delta = end-start
            length2 = float(delta@delta)
            if length2 <= 0:
                raise ValueError("Degenerate footprint")
            u = np.clip((vertices-start)@delta/length2, 0., 1.)
            distance = min(distance, float(np.linalg.norm(vertices-start-u[:,None]*delta, axis=1).min()))
    return distance


def footprint_signed_boundary_gap(a, b):
    """Disjoint edge distance, or negative minimum SAT overlap depth."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    distance = footprint_boundary_distance(a, b)
    if distance is not None:
        return float(distance)
    depths = []
    for polygon in (a, b):
        for index in (0, 1):
            edge = polygon[(index+1) % 4] - polygon[index]
            axis = np.array([-edge[1], edge[0]]) / np.linalg.norm(edge)
            projected_a, projected_b = a @ axis, b @ axis
            depths.append(min(projected_a.max()-projected_b.min(),
                              projected_b.max()-projected_a.min()))
    return -float(min(depths))


def footprint_signed_neighbour_gaps(positions, angles, sizes):
    """Adjacent rotated-footprint gaps, including bounded negative overlap."""
    footprints = [rectangle(p, a, size) for p, a, size in zip(positions, angles, sizes)]
    return np.asarray([footprint_signed_boundary_gap(a, b)
                       for a, b in zip(footprints[:-1], footprints[1:])])


def footprint_neighbour_gaps(positions, angles, sizes):
    """Reject all actual pair intersections, then measure adjacent edge gaps."""
    footprints = [rectangle(p, a, size) for p,a,size in zip(positions,angles,sizes)]
    gaps = []
    for i in range(len(footprints)):
        for j in range(i+1,len(footprints)):
            distance = footprint_boundary_distance(footprints[i], footprints[j])
            if distance is None:
                return None
            if j == i+1:
                gaps.append(distance)
    return np.asarray(gaps)


def quat_yaw_tilt(q):
    q = np.asarray(q, float)
    n = np.linalg.norm(q, axis=-1)
    if np.any(np.abs(n-1) > .02):
        raise Fault("invalid_quaternion")
    w, x, y, z = np.moveaxis(q / n[..., None], -1, 0)
    return np.arctan2(2*(w*z+x*y), 1-2*(y*y+z*z)), np.arccos(np.clip(1-2*(x*x+y*y), -1., 1.))


def slot_geometry_ready(g, pose, mapping, tray, slot, criteria, gap_margin=.001, *, require_full_footprint=True, use_actual_gap=False, reservation_positions=None, approximate_overlap_cap_m=0.):
    """Stop refining an acceptable slot without stealing adjacent tray space.

    Accepted neighbours use their measured poses; unplaced neighbours reserve
    their target footprints. This is a planning decision, never final success.
    """
    if slot not in range(len(mapping)) or mapping[slot]!=tray:return False
    if not g.at_slot(pose,tray,slot,position_tol=criteria.position_m,
                     angle_tol=np.deg2rad(criteria.yaw_deg),tilt_tol=np.deg2rad(criteria.tilt_deg)):
        return False
    yaw,_=quat_yaw_tilt(pose[:,3:])
    if require_full_footprint:
        if not g.footprint_supported(pose[tray,:3],yaw[tray],g.sizes[tray],margin=0.):
            return False
    elif g.support_table(pose[tray,:3]) is None:
        return False
    positions=[];angles=[];sizes=[]
    for s,t in enumerate(mapping):
        accepted=(t==tray or g.at_slot(pose,t,s,position_tol=criteria.position_m,
            angle_tol=np.deg2rad(criteria.yaw_deg),tilt_tol=np.deg2rad(criteria.tilt_deg)))
        positions.append(pose[t,:3] if accepted else (g.goals[s] if reservation_positions is None else reservation_positions[s]))
        angles.append(yaw[t] if accepted else g.goal_yaw[s]);sizes.append(g.sizes[t])
    local=g.to_belt(np.asarray(positions));angles=np.asarray(angles)-g.belt_yaw;sizes=np.asarray(sizes)
    ext=.5*(sizes[:,0]*abs(np.cos(angles))+sizes[:,1]*abs(np.sin(angles)))
    gaps=np.diff(local[:,0])-ext[:-1]-ext[1:]
    margin=min(gap_margin,(criteria.gap_max_m-criteria.gap_min_m)/4)
    if use_actual_gap:
        if approximate_overlap_cap_m > 0:
            footprints=[rectangle(position,angle,size) for position,angle,size in
                        zip(positions,np.asarray(angles)+g.belt_yaw,sizes)]
            if any(footprint_signed_boundary_gap(footprints[i],footprints[j]) < -approximate_overlap_cap_m
                   for i in range(len(positions)) for j in range(i+1,len(positions))):
                return False
            gaps=footprint_signed_neighbour_gaps(positions, np.asarray(angles)+g.belt_yaw, sizes)
        else:
            gaps=footprint_neighbour_gaps(positions, np.asarray(angles)+g.belt_yaw, sizes)
            if gaps is None:
                return False
        margin=0.
    minimum_gap = -approximate_overlap_cap_m if approximate_overlap_cap_m > 0 else criteria.gap_min_m
    if not all(minimum_gap+margin<=gaps[i]<=criteria.gap_max_m-margin
               for i in (slot-1,slot) if 0<=i<len(gaps)):
        return False
    # The scheduler reserves each future nominal placement with 2 mm clearance.
    # Passing only the final gap tolerance can leave a tray obstructing that
    # reservation, causing the next operation to select it again indefinitely.
    for s,t in enumerate(mapping):
        if s==slot:continue
        if not g.at_slot(pose,t,s,position_tol=criteria.position_m,
                         angle_tol=np.deg2rad(criteria.yaw_deg),tilt_tol=np.deg2rad(criteria.tilt_deg)):
            future=rectangle(g.goals[s] if reservation_positions is None else reservation_positions[s],g.goal_yaw[s],g.sizes[t])
            if overlap(g.footprint(pose,tray),future,clearance=.002):return False
    return True


def push_overhang_kwargs(cfg):
    """Keep the legacy call signature unless the explicit approximate flag is on."""
    return ({'allow_supported_overhang': True}
            if getattr(cfg,'approximate_completion_enabled',False) and
               getattr(cfg,'allow_supported_overhang',False) else {})


class Geometry:
    def __init__(self, spec: dict, *, expected_trays=3):
        self.spec = spec
        if type(expected_trays) is not int or expected_trays not in (1,3):raise Fault('unsupported_tray_scope')
        if len(spec.get("trays", [])) != expected_trays or len(spec.get("tables", [])) != 3 or len(spec.get("slots", [])) != 3:
            raise Fault("scene_object_count", f"Expected the approved 3 tables / {expected_trays} trays / 3 slots")
        self.ids = [x["tray_id"] for x in spec["trays"]]
        if len(set(self.ids)) != expected_trays:
            raise Fault("duplicate_tray_id")
        self.origin = np.array(spec["belt_frame"]["origin_world"], float)
        self.R = np.array(spec["belt_frame"]["rotation_world_from_belt"], float)
        if self.R.shape != (3, 3) or not np.allclose(self.R.T @ self.R, np.eye(3), atol=1e-6) or np.linalg.det(self.R) < .999:
            raise Fault("invalid_belt_rotation")
        self.belt_yaw = float(np.arctan2(self.R[1, 0], self.R[0, 0]))
        self.sizes = np.array([t.get("dimensions_m", [.56, .43, .105]) for t in spec["trays"]], float)
        self.goals = np.array([self.to_world(x["position_belt"]) for x in spec["slots"]])
        self.goal_yaw = np.array([self.belt_yaw + x["yaw_belt"] for x in spec["slots"]])
        self.period = float(spec.get("yaw_period_rad", 2*np.pi))
        if not (np.isclose(self.period, np.pi) or np.isclose(self.period, 2*np.pi)):
            raise Fault("unknown_yaw_contract")
        self.tables = {t["table_id"]: t for t in spec["tables"]}
        self.floor_top = min(t["dimensions_m"][2] for t in spec["tables"])
        self.belt_length = sum(t["dimensions_m"][0] for t in spec["tables"] if t["table_id"].startswith("front"))
        self.belt_width = min(t["dimensions_m"][1] for t in spec["tables"] if t["table_id"].startswith("front"))
        if self.belt_length <= 0:
            raise Fault("unsupported_table_naming")
        # Check actual table footprints before treating the front pair as one
        # supported union. The internal seam is not a fictitious 24 mm gap.
        front = [t for name,t in self.tables.items() if name.startswith('front')]
        intervals=[]
        for table in front:
            poly=rectangle(table['center_world'],table.get('yaw_world',0.),table['dimensions_m'])
            local=self.to_belt(np.c_[poly,np.repeat(self.origin[2],4)])
            intervals.append((float(local[:,0].min()),float(local[:,0].max()),float(local[:,1].min()),float(local[:,1].max())))
        intervals.sort()
        self.front_union = bool(len(intervals)==2 and
            abs(intervals[0][0])<1e-6 and abs(intervals[-1][1]-self.belt_length)<1e-6 and
            abs(intervals[0][1]-intervals[1][0])<1e-6 and
            all(abs(v0)<1e-6 and abs(v1-self.belt_width)<1e-6 for _,_,v0,v1 in intervals) and
            max(t['dimensions_m'][2] for t in front)-min(t['dimensions_m'][2] for t in front)<1e-6)

    def to_belt(self, p):
        return (np.asarray(p) - self.origin) @ self.R
    def to_world(self, p):
        return self.origin + self.R @ np.asarray(p)
    def footprint(self, pose, index, margin=0.):
        yaw, _ = quat_yaw_tilt(np.asarray(pose)[index, 3:])
        return rectangle(pose[index, :3], yaw, self.sizes[index], margin)
    def support_table(self, position):
        local_belt=self.to_belt(position)
        if self.front_union and .012<=local_belt[0]<=self.belt_length-.012 and .012<=local_belt[1]<=self.belt_width-.012:
            front=[name for name in self.tables if name.startswith('front')]
            return min(front,key=lambda name:np.linalg.norm(np.asarray(position)[:2]-np.asarray(self.tables[name]['center_world'])[:2]))
        matches = []
        for name, t in self.tables.items():
            local = rz(t.get("yaw_world", 0.)).T @ (np.asarray(position) - np.asarray(t["center_world"]))
            if np.all(np.abs(local[:2]) <= np.asarray(t["dimensions_m"][:2])/2 - .012):
                matches.append(name)
        return matches[0] if len(matches) == 1 else None
    def top_available(self, pose, i):
        # Use current poses, not stale initial support_parent after a successful move.
        return not any(j != i and pose[j, 2] > pose[i, 2] + .025 and overlap(self.footprint(pose, i), self.footprint(pose, j)) for j in range(len(self.ids)))
    def front_supported(self, position):
        return str(self.support_table(position)).startswith("front")
    def footprint_supported(self, position, yaw, size, margin=.004):
        # Candidate staging areas require the WHOLE footprint, unlike the source
        # scene's COM-only initial-overhang allowance. Adjacent front tables form a union.
        pts = rectangle(position, yaw, size)
        local = self.to_belt(np.c_[pts, np.repeat(self.origin[2], 4)])
        return bool(np.all(local[:, 0] >= margin) and np.all(local[:, 0] <= self.belt_length-margin) and np.all(local[:, 1] >= margin) and np.all(local[:, 1] <= self.belt_width-margin))
    def push_possible(self, pose, tray, destination, yaw, max_distance=.18, max_yaw=np.deg2rad(15), *, allow_supported_overhang=False):
        if not self.top_available(pose, tray) or not self.front_supported(pose[tray, :3]) or not self.front_supported(destination):
            return False
        start_yaw, tilt = quat_yaw_tilt(pose[tray, 3:])
        delta = float(wrap_angle(yaw-start_yaw, self.period))
        if tilt > np.deg2rad(5) or np.linalg.norm(destination[:2]-pose[tray, :2]) > max_distance or abs(delta) > max_yaw:
            return False
        for u in np.linspace(0., 1., 25):
            p = (1-u)*pose[tray, :3] + u*np.asarray(destination)
            heading = start_yaw + u*delta
            # The legacy route requires full support while building the 4 mm
            # inset. The explicit approximate route admits a supported COM
            # at every sample, including a source footprint overhang.
            if allow_supported_overhang:
                supported=self.front_supported(p)
            else:
                supported=self.footprint_supported(p, heading, self.sizes[tray], margin=.004*u)
            if not supported:
                return False
            poly = rectangle(p, heading, self.sizes[tray])
            if any(j != tray and overlap(poly, self.footprint(pose, j), clearance=.002) for j in range(len(self.ids))):
                return False
        return True


    def blockers(self, pose, tray, destination, yaw, clearance=.0):
        poly = rectangle(destination, yaw, self.sizes[tray])
        return [j for j in range(len(self.ids)) if j != tray and overlap(poly, self.footprint(pose, j), clearance)]
    def buffer(self, pose, tray, clearance=.025):
        # Prefer the currently unused far end; bounded candidates, no resampling a scene.
        yaw = self.goal_yaw[0]
        for u in np.linspace(self.belt_length-.25, .25, 30):
            p = self.to_world([u, self.belt_width/2, 0.])
            p[2] += .001
            if self.footprint_supported(p, yaw, self.sizes[tray]) and not self.blockers(pose, tray, p, yaw, clearance):
                if np.linalg.norm(p[:2]-pose[tray, :2]) > .15:
                    return p, yaw
        raise Fault("no_free_buffer", "Cannot clear an occupied target without an empty supported area")
    def best_mapping(self, pose):
        yaw, _ = quat_yaw_tilt(pose[:, 3:])
        def cost(p):
            return sum(np.linalg.norm(pose[t, :2]-self.goals[s, :2]) + .05*abs(wrap_angle(yaw[t]-self.goal_yaw[s], self.period)) for s, t in enumerate(p))
        return min(permutations(range(3)), key=cost)
    def at_slot(self, pose, tray, slot, position_tol=.015,
                angle_tol=np.deg2rad(3.), tilt_tol=np.deg2rad(4.)):
        yaw, tilt = quat_yaw_tilt(pose[tray, 3:])
        return bool(np.linalg.norm(pose[tray, :3]-self.goals[slot]) <= position_tol and
                    abs(wrap_angle(yaw-self.goal_yaw[slot], self.period)) <= angle_tol and
                    tilt <= tilt_tol)


@dataclass
class Operation:
    tray: int
    slot: int
    destination: np.ndarray
    yaw: float
    temporary: bool = False


class Scheduler:
    def __init__(self, geometry: Geometry, criteria=None, *, consistent_placement=False, require_full_footprint=True, use_actual_gap=False, approximate_overlap_cap_m=0., allow_supported_overhang=False):
        self.g = geometry
        self.criteria = criteria
        self.mapping = None
        self.consistent_placement = consistent_placement
        self.require_full_footprint = require_full_footprint
        self.use_actual_gap = use_actual_gap
        self.approximate_overlap_cap_m = approximate_overlap_cap_m
        self.allow_supported_overhang = allow_supported_overhang
        self.reservation_plan = None
    def planning_destination(self, slot):
        from .reservation_plan import positions
        planned=positions(self.g,self.mapping,self.reservation_plan)
        return (self.g.goals if planned is None else planned)[slot].copy()
    def choose(self, pose, forces=None):
        g = self.g
        if self.mapping is None:
            self.mapping = g.best_mapping(pose)
        from .reservation_plan import positions, protected_unchanged
        if self.reservation_plan is not None and not protected_unchanged(g,self.mapping,self.reservation_plan,pose,self.criteria):
            raise Fault('adaptive_reservation_protected_pose_changed')
        reservation_positions=positions(g,self.mapping,self.reservation_plan)
        # Do not mark task complete solely from geometry. Final stable physical gate follows.
        for slot, tray in enumerate(self.mapping):
            if self.criteria is None:
                at_slot = g.at_slot(pose, tray, slot)
            else:
                at_slot = g.at_slot(
                    pose, tray, slot,
                    position_tol=self.criteria.position_m,
                    angle_tol=np.deg2rad(self.criteria.yaw_deg),
                    tilt_tol=np.deg2rad(self.criteria.tilt_deg),
                )
            if at_slot and self.consistent_placement and self.criteria is not None:
                at_slot=slot_geometry_ready(g,pose,self.mapping,tray,slot,self.criteria,
                    require_full_footprint=self.require_full_footprint, use_actual_gap=self.use_actual_gap,
                    reservation_positions=reservation_positions,
                    approximate_overlap_cap_m=self.approximate_overlap_cap_m)
            if at_slot:
                continue
            if not g.top_available(pose, tray):
                upper = [j for j in range(3) if pose[j, 2] > pose[tray, 2] + .025 and overlap(g.footprint(pose, tray), g.footprint(pose, j)) and g.top_available(pose, j)]
                if not upper:
                    raise Fault("cyclic_or_unresolved_stack")
                t = upper[0]
                target_slot = self.mapping.index(t)
                if not g.blockers(pose, t, self.planning_destination(target_slot), g.goal_yaw[target_slot], .002):
                    return Operation(t, target_slot, self.planning_destination(target_slot), g.goal_yaw[target_slot])
                p, yaw = g.buffer(pose, t)
                return Operation(t, -1, p, yaw, True)
            blockers = g.blockers(pose, tray, self.planning_destination(slot), g.goal_yaw[slot], .002)
            if blockers:
                protected=set() if self.reservation_plan is None else set(self.reservation_plan['protected_trays'])
                if any(j in protected for j in blockers):raise Fault('adaptive_reservation_protected_blocker')
                top = [j for j in blockers if g.top_available(pose, j)]
                if not top:
                    # The requested tray itself can sit on a destination blocker.
                    # It is excluded from blockers, so searching only that list
                    # incorrectly declares a movable stack deadlocked. Clear an
                    # exposed upper tray first; buffer() still enforces support
                    # and separation, and execution must pass all physical guards.
                    upper = [j for j in range(3) if g.top_available(pose, j) and any(
                        pose[j, 2] > pose[b, 2] + .025 and
                        overlap(g.footprint(pose, j), g.footprint(pose, b))
                        for b in blockers)]
                    if upper:
                        p, yaw = g.buffer(pose, upper[0])
                        return Operation(upper[0], -1, p, yaw, True)
                    raise Fault("destination_blocked_by_stack")
                # A previously accepted tray can still intrude into its next
                # neighbour's slot within the 3 cm per-object tolerance.
                # Repair that small supported error before scheduling a costly
                # lift to the far buffer. The complete push sweep must be free.
                for blocker in top:
                    own_slot = self.mapping.index(blocker)
                    if (np.linalg.norm(pose[blocker, :2]-self.planning_destination(own_slot)[:2]) > .006 and
                            g.push_possible(pose, blocker, self.planning_destination(own_slot),
                                            g.goal_yaw[own_slot],
                                            **({'allow_supported_overhang': True} if self.allow_supported_overhang else {}))):
                        return Operation(blocker, own_slot, self.planning_destination(own_slot),
                                         g.goal_yaw[own_slot])
                p, yaw = g.buffer(pose, top[0])
                return Operation(top[0], -1, p, yaw, True)
            return Operation(tray, slot, self.planning_destination(slot), g.goal_yaw[slot])
        return None


def placement_ok(rows: dict, geometry: Geometry, criteria: Criteria, fps=20, *,
                 use_actual_gap=False, approximate=False, approximate_overlap_cap_m=0.):
    """Final gate: strict uses episode evidence; approximate uses the stable tail."""
    pose = np.asarray(rows["tray_pose"])
    n = len(pose)
    required = math.ceil(criteria.stable_s*fps)+1
    reasons = []
    for key in ("qpos", "qvel", "action", "base_action", "tray_pose"):
        if key in rows and not np.isfinite(rows[key]).all():
            reasons.append("nonfinite:"+key)
    if n < required:
        return False, {"reasons": reasons+["insufficient_stable_window"]}
    if not approximate:
        if np.any(rows["floor_contact"]): reasons.append("floor_contact")
        if np.any(rows["illegal_collision"]): reasons.append("illegal_collision")
        if np.max(rows["max_penetration"], initial=0.) > criteria.penetration_m: reasons.append("penetration")
        if np.any(rows.get("wrist_violation", np.zeros(n))): reasons.append("wrist_camera_violation")
        if 'transition_completed' in rows and not np.all(rows['transition_completed']): reasons.append('incomplete_control_interval')
    elif np.any(np.asarray(rows['floor_contact'])[-required:]):
        reasons.append('floor_contact')
    g = geometry
    best = None
    tail = pose[-required:]
    if approximate and any(not g.front_supported(point) for point in tail[:, :, :3].reshape(-1, 3)):
        reasons.append('not_front_supported')
    yaw, tilt = quat_yaw_tilt(tail[:, :, 3:])
    speed = np.linalg.norm(np.diff(tail[:, :, :3], axis=0), axis=2)*fps
    if np.any(speed > criteria.max_speed_m_s): reasons.append("not_stationary")
    if np.any(tilt > np.deg2rad(criteria.tilt_deg)): reasons.append("tilt")
    if np.any(np.asarray(rows["table_contact"])[-required:] <= 0): reasons.append("not_table_supported")
    if np.any(np.asarray(rows["gripper_contact_force"])[-required:] > criteria.contact_n): reasons.append("not_released")
    if np.any(np.asarray(rows["state"])[-required:, [7, 15]] < .06): reasons.append("grippers_not_open")
    local = g.to_belt(tail[:, :, :3])
    for p in permutations(range(3)):
        position = np.linalg.norm(tail[:, p, :3]-g.goals[None], axis=2)
        angles = np.abs(wrap_angle(yaw[:, p]-g.goal_yaw[None], g.period))
        relative_yaw = yaw[:, p]-g.belt_yaw
        ext = .5*(g.sizes[np.array(p), 0][None]*np.abs(np.cos(relative_yaw)) + g.sizes[np.array(p), 1][None]*np.abs(np.sin(relative_yaw)))
        gaps = np.diff(local[:, p, 0], axis=1)-ext[:, :-1]-ext[:, 1:]
        pose_ok=np.all(position <= criteria.position_m) and np.all(angles <= np.deg2rad(criteria.yaw_deg))
        if use_actual_gap:
            if not pose_ok:
                continue
            if any(g.support_table(point) is None for point in tail[:,:, :3].reshape(-1,3)):
                continue
            if approximate and approximate_overlap_cap_m > 0:
                if any(footprint_signed_boundary_gap(g.footprint(frame,i),g.footprint(frame,j)) < -approximate_overlap_cap_m
                       for frame in tail for i in range(3) for j in range(i+1,3)):
                    continue
                actual=[footprint_signed_neighbour_gaps(frame[list(p),:3],
                    headings[list(p)],g.sizes[list(p)]) for frame,headings in zip(tail,yaw)]
            else:
                actual=[footprint_neighbour_gaps(frame[list(p),:3],
                    headings[list(p)],g.sizes[list(p)]) for frame,headings in zip(tail,yaw)]
                if any(value is None for value in actual):
                    continue
            gaps=np.asarray(actual)
        minimum_gap = (-approximate_overlap_cap_m if approximate and approximate_overlap_cap_m > 0
                       else criteria.gap_min_m)
        if pose_ok and np.all(gaps >= minimum_gap-1e-6) and np.all(gaps <= criteria.gap_max_m+1e-6):
            best = {"slot_to_tray": [g.ids[t] for t in p], "max_position_error_m": float(position.max()), "max_yaw_error_deg": float(np.degrees(angles.max())), "final_gaps_m": gaps[-1].tolist()}
            if use_actual_gap:
                best['gap_measure']=('signed_rotated_footprint_boundary' if approximate and approximate_overlap_cap_m > 0
                                     else 'disjoint_rotated_footprint_euclidean_boundary')
            break
    if best is None: reasons.append("pose_or_gap_outside_contract")
    return not reasons, {"reasons": reasons, "stable_samples": required, "placement": best}
