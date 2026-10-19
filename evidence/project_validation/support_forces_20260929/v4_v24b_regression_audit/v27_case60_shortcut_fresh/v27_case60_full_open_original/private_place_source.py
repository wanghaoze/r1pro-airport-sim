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
    alignment_completed=False
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
            if c.transport_align_use_full_budget:
                alignment_plan=retime_push_to_budget(r,alignment_plan,remaining(r)-c.primitive_settle_s,
                    event_name='primitive_transport_align_budget_retime')
            execute(r,alignment_plan)
            settle(r,lambda x:np.linalg.norm(x['tray_pose'][tray,:2]-staged[:2])<=c.criteria.position_m,c.primitive_settle_s)
        alignment_completed=True
    e=r.observation()
    with action(machine,'place',table_height_m=top,staged=staged,retained_side=keep):
        machine.transition(State.PLACE_TRAY,'descend')
        saved_alignment_relation = ({side:value.copy() for side,value in r.grasp_rel.items()}
            if c.placement_preserve_command_grasp_enabled and alignment_completed and valid_command_grasp(r,tray) else None)
        # The original measured reference always gets first refusal. Compliance
        # validation remains outside the candidate planning catch.
        continue_loaded_reference(r)
        from .reference_candidates import plan_reference_candidate
        descent, release_plan = plan_reference_candidate(r,
            lambda: _plan_place_descent(machine, operation, staged, e, top, combined_descent,
                keep, release, alignment_completed), saved_alignment_relation,
            enabled=c.placement_preserve_command_grasp_enabled, check_command=checked_command_tcp)
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
        release_frames=finish_release_verification(r,placed,release_frames)
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
