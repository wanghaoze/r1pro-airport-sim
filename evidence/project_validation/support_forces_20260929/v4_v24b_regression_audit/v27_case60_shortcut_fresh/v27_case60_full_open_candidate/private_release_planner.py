def _plan_place_descent(machine, operation, staged, e, top, combined_descent, keep, release, alignment_completed):
    r=machine.r;c=machine.c;tray=operation.tray
    target=e['tray_pose'][tray,:3].copy()
    yaw,_=quat_yaw_tilt(e['tray_pose'][tray,3:])
    yaw=yaw+float(wrap_angle(operation.yaw-yaw,machine.g.period))
    # Correct measured alignment residual as part of the fully planned
    # descent, rather than preserving an off-centre table-edge arrival.
    target[:2]=staged[:2]
    # All descents command a level tray, including an already aligned
    # arrival. Retaining the measured arrival tilt embeds servo sag in the
    # target; later physical leveling would then lift its bottom off-table.
    body_id=r.m.body(machine.g.ids[tray]).id
    vertices=r.evidence.local_vertices[body_id]
    target_rotation=rz(yaw)
    target=touchdown_position(target,vertices,target_rotation,table_height=top,
                              preload=c.primitive_touchdown_preload_m)
    if c.placement_alignment_xy_feedforward_enabled:
        from .alignment_feedforward import alignment_xy_target
        target, correction_info = alignment_xy_target(machine.g, e['tray_pose'], tray,
            staged, target, yaw, alignment_completed=alignment_completed,
            scope=c.placement_alignment_xy_feedforward_scope)
        machine.log.event('placement_alignment_xy_feedforward', target_tray=tray, **correction_info)
    points=object_points(r,target,yaw)
    machine.log.event('primitive_descent_geometry',combined_xy_descent=combined_descent,target_position=target,
                      target_yaw_rad=yaw,target_tilt_rad=0.)
    if combined_descent and keep:
        for s in release:
            col=7 if s=='left' else 15;start=float(points[0][col])
            preload=max(c.gripper_close_m,float(r.sim.state()[col])-.005)
            for i,point in enumerate(points):point[col]=start+(preload-start)*i/max(1,len(points)-1)
        machine.log.event('primitive_supported_release_preload',sides=release,
                          qualification='fingers_remain_clamped_until_measured_table_contact')
    # Release only enough to clear measured fingers; the ordinary open
    # limit remains unchanged. Full opening may follow during retreat.
    release_start=np.array(points[-1],float)
    release_end=release_endpoint(release_start,r.sim.state(),release,
                                open_limit=c.gripper_open_m,clearance=c.primitive_release_clearance_m)
    if combined_descent and keep:
        for side in release:release_end[7 if side=='left' else 15]=c.gripper_open_m
    machine.log.event('primitive_release_plan',sides=release,measured_opening=r.sim.state()[[7,15]],
                      command_opening=release_end[[7,15]],clearance_m=c.primitive_release_clearance_m)
    release_plan=plan(r,[release_start,release_end],available=remaining(r)-.3)
    try:
        descent_frames=descent_budget_frames(remaining_frames=r.primitive_deadline_step-r.steps,
                                            release_frames=release_plan[1],support_frames=math.ceil(.1*c.fps))
    except ValueError as exc:
        raise Fault('primitive_insufficient_time',str(exc)) from exc
    descent=plan(r,points,available=descent_frames/c.fps,allow_shortcut=True)
    return descent, release_plan
