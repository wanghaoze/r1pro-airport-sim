"""Engine-independent, named SI trajectory and immutable source provenance."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import numpy as np

CHANNELS = tuple([f"left_arm_joint{i}" for i in range(1, 8)] + ["left_gripper_opening_m"]
                 + [f"right_arm_joint{i}" for i in range(1, 8)] + ["right_gripper_opening_m"]
                 + [f"torso_joint{i}" for i in range(1, 5)])
PROMPTS = ("Pick up the tray", "Place the tray")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf8")
    tmp.replace(path)


@dataclass(frozen=True)
class Trajectory:
    timestamps: np.ndarray
    feedback: np.ndarray
    commands: np.ndarray
    channels: tuple[str, ...]
    provenance: dict

    def __post_init__(self):
        t, q, u = (np.array(v, dtype=np.float64, copy=True)
                   for v in (self.timestamps, self.feedback, self.commands))
        if t.ndim != 1 or len(t) < 2 or not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
            raise ValueError("real2sim_invalid_timestamps")
        if q.shape != (len(t), len(self.channels)) or u.shape != q.shape:
            raise ValueError("real2sim_invalid_channel_shape")
        if len(set(self.channels)) != len(self.channels) or not np.isfinite(q).all() or not np.isfinite(u).all():
            raise ValueError("real2sim_duplicate_or_nonfinite_channels")
        for name, value in (("timestamps", t), ("feedback", q), ("commands", u)):
            value.setflags(write=False)
            object.__setattr__(self, name, value)

    @property
    def seconds(self):
        return self.timestamps - self.timestamps[0]

    def save(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        np.savez_compressed(directory / "trajectory.npz", timestamps=self.timestamps,
                            feedback=self.feedback, commands=self.commands)
        write_json(directory / "manifest.json", dict(schema="real2sim_trajectory/1",
                   channels=self.channels, units=["m" if "opening" in n else "rad" for n in self.channels],
                   source_domain="real_world/user_provided", frames=len(self.timestamps),
                   trajectory_sha256=sha256(directory / "trajectory.npz"), provenance=self.provenance))

    @classmethod
    def load(cls, directory):
        directory = Path(directory)
        m = json.loads((directory / "manifest.json").read_text(encoding="utf8"))
        if m["schema"] != "real2sim_trajectory/1" or sha256(directory / "trajectory.npz") != m["trajectory_sha256"]:
            raise ValueError("real2sim_bundle_identity_mismatch")
        with np.load(directory / "trajectory.npz", allow_pickle=False) as a:
            return cls(a["timestamps"], a["feedback"], a["commands"], tuple(m["channels"]), m["provenance"])


def from_record(record):
    """Read original Parquet at original timestamps, not the 20 Hz training cache."""
    import pyarrow.parquet as pq
    if record.get("domain") != "real" or record.get("prompt") not in PROMPTS:
        raise ValueError("real2sim_real_pick_place_source_required")
    path = Path(record["parquet"])
    digest = sha256(path)
    if digest != record["parquet_sha256"]:
        raise ValueError("real2sim_source_hash_mismatch")
    table = pq.read_table(path)
    def array(name):
        return np.asarray(table[name].to_pylist(), dtype=np.float64)
    velocity = array("action.chassis.velocities")
    if velocity.shape != (len(table), 6) or not np.isfinite(velocity).all() or np.any(velocity != 0):
        raise ValueError("real2sim_moving_base_contract_required")
    values = []
    for prefix in ("observation.state", "action"):
        parts = [array(prefix + "." + name) for name in
                 ("left_arm", "left_gripper", "right_arm", "right_gripper", "torso")]
        parts = [p[:, None] if p.ndim == 1 else p for p in parts]
        if [p.shape[1] for p in parts] != [7, 1, 7, 1, 4]:
            raise ValueError("real2sim_r1pro_channel_contract_mismatch")
        q = np.concatenate(parts, axis=1)
        q[:, [7, 15]] *= .001
        values.append(q)
    provenance = {k: record[k] for k in ("dataset", "episode_index", "raw_file_name", "split", "prompt", "parquet", "parquet_sha256", "videos")}
    provenance.update(base_policy="recorded_zero_velocity_fixed_initial_base", gripper="total_opening_mm_to_m",
                      torso="four_recorded_joint_angles_rad", timestamps="original_no_resampling",
                      original_frames=len(table), feedback_not_clipped=True)
    return Trajectory(array("timestamp"), *values, CHANNELS, provenance)
