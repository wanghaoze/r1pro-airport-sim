"""Thin native SDK adapters. SDKs are imported only when their backend is created.

Isaac/Genesis callers own asset loading, gains, contacts and World/Scene lifecycle.
All positions are rad/metres. Isaac stages must use metres; USD angles are NOT
passed through this API. A built, unbatched articulation/entity is required.
"""
import numpy as np


class MujocoBackend:
    def __init__(self, xml, mapping):
        import mujoco
        self.mj = mujoco
        self.model = mujoco.MjModel.from_xml_path(str(xml))
        self.data = mujoco.MjData(self.model)
        self.mapping = mapping
        self.timestep = float(self.model.opt.timestep)
        self.jids = np.array([self.model.joint(n).id for n in mapping.joints])
        self.qids = self.model.jnt_qposadr[self.jids]
        self.vids = self.model.jnt_dofadr[self.jids]
        self.drives = [(i, self.model.actuator(b.actuator).id)
                       for i, b in enumerate(mapping.bindings) if b.actuator]
        self.initialized = False
        self.steps = 0

    def initialize(self, positions):
        if self.initialized:
            raise RuntimeError("real2sim_second_initialization_forbidden")
        home = self.mj.mj_name2id(self.model, self.mj.mjtObj.mjOBJ_KEY, "real2sim_home")
        if home >= 0:
            self.mj.mj_resetDataKeyframe(self.model, self.data, home)
        # Hold any existing position-driven base at the scene's initial pose.
        for aid in range(self.model.nu):
            if self.model.actuator_trntype[aid] != self.mj.mjtTrn.mjTRN_JOINT:
                raise ValueError("real2sim_joint_position_actuators_required")
            jid = int(self.model.actuator_trnid[aid, 0])
            self.data.ctrl[aid] = self.data.qpos[self.model.jnt_qposadr[jid]]
        self.data.qpos[self.qids] = positions
        self.data.qvel[self.vids] = 0.
        self.command(positions)
        self.mj.mj_forward(self.model, self.data)
        self.initialized = True

    def command(self, positions):
        # Keep raw references. Any engine-native ctrlrange clamp remains visible.
        for index, aid in self.drives:
            self.data.ctrl[aid] = positions[index]

    def step(self):
        before = float(self.data.time)
        warnings = self.data.warning.number.copy()
        self.mj.mj_step(self.model, self.data)
        self.mj.mj_forward(self.model, self.data)
        self.steps += 1
        if (not np.isfinite(self.data.qpos).all() or not np.isfinite(self.data.qvel).all()
                or abs(self.data.time - before - self.timestep) > 1e-8
                or np.any(self.data.warning.number > warnings)):
            raise RuntimeError("real2sim_physics_nonfinite_reset_or_warning")

    def observe(self):
        return self.data.qpos[self.qids].copy()

    def limit_audit(self, trajectory):
        rows = []
        for index, jid in enumerate(self.jids):
            b = self.mapping.bindings[index]
            col = self.mapping.channels.index(b.channel)
            lo, hi = self.model.jnt_range[jid]
            entry = dict(joint=b.joint, limited=bool(self.model.jnt_limited[jid]),
                         lower=float(lo), upper=float(hi))
            for kind, values in (("feedback", trajectory.feedback), ("command", trajectory.commands)):
                v = values[:, col] * b.scale + b.offset
                entry[kind] = dict(min=float(v.min()), max=float(v.max()),
                                  outside_count=int(np.sum((v < lo) | (v > hi))) if entry["limited"] else 0)
            rows.append(entry)
        return rows

    def contacts(self):
        rows = []
        for index, c in enumerate(self.data.contact):
            force = np.zeros(6)
            self.mj.mj_contactForce(self.model, self.data, index, force)
            rows.append(dict(geom1=int(c.geom1), geom2=int(c.geom2),
                             distance_m=float(c.dist), normal_force_n=float(force[0])))
        return rows


def _numpy(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value, dtype=float)


class IsaacSimBackend:
    """SingleArticulation + World. Construct after SimulationApp and world.reset()."""
    def __init__(self, articulation, world, mapping, *, action_factory=None):
        if action_factory is None:
            from isaacsim.core.utils.types import ArticulationAction
            action_factory = ArticulationAction
        self.robot, self.world, self.action_factory = articulation, world, action_factory
        self.indices = np.array([articulation.get_dof_index(n) for n in mapping.joints], dtype=int)
        if len(set(self.indices.tolist())) != len(mapping.joints) or np.any(self.indices < 0):
            raise ValueError("real2sim_invalid_engine_joint_indices")
        self.timestep = float(world.get_physics_dt())
        self.initialized = False

    def initialize(self, positions):
        if self.initialized:
            raise RuntimeError("real2sim_second_initialization_forbidden")
        self.robot.set_joint_positions(positions, joint_indices=self.indices)
        self.robot.set_joint_velocities(np.zeros_like(positions), joint_indices=self.indices)
        self.command(positions)
        self.initialized = True

    def command(self, positions):
        self.robot.apply_action(self.action_factory(joint_positions=np.asarray(positions), joint_indices=self.indices))

    def step(self):
        self.world.step(render=False)

    def observe(self):
        return _numpy(self.robot.get_joint_positions(joint_indices=self.indices))


class GenesisBackend:
    """Built RigidEntity + Scene, unbatched. Position PD gains are scene-owned."""
    def __init__(self, entity, scene, mapping, *, timestep):
        self.robot, self.scene = entity, scene
        joints = [entity.get_joint(n) for n in mapping.joints]
        if any(j.n_dofs != 1 for j in joints):
            raise ValueError("real2sim_scalar_joints_required")
        self.indices = [int(j.dof_idx_local) for j in joints]
        if len(set(self.indices)) != len(self.indices) or min(self.indices) < 0:
            raise ValueError("real2sim_invalid_engine_joint_indices")
        self.timestep = float(timestep)
        self.initialized = False

    def initialize(self, positions):
        if self.initialized:
            raise RuntimeError("real2sim_second_initialization_forbidden")
        self.robot.set_dofs_position(positions, dofs_idx_local=self.indices, zero_velocity=True)
        self.command(positions)
        self.initialized = True

    def command(self, positions):
        self.robot.control_dofs_position(positions, dofs_idx_local=self.indices)

    def step(self):
        self.scene.step()

    def observe(self):
        return _numpy(self.robot.get_dofs_position(dofs_idx_local=self.indices))
