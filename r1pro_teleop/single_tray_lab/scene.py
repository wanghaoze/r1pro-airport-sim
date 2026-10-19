"""New scenes with the original table/contact assets and passive passenger items."""
from dataclasses import asdict, dataclass
from pathlib import Path
import copy, hashlib, json, math
import xml.etree.ElementTree as ET
import numpy as np
from .camera_visuals import remove_wrist_camera_housing_visuals

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT/'resources/single_tray_lab_v1'
TEMPLATE = ROOT/'outputs/r1pro_tray_scene/scene_direct_grasp_720p.xml'
CAMERAS = ('head_left','head_right','left_wrist','right_wrist')

def passenger_heights(kinds,*,cloth=True):
    """Passenger-finished stack with small physical release gaps, in metres."""
    laptop_layer=.018 if 'laptop' in kinds else 0.
    return dict(laptop=.012+.009+.002,
        backpack=.012+laptop_layer+.060+.003,
        coat=.012+.006+(0. if cloth else .025))

def passenger_offsets(kinds):
    """Coat beside a backpack/laptop stack, all inside the original tray."""
    separate='coat' in kinds and any(kind in kinds for kind in ('backpack','laptop'))
    return {kind:np.array([0.,(.13 if kind=='coat' else -.13) if separate else 0.,0.]) for kind in kinds}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def fmt(values):
    return ' '.join(format(float(v), '.12g') for v in values)

@dataclass(frozen=True)
class LabSceneConfig:
    seed: int = 20261005
    split: str = 'train'
    robot_x: float = .10
    robot_y: float = 0.
    tray_y: float = -.24
    tray_x: float = .85
    table_top: float = .8
    left_edge_margin: float = .025
    lift_clearance: float = .18
    gripper_kp: float = 2000.
    arm_kp: float = 250.
    noslip_iterations: int = 0
    friction_impratio: float = 10.
    payloads: tuple = ('laptop','backpack','coat')
    cloth_enabled: bool = True
    allow_front_lateral: bool = False

    def validate(self):
        if self.split not in ('train','val','test'):raise ValueError('single_tray_unknown_split')
        if self.table_top != .8:raise ValueError('original_table_height_must_be_preserved')
        if not set(self.payloads)<= {'laptop','backpack','coat'} or len(set(self.payloads))!=len(self.payloads):
            raise ValueError('unknown_or_duplicate_passenger_item')
        if not np.isfinite([self.robot_x,self.robot_y,self.tray_y,self.tray_x,self.left_edge_margin,self.lift_clearance,self.gripper_kp,self.arm_kp]).all():
            raise ValueError('single_tray_nonfinite_geometry')
        if self.gripper_kp<=0 or self.lift_clearance<=0:raise ValueError('positive_motor_gain_and_lift_required')
        if not 0<self.arm_kp<=2000:raise ValueError('arm_gain_must_be_positive_and_at_most_2000')
        if type(self.noslip_iterations) is not int or not 0<=self.noslip_iterations<=3:
            raise ValueError('explicit_noslip_iterations_must_be_integer_0_to_3')
        if self.noslip_iterations and self.cloth_enabled and 'coat' in self.payloads:
            raise ValueError('mujoco_discrete_flex_does_not_support_noslip')
        if not np.isfinite(self.friction_impratio) or not 1<=self.friction_impratio<=1000:
            raise ValueError('explicit_friction_impratio_must_be_1_to_1000')
        if not 0 < self.left_edge_margin < .15:raise ValueError('single_tray_edge_margin_invalid')
        if not -.3 <= self.tray_y <= .3:raise ValueError('single_tray_initial_outside_original_table')
        if self.allow_front_lateral:raise ValueError('front_lateral_motion_not_implemented_in_fixed_base_profile')

def _material(asset,name,color,**attributes):
    ET.SubElement(asset,'material',name=name,rgba=fmt(color),**attributes)

def _camera_xml(root):
    from scripts.upgrade_airport_fourcam import camera_profile
    from scipy.spatial.transform import Rotation
    audit=ROOT/'resources/calibration/camera_audit.json'
    profile=camera_profile(json.loads(audit.read_text()))
    for name,stream in profile['streams'].items():
        for parent in root.iter():
            for child in list(parent):
                if child.tag=='camera' and child.get('name')==name:parent.remove(child)
        mount=next(body for body in root.iter('body') if body.get('name')==stream['parent'])
        rotation=Rotation.from_quat(stream['quaternion_xyzw']).as_matrix() @ np.diag([1.,-1.,-1.])
        quaternion=Rotation.from_matrix(rotation).as_quat()[[3,0,1,2]]
        k=stream['K'];w=stream['width'];h=stream['height']
        ET.SubElement(mount,'camera',name=name,pos=fmt(stream['position_m']),quat=fmt(quaternion),
            resolution=f'{w} {h}',sensorsize=f'{w} {h}',focalpixel=fmt([k[0],k[4]]),
            principalpixel=fmt([w/2-k[2],h/2-k[5]]))
    return profile

def generate_scene(output, config=None, *, loaded=False, require_blender=False):
    config=config or LabSceneConfig();config.validate();output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    tree=ET.parse(TEMPLATE);root=tree.getroot();root.set('model','R1Pro_single_tray_photo_lab_v1')
    root.find('option').set('noslip_iterations',str(config.noslip_iterations))
    root.find('option').set('impratio',fmt([config.friction_impratio]))
    # Gain tuning preserves original 40 N motor / 100 N joint caps, damping
    # and all contact geometry. It does not change friction or object inertia.
    for side in ('left','right'):
        motor=root.find(f"actuator/position[@name='{side}_gripper_target']")
        motor.set('kp',fmt([config.gripper_kp]))
        for joint in range(1,8):
            arm=root.find(f"actuator/position[@name='{side}_arm_joint{joint}_target']")
            arm.set('kp',fmt([config.arm_kp]))
    if config.cloth_enabled and 'coat' in config.payloads:
        # MuJoCo 3.13 requires its discrete integrator for implicit flex elasticity.
        root.find('option').set('integrator','discrete')
        root.find('option').set('iterations','200')
    asset=root.find('asset');world=root.find('worldbody');source_files={str(TEMPLATE.relative_to(ROOT)):sha(TEMPLATE)}
    for node in root.iter():
        if node.get('file'):
            path=(TEMPLATE.parent/node.get('file')).resolve()
            node.set('file',str(path).replace('\\','/'))
            if path.is_relative_to(ROOT):source_files[str(path.relative_to(ROOT))]=sha(path)
    # Geometry, collision, inertia and friction of the user's existing table stay exact.
    table=next(b for b in world.findall('body') if b.get('name')=='table')
    table_xml=ET.tostring(table)
    robot=next(b for b in world.findall('body') if b.get('name')=='base_link')
    robot.set('pos',fmt([config.robot_x,config.robot_y,0]))
    _material(asset,'robot_silver',[.69,.68,.64,1],specular='.65',shininess='.65',reflectance='.12')
    _material(asset,'robot_black',[.045,.049,.05,1],specular='.22',shininess='.25')
    black_tokens=('base_link','wheel','steer','torso_link1','torso_link3','torso_link4','zed_link','gripper','realsense')
    for body in robot.iter('body'):
        for geom in body.findall('geom'):
            if geom.get('group')=='1' and geom.get('contype')=='0':
                geom.attrib.pop('rgba',None)
                geom.set('material','robot_black' if any(t in body.get('name','') for t in black_tokens) else 'robot_silver')
    tray=next(b for b in world.findall('body') if b.get('name')=='tray')
    tray.set('pos',fmt([config.tray_x,config.tray_y,.801]));tray.set('quat',fmt([math.sqrt(.5),0,0,math.sqrt(.5)]))
    for name,y in (('long_rim_left',.14),('long_rim_right',-.14)):
        # In tray local coordinates X is the long axis, +Y is the robot-facing edge.
        ET.SubElement(tray,'site',name=name,pos=fmt([y,.215,.096]),size='.003',group='4',rgba='0 0 0 0')
    key=root.find('keyframe')
    if key is not None:root.remove(key)  # Additional passenger/flex DOFs require fresh initial state.
    target=world.find("site[@name='place_target']")
    if target is not None:world.remove(target)
    profile=_camera_xml(root)
    profile['visual_geometry_revision']=remove_wrist_camera_housing_visuals(root)
    root.find('visual/global').set('offwidth','1920');root.find('visual/global').set('offheight','1536')
    floor=world.find("geom[@name='floor']")
    ET.SubElement(asset,'texture',name='lab_floor_grain',type='2d',builtin='checker',width='128',height='128',
                  rgb1='.73 .74 .73',rgb2='.75 .75 .74')
    _material(asset,'lab_floor',[.82,.82,.80,1],texture='lab_floor_grain',texrepeat='90 90',specular='.06')
    if floor is not None:floor.attrib.pop('rgba',None);floor.set('material','lab_floor')
    for light in list(world.findall('light')):world.remove(light)
    for i,(x,y) in enumerate(((-1.2,-1.5),(1.8,-1.5),(-1.2,1.5),(1.8,1.5))):
        ET.SubElement(world,'light',name=f'lab_ceiling_{i}',pos=fmt([x,y,3.0]),dir='0 0 -1',
                      diffuse='.25 .25 .24',ambient='.04 .04 .04',castshadow='true' if i==0 else 'false')
    mesh_manifest=ASSETS/'manifest.json'
    if require_blender and not mesh_manifest.exists():raise ValueError('single_tray_blender_assets_missing')
    mesh_assets=json.loads(mesh_manifest.read_text()) if mesh_manifest.exists() else {}
    for body_name,parts in mesh_assets.get('robot_visual_overrides',{}).items():
        body=next(b for b in robot.iter('body') if b.get('name')==body_name)
        for geom in list(body.findall('geom')):
            if geom.get('contype')=='0' and geom.get('group')=='1':body.remove(geom)
        for index,part in enumerate(parts):
            name=f'lab_robot_{body_name}_{index}'
            ET.SubElement(asset,'mesh',name=name,file=str((ASSETS/part['mesh']).resolve()).replace('\\','/'))
            ET.SubElement(body,'geom',name=name,type='mesh',mesh=name,contype='0',conaffinity='0',mass='0',group='1',material=part['material'])
    for i,item in enumerate(mesh_assets.get('room_objects',[])):
        if item.get('role')=='work_table':continue
        mesh_path=(ASSETS/item['mesh']).resolve();name=f'lab_room_{i:03d}'
        ET.SubElement(asset,'mesh',name=name,file=str(mesh_path).replace('\\','/'))
        body=ET.SubElement(world,'body',name=name,pos=fmt(item.get('world_position_m',item.get('position',[0,0,0]))),quat=fmt(item.get('world_quaternion_wxyz',[1,0,0,0])))
        ET.SubElement(body,'geom',type='mesh',mesh=name,contype='0',conaffinity='0',mass='0',group='1',
                      rgba=fmt(item.get('rgba',[.6,.6,.6,1])))
    payload_manifest=[];park=np.array([-2.5,2.4,.3]);rng=np.random.default_rng(config.seed)
    heights=passenger_heights(config.payloads,cloth=config.cloth_enabled)
    offsets=passenger_offsets(config.payloads)
    mesh_map=mesh_assets.get('payloads',{})
    for i,kind in enumerate(config.payloads):
        name='passenger_'+kind
        if kind=='coat' and config.cloth_enabled:
            coat_pos=(np.array([config.tray_x,config.tray_y,.801+heights[kind]])+offsets[kind] if loaded else park+[0,.55,0])
            flex=ET.SubElement(world,'flexcomp',name=name,type='grid',count='9 7 1',spacing='.03 .03 .03',
                pos=fmt(coat_pos),radius='.0025',mass='.25',dim='2',rgba='.12 .19 .24 '+('1' if loaded else '0'))
            coat_mesh=ASSETS/'meshes/coat_physics.obj'
            if coat_mesh.exists():
                for attr in ('count','spacing'):flex.attrib.pop(attr,None)
                flex.set('type','mesh');flex.set('file',str(coat_mesh.resolve()).replace('\\','/'))
            ET.SubElement(flex,'contact',selfcollide='auto',friction='.7 .005 .0001',solref='.012 1')
            ET.SubElement(flex,'elasticity',young='20000',poisson='.2',thickness='.001',elastic2d='both',damping='.01')
            payload_manifest.append(dict(kind=kind,name=name,flex=True,mass_kg=.25,parked_position=list(coat_pos),
                representation='dynamic_2d_flex_foldable_sheet_approximation',photo_dimensions_measured=False))
            continue
        sizes={'laptop':(.15,.105,.009),'backpack':(.14,.10,.06),'coat':(.135,.11,.025)}
        masses={'laptop':1.15,'backpack':.65,'coat':.25};half=np.array(sizes[kind])
        pos=(np.array([config.tray_x,config.tray_y,.801+heights[kind]])+offsets[kind] if loaded else park+[0,i*.35,0])
        body=ET.SubElement(world,'body',name=name,pos=fmt(pos))
        ET.SubElement(body,'freejoint',name=name+'_free')
        visual_parts=mesh_map.get(kind,{}).get('parts',[])
        color={'laptop':[.085,.09,.1,1],'backpack':[.10,.13,.16,1],'coat':[.12,.19,.24,1]}[kind]
        for index,part in enumerate(visual_parts):
            mesh_name=name+f'_mesh_{index}'
            ET.SubElement(asset,'mesh',name=mesh_name,file=str((ASSETS/part['mesh']).resolve()).replace('\\','/'))
            part_color=part.get('rgba',color)
            ET.SubElement(body,'geom',name=name+f'_visual_{index}',type='mesh',mesh=mesh_name,contype='0',conaffinity='0',mass='0',group='1',pos=fmt([0,0,-half[2]]),rgba=fmt(part_color[:3]+[1 if loaded else 0]))
        ET.SubElement(body,'geom',name=name+'_collision',type='box',size=fmt(half),mass=str(masses[kind]),
                      friction='.7 .005 .0001',condim='4',group='3' if visual_parts else '1',rgba=fmt(color[:3]+[1 if loaded else 0]))
        payload_manifest.append(dict(kind=kind,name=name,joint=name+'_free',flex=False,mass_kg=masses[kind],
                                     half_size=half.tolist(),parked_position=list(pos),representation='passive_rigid_compound_proxy'))
    if ET.tostring(table)!=table_xml:raise ValueError('original_table_changed_during_lab_generation')
    xml=output/'scene.xml';ET.indent(root);tree.write(xml,encoding='unicode')
    manifest=dict(schema='airport_single_tray_scene/1',scene_id=f'single_tray_{config.seed}',source='simulation/program_generated',
        scene_generator_sha256=sha(Path(__file__)),
        passenger_layout=dict(heights_above_tray_origin_m=heights,
            offsets_world_m={kind:value.tolist() for kind,value in offsets.items()},
            source='simulation/program_generated',training_eligible=False),
        split=config.split,config=asdict(config),xml=str(xml),xml_sha256=sha(xml),template=str(TEMPLATE.relative_to(ROOT)),
        original_table_sha256=hashlib.sha256(table_xml).hexdigest(),original_assets_sha256=source_files,
        table=dict(body='table',position=[.85,0,0],yaw=math.pi/2,size=[1.2,.6,.8],top_z=.8,long_axis_world=[0,1,0]),
        tray=dict(body='tray',joint='tray_free',size=[.56,.43,.105],yaw=math.pi/2,position=[config.tray_x,config.tray_y,.801],
                  front_rim_local_y=.215,rim_grasp_z=.096,goal_position=[config.tray_x,.6-.28-config.left_edge_margin,.801],
                  goal_position_semantics='nominal_unrotated_centre_reference',
                  goal_completion='actual_leftmost_corner_and_table_support',goal_edge_world_coordinate_m=.6-config.left_edge_margin),
        frame=dict(robot_forward=[1,0,0],robot_left=[0,1,0],base_mode='fixed_front',side_access_allowed=False),
        camera=profile,payloads=payload_manifest,payload_loaded_initially=loaded,
        training_actions=['pick_empty','place_empty','push_loaded'],environment_only_actions=['passenger_load','passenger_settle'],
        environment_reconstruction='photo_reference_approximate_layout_unmeasured',blender_assets_present=mesh_manifest.exists(),
        blender_manifest_sha256=sha(mesh_manifest) if mesh_manifest.exists() else None,
        reference_photos={p.name:sha(p) for p in sorted((ASSETS/'reference_photos').glob('*.jpg'))},
        physics_options=dict(root.find('option').attrib),softbody_integrator_change_explicit=config.cloth_enabled and 'coat' in config.payloads,
        numerical_friction_solver_change_explicit=config.noslip_iterations>0 or config.friction_impratio!=10.)
    (output/'scene.json').write_text(json.dumps(manifest,indent=2))
    return manifest

def passenger_load(sim, scene):
    """Explicit environmental state transition; never changes robot/tray/time/control."""
    import mujoco
    model,data=sim.model,sim.data;before=data.qpos.copy();velocity=data.qvel.copy();ctrl=data.ctrl.copy();stamp=data.time
    tray=data.body('tray').xpos.copy();allowed_q=[];allowed_v=[];events=[]
    heights=passenger_heights(tuple(item['kind'] for item in scene['payloads']),
        cloth=any(item['kind']=='coat' and item['flex'] for item in scene['payloads']))
    offsets=passenger_offsets(tuple(item['kind'] for item in scene['payloads']))
    for item in scene['payloads']:
        kind=mujoco.mjtObj.mjOBJ_FLEX if item['flex'] else mujoco.mjtObj.mjOBJ_JOINT
        name=item['name'] if item['flex'] else item['joint']
        if mujoco.mj_name2id(model,kind,name)<0:raise ValueError('passenger_model_identity_missing:'+name)
    for i,item in enumerate(scene['payloads']):
        if item['flex']:
            fid=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_FLEX,item['name']);adr=model.flex_vertadr[fid];count=model.flex_vertnum[fid]
            body_ids=np.unique(model.flex_vertbodyid[adr:adr+count]);center=np.asarray(item['parked_position'])
            # Near-resting passenger stack; initial garment/backpack overlap
            # and large artificial drop impacts are not part of this task.
            goal=tray+offsets[item['kind']]+np.array([0,0,heights[item['kind']]]);shift=goal-center
            for body_id in body_ids:
                for jid in range(model.body_jntadr[body_id],model.body_jntadr[body_id]+model.body_jntnum[body_id]):
                    qadr=int(model.jnt_qposadr[jid]);vadr=int(model.jnt_dofadr[jid])
                    allowed_q.append(qadr);allowed_v.append(vadr)
                    data.qpos[qadr]=float(model.jnt_axis[jid]@shift);data.qvel[vadr]=0
            events.append(dict(kind='flex_rgba',index=int(fid),before=model.flex_rgba[fid].copy().tolist(),after=model.flex_rgba[fid][:3].tolist()+[1.]))
            model.flex_rgba[fid,3]=1.
        else:
            joint=model.joint(item['joint']);qadr=int(model.jnt_qposadr[joint.id]);vadr=int(model.jnt_dofadr[joint.id])
            z=heights[item['kind']]
            data.qpos[qadr:qadr+7]=np.r_[tray+offsets[item['kind']]+[0,0,z],1,0,0,0];data.qvel[vadr:vadr+6]=0
            allowed_q.extend(range(qadr,qadr+7));allowed_v.extend(range(vadr,vadr+6))
            body_id=model.body(item['name']).id
            for geom in range(model.body_geomadr[body_id],model.body_geomadr[body_id]+model.body_geomnum[body_id]):
                events.append(dict(kind='geom_rgba',index=int(geom),before=model.geom_rgba[geom].copy().tolist(),after=model.geom_rgba[geom][:3].tolist()+[1.]))
                model.geom_rgba[geom,3]=1.
    qmask=np.ones(model.nq,dtype=bool);qmask[allowed_q]=False;vmask=np.ones(model.nv,dtype=bool);vmask[allowed_v]=False
    if not np.array_equal(before[qmask],data.qpos[qmask]) or not np.array_equal(velocity[vmask],data.qvel[vmask]) or not np.array_equal(ctrl,data.ctrl) or stamp!=data.time:
        raise ValueError('passenger_load_changed_robot_tray_or_control')
    mujoco.mj_forward(model,data)
    return dict(schema='airport_passenger_environment_transition/1',action='passenger_load',time=float(stamp),
        qpos_indices=allowed_q,qpos_before=before[allowed_q].tolist(),qpos_after=data.qpos[allowed_q].tolist(),
        qvel_indices=allowed_v,qvel_before=velocity[allowed_v].tolist(),qvel_after=data.qvel[allowed_v].tolist(),
        model_visual_changes=events,physics_mass_inertia_contact_unchanged=True,robot_tray_time_control_unchanged=True,
        payload_mass_kg=sum(item['mass_kg'] for item in scene['payloads']),training_eligible=False)
