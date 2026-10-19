def push(machine,operation,side,relation,*,separation=False,free_retreat=False):
    from .runtime import _homogeneous
    r=machine.r;c=machine.c;tray=operation.tray
    with action(machine,'push',destination=operation.destination,yaw=operation.yaw,separation=separation):
        free_goal=None
        withdraw_free=False
        if free_retreat:
            free='right' if side=='left' else 'left';p,R=r.sim.tcp(free)
            withdraw_free=getattr(r,'primitive_lift_xy_shift_m',0.)>.005
            p[2]+=0.06
            if withdraw_free:p[:2]-=.06*r.d.body('base_link').xmat.reshape(3,3)[:2,0]
            free_goal=(free,p,R)
        e=r.observation();actual=e['tray_pose'][tray];yaw,_=quat_yaw_tilt(actual[3:])
        if free_retreat:
            # Continue the already loaded retained hand's COMMAND relationship.
            # Reconstructing from the deflected measured TCP discards its servo
            # compression, leaving a systematic short push at every handoff.
            shadow=r._shadow(r.sim.target).site(side+'_tcp')
            measured=r.sim.tcp(side)[0]
            error=float(np.linalg.norm(shadow.xpos-measured))
            if error>.05:raise Fault('primitive_excess_servo_deflection',{side:error})
            body=r.d.body(machine.g.ids[tray])
            relation=np.linalg.inv(_homogeneous(body.xpos,body.xmat.reshape(3,3)))@_homogeneous(shadow.xpos,shadow.xmat.reshape(3,3))
            machine.log.event('primitive_push_compliance_reference',side=side,tcp_deflection_m=error,
                              qualification='command_reference_only_not_observed_rigid_attachment')
        delta=operation.destination[:2]-actual[:2]
        position=actual[:3].copy();position[:2]=operation.destination[:2]
        feedforward=.012 if separation else c.primitive_push_compensation_m
        if withdraw_free:feedforward=min(feedforward,.020)
        position[:2]+=feedforward*delta/max(float(np.linalg.norm(delta)),1e-9)
        if withdraw_free:position[2]-=c.push_withdraw_preload_scale*c.primitive_touchdown_preload_m
        machine.log.event('primitive_push_feedforward',distance_m=feedforward,
                          nominal_destination=operation.destination,command_position=position)
        R=r.d.body(machine.g.ids[tray]).xmat.reshape(3,3).copy()
        R=rz(float(wrap_angle(operation.yaw-yaw,machine.g.period)))@R
        T=_homogeneous(position,R)@relation
        goals={side:(T[:3,3],T[:3,:3])}
        if free_goal is not None:goals[free_goal[0]]=(free_goal[1],free_goal[2])
        # Free-arm clearance and the held-arm push share ONE continuous path.
        # Preserve the free gripper's open target; only the retained hand closes.
        command_reference = c.loaded_command_reference_enabled
        normal_start_z = (float(r._shadow(r.sim.target).site(side+'_tcp').xpos[2])
                          if command_reference else None)
        points=r.cartesian(goals,wrist=True,preview_only=True,start_from_command=command_reference)
        for point in points:point[7 if side=='left' else 15]=c.gripper_close_m
        if withdraw_free:
            col=7 if free=='left' else 15;start=float(points[0][col])
            for i,point in enumerate(points):point[col]=start+(c.gripper_open_m-start)*i/max(1,len(points)-1)
        available=remaining(r)-c.primitive_settle_s
        if withdraw_free:
            free_points=r.cartesian({free:(free_goal[1],free_goal[2])},opening=c.gripper_open_m,
                                    wrist=True,preview_only=True,start_from_command=command_reference)
            # Give the released fingers clearance BEFORE the tray reaches
            # them. Keep this intermediate knot in the single C2 reference.
            from scipy.spatial.transform import Rotation,Slerp
            previous=np.array(free_points[-1],float);shadow=r._shadow(previous).site(side+'_tcp')
            start_p=shadow.xpos.copy();start_R=shadow.xmat.reshape(3,3).copy()
            rotations=Slerp([0,1],Rotation.from_matrix(np.stack([start_R,T[:3,:3]])))
            count=max(1,math.ceil(float(np.linalg.norm(T[:3,3]-start_p))/.025))
            held_points=[previous.copy()]
            for u in np.linspace(0,1,count+1)[1:]:
                previous=r.solve_pair({side:(start_p+u*(T[:3,3]-start_p),rotations(u).as_matrix())},previous)
                previous[7 if side=='left' else 15]=c.gripper_close_m
                held_points.append(previous.copy())
            middle=np.array(free_points[-1],float)
            cols=np.arange(0,7) if side=='left' else np.arange(8,15)
            middle[cols]+=.3*(held_points[-1][cols]-middle[cols])
            points=np.stack([points[0],middle,held_points[len(held_points)//2],held_points[-1]])
        normal_check = None
        if command_reference:
            normal_check = lambda path: supported_normal_path_rejection(
                r, path, side, normal_start_z, float(T[2,3]))
            machine.log.event('supported_command_reference',side=side,
                start_z_m=normal_start_z,end_z_m=float(T[2,3]),normal_tolerance_m=.00025,
                validation_samples=201,shortcut_enabled=not withdraw_free,
                qualification='command_geometry_only_original_physical_support_guards_required')
        planned=plan(r,points,available=available,minimum=min(2.4,available-.05),
                     allow_shortcut=not withdraw_free,
                     extra_path_check=normal_check)
        if c.push_use_full_budget:
            planned=retime_push_to_budget(r,planned,available)
        if c.push_yaw_feedback_enabled:
            from .yaw_feedback import execute_feedback
            feedback_start_z=float(r._shadow(r.sim.target).site(side+'_tcp').xpos[2])
            feedback_normal_check=lambda path: supported_normal_path_rejection(
                r,path,side,feedback_start_z,float(T[2,3]))
            execute_feedback(machine,planned,operation,side,position,R,relation,free_goal,feedback_normal_check)
        else:
            execute(r,planned)
        def accepted(x):
            pose=x['tray_pose'][tray];a,_=quat_yaw_tilt(pose[3:])
            geometry=(not machine.g.blockers(x['tray_pose'],tray,pose[:3],a,.085)) if separation else (
                np.linalg.norm(pose[:2]-operation.destination[:2])<=c.criteria.position_m and
                abs(wrap_angle(a-operation.yaw,machine.g.period))<=np.deg2rad(c.criteria.yaw_deg))
            # Final neighbour clearance is checked after measured release in
            # Machine.verify_operation; a loaded gripper elastically biases yaw.
            if free_retreat:
                geometry=geometry and x['gripper_contact_force'][tray,1 if side=='left' else 0]<=c.criteria.contact_n
            return geometry and x['table_contact'][tray]>0 and x['gripper_contact_force'][tray,0 if side=='left' else 1]>c.criteria.contact_n
        settle(r,accepted,c.primitive_settle_s)
