"""Timing, units, native-drive routing and preserved scene tests."""
from types import SimpleNamespace
import numpy as np
import pytest
from r1pro_teleop.real2sim import Trajectory, JointMap, Binding, r1pro_map, replay
from r1pro_teleop.real2sim.backends import IsaacSimBackend, GenesisBackend, MujocoBackend
from r1pro_teleop.real2sim.model import build_model
from r1pro_teleop.real2sim.registration import estimate_registration, validate_registration


def test_registration_distinguishes_supported_pick_and_held_place():
    channels = ('left_gripper_opening_m','right_gripper_opening_m')
    pads = np.array([[[.5,.22,1.], [.5,-.22,1.]]] * 3)
    pick = Trajectory([0,1,2], np.zeros((3,2)), [[.08,.08],[0,.08],[0,0]], channels,
                      dict(prompt='Pick up the tray', parquet_sha256='source'))
    r = validate_registration(estimate_registration(pick,pads))
    assert r['anchor_frame'] == 1 and r['tray_pose']['xyz'][2] == pytest.approx(.801)
    assert r['status'] == 'estimated_not_measured' and not r['scene_registration_verified']
    place = Trajectory([0,1,2], np.zeros((3,2)), [[0,0],[0,0],[.1,.1]], channels,
                       dict(prompt='Place the tray', parquet_sha256='source'))
    r = estimate_registration(place,pads)
    assert r['tray_pose']['xyz'][2] == pytest.approx(.91)
    assert r['source_parquet_sha256'] == 'source'
    r['tray_pose']['quaternion_wxyz'] = [0,0,0,0]
    with pytest.raises(ValueError, match='pose'):
        validate_registration(r)


def test_registration_changes_home_only_and_preserves_collision():
    import mujoco
    from r1pro_teleop.real2sim.mujoco_registration import apply_initial_registration
    model = mujoco.MjModel.from_xml_string('''<mujoco><worldbody>
      <body name="base_link" pos="-1 .2 0" quat="0 0 0 1"><joint name="agent_base_x" type="slide" axis="1 0 0"/>
      <joint name="agent_base_y" type="slide" axis="0 1 0"/>
      <joint name="agent_base_yaw" axis="0 0 1"/><geom size=".1"/></body>
      <body name="tray"><freejoint name="tray_free"/><geom size=".2 .1 .02" type="box"/></body>
      </worldbody><keyframe><key name="real2sim_home"/></keyframe></mujoco>''')
    data = mujoco.MjData(model); before = data.qpos.copy(); collision = model.geom_size.copy()
    r = dict(schema='real2sim_registration/1',units='metres_radians',quaternion_order='wxyz',frame='scene_world',
             base_pose=dict(xyz=[.3,.1,0],quaternion_wxyz=[1,0,0,0]),
             tray_pose=dict(xyz=[.85,0,.9],quaternion_wxyz=[1,0,0,0]))
    apply_initial_registration(model,r)
    assert np.array_equal(data.qpos,before) and np.array_equal(model.geom_size,collision)
    mujoco.mj_resetDataKeyframe(model,data,0)
    mujoco.mj_forward(model,data)
    assert data.body('base_link').xpos == pytest.approx([.3,.1,0])
    assert data.body('base_link').xmat.reshape(3,3) == pytest.approx(np.eye(3))
    assert data.qpos[3:6] == pytest.approx([.85,0,.9])


def test_collision_bundle_replaces_only_four_boxes_and_checks_identity(tmp_path):
    import xml.etree.ElementTree as ET
    from r1pro_teleop.real2sim.collision import apply_finger_collision_bundle
    from r1pro_teleop.real2sim.trajectory import write_json,sha256
    root=ET.fromstring('<mujoco><asset/><worldbody/></mujoco>');links={}
    mesh=tmp_path/'part.obj';mesh.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\nf 1 2 4\nf 1 3 4\nf 2 3 4\n')
    for side in ('left','right'):
        for i in (1,2):
            name=f'{side}_gripper_finger_link{i}'
            body=ET.SubElement(root.find('worldbody'),'body',name=name)
            ET.SubElement(body,'inertial',mass='1');ET.SubElement(body,'geom',name=name+'_visual',type='mesh',mesh='visual',contype='0')
            ET.SubElement(body,'geom',name=name+'_contact',type='box',size='.03 .005 .02',pos='0 .01 0',friction='1.2 .005 .0001')
            links[name]=dict(origin_xyz='0 0 0',origin_rpy='0 0 0',source_mesh_sha256='source',parts=[dict(file='part.obj',sha256=sha256(mesh))])
    write_json(tmp_path/'manifest.json',dict(schema='real2sim_finger_collision/1',urdf_sha256='urdf',method='test',links=links))
    before=[ET.tostring(e) for e in root.findall('.//inertial')]
    with pytest.raises(ValueError,match='identity'):
        apply_finger_collision_bundle(root,tmp_path,'wrong')
    report=apply_finger_collision_bundle(root,tmp_path,'urdf')
    assert len(report['changes'])==4 and len(root.findall('./asset/mesh'))==4
    assert before==[ET.tostring(e) for e in root.findall('.//inertial')]
    assert len([g for g in root.findall('.//geom') if g.get('contype')=='0'])==4
    assert not root.findall(".//geom[@type='box']")


def test_mapping_roundtrip_and_differential_fingers():
    m = r1pro_map(); q = np.arange(20) / 100
    q[7] = .08; q[15] = .06
    physical = m.encode(q)
    assert physical[7:9].tolist() == [.04, .04]
    assert np.allclose(m.decode(physical), q)
    physical[7] = .03; physical[8] = .05
    assert m.decode(physical)[7] == pytest.approx(.08)


def test_original_clock_zoh_no_lookahead_no_repeated_resets():
    t = Trajectory(np.array([4., 4.033333, 4.067, 4.1]), np.zeros((4, 1)),
                   np.arange(4.)[:, None], ("q",), {})
    m = JointMap(("q",), [Binding("physical", "q")])
    class Engine:
        timestep = .002
        def __init__(self): self.resets = 0; self.targets = []; self.q = np.zeros(1)
        def initialize(self, q): self.resets += 1; self.q = q
        def command(self, q): self.targets.append(float(q[0])); self.q = q
        def step(self): pass
        def observe(self): return self.q
    e = Engine(); r = replay(t, m, e)
    assert e.resets == 1 and r["physics_steps"] == 50
    assert e.targets[16:18] == [0., 1.]
    assert r["actual_times"] == pytest.approx([0, .034, .068, .1])
    assert r["source_command_indices"].tolist() == [-1, 0, 1, 2]
    assert r["max_sample_delay_s"] < e.timestep
    assert r["task_success"] is None


def test_bundle_tampering_and_bad_time(tmp_path):
    q = np.zeros((2, 1)); t = Trajectory([0, 1], q, q, ("q",), {"split": "test"})
    t.save(tmp_path / "bundle")
    assert Trajectory.load(tmp_path / "bundle").provenance["split"] == "test"
    with (tmp_path / "bundle/trajectory.npz").open("ab") as f: f.write(b"tampered")
    with pytest.raises(ValueError, match="identity"):
        Trajectory.load(tmp_path / "bundle")
    with pytest.raises(ValueError, match="timestamps"):
        Trajectory([1, 1], q, q, ("q",), {})


def test_isaac_routes_zero_targets_as_explicit_indices():
    calls = []
    robot = SimpleNamespace(get_dof_index=lambda n: {"a": 4, "b": 2}[n],
        set_joint_positions=lambda *a, **k: calls.append(("reset", a, k)),
        set_joint_velocities=lambda *a, **k: None,
        apply_action=lambda action: calls.append(("drive", action)),
        get_joint_positions=lambda **k: np.array([.2, .4]))
    world = SimpleNamespace(get_physics_dt=lambda: .002, step=lambda **k: calls.append(("step", k)))
    m = JointMap(("x", "y"), [Binding("a", "x"), Binding("b", "y")])
    b = IsaacSimBackend(robot, world, m, action_factory=lambda **kw: kw)
    b.initialize(np.zeros(2)); b.command(np.zeros(2)); b.step()
    assert calls[2][1]["joint_indices"].tolist() == [4, 2]
    assert calls[2][1]["joint_positions"].tolist() == [0, 0]
    assert sum(c[0] == "reset" for c in calls) == 1
    with pytest.raises(RuntimeError): b.initialize(np.zeros(2))


def test_genesis_native_position_controller():
    calls = []
    robot = SimpleNamespace(get_joint=lambda n: SimpleNamespace(n_dofs=1, dof_idx_local=3),
        set_dofs_position=lambda *a, **k: calls.append(("reset", a, k)),
        control_dofs_position=lambda *a, **k: calls.append(("drive", a, k)),
        get_dofs_position=lambda **k: np.array([.12]))
    b = GenesisBackend(robot, SimpleNamespace(step=lambda: None),
                       JointMap(("q",), [Binding("a", "q")]), timestep=.002)
    b.initialize(np.array([.1])); b.command(np.array([.2])); b.step()
    assert [c[0] for c in calls] == ["reset", "drive", "drive"]
    assert b.observe() == pytest.approx([.12])
    with pytest.raises(RuntimeError): b.initialize(np.array([.1]))


def test_original_parquet_units_torso_and_hash(tmp_path):
    pa = pytest.importorskip("pyarrow"); pq = pytest.importorskip("pyarrow.parquet")
    from r1pro_teleop.real2sim.trajectory import from_record, sha256
    cols = {"timestamp": [0., 1/30], "action.chassis.velocities": [[0.] * 6] * 2}
    for prefix in ("action", "observation.state"):
        for side in ("left", "right"):
            cols[prefix + "." + side + "_arm"] = [[.1] * 7] * 2
            cols[prefix + "." + side + "_gripper"] = [80., 102.7] if prefix != "action" else [80., 0.]
        cols[prefix + ".torso"] = [[.2, -.5, -.72, .001]] * 2
    path = tmp_path / "raw.parquet"; pq.write_table(pa.table(cols), path)
    record = dict(domain="real", prompt="Pick up the tray", dataset="raw", episode_index=1,
                  raw_file_name="x.mcap", split="test", parquet=str(path), parquet_sha256=sha256(path), videos={})
    t = from_record(record)
    assert t.feedback[1, 7] == pytest.approx(.1027)
    assert t.commands[0, 7] == pytest.approx(.08)
    assert t.feedback[0, 16:].tolist() == [.2, -.5, -.72, .001]
    record["parquet_sha256"] = "incorrect"
    with pytest.raises(ValueError, match="hash"):
        from_record(record)


def test_scene_restores_torso_preserves_collision_and_physics(tmp_path):
    from pathlib import Path
    import xml.etree.ElementTree as ET
    import mujoco
    root = Path(__file__).resolve().parents[1]
    source = root / "outputs/r1pro_tray_scene/scene_direct_grasp_720p.xml"
    urdf = root / "resources/real2sim_20261012_v1/r1_pro_source.urdf"
    dest = tmp_path / "model.xml"
    # Exercise an unnamed environmental joint too (as generated by flex bodies).
    tree = ET.parse(source); xml = tree.getroot()
    for node in xml.iter():
        if node.get("file"):
            node.set("file", str((source.parent / node.get("file")).resolve()))
    for keyframe in xml.findall("keyframe"): xml.remove(keyframe)
    body = ET.SubElement(xml.find("worldbody"), "body", name="unnamed_environment", pos="10 0 1")
    ET.SubElement(body, "joint", type="slide", axis="0 0 1", limited="false")
    ET.SubElement(body, "geom", type="sphere", size=".01", mass=".01")
    source = tmp_path / "source.xml"; tree.write(source)
    old = mujoco.MjModel.from_xml_path(str(source))
    build_model(source, urdf, dest)
    b = MujocoBackend(dest, r1pro_map())
    assert b.model.nq == old.nq + 4
    assert b.model.ngeom == old.ngeom and b.model.ncam == old.ncam
    assert np.array_equal(b.model.geom_contype, old.geom_contype)
    assert np.array_equal(b.model.body_mass, old.body_mass)
    assert np.array_equal(b.model.cam_quat, old.cam_quat)
    # Raw total opening maps to two positive outward half-openings, equivalent
    # to the signed URDF coordinates; zero must not retain the old 2mm clamp.
    for side in ('left', 'right'):
        for i, axis in ((1, [0, 1, 0]), (2, [0, -1, 0])):
            jid = b.model.joint(f'{side}_gripper_finger_joint{i}').id
            assert b.model.jnt_range[jid] == pytest.approx([0, .05])
            assert b.model.jnt_axis[jid] == pytest.approx(axis)
        aid = b.model.actuator(f'{side}_gripper_target').id
        assert b.model.actuator_ctrlrange[aid] == pytest.approx([0, .05])
        assert b.model.actuator_forcerange[aid] == pytest.approx([-100, 100])
    wider=tmp_path/'wider.xml'
    build_model(source,urdf,wider,tray_width_scale=1.07)
    wm=mujoco.MjModel.from_xml_path(str(wider))
    assert np.allclose(wm.body_mass,b.model.body_mass)
    assert np.allclose(wm.body_inertia[:wm.body('tray').id],b.model.body_inertia[:b.model.body('tray').id])
    assert not np.allclose(wm.body_inertia[wm.body('tray').id],b.model.body_inertia[b.model.body('tray').id])
    assert np.allclose(wm.cam_quat,b.model.cam_quat)
    q = np.zeros(20); q[[3, 11]] = -1.62; q[[7, 15]] = .1; q[16:]=[.2, -.5, -.72, 0]
    t = Trajectory([0, .01], [q, q], [q, q], r1pro_map().channels, {})
    r = replay(t, r1pro_map(), b)
    assert r["physics_steps"] == 5 and b.steps == 5
    assert b.data.time == pytest.approx(.01)
    with pytest.raises(RuntimeError): b.initialize(r1pro_map().encode(q))
