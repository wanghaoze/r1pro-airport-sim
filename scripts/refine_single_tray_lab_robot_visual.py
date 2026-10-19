"""Blender-only visual face partition; original geometry/collision/inertia untouched."""
from pathlib import Path
import argparse,hashlib,json,sys
def main():
    import bpy
    p=argparse.ArgumentParser();p.add_argument('--output',default='resources/single_tray_lab_v1');p.add_argument('--render',action='store_true')
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    project=Path(__file__).resolve().parents[1];out=(project/a.output).resolve()
    if not out.is_relative_to(project):raise ValueError('output_not_in_project')
    source=project/'outputs/r1pro_tray_scene/assets/r1_pro/meshes/torso_link4.obj';source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    verts=[];faces=[]
    for line in source.read_text().splitlines():
        words=line.split()
        if words and words[0]=='v':verts.append(tuple(map(float,words[1:4])))
        elif words and words[0]=='f':
            f=[int(w.split('/')[0])-1 for w in words[1:]]
            faces.extend((f[0],f[i],f[i+1]) for i in range(1,len(f)-1))
    parts={'robot_silver':[],'robot_black':[]}
    for index,face in enumerate(faces):
        x=sum(verts[i][0] for i in face)/3;z=sum(verts[i][2] for i in face)/3
        parts['robot_silver' if x>.025 and z<.25 else 'robot_black'].append(index)
    assert sorted(i for indices in parts.values() for i in indices)==list(range(len(faces)))
    bpy.ops.wm.open_mainfile(filepath=str(out/'single_tray_lab.blend'))
    old=bpy.data.objects['robot_visual_copy_torso_link4'];transform=old.matrix_world.copy();bpy.data.objects.remove(old,do_unlink=True)
    overrides=[]
    for name,indices in parts.items():
        used=sorted({i for f in indices for i in faces[f]});mapping={old:new for new,old in enumerate(used)}
        vv=[verts[i] for i in used];ff=[tuple(mapping[i] for i in faces[f]) for f in indices]
        path=out/'meshes'/f'torso_link4_{name}.obj'
        path.write_text('# Original visual face subset, coordinate values unchanged; metres Z-up\n'+
            ''.join('v '+' '.join(format(x,'.17g') for x in v)+'\n' for v in vv)+
            ''.join('f '+' '.join(str(i+1) for i in f)+'\n' for f in ff))
        mesh=bpy.data.meshes.new(name);mesh.from_pydata(vv,[],ff);mesh.update()
        obj=bpy.data.objects.new('robot_visual_copy_torso_link4_'+name,mesh);bpy.context.scene.collection.objects.link(obj);obj.matrix_world=transform
        material=bpy.data.materials['silver_gray_polished_panels' if name=='robot_silver' else 'matte_black'];obj.data.materials.append(material)
        for face in mesh.polygons:face.use_smooth=True
        overrides.append(dict(mesh=str(path.relative_to(out)).replace('\\','/'),mesh_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            material=name,rgba=list(material.diffuse_color),vertices=len(vv),triangles=len(ff),local_geometry_coordinates_unchanged=True))
    manifest=json.loads((out/'manifest.json').read_text());manifest['robot_visual_overrides']={'torso_link4':overrides}
    manifest['robot_visual_partition_audit']=dict(source_mesh=str(source.relative_to(project)).replace('\\','/'),source_sha256=source_sha,
        source_triangles=len(faces),source_vertices=len(verts),silver_triangles=len(parts['robot_silver']),black_triangles=len(parts['robot_black']),
        rule='triangle centroid local X>0.025m and local Z<0.25m is silver chest; remaining original faces black',
        exact_disjoint_face_union=True,reference_fidelity='Approximate photo-informed material partition, not measured surface segmentation',
        original_collision_and_inertia_untouched=True)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==source_sha
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    palette=json.loads((out/'robot_appearance.json').read_text());palette['robot_visual_overrides']=manifest['robot_visual_overrides']
    (out/'robot_appearance.json').write_text(json.dumps(palette,indent=2))
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'single_tray_lab.blend'))
    if a.render:
        bpy.context.scene.render.filepath=str(out/'previews/lab_overview.png');bpy.ops.render.render(write_still=True)
    print(json.dumps(manifest['robot_visual_partition_audit']))
if __name__=='__main__':main()
