# Single-policy evaluation

Open http://100.104.0.108:9080/ on the workstation network, then **Policy evaluation**. The hosted Site has the same page; GPU control retains its existing owner identity requirement. The workstation build needs no login.

1. Choose any registered Room 000–031 and one saved checkpoint. Register additional compatible checkpoint paths under **Data & training → Evaluation & MSE → Model checkpoint paths** on the workstation.
2. Set **Maximum simulation duration** (1–120 seconds). The limit is total executed physics action frames at 20 Hz, shared across Pick and Place. Waiting for a model reply does not consume simulated time. A successful task or model/physics failure ends earlier.
3. Advanced settings independently limit each inference request (1–300 seconds) and total wall time including initialization (10–3600 seconds). Media finalization may finish after the guard.
4. Click **Start policy evaluation**. Each run has its own immutable ID, room, checkpoint and configuration. One GPU job executes at a time; loading, native initialization and queueing are shown separately.
5. Watch measured native body poses in the orbitable 3D view, four native camera views, actual frames, simulated elapsed time and model latency. The 3D representation uses the existing website source geometry bound to measured PhysX body poses. Cameras show the exact native renderer. The optimized runtime prefetches one request while executing valid cached predictions and discards elapsed prediction prefixes; it waits if the buffer runs out. Sample age exposes stale frames. This is live monitoring, not a claim of sustained 20 Hz wall-clock performance.
6. After the run stops, **This run’s result & downloads** offers overview, head, left/right wrist MP4 and the report. Files belong to the selected run; they are not the static demo. **Previous runs** restores a prior result. Video playback uses the 20 Hz simulation timeline; wall-time statistics are separate. Zero executed frames means no motion video. Files above the current 32 MB cloud upload bound remain on the workstation and are explicitly flagged.

## Mandatory robot filter (2026-10-21)

All new single, batch and automatic policy simulations use Robot limits. Legacy strict/clip selections cannot disable execution filtering. HTTP and file model replies retain raw predictions separately; the simulator applies the mechanical/config intersection, arm step and velocity caps, gripper bounds, fixed-base mask, feedback freshness and tracking guards before every submitted frame. Invalid/nonfinite or incomplete actions are rejected before clipping. Existing registered limits are retained; no missing gripper channel is synthesized. Shared services must advertise the exact filter contract.

Filtered task passes are shown separately and excluded from pure-model success rates and training. Offline MSE continues to use raw predictions. Historical modes/results below describe older releases. Command bounds alone do not establish collision, acceleration/effort or hardware safety. The original TOML source path is currently unavailable; the archived limit values and verified mechanical XML are used.

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

## 2026-10-21 运行控制更新

默认10000秒有限仿真上限、整体墙钟保护0（关闭），支持Stop policy请求与实际cancelled确认。GPU清单来自工作站，仿真/渲染、推理和训练分别选择；realtime仍是CPU PhysX，baseline为GPU PhysX。四项filter软限制可在登记上界内调整，所有模型共享逐帧及25子步插值约束。网页展示错误、完整结构化堆栈、日志尾部/全日志错误摘录和终态完整脱敏诊断包。详见统一规范1.183；实测结果见 reports/WEB_CONTROLS_20261021.md。

## 2026-10-23 G0.5本地修复补充

本地协议修复通过78项CPU测试，包含实际loopback HTTP/WebSocket与synthetic预测；任务切换重建上下文，动作严格单步/完整/有限，raw_shape校验与具体模型错误传递已修复。未部署或验证工作站G0.5物理执行，旧缺夹爪失败不改为通过；见[修复报告](../../reports/G05_REPAIR_20261023.md)。
