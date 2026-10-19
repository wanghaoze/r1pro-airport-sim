def place(machine,operation,staged):
    """One local descent plus confirmed unloading/release; base travel is separate."""
    r=machine.r;c=machine.c;tray=operation.tray;e=r.observation()
    table=machine.g.support_table(staged)
    if table is None:raise Fault('primitive_place_no_table')
    top=machine.g.tables[table]['dimensions_m'][2]
    need_push=np.linalg.norm(staged[:2]-operation.destination[:2])>.01
    keep=None
    if need_push and c.keep_place_contact:
        direction=operation.destination[:2]-staged[:2]
        keep=min(('left','right'),key=lambda s:np.dot(r.sim.tcp(s)[0][:2]-staged[:2],direction))
    release=[s for s in ('left','right') if s!=keep]
    # Explicit transport endpoint, not repeated corrections hidden in place.
    # It has its own complete three-second budget and audit event.
    combined_descent=getattr(r,'primitive_lift_xy_shift_m',0.)>.005
    alignment_plan=None
    if combined_descent:
        # The pickup's lateral escape does not imply that the destination
        # requires a combined move. Try a complete private loaded alignment
        # first; a rejected proposal has executed no part of the trajectory.
        try:
            continue_loaded_reference(r)
            current=r.observation()['tray_pose'][tray]
            aligned=current[:3].copy();aligned[:2]=staged[:2]
            yaw,_=quat_yaw_tilt(current[3:])
            goal_yaw=yaw+float(wrap_angle(operation.yaw-yaw,machine.g.period))
            points=object_points(r,aligned,goal_yaw)
            alignment_plan=plan(r,points,available=c.primitive_seconds-c.primitive_settle_s,allow_shortcut=True)
        except Fault as exc:
            machine.log.event('transport_align_deferred',reason=exc.code,detail=exc.detail,
                              qualification='planning_rejection_before_any_alignment_motion')
        else:
            combined_descent=False
            machine.log.event('transport_align_separated',qualification='complete_alignment_planned_before_execution')
    if not combined_descent:
        with action(machine,'transport_align',destination_xy=staged[:2]):
            if alignment_plan is None:
                continue_loaded_reference(r)
                current=r.observation()['tray_pose'][tray]
                aligned=current[:3].copy();aligned[:2]=staged[:2]
                yaw,_=quat_yaw_tilt(current[3:]);goal_yaw=yaw+float(wrap_angle(operation.yaw-yaw,machine.g.period))
                points=object_points(r,aligned,goal_yaw)
                alignment_plan=plan(r,points,available=remaining(r)-c.primitive_settle_s,allow_shortcut=True)
            machine.transition(State.TRANSPORT_TRAY,'preplace')
            execute(r,alignment_plan)
            settle(r,lambda x:np.linalg.norm(x['tray_pose'][tray,:2]-staged[:2])<=c.criteria.position_m,c.primitive_settle_s)
    e=r.observation()
    with action(machine,'place',table_height_m=top,staged=staged,retained_side=keep):
        machine.transition(State.PLACE_TRAY,'descend')
        continue_loaded_reference(r)
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
        machine.log.event('primitive_release_plan',sides=release,measured_opening=r.sim.state()[[7,15]],
                          command_opening=release_end[[7,15]],clearance_m=c.primitive_release_clearance_m)
        release_plan=plan(r,[release_start,release_end],available=remaining(r)-.3)
        try:
            descent_frames=descent_budget_frames(remaining_frames=r.primitive_deadline_step-r.steps,
                                                release_frames=release_plan[1],support_frames=math.ceil(.1*c.fps))
        except ValueError as exc:
            raise Fault('primitive_insufficient_time',str(exc)) from exc
        descent=plan(r,points,available=descent_frames/c.fps,allow_shortcut=True)
        machine.transition(State.PLACE_TRAY,'descend')
        support_frames=execute(r,descent,lambda x:x['table_contact'][tray]>0)
        machine.transition(State.PLACE_TRAY,'support_contact')
        # Touchdown authorizes STARTING the smooth opening ramp. Table support
        # is checked throughout that ramp; final placement still needs stable
        # release observations and the task's separate one-second acceptance.
        if support_frames<1:settle(r,lambda x:x['table_contact'][tray]>0,.1,stable_frames=1)
        r.holding=None;r.grasp_rel=None
        if keep:r.retained_contact=(tray,keep);r.check_retained_contact()
        cols=[0 if s=='left' else 1 for s in release]
        def placed(x):
            pose=x['tray_pose'][tray];a,tilt=quat_yaw_tilt(pose[3:])
            return (x['table_contact'][tray]>0 and
                np.all(x['gripper_contact_force'][tray,cols]<=c.criteria.contact_n) and
                np.linalg.norm(pose[:3]-staged)<=c.criteria.position_m and
                abs(wrap_angle(a-operation.yaw,machine.g.period))<=np.deg2rad(c.criteria.yaw_deg) and
                tilt<=np.deg2rad(c.criteria.tilt_deg))
        machine.transition(State.PLACE_TRAY,'open')
        release_frames=execute(r,release_plan,placed)
        if release_frames<2:
            x=r.observation()
            raise Fault('primitive_release_not_verified',{'stable_frames':release_frames,
                'force':x['gripper_contact_force'][tray],'table_contact':int(x['table_contact'][tray]),
                'pose':x['tray_pose'][tray],'command_opening':r.sim.target[[7,15]],
                'measured_opening':r.sim.state()[[7,15]]})
    if keep:
        return machine.push(operation,retained_side=keep)
    machine.retreat()
    return False
