"""Room-local reduction of actual PhysX contact views, for empty Pick/Place.

Runs only on the shared engine thread. No pose writes or simulated feedback.
"""
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .isaac_collision_footprint import maximum_union_overhang


def cpu(x):
    return x.detach().cpu().numpy() if hasattr(x, 'detach') else np.asarray(x)


class RoomContacts:
    def __init__(self, view, names, owners, origin, size, tables, footprint):
        self.view = view
        self.names = list(names)
        self.index = {Path(p).name: i for i, p in enumerate(view.prim_paths)}
        if set(self.index) != set(names):
            raise ValueError('parallel_contact_sensor_identity')
        self.owners = list(owners)
        self.origin = np.asarray(origin)
        self.size = np.asarray(size)
        self.tables = tables
        self.footprint = np.asarray(footprint)
        self.tray_cols = np.flatnonzero(np.asarray(owners) == 'tray_0')
        self.table_cols = np.array([i for i, o in enumerate(owners)
                                   if o in {t['table_id'] for t in tables}], int)
        if not len(self.table_cols):
            raise ValueError('parallel_table_filters_missing')
        self.last_detail = None

    def contact(self, detailed=False):
        scalar = np.linalg.norm(cpu(self.view.get_contact_force_matrix(dt=.002)), axis=-1)
        if scalar.shape != (len(self.names), len(self.owners)):
            raise ValueError('parallel_contact_matrix_shape:' + str(scalar.shape))
        fingers = np.zeros((1, 2))
        for s, side in enumerate(('left', 'right')):
            ids = [self.index[f'{side}_gripper_finger_link{k}'] for k in (1, 2)]
            fingers[0, s] = scalar[np.ix_(ids, self.tray_cols)].sum()
        table = np.array([scalar[self.index['tray_0'], self.table_cols].sum()])
        data = self.view.get_contact_force_data(dt=.002)
        counts, starts = [cpu(x).reshape(scalar.shape) for x in data[4:]]
        active = [j for row, col in np.argwhere(counts > 0)
                  for j in range(int(starts[row, col]), int(starts[row, col]+counts[row, col]))]
        if active:
            import torch
            sep = data[3]
            depth = max(0., -float(sep[torch.as_tensor(active, device=sep.device)].min().item())) if hasattr(sep, 'detach') else max(0., -float(np.asarray(sep)[active].min()))
        else:
            depth = 0.
        if detailed:
            forces, points, normals, separations = [cpu(x).copy() for x in data[:4]]
            self.last_detail = (forces, points-self.origin, normals, separations, counts, starts)
        if not np.isfinite(np.r_[fingers.ravel(), table, depth]).all():
            raise ValueError('parallel_nonfinite_contact')
        return fingers, table, np.zeros((1, 2)), depth

    def observation(self, state, command, base_pose, initial_bottom):
        positions, quats = [cpu(x).copy() for x in self.view.get_world_poses()]
        positions -= self.origin
        velocities = cpu(self.view.get_velocities()).copy()
        idx = self.index['tray_0']
        pose = np.r_[positions[idx], quats[idx]]
        R = Rotation.from_quat(pose[[4, 5, 6, 3]]).as_matrix()
        w, x, y, z = base_pose[3:]
        yaw = float(np.arctan2(2*(w*z+x*y), 1-2*(y*y+z*z)))
        forward = np.array([np.cos(yaw), np.sin(yaw), 0.])
        left = np.array([-np.sin(yaw), np.cos(yaw), 0.])
        fingers, table, support, depth = self.contact(detailed=True)
        forces, points, normals, separation, counts, starts = self.last_detail
        edges = np.zeros((1, 2), int)
        short = int(np.argmin(self.size[:2])); long = 1-short
        for si, side in enumerate(('left', 'right')):
            signs = []
            for k in (1, 2):
                row = self.index[f'{side}_gripper_finger_link{k}']
                for col in self.tray_cols:
                    a = int(starts[row, col]); b = a+int(counts[row, col])
                    for point, force in zip(points[a:b], forces[a:b]):
                        if abs(float(np.ravel(force)[0])) <= .01: continue
                        local = R.T @ (point-pose[:3])
                        d = abs(abs(local[short])-self.size[short]/2)
                        if d <= .05 and d <= abs(abs(local[long])-self.size[long]/2):
                            signs.append(int(np.sign(local[short])))
            if signs and len(set(signs)) == 1: edges[0, si] = signs[0]
        axis = R[:, int(np.argmax(self.size[:2]))]
        angle = np.arccos(np.clip(abs(axis[:2] @ forward[:2])/np.linalg.norm(axis[:2]), 0, 1))
        boundary = maximum_union_overhang(self.footprint @ R.T+pose[:3], self.tables) <= .05
        rows = []
        by_index = {v:k for k,v in self.index.items()}
        for row, col in np.argwhere(counts > 0):
            a = int(starts[row, col]); b = a+int(counts[row, col])
            for j in range(a,b):
                f = float(np.ravel(forces[j])[0]); sep = float(np.ravel(separation[j])[0])
                if abs(f) <= .01 and sep >= 0: continue
                rows.append(dict(sensor=by_index[int(row)], other=self.owners[int(col)],
                    point_world=points[j].tolist(), normal_world=normals[j].tolist(),
                    normal_force_n=f, separation_m=sep))
        self.contact_rows = rows
        return dict(state=np.asarray(state).copy(), command=np.asarray(command).copy(),
            tray_pose=pose[None], finger_force=fingers, table_force=table,
            payload_rigid_support=support, long_edge_sign=edges, loaded=np.zeros(1,bool),
            payload_on_tray=np.zeros(1,bool), payload_speed=np.zeros(1),
            boundary_ok=np.array([boundary]), axis_error_rad=np.array([angle]),
            lift_clearance=np.array([pose[2]-initial_bottom]), robot_position=base_pose[:3].copy(),
            robot_yaw=yaw, robot_forward=forward, robot_left=left,
            penetration_m=depth, coat_positions=np.empty((1,0,3)),
            tray_velocity=velocities[idx:idx+1], rigid_pose=np.c_[positions,quats],
            front_region_ok=True)
