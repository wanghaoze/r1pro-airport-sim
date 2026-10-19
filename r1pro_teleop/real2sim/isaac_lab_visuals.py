"""Project-owned Blender laboratory -> visual-only USD session overrides.

No collision, camera calibration, joint, inertia or actuator edits are allowed.
"""
from pathlib import Path
import hashlib
import json
import numpy as np


def obj_mesh(path):
    vertices=[];counts=[];indices=[]
    for line in Path(path).read_text().splitlines():
        w=line.split()
        if w and w[0]=='v':vertices.append(list(map(float,w[1:4])))
        elif w and w[0]=='f':
            face=[int(x.split('/')[0]) for x in w[1:]]
            indices.extend(i-1 if i>0 else len(vertices)+i for i in face);counts.append(len(face))
    return np.asarray(vertices,float),counts,indices


def physics_fingerprint(stage):
    from pxr import Usd,UsdPhysics,UsdGeom
    rows=[]
    for p in Usd.PrimRange.Stage(stage,Usd.TraverseInstanceProxies()):
        physical=any(p.HasAPI(a) for a in (UsdPhysics.CollisionAPI,UsdPhysics.RigidBodyAPI,UsdPhysics.MassAPI,UsdPhysics.ArticulationRootAPI)) or p.IsA(UsdPhysics.Joint)
        camera=p.IsA(UsdGeom.Camera) and p.GetName()!='FastPresentationCamera'
        if not physical and not camera:continue
        attrs={}
        for a in p.GetAttributes():
            n=a.GetName()
            if n.startswith(('physics:','physx','xformOp:')) or camera or (p.HasAPI(UsdPhysics.CollisionAPI) and n in ('points','faceVertexIndices','faceVertexCounts')):
                v=a.Get()
                try:value=hashlib.sha256(np.asarray(v).tobytes()).hexdigest() if n in ('points','faceVertexIndices','faceVertexCounts') else str(v)
                except (TypeError,ValueError):value=str(v)
                attrs[n]=value
        rows.append((str(p.GetPath()),attrs))
    return hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()


def apply_lab_visuals(stage,assets,model):
    from pxr import Usd,UsdGeom,UsdShade,UsdPhysics,UsdLux,Gf,Sdf,Vt
    assets=Path(assets);manifest=json.loads((assets/'manifest.json').read_text());palette=json.loads((assets/'robot_appearance.json').read_text())
    before=physics_fingerprint(stage);root='/FastLabVisuals';UsdGeom.Xform.Define(stage,root)
    materials={}
    def material(name,rgba,properties=None):
        if name in materials:return materials[name]
        properties=properties or {};m=UsdShade.Material.Define(stage,root+'/Materials/'+name);s=UsdShade.Shader.Define(stage,str(m.GetPath())+'/Surface');s.CreateIdAttr('UsdPreviewSurface')
        s.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgba[:3]));s.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(float(properties.get('roughness',.55)));s.CreateInput('metallic',Sdf.ValueTypeNames.Float).Set(float(properties.get('metallic',0.)));s.CreateInput('opacity',Sdf.ValueTypeNames.Float).Set(float(rgba[3]))
        if properties.get('emission_strength'):s.CreateInput('emissiveColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*[c*properties['emission_strength'] for c in rgba[:3]]))
        m.CreateSurfaceOutput().ConnectToSource(s.ConnectableAPI(),'surface');materials[name]=m;return m
    def mesh(path,vertices,counts,indices,mat):
        m=UsdGeom.Mesh.Define(stage,path);m.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(np.asarray(vertices,np.float32)));m.CreateFaceVertexCountsAttr(counts);m.CreateFaceVertexIndicesAttr(indices);m.CreateSubdivisionSchemeAttr('none');UsdShade.MaterialBindingAPI.Apply(m.GetPrim()).Bind(mat)
        return m
    room=[]
    for row in manifest['room_objects']:
        if row['kind']!='background_visual':continue
        path=assets/row['mesh']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['mesh_sha256']:raise ValueError('lab_mesh_identity_changed:'+str(path))
        vertices,counts,indices=obj_mesh(path);m=mesh(root+'/Room/'+row['name'],vertices,counts,indices,material(row['material'],row['rgba'],row.get('material_properties')))
        x=UsdGeom.Xformable(m);x.AddTranslateOp().Set(Gf.Vec3d(*row['world_position_m']));q=row['world_quaternion_wxyz'];x.AddOrientOp().Set(Gf.Quatf(q[0],Gf.Vec3f(*q[1:])))
        if row['entity']=='floor':
            uv=UsdGeom.PrimvarsAPI(m).CreatePrimvar('st',Sdf.ValueTypeNames.TexCoord2fArray,UsdGeom.Tokens.vertex)
            uv.Set(Vt.Vec2fArray.FromNumpy(np.asarray(vertices[:,:2]*4,np.float32)))
            mat=materials[row['material']];tex=UsdShade.Shader.Define(stage,str(mat.GetPath())+'/Grain');tex.CreateIdAttr('UsdUVTexture');tex.CreateInput('file',Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(assets/'textures/floor_grain.png')));tex.CreateInput('wrapS',Sdf.ValueTypeNames.Token).Set('repeat');tex.CreateInput('wrapT',Sdf.ValueTypeNames.Token).Set('repeat')
            reader=UsdShade.Shader.Define(stage,str(mat.GetPath())+'/UV');reader.CreateIdAttr('UsdPrimvarReader_float2');reader.CreateInput('varname',Sdf.ValueTypeNames.Token).Set('st');tex.CreateInput('st',Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(),'result');UsdShade.Shader(stage.GetPrimAtPath(str(mat.GetPath())+'/Surface')).GetInput('diffuseColor').ConnectToSource(tex.ConnectableAPI(),'rgb')
        room.append(row['name'])
    visual=[];partitions=[]
    candidates=[p for p in Usd.PrimRange.Stage(stage,Usd.TraverseInstanceProxies()) if p.IsA(UsdGeom.Mesh) and not p.HasAPI(UsdPhysics.CollisionAPI) and p.GetName().startswith('robot_geom_')]
    for old in candidates:
        wrapper=old.GetParent();body=wrapper.GetParent();name=body.GetName();path=str(old.GetPath());wrapper.SetInstanceable(False);p=stage.GetPrimAtPath(path)
        if name in palette.get('robot_visual_overrides',{}):
            geom=model.geom(wrapper.GetName());mid=int(model.geom_dataid[geom.id]);q=model.mesh_quat[mid];from scipy.spatial.transform import Rotation
            rotation=Rotation.from_quat(np.r_[q[1:],q[0]]).as_matrix();parts=[]
            for row in palette['robot_visual_overrides'][name]:
                vertices,counts,indices=obj_mesh(assets/row['mesh']);scale=model.mesh_scale[mid] if hasattr(model,'mesh_scale') else 1.;parts.append((row,vertices*scale,counts,indices))
            original=np.asarray(UsdGeom.Mesh(p).GetPointsAttr().Get());combined=np.concatenate([x[1] for x in parts])
            if not np.allclose([original.min(0),original.max(0)],[combined.min(0),combined.max(0)],atol=2e-5):
                parts=[(row,(vertices-model.mesh_pos[mid])@rotation,counts,indices) for row,vertices,counts,indices in parts]
                combined=np.concatenate([x[1] for x in parts])
            if not np.allclose([original.min(0),original.max(0)],[combined.min(0),combined.max(0)],atol=2e-5):raise ValueError('robot_partition_coordinate_mismatch:'+name)
            if sum(len(x[2]) for x in parts)!=len(UsdGeom.Mesh(p).GetFaceVertexCountsAttr().Get()):raise ValueError('robot_partition_face_union_mismatch')
            UsdGeom.Imageable(p).MakeInvisible()
            for row,vertices,counts,indices in parts:mesh(str(wrapper.GetPath())+'/'+row['material'],vertices,counts,indices,material(row['material'],row['rgba'],dict(roughness=.22 if row['material']=='robot_silver' else .55,metallic=.78 if row['material']=='robot_silver' else 0.)))
            partitions.append(name)
        else:
            silver=name in palette['silver_meshes'];mat=material('robot_silver' if silver else 'robot_black',palette['silver_rgba'] if silver else palette['black_rgba'],dict(roughness=.22 if silver else .55,metallic=.78 if silver else 0.));UsdShade.MaterialBindingAPI.Apply(p).Bind(mat)
        visual.append(dict(body=name,visual_path=path))
    if not visual:raise ValueError('native_robot_visuals_not_found')
    # Preserve physics instances and their physics-purpose material bindings.
    # A separate render-only sibling restores the source table/tray RGBA.
    source_colors=[]
    for p in list(Usd.PrimRange.Stage(stage,Usd.TraverseInstanceProxies())):
        if p.GetName() in ('floor','ground','floor_geom') and p.IsA(UsdGeom.Imageable):
            target=p.GetParent() if p.IsInstanceProxy() else p
            UsdGeom.Imageable(target).MakeInvisible()
        if not p.IsA(UsdGeom.Mesh) or any(part.startswith('robot_geom_') for part in str(p.GetPath()).split('/')) or str(p.GetPath()).startswith(root):continue
        if UsdGeom.Imageable(p).ComputeVisibility()=='invisible' or UsdGeom.Imageable(p).ComputePurpose()=='guide':continue
        wrapper=p.GetParent()
        try:gid=model.geom(wrapper.GetName()).id
        except KeyError:continue
        rgba=model.geom_rgba[gid].tolist();original=UsdGeom.Mesh(p)
        copy_root=UsdGeom.Xform.Define(stage,str(wrapper.GetPath())+'_RenderAppearance')
        UsdGeom.Xformable(copy_root).AddTransformOp().Set(UsdGeom.Xformable(wrapper).GetLocalTransformation())
        copy=mesh(str(copy_root.GetPath())+'/Surface',np.asarray(original.GetPointsAttr().Get()),original.GetFaceVertexCountsAttr().Get(),original.GetFaceVertexIndicesAttr().Get(),material('source_'+wrapper.GetName(),rgba,dict(roughness=.6)))
        normals=original.GetNormalsAttr().Get()
        if normals is not None:copy.CreateNormalsAttr(normals);copy.SetNormalsInterpolation(original.GetNormalsInterpolation())
        UsdGeom.Imageable(wrapper).MakeInvisible();source_colors.append(wrapper.GetName())
    dome=UsdLux.DomeLight.Define(stage,'/TaskDomeLight');dome.CreateIntensityAttr(600.)
    for i,(x,y) in enumerate([(0.,-1.4),(0.,1.4),(2.,-1.4),(2.,1.4)]):
        light=UsdLux.RectLight.Define(stage,root+f'/Lighting/Panel{i}');light.CreateWidthAttr(1.);light.CreateHeightAttr(.65);light.CreateIntensityAttr(2500.);light.CreateColorAttr(Gf.Vec3f(1.,.98,.94));UsdGeom.Xformable(light).AddTranslateOp().Set(Gf.Vec3d(x,y,2.85))
    after=physics_fingerprint(stage)
    if before!=after:raise ValueError('visual_patch_modified_physics_or_original_cameras')
    return dict(schema='isaac_lab_visual_translation/1',room_objects=len(room),robot_visuals=len(visual),source_object_colors=source_colors,torso_partitions=partitions,physics_and_original_camera_fingerprint=after,physics_and_original_cameras_unchanged=True,source_manifest_sha256=hashlib.sha256((assets/'manifest.json').read_bytes()).hexdigest(),fidelity='Same project Blender assets and palette as MuJoCo; photo-inspired, not measured real-room calibration',lighting=dict(profile='lab_exposure_v2',dome_intensity=600.,panel_intensity=2500.,panels=4,post_video_exposure_filter=False),visuals=visual)
