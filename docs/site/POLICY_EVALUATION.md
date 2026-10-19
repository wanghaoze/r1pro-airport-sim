# Single-policy evaluation

Open http://100.104.0.108:9080/ on the workstation network, then **Policy evaluation**. The hosted Site has the same page; GPU control retains its existing owner identity requirement. The workstation build needs no login.

1. Choose any registered Room 000–031 and one saved checkpoint. Register additional compatible checkpoint paths under **Data & training → Evaluation & MSE → Model checkpoint paths** on the workstation.
2. Set **Maximum simulation duration** (1–120 seconds). The limit is total executed physics action frames at 20 Hz, shared across Pick and Place. Waiting for a model reply does not consume simulated time. A successful task or model/physics failure ends earlier.
3. Advanced settings independently limit each inference request (1–300 seconds) and total wall time including initialization (10–3600 seconds). Media finalization may finish after the guard.
4. Click **Start policy evaluation**. Each run has its own immutable ID, room, checkpoint and configuration. One GPU job executes at a time; loading, native initialization and queueing are shown separately.
5. Watch measured native body poses in the orbitable 3D view, four native camera views, actual frames, simulated elapsed time and model latency. The 3D representation uses the existing website source geometry bound to measured PhysX body poses. Cameras show the exact native renderer. The view freezes during inference; sample age exposes stale frames. This is live monitoring, not a claim of sustained 20 Hz wall-clock performance.
6. After the run stops, **This run’s result & downloads** offers overview, head, left/right wrist MP4 and the report. Files belong to the selected run; they are not the static demo. **Previous runs** restores a prior result. Video playback uses the 20 Hz simulation timeline; wall-time statistics are separate. Zero executed frames means no motion video. Files above the current 32 MB cloud upload bound remain on the workstation and are explicitly flagged.

## Measured acceptance, 2026-10-19

- Room 001 / latest mixed π0.5 / requested 1 s: 15 executed frames (0.75 s), 37 measured bodies and four cameras; left_arm_joint4 prediction exceeded the unchanged mechanical range. Four per-run MP4 files and report published. Browser download SHA verified. This is a completed diagnostic, not Pick/Place success.
- Room 000 / same checkpoint: first output chunk exceeded the range; zero executed frames, report only.
- Room 007 / G0.5: native initialization and camera-to-service request completed; adapter returned HTTP 500, no executed frames. Existing missing gripper output remains unresolved; no fallback was added.
- CPU contract tests verify total frame truncation at 17 and 20 frames, original room 31 correlation and per-request timeout. These tests are not physical success evidence.

Evidence: `runs/web_live_policy_20261019_v1/verification.json`, `assets_bindings_validation.json`, `ros_roundtrip.json`. Service release: `/home/michelle/haoze/r1pro-airport-sim/releases/scene_studio_live_policy_20261019_v5`.

## Start the workstation website

```bash
cd /home/michelle/haoze/r1pro-airport-sim/releases/scene_studio_live_policy_20261019_v5
STUDIO_HOST=100.104.0.108 bash offline/start.sh
```

The supervisor holds a single-instance lock; do not launch another copy while it is healthy. The UI starts isolated ROS 2 domain 86 diagnostics. It may reuse a matching owned checkpoint server after identity/health validation; shared servers are not killed when a run finishes. No hardware control, teacher, IK or implicit gripper repair is enabled.

## Explicit clipping diagnostic (workstation v8)

Choose Action handling → Limit-clipped diagnostic to inspect continued model behaviour when small out-of-range predictions stop strict execution. Strict mode remains the default. The diagnostic clips complete finite arm/gripper predictions to existing model joint ranges and logs original/applied values. It does not repair missing channels, use IK or change mechanical limits. These runs are excluded from pure-model success rates.

Room000 / real90sim10 reached40frames/2s in run4201ad6f and stopped at the configured limit. Native rollout took19.26s wall time, so sustained real-time performance is not achieved. The page shows Ended and Stop reason above3D.
