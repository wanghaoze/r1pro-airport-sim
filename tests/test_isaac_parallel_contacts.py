"""Contact-view contract tests; no engine or fabricated physical pass."""
import sys
from types import SimpleNamespace
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from r1pro_teleop.real2sim.isaac_parallel_contacts import RoomContacts


class FakeView:
    def __init__(self, origin, tray_xy=(0.,0.), yaw=0.):
        self.names=['tray_0','left_gripper_finger_link1','left_gripper_finger_link2',
                    'right_gripper_finger_link1','right_gripper_finger_link2']
        # Deliberately shuffled sensor rows: names cannot be treated as indices.
        self.order=[2,0,4,1,3]
        self.prim_paths=['/room/'+self.names[i] for i in self.order]
        self.origin=np.asarray(origin);self.R=Rotation.from_euler('z',yaw).as_matrix()
        self.tray=np.array([*tray_xy,.8]);self.calls=[]
        self.matrix=np.zeros((5,2,3));self.counts=np.zeros((5,2),int);self.starts=np.zeros((5,2),int)
        self.points=[];self.forces=[];self.separations=[]
        for name,point in [('left_gripper_finger_link1',[0,.215,.05]),
                           ('left_gripper_finger_link2',[.02,.215,.05]),
                           ('right_gripper_finger_link1',[0,-.215,.05]),
                           ('right_gripper_finger_link2',[-.02,-.215,.05])]:
            row=self.prim_paths.index('/room/'+name)
            self.starts[row,0]=len(self.points);self.counts[row,0]=1
            self.points.append(self.origin+self.tray+self.R@point)
            self.forces.append([2.]);self.separations.append([-.001])
            self.matrix[row,0]=[0,0,2.]
        self.matrix[self.prim_paths.index('/room/tray_0'),1]=[0,0,20.]
        self.points=np.array(self.points);self.forces=np.array(self.forces);self.separations=np.array(self.separations)
    def get_contact_force_matrix(self,dt):
        self.calls.append(('matrix',dt));return self.matrix
    def get_contact_force_data(self,dt):
        self.calls.append(('detail',dt))
        return self.forces,self.points,np.tile([0,0,1.],(4,1)),self.separations,self.counts,self.starts
    def get_world_poses(self):
        positions=np.tile(self.origin+self.tray,(5,1))
        q=Rotation.from_matrix(self.R).as_quat();wxyz=q[[3,0,1,2]]
        return positions,np.tile(wxyz,(5,1))
    def get_velocities(self):return np.zeros((5,6))


def make(monkeypatch,origin=(8.,-4.,0.),tray_xy=(0.,0.),yaw=0.):
    # Numpy FakeView never exercises the optional torch indexing branch.
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace())
    view=FakeView(origin,tray_xy,yaw)
    footprint=np.array([[x,y,z] for x in (-.28,.28) for y in (-.215,.215) for z in (0,.1)])
    tables=[dict(table_id='front_left',center_world=[0,0,0],dimensions_m=[1,1,.8],yaw_world=0)]
    contacts=RoomContacts(view,view.names,['tray_0','front_left'],origin,[.56,.43,.1],tables,footprint)
    return view,contacts


def obs(contacts,yaw=0.):
    q=Rotation.from_euler('z',yaw).as_quat()[[3,0,1,2]]
    return contacts.observation(np.zeros(19),np.zeros(19),np.r_[[-.5,0,0],q],.8)


def test_room_translation_is_removed_from_pose_and_actual_contact_points(monkeypatch):
    view,c=make(monkeypatch);r=obs(c)
    assert np.allclose(r['tray_pose'][0,:3],[0,0,.8])
    assert np.allclose(c.last_detail[1],view.points-view.origin)
    assert all(abs(row['point_world'][0])<1 and abs(row['point_world'][1])<1 for row in c.contact_rows)
    assert r['long_edge_sign'].tolist()==[[1,-1]]
    assert r['boundary_ok'].tolist()==[True]


def test_long_edges_are_tray_local_under_yaw_and_room_offset(monkeypatch):
    view,c=make(monkeypatch,origin=(-16,12,0),yaw=np.pi/2);r=obs(c,np.pi/2)
    assert r['long_edge_sign'].tolist()==[[1,-1]]
    assert r['axis_error_rad'][0]==pytest.approx(0,abs=1e-7)


def test_short_edge_and_mixed_edges_do_not_prove_opposing_grasp(monkeypatch):
    view,c=make(monkeypatch)
    view.points[0]=view.origin+view.tray+[.28,0,.05]
    view.points[1]=view.origin+view.tray+[.28,.01,.05]
    assert obs(c)['long_edge_sign'][0,0]==0
    view,c=make(monkeypatch)
    view.points[1]=view.origin+view.tray+[0,-.215,.05]
    assert obs(c)['long_edge_sign'][0,0]==0


def test_boundary_uses_actual_mesh_pose_not_tcp_or_room_origin(monkeypatch):
    _,c=make(monkeypatch,tray_xy=(.269,0))
    assert obs(c)['boundary_ok'][0]
    _,c=make(monkeypatch,tray_xy=(.331,0))
    assert not obs(c)['boundary_ok'][0]


def test_source_force_is_newtons_using_real_two_ms_timestep(monkeypatch):
    view,c=make(monkeypatch);r=obs(c)
    assert view.calls==[('matrix',.002),('detail',.002)]
    assert r['finger_force'].tolist()==[[4.,4.]]
    assert r['table_force'].tolist()==[20.]
    assert r['penetration_m']==pytest.approx(.001)
    assert c.contact_rows[0]['normal_force_n']==2.


def test_no_actual_contact_cannot_be_qualified_from_geometry(monkeypatch):
    view,c=make(monkeypatch);view.counts[:]=0;view.matrix[:]=0
    r=obs(c)
    assert r['long_edge_sign'].tolist()==[[0,0]]
    assert r['finger_force'].tolist()==[[0,0]]
    assert r['penetration_m']==0
