"""Run with Blender 5.2 --background --python this.py -- --output DIR.

Photo-inspired visual assets, metres/Z-up. Original robot/table geometry is
read-only; the editable .blend is an illustration, not a physics episode.
The separate coat_physics.obj is an open triangulated rest surface for flex.
"""
from pathlib import Path
import argparse, hashlib, json, math, random, sys, xml.etree.ElementTree as ET

def arguments():
    p=argparse.ArgumentParser();p.add_argument('--output',default='resources/single_tray_lab_v1')
    p.add_argument('--render',action='store_true');p.add_argument('--render-width',type=int,default=1280)
    return p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])

def main():
    import bpy
    from mathutils import Vector,Matrix,Quaternion
    a=arguments();project=Path(__file__).resolve().parents[1];out=(project/a.output).resolve()
    if not out.is_relative_to(project):raise ValueError('assets_must_remain_in_project')
    out.mkdir(parents=True,exist_ok=True)
    if (out/'single_tray_lab.blend').exists():raise ValueError('refuse_existing_blend; use_new_output_version')
    for folder in ('meshes','textures','previews'): (out/folder).mkdir(exist_ok=True)
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    scene=bpy.context.scene;scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1
    materials={};groups={};sources={};objects=[]
    def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    def material(name,rgba,rough=.55,metal=0.,transmission=0.,emission=0.):
        m=bpy.data.materials.new(name);m.use_nodes=True;m.diffuse_color=rgba
        bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=rgba
        bs.inputs['Roughness'].default_value=rough;bs.inputs['Metallic'].default_value=metal
        bs.inputs['Alpha'].default_value=rgba[3];bs.inputs['Transmission Weight'].default_value=transmission
        if emission:bs.inputs['Emission Color'].default_value=rgba;bs.inputs['Emission Strength'].default_value=emission
        materials[name]=dict(rgba=list(rgba),roughness=rough,metallic=metal,transmission=transmission,emission_strength=emission)
        return m
    mat={
        'floor':material('floor_light_gray_granular',(.68,.69,.68,1),.87),
        'white':material('wall_white',(.84,.85,.84,1),.72),
        'gap':material('wall_groove_shadow',(.57,.59,.58,1),.8),
        'black':material('matte_black',(.018,.022,.025,1),.55),
        'screen':material('black_display_glass',(.009,.013,.017,1),.21,.12),
        'wood':material('warm_oak',(.44,.28,.14,1),.5),
        'desk':material('gray_wood_desk',(.35,.34,.31,1),.6),
        'silver':material('silver_gray_polished_panels',(.61,.63,.65,1),.22,.78),
        'steel':material('gray_metal',(.24,.27,.29,1),.4,.65),
        'glass':material('glass_partition',(.62,.72,.70,.23),.15,.0,1.),
        'frost':material('glass_frosted_dots',(.71,.71,.59,.74),.8),
        'fabric':material('gray_mesh_chair_fabric',(.13,.15,.16,1),.92),
        'green':material('green_chair_upholstery',(.32,.41,.055,1),.75),
        'pack':material('backpack_charcoal_canvas',(.045,.052,.055,1),.94),
        'coat':material('coat_blue_gray_fabric',(.13,.18,.23,1),.98),
        'laptop':material('laptop_dark_graphite',(.10,.115,.13,1),.48,.24),
        'light':material('lamp_diffuser',(.94,.95,.94,1),.3,emission=3.),
        'exit':material('exit_green',(.01,.35,.20,1),.6,emission=.8),
    }
    rng=random.Random(42005);size=512;pixels=[]
    image=bpy.data.images.new('floor_grain_generated',width=size,height=size)
    for i in range(size*size):
        v=max(.43,min(.80,.665+rng.gauss(0,.047)));pixels.extend((v,v*1.01,v*.99,1.))
    image.pixels=pixels;image.filepath_raw=str(out/'textures/floor_grain.png');image.file_format='PNG';image.save()
    nodes=mat['floor'].node_tree.nodes;tex=nodes.new('ShaderNodeTexImage');tex.image=image
    uv=nodes.new('ShaderNodeTexCoord');mapping=nodes.new('ShaderNodeVectorMath');mapping.operation='SCALE';mapping.inputs[3].default_value=4
    mat['floor'].node_tree.links.new(uv.outputs['Generated'],mapping.inputs[0]);mat['floor'].node_tree.links.new(mapping.outputs[0],tex.inputs['Vector'])
    mat['floor'].node_tree.links.new(tex.outputs['Color'],nodes.get('Principled BSDF').inputs['Base Color'])
    materials[mat['floor'].name]['texture']='textures/floor_grain.png'

    def register(o,group,m):
        o.data.materials.clear();o.data.materials.append(m);groups.setdefault(group,[]).append(o);return o
    def box(name,size,loc,m,group,bevel=.0):
        bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name=name;o.dimensions=size
        bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
        if bevel:
            mod=o.modifiers.new('soft_edges','BEVEL');mod.width=bevel;mod.segments=3
            mod=o.modifiers.new('weighted_surface_normals','WEIGHTED_NORMAL')
        return register(o,group,m)
    def cylinder(name,radius,depth,loc,m,group,rotation=(0,0,0),vertices=24):
        bpy.ops.mesh.primitive_cylinder_add(vertices=vertices,radius=radius,depth=depth,location=loc,rotation=rotation)
        o=bpy.context.object;o.name=name;return register(o,group,m)
    def tube(name,points,radius,m,group):
        curve=bpy.data.curves.new(name,'CURVE');curve.dimensions='3D';curve.bevel_depth=radius;curve.bevel_resolution=2
        spline=curve.splines.new('POLY');spline.points.add(len(points)-1)
        for point,co in zip(spline.points,points):point.co=(*co,1)
        o=bpy.data.objects.new(name,curve);scene.collection.objects.link(o);bpy.context.view_layer.objects.active=o;o.select_set(True)
        bpy.ops.object.convert(target='MESH');o=bpy.context.object;return register(o,group,m)
    def label(text,loc,size,rotation,m):
        data=bpy.data.curves.new(text,'FONT');data.body=text;data.size=size;data.extrude=.0004
        o=bpy.data.objects.new(text,data);scene.collection.objects.link(o);o.location=loc;o.rotation_euler=rotation;o.data.materials.append(m)
        return o
    def group_meshes(group,anchor=None,quat=(1,0,0,0),kind='background_visual'):
        # One mesh per material so MuJoCo import does not lose face materials.
        parts={}
        if anchor is None:
            points=[obj.matrix_world@Vector(c) for obj in groups[group] for c in obj.bound_box]
            low=[min(v[k] for v in points) for k in range(3)];high=[max(v[k] for v in points) for k in range(3)]
            anchor=((low[0]+high[0])/2,(low[1]+high[1])/2,low[2])
        inv=(Matrix.Translation(anchor)@Quaternion(quat).to_matrix().to_4x4()).inverted()
        deps=bpy.context.evaluated_depsgraph_get()
        for obj in groups[group]:
            ev=obj.evaluated_get(deps);mesh=ev.to_mesh();mesh.calc_loop_triangles()
            name=obj.data.materials[0].name;v,f=parts.setdefault(name,([],[]));offset=len(v)
            v.extend(tuple(inv@obj.matrix_world@vert.co) for vert in mesh.vertices)
            f.extend(tuple(offset+i for i in face.vertices) for face in mesh.loop_triangles);ev.to_mesh_clear()
        entries=[]
        for index,(name,(verts,faces)) in enumerate(parts.items()):
            path=out/'meshes'/f'{group}_{index}.obj';write_obj(path,verts,faces,name)
            low=[min(v[k] for v in verts) for k in range(3)];high=[max(v[k] for v in verts) for k in range(3)]
            entry=dict(name=f'{group}_{index}',entity=group,kind=kind,mesh=str(path.relative_to(out)).replace('\\','/'),mesh_sha256=sha(path),
                local_dimensions_m=[high[k]-low[k] for k in range(3)],local_bounds_m=[low,high],world_position_m=list(anchor),
                world_quaternion_wxyz=list(quat),rgba=materials[name]['rgba'],material=name,material_properties=materials[name],
                collision_policy='visual_only; scene pipeline owns separate physical geometry')
            entries.append(entry)
        return entries
    def write_obj(path,verts,faces,name=None):
        lines=['# Blender-generated Z-up mesh, units metres; no axis conversion']
        if name:lines+=['mtllib '+path.with_suffix('.mtl').name,'usemtl '+name]
        lines.extend('v %.9g %.9g %.9g'%v for v in verts);lines.extend('f '+' '.join(str(i+1) for i in f) for f in faces)
        path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        if name:
            p=materials[name];r=p['rgba'];path.with_suffix('.mtl').write_text(f'newmtl {name}\nKd {r[0]} {r[1]} {r[2]}\nd {r[3]}\n',encoding='utf-8')
    def normalize_group(group,target):
        pts=[o.matrix_world@Vector(c) for o in groups[group] for c in o.bound_box]
        low=Vector([min(v[k] for v in pts) for k in range(3)]);high=Vector([max(v[k] for v in pts) for k in range(3)])
        center=Vector(((low.x+high.x)/2,(low.y+high.y)/2,low.z));scale=Vector([target[k]/(high[k]-low[k]) for k in range(3)])
        trans=Matrix.Diagonal((*scale,1))@Matrix.Translation(-center)
        for obj in groups[group]:obj.matrix_world=trans@obj.matrix_world

    # Room layout is an approximate arrangement inspired by the six photos.
    box('granular_floor',(7,6,.035),(.8,0,-.0175),mat['floor'],'floor')
    box('back_white_wall',(.10,6,3.05),(-2.75,0,1.525),mat['white'],'back_wall')
    for i in range(77):box('vertical_white_slats',(.018,.071,2.95),(-2.688,-2.96+i*.077,1.475),mat['white'],'wall_slats')
    box('right_white_wall',(7,.08,3.05),(.8,-3.0,1.525),mat['white'],'side_wall')
    box('display_black_frame',(.08,1.68,.96),(-2.64,.64,1.83),mat['black'],'wall_display',.013)
    box('display_off_screen',(.013,1.59,.86),(-2.589,.64,1.83),mat['screen'],'wall_display',.006)
    box('door_oak',(.075,.95,2.35),(-2.64,2.18,1.175),mat['wood'],'wood_door',.008)
    tube('door_handle',[(-2.57,1.83,.93),(-2.57,1.83,1.5)],.012,mat['black'],'wood_door')
    box('exit_sign',(.026,.43,.20),(-2.58,2.18,2.56),mat['exit'],'exit_sign',.005)
    label('EXIT',(-2.559,2.31,2.51),.12,(math.pi/2,0,-math.pi/2),mat['white'])
    for j in range(3):
        y=-2.37+j*.58
        box('oak_upper_cabinet',(.38,.56,.94),(-2.5,y,2.10),mat['wood'],'wood_cabinets',.008)
        box('oak_lower_cabinet',(.48,.56,.80),(-2.45,y,.40),mat['wood'],'wood_cabinets',.007)
        box('cabinet_handle',(.01,.018,.26),(-2.18,y+.20,.48),mat['black'],'wood_cabinets',.004)
    box('glass_partition',(5.7,.02,2.70),(.68,2.96,1.35),mat['glass'],'glass_partition')
    for x in (-2.18,-.76,.67,2.10,3.53):box('glass_frame',(.027,.035,2.75),(x,2.975,1.375),mat['steel'],'glass_frame')
    for ix in range(42):
        for iz in range(13):
            cylinder('frosted_dot',.019,.001,( -2.08+ix*.133,2.943,.25+iz*.16),mat['frost'],'glass_dots',(math.pi/2,0,0),vertices=12)
    for x in (-1.4,.0,1.4,2.8):
        box('acoustic_raft',(1.10,1.8,.045),(x,.1,2.88),mat['white'],'ceiling_rafts',.03)
        cylinder('round_light',.255,.05,(x,-1.30,2.84),mat['light'],'ceiling_lights')
        cylinder('ceiling_air_vent',.20,.018,(x,1.55,2.85),mat['white'],'ceiling_vents')
    for y in (-2.35,2.34):cylinder('exposed_round_pipe',.085,6.5,(.6,y,3.01),mat['white'],'ceiling_pipes',(0,math.pi/2,0))
    for x in (-1.6,.55,2.65):box('ceiling_cross_beam',(.15,5.8,.16),(x,0,3.05),mat['white'],'ceiling_beams')
    for j in range(3):
        y=-1.9+j*.85;group='desk_'+str(j)
        box('gray_workstation_top',(1.1,.80,.04),(-1.69,y,.75),mat['desk'],group,.01)
        for xx in (-2.1,-1.30):box('workstation_leg',(.055,.65,.71),(xx,y,.355),mat['black'],group)
        box('monitor_panel',(.035,.54,.34),(-2.13,y,.99),mat['black'],group,.008)
        box('monitor_stem',(.045,.045,.17),(-2.13,y,.82),mat['steel'],group)
        box('keyboard',(.14,.41,.019),(-1.78,y,.779),mat['black'],group,.004)
    def chair(group,pos,green=False):
        x,y=pos;m=mat['green'] if green else mat['fabric'];frame=mat['white'] if green else mat['black']
        box('seat',(.46,.46,.07),(x,y,.47),m,group,.034)
        box('back',(.065,.46,.46),(x+.19,y,.75),m,group,.027)
        cylinder('chair_column',.035,.34,(x,y,.25),frame,group)
        for i in range(5):
            angle=i*math.tau/5;px=x+math.cos(angle)*.27;py=y+math.sin(angle)*.27
            tube('chair_spoke',[(x,y,.14),(px,py,.07)],.019,frame,group)
            cylinder('caster',.043,.029,(px,py,.048),mat['black'],group,(math.pi/2,0,angle))
        for side in (-1,1):tube('armrest',[(x-.1,y+side*.27,.45),(x-.1,y+side*.27,.64),(x+.13,y+side*.27,.64)],.013,frame,group)
    for i,pos in enumerate([(-.78,-1.95),(-.78,-.9)]):chair('office_chair_'+str(i),pos)
    for i,x in enumerate((.2,1.0,1.8)):chair('green_chair_'+str(i),(x,2.25),True)
    for i,(x,y) in enumerate([(2.15,-2.45),(3.05,-2.45)]):
        group='equipment_case_'+str(i);box('black_flight_case',(.74,.72,.68),(x,y,.36),mat['black'],group,.015)
        for z in (.045,.70):box('silver_case_edge',(.76,.735,.019),(x,y,z),mat['silver'],group)
        for side in (-1,1):box('case_corner',(.028,.025,.65),(x+.36,y+side*.35,.36),mat['silver'],group)
        box('case_latch',(.010,.050,.10),(x+.38,y,.39),mat['silver'],group,.005)

    # Payloads use local XY-centred, bottom-Z-zero frames and separate materials.
    box('pack_body',(.28,.20,.115),(0,0,.059),mat['pack'],'backpack',.026)
    box('pack_front_pocket',(.205,.025,.079),(0,-.096,.044),mat['pack'],'backpack',.016)
    tube('zipper',[(-.102,-.111,.090),(0,-.115,.098),(.102,-.111,.090)],.002,mat['steel'],'backpack')
    for side in (-1,1):tube('pack_strap',[(side*.075,.067,.010),(side*.088,.112,.025),(side*.075,.072,.093)],.006,mat['black'],'backpack')
    tube('handle',[(-.026,.060,.111),(-.022,.073,.132),(.022,.073,.132),(.026,.060,.111)],.004,mat['black'],'backpack')
    normalize_group('backpack',(.28,.20,.12))
    box('laptop_base',(.30,.21,.009),(0,0,.0045),mat['laptop'],'laptop',.003)
    box('laptop_closed_lid',(.299,.208,.008),(0,0,.014),mat['laptop'],'laptop',.003)
    box('hinge_line',(.277,.003,.003),(0,.099,.010),mat['black'],'laptop',.001)
    cylinder('lid_round_mark',.012,.0003,(0,0,.0181),mat['black'],'laptop',vertices=32)
    normalize_group('laptop',(.30,.21,.018))
    nx,ny=9,7;verts=[];faces=[]
    for j in range(ny):
        y=-.11+j*.22/(ny-1);width=.135 if y>=.026 else .094
        for i in range(nx):
            x=-width+2*width*i/(nx-1);yy=y
            if j==ny-1:yy-=.022*math.exp(-(x/.033)**2)
            z=.012+.009*math.sin(x*33)*math.cos(y*24)+.004*math.sin(y*42)
            verts.append((x,yy,z))
    for j in range(ny-1):
        for i in range(nx-1):
            k=j*nx+i;faces.extend(((k,k+1,k+nx+1),(k,k+nx+1,k+nx)))
    minz=min(v[2] for v in verts);verts=[(x,y,z-minz) for x,y,z in verts]
    write_obj(out/'meshes/coat_physics.obj',verts,faces)
    mesh=bpy.data.meshes.new('coat_rest_surface');mesh.from_pydata(verts,[],faces);mesh.update()
    o=bpy.data.objects.new('coat_visual_reference',mesh);scene.collection.objects.link(o);register(o,'coat',mat['coat'])
    solid=o.modifiers.new('visual_thickness_only','SOLIDIFY');solid.thickness=.002
    sub=o.modifiers.new('visual_smooth_folds','SUBSURF');sub.levels=2

    room=[]
    payload_groups={'backpack','laptop','coat'}
    for group in groups:
        if group not in payload_groups:room.extend(group_meshes(group))
    payloads={name:dict(parts=group_meshes(name,anchor=(0,0,0),kind='payload_visual'),origin='XY bounding centre, bottom Z zero',
        physics_implementation='scene pipeline owns dynamic body/flex, not this Blender preview') for name in payload_groups}
    payloads['coat'].update(physics_mesh='meshes/coat_physics.obj',physics_mesh_sha256=sha(out/'meshes/coat_physics.obj'),
        physics_vertices=len(verts),physics_triangles=len(faces),physics_mesh_closed=False,
        required_physics='MuJoCo dynamic flex surface; high-poly fixed visual reference is not a soft body',
        tunable_physics=dict(mass_kg=None,contact_friction=None,stretch_stiffness=None,bending_stiffness=None))
    # Arrange payload previews only after export, so their file coordinates remain local.
    for name,loc in [('backpack',(.82,-.12,.815)),('laptop',(.90,.13,.815)),('coat',(.83,-.12,.935))]:
        for obj in groups[name]:obj.location+=Vector(loc)

    def import_obj(path,name,matrix,material_override=None):
        path=Path(path);sources[str(path.relative_to(project)).replace('\\','/')]=sha(path)
        vv=[];ff=[]
        for line in path.read_text(errors='replace').splitlines():
            words=line.split()
            if words and words[0]=='v':vv.append(tuple(map(float,words[1:4])))
            elif words and words[0]=='f':
                indices=[int(w.split('/')[0])-1 for w in words[1:]]
                ff.extend((indices[0],indices[i],indices[i+1]) for i in range(1,len(indices)-1))
        mesh=bpy.data.meshes.new(name);mesh.from_pydata(vv,[],ff);mesh.update();ob=bpy.data.objects.new(name,mesh);scene.collection.objects.link(ob)
        ob.matrix_world=matrix
        if material_override is None:
            color=(.44,.44,.43,1);mtl=path.with_suffix('.mtl')
            if mtl.exists():
                sources[str(mtl.relative_to(project)).replace('\\','/')]=sha(mtl)
                for line in mtl.read_text(errors='replace').splitlines():
                    if line.startswith('Kd '):color=(*map(float,line.split()[1:4]),1);break
            material_override=material(name+'_source_material',color)
        ob.data.materials.append(material_override);return ob
    table=project/'outputs/r1pro_tray_scene/assets/table';table_matrix=Matrix.Translation((.85,0,0))@Matrix.Rotation(math.pi/2,4,'Z')
    for path in sorted(table.glob('table_*.obj')):import_obj(path,'unchanged_work_table_'+path.stem,table_matrix)
    tray=project/'outputs/r1pro_tray_scene/assets/tray';tray_matrix=Matrix.Translation((.85,0,.80))@Matrix.Rotation(math.pi/2,4,'Z')
    for path in sorted(tray.glob('tray_*.obj')):import_obj(path,'unchanged_tray_visual_'+path.stem,tray_matrix)
    robot_xml=project/'outputs/r1pro_tray_scene/robot.xml';sources[str(robot_xml.relative_to(project)).replace('\\','/')]=sha(robot_xml)
    robot_root=ET.fromstring(robot_xml.read_text());assets={m.attrib['name']:project/'outputs/r1pro_tray_scene'/m.attrib['file'] for m in robot_root.findall('./asset/mesh')}
    robot_objects=[]
    def transform(element):
        pos=list(map(float,element.attrib.get('pos','0 0 0').split()));quat=list(map(float,element.attrib.get('quat','1 0 0 0').split()))
        return Matrix.Translation(pos)@Quaternion(quat).to_matrix().to_4x4()
    def body(element,parent):
        world=parent@transform(element)
        for g in element.findall('geom'):
            if g.attrib.get('contype')!='0' or g.attrib.get('type')!='mesh':continue
            name=g.attrib['mesh'];silver=(name in ('torso_link2','torso_link4') or any(name.endswith('arm_link'+str(i)) for i in (1,3,5,7)))
            robot_objects.append(import_obj(assets[name],'robot_visual_copy_'+name,world@transform(g),mat['silver'] if silver else mat['black']))
        for child in element.findall('body'):body(child,world)
    for child in robot_root.findall('./worldbody/body'):body(child,Matrix.Identity(4))
    if robot_objects:
        minz=min((o.matrix_world@Vector(c)).z for o in robot_objects for c in o.bound_box)
        for ob in robot_objects:ob.location.z-=minz
    robot_palette=dict(schema='single_tray_robot_visual_palette/1',source_robot_xml='outputs/r1pro_tray_scene/robot.xml',
        silver_rgba=materials[mat['silver'].name]['rgba'],black_rgba=materials[mat['black'].name]['rgba'],
        silver_meshes=['torso_link2','torso_link4']+[side+'_arm_link'+str(i) for side in ('left','right') for i in (1,3,5,7)],
        black_meshes_policy='remaining visual links, joints, head housing, base and fingers',
        application_scope='contype=0/conaffinity=0 visual geoms only; no collision mesh, mass, inertia, joint, camera or kinematic changes')
    (out/'robot_appearance.json').write_text(json.dumps(robot_palette,indent=2))
    world=bpy.data.worlds.new('lab_ambient');world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(.52,.56,.60,1)
    world.node_tree.nodes['Background'].inputs[1].default_value=.55;scene.world=world
    def light(name,loc,energy,size):
        data=bpy.data.lights.new(name,'AREA');data.energy=energy;data.shape='DISK';data.size=size
        o=bpy.data.objects.new(name,data);scene.collection.objects.link(o);o.location=loc
    for x in (-1.4,.7,2.8):light('ceiling_softbox',(x,-.7,2.76),260,1.7)
    light('glass_side_fill',(.1,1.8,2.4),110,1.2)
    cam_data=bpy.data.cameras.new('preview_camera');cam=bpy.data.objects.new('preview_camera',cam_data);scene.collection.objects.link(cam)
    cam.location=(3.70,-2.55,2.55);cam.rotation_euler=(Vector((.3,0,1.05))-cam.location).to_track_quat('-Z','Y').to_euler();cam_data.lens=27;scene.camera=cam
    scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=24;scene.cycles.use_denoising=True
    scene.render.resolution_x=a.render_width;scene.render.resolution_y=int(a.render_width*.75);scene.render.resolution_percentage=100
    scene.view_settings.view_transform='AgX'
    references=[dict(path=str(p.relative_to(out)).replace('\\','/'),sha256=sha(p)) for p in sorted((out/'reference_photos').glob('*.jpg'))]
    manifest=dict(schema='single_tray_lab_visual_assets/1',creator='program_generated_in_Blender',blender_version=bpy.app.version_string,
        units='metres',axes=dict(x='robot_forward',y='robot_left',z='up'),quaternion_order='wxyz',
        fidelity='Photo-inspired approximate arrangement; no measured room survey or exact reconstruction claim',
        room_dimensions_assumed_m=[7,6,3.05],room_objects=room,payloads=payloads,materials=materials,reference_photos=references,
        mesh_origin_policy='Room entity local XY footprint centre, minimum local Z zero; all material parts share entity anchor/world pose',
        operation_table=dict(source='outputs/r1pro_tray_scene/assets/table/table_*.obj',unchanged=True,
            included_in_room_objects=False,preview_world_position_m=[.85,0,0],preview_yaw_rad=math.pi/2,
            physical_table_contract='Root clones original table body, collision/friction/inertia. These previews never replace it.'),
        source_resources_sha256=sources,robot_appearance='robot_appearance.json',
        preview_scope='Editable visual mockup, no physics or trajectory success claim; source robot/table copied for display only',
        cloth_scope='coat_physics.obj is an open rest surface only. Root must instantiate real dynamic flex; coat high-poly mesh is not soft-body physics.')
    assert all(sha(project/path)==digest for path,digest in sources.items())
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False),encoding='utf-8')
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'single_tray_lab.blend'))
    if a.render:
        scene.render.filepath=str(out/'previews/lab_overview.png');bpy.ops.render.render(write_still=True)
    print(json.dumps(dict(status='assets_created',output=str(out),room_mesh_parts=len(room),payload_mesh_parts={k:len(v['parts']) for k,v in payloads.items()},
        coat_physics_vertices=len(verts),coat_physics_triangles=len(faces),original_source_hashes_unchanged=True)))

if __name__=='__main__':main()
