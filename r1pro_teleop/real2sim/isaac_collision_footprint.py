"""Measure the actual imported tray collision vertices, not an enclosing box.

No geometry, collision flag, pose or acceptance tolerance is modified here.
"""
import hashlib
import json
import numpy as np


def native_mesh_footprint(stage, body_path):
    from pxr import Usd, UsdGeom, UsdPhysics
    body=stage.GetPrimAtPath(body_path)
    if not body:raise ValueError('native_footprint_body_missing')
    cache=UsdGeom.XformCache();inverse=np.linalg.inv(np.asarray(cache.GetLocalToWorldTransform(body)))
    rows=[];points=[]
    for prim in Usd.PrimRange(body,Usd.TraverseInstanceProxies()):
        if not prim.HasAPI(UsdPhysics.CollisionAPI):continue
        if UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get() is False:continue
        if not prim.IsA(UsdGeom.Mesh):raise ValueError('native_footprint_unsupported_shape:'+str(prim.GetPath()))
        vertices=np.asarray(UsdGeom.Mesh(prim).GetPointsAttr().Get(),float)
        matrix=np.asarray(cache.GetLocalToWorldTransform(prim))@inverse
        local=np.c_[vertices,np.ones(len(vertices))]@matrix
        local=local[:,:3]/local[:,3:4]
        if not np.isfinite(local).all():raise ValueError('native_footprint_nonfinite_vertices')
        rows.append(dict(path=str(prim.GetPath()),vertex_count=len(vertices),
                         body_local_vertices_sha256=hashlib.sha256(local.tobytes()).hexdigest(),
                         approximation=UsdPhysics.MeshCollisionAPI(prim).GetApproximationAttr().Get()))
        points.append(local)
    if not points:raise ValueError('native_footprint_collision_meshes_missing')
    vertices=np.concatenate(points)
    return dict(schema='native_collision_vertex_footprint/1',body_path=body_path,
                body_local_vertices_m=vertices.tolist(),collision_meshes=rows,
                geometry_modified=False,tolerance_modified=False,
                vertices_sha256=hashlib.sha256(vertices.tobytes()).hexdigest())


def maximum_union_overhang(points,tables):
    """Each vertex may belong to any unchanged tabletop footprint."""
    p=np.asarray(points,float);dist=[]
    for table in tables:
        angle=float(table['yaw_world']);c,s=np.cos(angle),np.sin(angle)
        rotation=np.array([[c,-s],[s,c]])
        local=(p[:,:2]-np.asarray(table['center_world'][:2]))@rotation
        outside=abs(local)-np.asarray(table['dimensions_m'][:2])/2
        dist.append(np.maximum(outside,0).max(axis=1))
    if not dist:raise ValueError('native_footprint_tables_missing')
    return float(np.min(dist,axis=0).max())
