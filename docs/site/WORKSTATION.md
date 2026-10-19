# Scene Studio offline / ROS 2 workstation guide

This edition runs on `xinmatrix` without ChatGPT login. Web assets, SQLite, version history and artifact access are local. The existing project's datasets, Isaac resources and model weights remain at their original paths; the source export does not duplicate checkpoints or training videos.

## Start the deployed service

```bash
cd /home/michelle/haoze/r1pro-airport-sim/releases/scene_studio_offline_20261019_v2
bash offline/start.sh
```

Open `http://127.0.0.1:9080` on the workstation. To bind to the workstation's existing private network address:

```bash
STUDIO_HOST=100.104.0.108 bash offline/start.sh
```

Open `http://100.104.0.108:9080` from a device that can reach that network. Only start one instance: the supervisor holds a lock and refuses duplicates. `Ctrl+C` stops that supervisor's web/bridge children; queued GPU jobs have their own recorded process lifecycle. It does not stop unrelated training, simulation or robot services.

For detached operation:

```bash
mkdir -p /home/michelle/haoze/r1pro-airport-sim/runs/scene_studio_offline_20261019_v1
nohup env STUDIO_HOST=100.104.0.108 bash offline/start.sh \
  > /home/michelle/haoze/r1pro-airport-sim/runs/scene_studio_offline_20261019_v1/launcher.log 2>&1 < /dev/null &
```

Before rerunning, check `runs/scene_studio_offline_20261019_v1/heartbeat.json`, `supervisor.identity.json` and the recorded PID/start time/command. Logs, actual child exit receipts, database and bridge state are in this run directory. A healthy existing instance should be reused.

## Build from the source export

The export includes a prebuilt `offline-dist/`: Node 24 can run the web server without npm installation or Internet access. The GPU bridge additionally uses the existing non-base project Python environment.

For frontend development on a machine with Node 24:

```bash
npm ci
node offline/build.mjs
bash offline/start.sh
```

Dependency installation needs registry access unless packages are already cached. Runtime basic scene commands do not require GPT. An optional GPT key enables online conversation, so leave it unset for fully offline operation.

Default environments:

- Web: Node 24.
- Bridge: `/home/michelle/miniconda3/envs/r1pro-tray/bin/python`.
- π0.5 model: `/home/michelle/miniconda3/envs/r1pro-vla/bin/python`.
- Isaac: `/home/michelle/miniconda3/envs/env_isaaclab6/bin/python`.
- ROS 2 Jazzy: source `/opt/ros/jazzy/setup.bash`; `/home/michelle/miniconda3/envs/galaxea_ros_jazzy312/bin/python` plus NumPy.

`AIRPORT_PROJECT` sets the existing project root; `STUDIO_PYTHON`, `STUDIO_ROS_PYTHON`, `STUDIO_HOST` and `STUDIO_PORT` override local service settings. Model/framework environments are intentionally separate. No system/base Python installation is required.

## Register a model by path

In the offline website: **Data & training → Evaluation & MSE → Model checkpoint paths**.

1. Choose **π0.5**, **Galaxea AI G0.5** or **NVIDIA GR00T**.
2. Paste the absolute workstation checkpoint path.
3. Choose the checkpoint's gripper mapping.
4. Click **Register checkpoint path**. Read the returned validation status.
5. Under **Isaac VLA closed loop**, select **ROS 2 topics**, the model checkpoint, rooms and action frame budget; click **Create VLA evaluation**.

Configuration is saved in the project `configs/studio_ros2_models.json`. Each evaluation freezes its model configuration in a new run. It does not alter weights or existing training data. A saved path is not proof that a model loaded or passed a physical task.

### π0.5

Existing project checkpoints are registered from their saved training receipts and include the current 10,000-update mixed model. A custom path must match a complete registered checkpoint with its own model specification, normalization and content bindings. Input is measured mobile19 state, three native RGB cameras and the task text; output is H20 joint targets, using five steps before replanning.

### Galaxea AI G0.5

User-provided checkpoint:

```text
/home/michelle/g05_frontloader_20261015/runs/frontloader/train_10epochs/last.pt
```

Its neighboring `.hydra/config.yaml`, `dataset_stats.json`, `hf_processor/` and `action_tokenizer.pt` are required. The existing model environment is `code/.venv/bin/python` in the same frontloader project. The service starts its own local WebSocket model process and preserves its actual exit code. One connection per room preserves separate model histories.

The user confirmed **100 = 100% = 80 mm full opening**: choose `0–100% → 0–80 mm`. Observed openings in metres are multiplied by 1250 for the model; model gripper outputs are divided by 1250 for simulation. Joint targets remain radians; base is explicitly fixed. No output clipping or IK is added.

This checkpoint was trained at **30 Hz**, with an internal horizon of 32. The approved initial evaluation is a **20 Hz diagnostic**, explicitly not a timing-matched comparison with π0.5. Its server returns one action per request; the transport executes one action then supplies the next actual observation. It does not fabricate a 20-step chunk from a single reply.

### GR00T

Register a checkpoint directory. A compatible joint-space fine-tuned checkpoint must include `studio_model.json`, for example:

```json
{
  "actionSpace": "joint_absolute",
  "gripperUnit": "m",
  "horizon": 20,
  "modelPython": "/absolute/path/to/groot/environment/bin/python",
  "embodimentTag": "new_embodiment",
  "cameraKeys": {"head_left":"head_left","left_wrist":"left_wrist","right_wrist":"right_wrist"},
  "stateKeys": {"left_arm":"left_arm","left_gripper":"left_gripper","right_arm":"right_arm","right_gripper":"right_gripper"},
  "actionKeys": {"left_arm":"left_arm","left_gripper":"left_gripper","right_arm":"right_arm","right_gripper":"right_gripper"}
}
```

These keys must match the checkpoint's actual modality configuration; the example does not convert an incompatible model. Install the matching official GR00T runtime in that model's own environment. Pretrained EEF/relative-EEF outputs are rejected by this joint-space path. No GR00T checkpoint was supplied in this request; adapter implementation must not be described as verified GR00T inference.

## ROS 2 topic contract

All simulation transport uses **ROS_DOMAIN_ID=86**, localhost discovery, and namespace:

```text
/r1pro_sim/<evaluation_job_id>/room_<original_room_id>/
```

| Topic suffix | ROS message | Content |
|---|---|---|
| `joint_states` | `sensor_msgs/msg/JointState` | mobile19: left7/opening, right7/opening, relative base3; rad/m units |
| `camera/head_left/image_raw` | `sensor_msgs/msg/Image` | Native RGB8 HWC head view |
| `camera/left_wrist/image_raw` | `sensor_msgs/msg/Image` | Native RGB8 left wrist |
| `camera/right_wrist/image_raw` | `sensor_msgs/msg/Image` | Native RGB8 right wrist |
| `request` | `std_msgs/msg/String` | JSON requestId, roomId, checkpointId, prompt, horizon and action contract |
| `actions` | `std_msgs/msg/String` | JSON matching IDs and finite actions `[H,19]`, or error |

`header.frame_id` carries the request ID. Headers use ROS publication time, not a fabricated simulation timestamp. Commands must match room, checkpoint and outstanding request; duplicate/mismatched/stale replies are rejected. No response means failure, never teacher fallback. The raw model chunk and actually submitted fixed-base actions remain in the native evaluation evidence.

Inspect a running evaluation:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=86 ROS_LOCALHOST_ONLY=1
unset ROS_DISCOVERY_SERVER FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE
ros2 topic list --no-daemon
# Use the exact topic from that listing:
ros2 topic echo /r1pro_sim/JOB_ID/room_000/request --once
```

Each run saves `ros2_topics.json`, `ros2.heartbeat.json`, model/ROS logs and actual child exit receipts. To substitute your own ROS policy node, the transport CLI supports `--external-policy`; publish matching actions with the documented joint-space contract. This feature never publishes hardware `/motion_target` or `/hdas` commands.

## Batch provenance, reset and Help

- **Data & recipe → 32-room batch lineage** shows source batch, dataset version, split, requested rooms, qualified pairs, frozen training pairs, action segments and overflow. The current production source has 313 qualified pairs, while the frozen training release contains 300 pairs/600 action segments. Read the live manifest-derived table for each batch's counts.
- A model evaluation is a diagnostic and never automatically enters training. Creating a new dataset version remains separate from editing a scene or running a policy.
- **Reset selected rooms** restores robot and tray poses/colors for the selection. **Reset all 32 rooms** restores each room's own baseline and view; use Save version afterward. Undo remains available.
- **Help** is always available in the top navigation and includes MSE navigation, downloads, resets, dataset provenance and these workstation commands.

## Result interpretation

The current 32 rooms share the training parent scene: they measure training-scene closed-loop diagnostics, not held-out generalization or real-robot success. A failed model initialization is infrastructure failure. A completed process is not a successful Pick/Place. MSE currently retains the fixed π0.5 real Val/Test protocol; adding an external model does not silently reuse its normalization or declare a cross-model MSE comparison.
