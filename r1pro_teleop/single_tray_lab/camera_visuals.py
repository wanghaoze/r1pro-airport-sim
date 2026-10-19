"""Remove only wrist camera housing visuals; retain complete grippers."""

def remove_wrist_camera_housing_visuals(root):
    candidates = []
    for side in ('left', 'right'):
        for suffix in ('realsense_link',):
            name = f'{side}_{suffix}'
            kind = 'wrist_camera_housing' if suffix == 'realsense_link' else 'wrist_gripper_shell'
            body = root.find(f".//body[@name='{name}']")
            if body is None:
                raise ValueError('missing_' + kind + '_body:' + name)
            geoms = [g for g in body.findall('geom')
                     if g.get('mesh') == name and g.get('group') == '1']
            if len(geoms) != 1:
                raise ValueError('ambiguous_' + kind + '_visual:' + name)
            geom = geoms[0]
            weights = [float(geom.get(key)) for key in ('mass', 'density')
                       if key in geom.attrib]
            if (geom.get('contype') != '0' or geom.get('conaffinity') != '0'
                    or not weights or any(value != 0. for value in weights)):
                raise ValueError(kind + '_visual_is_physical:' + name)
            candidates.append((body, geom))
    removed = [dict(body=b.get('name'), geom=g.get('name'), mesh=g.get('mesh'))
               for b, g in candidates]
    for body, geom in candidates:
        body.remove(geom)
    return dict(profile='wrist_camera_housing_removed_gripper_shell_preserved_v3',
                removed_visuals=removed, collision_geometry_removed=False,
                camera_pose_changed=False, gripper_shell_visuals_removed=False,
                gripper_shell_visuals_preserved=True,
                finger_visuals_preserved=True, physical_grippers_preserved=True)
