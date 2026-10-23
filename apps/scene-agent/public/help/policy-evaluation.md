# Single-policy evaluation

## Current controls — 21 October 2026

Choose simulation/rendering GPU and model inference GPU separately. Realtime uses CPU PhysX plus GPU rendering; baseline uses GPU PhysX. Both run in NVIDIA Isaac Sim; Three.js is only the browser view. Under Data & training, select training GPUs (one or two on this workstation).

The robot filter is mandatory for every model. Expand **Joint interpolation filter · all models** to tighten step, velocity, tracking-error and feedback-age limits within the registered ceiling. New settings apply to new runs. 10000 seconds is a finite extended-run cap; errors, physical gates or successful task completion can end it earlier.

Click **Stop policy** for the selected running job. **Stop requested** waits for the worker; **cancelled** confirms termination. Expand **Errors & diagnostics** for browser/API/job errors and the selected run's errors/logs for full structured stacks. Log tails are labeled; the terminal **diagnostics.zip** contains full redacted logs. Long files that exceed the upload cap remain on the workstation with a visible error.

The historical optional Strict/clipping modes below describe older releases only. Current submissions always use the robot filter and are excluded from pure-model success rates.


Open http://100.104.0.108:9080/ on the workstation network, then **Policy evaluation**. The hosted Site has the same page; GPU control retains its existing owner identity requirement. The workstation build needs no login.

1. Choose any registered Room 000–031 and one saved checkpoint. Register additional compatible checkpoint paths under **Data & training → Evaluation & MSE → Model checkpoint paths** on the workstation.
2. Set **Maximum simulation duration** (1–10000 seconds (default 10000)). The limit is total executed physics action frames at 20 Hz, shared across Pick and Place. Waiting for a model reply does not consume simulated time. A successful task or model/physics failure ends earlier.
3. Advanced settings independently limit each inference request (1–300 seconds) and total wall time including initialization (0–604800 seconds (default 0: no overall wall guard)). Media finalization may finish after the guard.
4. Click **Start policy evaluation**. Each run has its own immutable ID, room, checkpoint and configuration. One GPU job executes at a time; loading, native initialization and queueing are shown separately.
5. Watch measured native body poses in the orbitable 3D view, four native camera views, actual frames, simulated elapsed time and model latency. The 3D representation uses the existing website source geometry bound to measured PhysX body poses. Cameras show the exact native renderer. The optimized runtime prefetches one request while executing valid cached predictions and discards elapsed prediction prefixes; it waits if the buffer runs out. Sample age exposes stale frames. This is live monitoring, not a claim of sustained 20 Hz wall-clock performance.
6. After the run stops, **This run’s result & downloads** offers overview, head, left/right wrist MP4 and the report. Files belong to the selected run; they are not the static demo. **Previous runs** restores a prior result. Video playback uses the 20 Hz simulation timeline; wall-time statistics are separate. Zero executed frames means no motion video. Files above the current 32 MB cloud upload bound remain on the workstation and are explicitly flagged.

## Measured acceptance, 2026-10-19

- Room 001 / latest mixed π0.5 / requested 1 s: 15 executed frames (0.75 s), 37 measured bodies and four cameras; left_arm_joint4 prediction exceeded the unchanged mechanical range. Four per-run MP4 files and report published. Browser download SHA verified. This is a completed diagnostic, not Pick/Place success.
- Room 000 / same checkpoint: first output chunk exceeded the range; zero executed frames, report only.
- Room 007 / G0.5: native initialization and camera-to-service request completed; adapter returned HTTP 500, no executed frames. Existing missing gripper output remains unresolved; no fallback was added.
- CPU contract tests verify total frame truncation at 17 and 20 frames, original room 31 correlation and per-request timeout. These tests are not physical success evidence.

Evidence: `runs/web_live_policy_20261019_v1/verification.json`, `assets_bindings_validation.json`, `ros_roundtrip.json`. Service release: `/home/michelle/haoze/r1pro-airport-sim/releases/scene_studio_live_policy_20261019_v11`.

## Start the workstation website

```bash
cd /home/michelle/haoze/r1pro-airport-sim/releases/scene_studio_live_policy_20261019_v11
STUDIO_HOST=100.104.0.108 bash offline/start.sh
```

The supervisor holds a single-instance lock; do not launch another copy while it is healthy. The UI starts isolated ROS 2 domain 86 diagnostics. It may reuse a matching owned checkpoint server after identity/health validation; shared servers are not killed when a run finishes. No hardware control, teacher, IK or implicit gripper repair is enabled.

## Explicit clipping diagnostic (workstation v8)

Choose Action handling → Limit-clipped diagnostic to inspect continued model behaviour when small out-of-range predictions stop strict execution. Strict mode remains the default. The diagnostic clips complete finite arm/gripper predictions to existing model joint ranges and logs original/applied values. It does not repair missing channels, use IK or change mechanical limits. These runs are excluded from pure-model success rates.

Room000 / real90sim10 reached40frames/2s in run4201ad6f and stopped at the configured limit. Native rollout took19.26s wall time, so sustained real-time performance is not achieved. The page shows Ended and Stop reason above3D.


## Runtime optimization and robot limits (2026-10-19)

New workstation runs default to **Robot limits**. Mechanical arm ranges and 0-80 mm gripper bounds are applied at the checkpoint endpoint; execution also enforces the previous real-robot configuration: 0.1 rad maximum step, 1.5 rad/s velocity (0.075 rad per 20 Hz frame), 0.25 rad tracking-error guard and 0.5 s feedback-age guard. Weights are unchanged. Raw and bounded outputs are recorded. Protected runs are excluded from pure-model success rates and training.

The realtime profile uses CPU PhysX for this single-room workload, GPU rendering/model inference, Fabric, warmup before execution, and one asynchronous inference request. All 25 physics substeps at 0.002 s, contact checks, camera views and fixed-base restrictions remain. The baseline uses synchronous requests and GPU PhysX. Both comparison runs use warmup and identical action limits.

Open **Policy evaluation / Measured runtime comparison / Room 000** for embedded videos, downloads, selected runs and the JSON report. Same checkpoint cp_d0c1ec449340c22c344ee87c, same initial room, 40 frames / 2 simulated seconds: baseline 15.871 s versus optimized 4.745 s wall time (3.345x faster). Physics stepping: 9.136 to 1.941 s; model waiting: 3.649 to 0.522 s. Real-time factor is 0.126x to 0.422x, still below real time. Both stopped at the requested duration, not a successful Pick/Place. This is one short paired speed measurement; CPU/GPU physics and asynchronous observations may produce different trajectories. Initialization/warmup and media finalization are reported separately. Comparison videos retain actual waiting time; normal per-run videos retain the 20 Hz simulation timeline.
