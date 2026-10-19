# Camera-driven checkpoint inference in Isaac

Verified on xinmatrix, 19 October 2026. This is simulation only.

## What actually ran

The latest registered 10,000-update Real50/Sim50 π0.5 checkpoint received five observations from Isaac's native head and wrist cameras through ROS 2. Twenty model action frames were applied to the simulated robot. A subsequent predicted left elbow target exceeded the mechanical range, so the controller stopped without clipping, IK, or teacher replacement. Pick/Place did not pass.

The native rollout covered 1.00 simulated second in 12.57 wall-clock seconds. First inference took 4.00 seconds; later inferences took approximately 0.44 seconds. **Sustained 20 Hz wall-clock execution was not achieved.** Physics/contact processing and synchronous inference both contribute to the delay. The exported wall-clock video preserves the measured waits; its 30 fps encoding is not a claim of 30 Hz control.

G0.5 loaded `step_51810.pt` (the supplied `last.pt` target), received actual simulator camera observations, and performed inference. Its AR server omitted both gripper outputs. Strict full-action validation rejected the response, so that run executed zero frames. An explicit arms-only mode with measured grippers held requires the user's decision. The approved gripper mapping remains 100%=80 mm; 30 Hz training / 20 Hz diagnostic is not a timing-matched comparison.

## Running services

Both checkpoint services were left running on GPU 0. They bind to workstation loopback, not robot hardware networks. Check fresh status before reusing or starting anything:

```bash
export AIRPORT_PROJECT=/home/michelle/haoze/r1pro-airport-sim
cat "$AIRPORT_PROJECT/runs/live_pi05_server_20261019_v1/live_status.json"
cat "$AIRPORT_PROJECT/runs/live_g05_20261019_v2/live_status.json"
cat "$AIRPORT_PROJECT/runs/live_pi05_server_20261019_v1/model_http.ready.json"
```

The π0.5 HTTP service advertises its current dynamic port in `model_http.ready.json`; `/health` returns its checkpoint identity. The G0.5 upstream WebSocket server is at `ws://127.0.0.1:9085`. Its v2 HTTP bridge does not implement GET health; use controller identity, heartbeat, model-ready metadata and inference logs. Ports and PIDs in old receipts are not live-status guarantees.

## Start a fresh server and one recorded simulation

Use a new run directory every time. The controller freezes checkpoint identity, starts the model and ROS nodes, waits for readiness, runs Isaac, records native camera videos, and keeps the server running after the diagnostic.

```bash
export AIRPORT_PROJECT=/home/michelle/haoze/r1pro-airport-sim
CODE="$AIRPORT_PROJECT/releases/studio_live_inference_20261019_v3"
PY=/home/michelle/miniconda3/envs/r1pro-vla/bin/python
RUN="$AIRPORT_PROJECT/runs/pi05_camera_demo_$(date +%Y%m%d_%H%M%S)"

"$PY" "$CODE/scripts/studio_live_inference.py" \
  --run "$RUN" \
  --checkpoint-id cp_8788068a6984a796aed42ef1 \
  --room 0 --frames 200 --gpu 0 --keep-server
```

The current services already use GPU memory. Reuse them, or stop only their verified controllers before starting replacements. The shared GPU-job lock prevents concurrent rollout controllers; it does not authorize stopping unrelated GPU workloads.

For G0.5, the checkpoint ID is `g05_6485e66046587989`. Stop the existing owned G0.5 controller before starting another instance, because port 9085 must have exactly one verified owner. The current strict controller will reject missing gripper outputs; do not interpret this command as a successful-task guarantee.

To start a server without immediately running Isaac, replace `--keep-server` with `--serve-only`. In a second terminal, run the simulator against that same fresh server directory once:

```bash
export CUDA_VISIBLE_DEVICES=0 STUDIO_SIM_GPU=0
flock -n "$AIRPORT_PROJECT/runs/web_studio_jobs_20261017_v1/gpu_job.lock" \
  "$PY" "$CODE/scripts/studio_vla_evaluate.py" --run "$RUN" \
  --native-python /home/michelle/miniconda3/envs/env_isaaclab6/bin/python
```

The evaluator leaves an external server running. Each run accepts one recorded episode; repeat with a fresh directory/server to avoid reusing observation IDs, cached actions or model history.

## Inspect and export

```bash
cat "$RUN/live_status.json"
cat "$RUN/progress.json"
cat "$RUN/report.json"
tail "$RUN/inference_events.jsonl"
cat "$RUN/ros2_topics.json"

/home/michelle/miniconda3/envs/r1pro-tray/bin/python \
  "$CODE/scripts/export_live_inference_video.py" --run "$RUN"
```

The export writes `video_export/camera_model_simulator_wallclock.mp4` and a SHA-256/timing receipt. It requires actually executed frames; a zero-frame failure cannot be exported as a working-motion demonstration. The four views are overview, head camera, left wrist and right wrist. The closing slate reports measured speed and failure/success. Original camera MP4s retain their 20 Hz simulation time base under `native/rooms/room_000/`.

## Observation-to-action contract

`ROS_DOMAIN_ID=86`, localhost discovery, `/r1pro_sim/<run>/room_000/`:

- Three `sensor_msgs/Image` RGB8 camera topics, one `sensor_msgs/JointState` with 19 channels, and a JSON request with exact prompt and checkpoint ID.
- Action replies correlate request ID, room and checkpoint. Model inference uses only current camera/state/task inputs; contact and tray metadata are used by physical task auditing, not policy inputs.
- π0.5 returns H20 absolute targets; the simulator executes up to five before observing again. G0.5's official server returns one step per request, with its own five-step cache.
- Arm positions are radians, full gripper openings are metres, and base actuation is explicitly fixed. No unannounced action clipping or missing-channel replacement occurs.
- Synchronous waiting pauses simulated time. Pacing prevents faster-than-20 Hz execution; it cannot make a slow inference/physics loop satisfy a 50 ms wall-clock deadline.

## Stop only the owned service

Foreground: press Ctrl+C. For an existing detached service, compare the PID, `/proc` start ticks, command and working directory against `controller.identity.json`, then send SIGTERM to that controller. It stops its own checkpoint/ROS children and records actual exit codes. Do not kill all Python, Isaac, ROS or GPU processes.

Evidence: `runs/realtime_inference_20261019_v1/`, native run `runs/live_pi05_20261019_v2`, strict G0.5 run `runs/live_g05_20261019_v2`. GR00T still requires a supplied compatible joint-action checkpoint.
