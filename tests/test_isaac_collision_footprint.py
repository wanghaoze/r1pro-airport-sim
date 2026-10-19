import numpy as np
import pytest
from r1pro_teleop.real2sim.isaac_collision_footprint import maximum_union_overhang, native_mesh_footprint


def test_boundary_uses_true_beveled_shape_without_changing_five_cm_gate():
    table=dict(center_world=[0,0,0],dimensions_m=[.6,1.2,.8],yaw_world=0.)
    angle=np.deg2rad(64.);c,s=np.cos(angle),np.sin(angle);rotation=np.array([[c,-s],[s,c]])
    rectangle=np.array([[-.28,-.215],[-.28,.215],[.28,-.215],[.28,.215]])
    bevel=np.array([[-.28,-.195],[-.26,-.215],[.26,-.215],[.28,-.195],
                    [.28,.195],[.26,.215],[-.26,.215],[-.28,.195]])
    def world(x):return np.c_[x@rotation.T+[.038,0],np.zeros(len(x))]
    assert maximum_union_overhang(world(rectangle),[table])>.05
    assert maximum_union_overhang(world(bevel),[table])<.05
    assert maximum_union_overhang(world(bevel)+[.04,0,0],[table])>.05


def test_vertices_can_be_supported_by_union_of_unchanged_tables():
    tables=[dict(center_world=[x,0,0],dimensions_m=[1,1,.8],yaw_world=0.) for x in (0.,1.)]
    assert maximum_union_overhang(np.array([[0,0,0],[1.4,0,0]]),tables)==0.


def test_native_extraction_preserves_local_geometry_and_does_not_mutate_stage():
    pxr=pytest.importorskip('pxr')
    from pxr import Usd,UsdGeom,UsdPhysics,Gf
    stage=Usd.Stage.CreateInMemory();body=UsdGeom.Xform.Define(stage,'/Body')
    body.AddTranslateOp().Set(Gf.Vec3d(12,24,.8))
    mesh=UsdGeom.Mesh.Define(stage,'/Body/Collision');mesh.CreatePointsAttr([(0.,0.,0.),(.2,.1,.01)])
    mesh.AddTranslateOp().Set(Gf.Vec3d(.01,.02,.03));UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
    before=stage.GetRootLayer().ExportToString();row=native_mesh_footprint(stage,'/Body')
    np.testing.assert_allclose(row['body_local_vertices_m'],[[.01,.02,.03],[.21,.12,.04]],atol=1e-8)
    assert row['geometry_modified'] is False and row['tolerance_modified'] is False
    assert stage.GetRootLayer().ExportToString()==before
