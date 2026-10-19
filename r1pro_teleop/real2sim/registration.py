"""Portable scene registration estimates, separate from replay and control.

These are offline initial conditions, not online trajectory corrections. SI units,
right-handed frames, xyz positions and wxyz quaternions throughout.
"""
import numpy as np


def estimate_registration(trajectory, pad_centres, *, table_xy=(.85, 0.),
                          table_height=.8, tray_size=(.56, .43, .105)):
    """Estimate from recorded FK, using existing scene geometry as a size prior.

    pad_centres is [frame, left/right, xyz] in base_link. Fore/aft contact along
    a long rim is underdetermined; retain a declared 0.50 m tray-centre prior.
    No physical replay outcomes are used to select the estimate.
    """
    pads = np.asarray(pad_centres, dtype=float)
    if pads.shape != (len(trajectory.seconds), 2, 3) or not np.isfinite(pads).all():
        raise ValueError("real2sim_invalid_registration_fk")
    grips = trajectory.commands[:, [trajectory.channels.index(s + '_gripper_opening_m')
                                      for s in ('left', 'right')]]
    # A phase detector relative to the recorded open/closed range, not acceptance.
    spans = np.ptp(grips, axis=0)
    thresholds = (grips.max(0) + grips.min(0)) / 2
    closed = grips <= thresholds
    prompt = trajectory.provenance['prompt']
    if prompt == 'Pick up the tray':
        if np.any(spans <= 0):
            raise ValueError('real2sim_pick_gripper_phase_missing')
        events = [(int(np.flatnonzero(closed[:, side])[0]), side) for side in range(2)]
        frame, side = min(events)
        yaw = 0.
        # Long-side collision centre from existing tapered tray, about 0.2013 m.
        rim_half_width = .2012916113247164
        centre = np.array([.50, pads[frame, side, 1] - (1 if side == 0 else -1)*rim_half_width,
                           table_height + .001])
        reference = centre.copy()
        method = 'first_recorded_gripper_closure_long_side_alignment_with_table_support'
        initial_state = 'resting_on_table'
    elif prompt == 'Place the tray':
        if not closed[0].all() or np.any(spans <= 0):
            raise ValueError('real2sim_place_held_phase_missing')
        frame = 0
        delta = pads[0, 0] - pads[0, 1]
        yaw = float(np.clip(np.arctan2(-delta[0], delta[1]), -.1745329252, .1745329252))
        centre = pads[0].mean(0) - np.array([0., 0., .09])
        # Align the anticipated release pose with the unchanged target table.
        release = int(np.flatnonzero(~closed.all(1))[0])
        reference = pads[release].mean(0)
        method = 'initial_bilateral_pad_midpoint_rim_height_prior_and_release_table_alignment'
        initial_state = 'held_pose_estimate_without_attachment'
    else:
        raise ValueError('real2sim_registration_prompt_unsupported')
    base = np.array([table_xy[0]-reference[0], table_xy[1]-reference[1], 0.])
    return dict(schema='real2sim_registration/1', status='estimated_not_measured',
        units='metres_radians', quaternion_order='wxyz', frame='scene_world',
        source_parquet_sha256=trajectory.provenance['parquet_sha256'],
        prompt=prompt, method=method, anchor_frame=frame,
        anchor_time_s=float(trajectory.seconds[frame]), initial_state=initial_state,
        base_pose=dict(xyz=base.tolist(), quaternion_wxyz=[1., 0., 0., 0.]),
        tray_pose=dict(xyz=(base+centre).tolist(),
                       quaternion_wxyz=[float(np.cos(yaw/2)),0.,0.,float(np.sin(yaw/2))]),
        tray_in_base_xyz=centre.tolist(), tray_yaw_rad=yaw,
        geometry_prior=dict(table_size_xyz_m=[1.2,.6,table_height], tray_size_xyz_m=list(tray_size),
                            dimensions_measured=False, source='existing_project_assets_unchanged'),
        uncertainty=dict(translation_m=.03, yaw_rad=.1745329252, interpretation='heuristic_range_not_confidence_interval'),
        assumptions=['base_static_as_recorded', 'tray_long_axis_parallel_to_base_forward',
                     'Pick_fore_aft_centre_0.50m_prior', 'Place_pad_to_tray_bottom_0.09m_prior',
                     'no_gain_friction_or_geometry_fitting'],
        scene_registration_verified=False)


def validate_registration(registration):
    if (registration.get('schema') != 'real2sim_registration/1'
            or registration.get('units') != 'metres_radians'
            or registration.get('quaternion_order') != 'wxyz'
            or registration.get('frame') != 'scene_world'):
        raise ValueError('real2sim_invalid_registration_schema')
    for key in ('base_pose', 'tray_pose'):
        pose = registration[key]
        p, q = np.asarray(pose['xyz']), np.asarray(pose['quaternion_wxyz'])
        if p.shape != (3,) or q.shape != (4,) or not np.isfinite(p).all() or not np.isfinite(q).all() or abs(np.linalg.norm(q)-1) > 1e-6:
            raise ValueError('real2sim_invalid_registration_pose')
    b = registration['base_pose']
    if abs(b['xyz'][2]) > 1e-9 or np.linalg.norm(np.asarray(b['quaternion_wxyz'])[1:3]) > 1e-9:
        raise ValueError('real2sim_registration_planar_base_required')
    return registration
