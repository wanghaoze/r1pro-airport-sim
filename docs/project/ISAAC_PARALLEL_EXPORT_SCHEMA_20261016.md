# Parallel Pick/Place export interface (2026-10-16)

Entry: `scripts/export_isaac_parallel_pickplace.py --run OUT --receipt ACTUAL_ENGINE_EXIT --parent-splits PARENT_SPLIT_JSON`.

This exports only independently audited complete physical Pick/Place pairs. It does not run simulation or training, relabel failures, or fabricate per-room process receipts. A normally closed engine can contain failed rooms; a shared nonzero/absent actual process exit is rejected. Parent mapping is an immutable object `{parent_scene_id: "train"|"val"|"test"}` from the original source registry. A train-only run remains train-only, `three_split_ready=false`.

`OUT/rooms/room_NNN/` uses existing fixed Pick/Place schema: result.json, native_trace.npz, native_steps.jsonl, native_mapping.json, visual_translation.json, place_initial_state.json, initial_base_station.json, and four original-camera MP4s. Result requires passed, video_demo_complete, model_executed=false, training_eligible=false (legacy benchmark status, exporter separately qualifies), actions with exact Pick/Place prompt/start/end, native_encoders with actual encoder returncode/path, case seed/parent_scene_id/parent_split/fixed_base_world/initial_base_world and motion. Exact collision footprint runs retain their vertex/mapping evidence. The reused audit checks actual physical endpoint forces/opposed long edges, release gap, stable support, existing boundary, 60-frame core duration and all native substeps.

Trace requires N controls and N+1 states/time; raw_action/action has19 channels, submitted_control[N,25,C], tray_pose[N+1,T,7], finger_contact_force[N,25,T,2], table_force[N,25,T], long_edge_sign and boundary_ok[N+1,T]. The full source includes preparation and fixes base command throughout. Place start must exactly equal Pick end with identical stored state and no reset. Per-room N may differ when rooms finish asynchronously.

Shared receipt path is supplied directly to backward-compatible `audit(case, receipt_path=...)`; no synthetic room exit files are created. `actual_child_wait=true` and returncode0 are mandatory. Every room encoder must also have actual returncode0; independent ffprobe must match N frames at20Hz. Failed room exports are isolated and retained in catalog; they cannot enter frozen batch manifests.

The engine writes `OUT/global_overview.mp4` from the same world render at each global frame and `global_overview.json` containing path, actual encoder returncode, frames, fps20, global_start_frame0, shared_world_render=true. Exporter verifies ffprobe and SHA. It never pads/trims/re-times room clips to pretend synchronous rendering. Existing `benchmark_summary.json` is copied as explicitly producer timing, including its SHA; export duration is reported separately, not called physics throughput.

Outputs: dataset/{pick_up_the_tray,place_the_tray}/{split}/room_NNN with four videos, aligned trajectory and immutable segment; dataset/batches/room_NNN/manifest.json; dataset_catalog.json; benchmark_export_summary.json; dataset_viewer.html; per-room viewer.html; VIDEO_PATHS.txt (one actual video path/line). Video and trajectory remain on server.

Validation: local nonbase pytest tests/test_isaac_parallel_export.py — 7 passed; py_compile passed. These are export-contract tests, not native physics or actual parallel throughput evidence. Server end-to-end export remains pending actual engine output.


## 实际部署与双卡证据（2026-10-16）
4房间code_v60验证已完整通过4/4、8片段；run isaacsim_parallel_live_20261016_v2/native，actualexit0和dataset_catalog闭合。并非32房间结果。32房间code_v61 run_v3已启动，机器人及托盘public/native tensor路径顺序均实查匹配，初始32位姿不重复。

当前32候选继承旧已预检可达池；属于小范围多姿态，不声称大角度调盘泛化。4房间验证与32生产有重叠种子，不能合并计为36个不同初态；生产版本独立冻结、不将旧串行同源变体重复计入独特覆盖。

双GPU按RenderProduct uint[] deviceIds轮流分配；官方接口说明：https://docs.isaacsim.omniverse.nvidia.com/latest/py/source/extensions/isaacsim.core.rendering_manager/docs/index.html 。已采样实际进程3813001 GPU1 SM20%、16%、14%而非仅显存上下文，GPU0承担物理及部分渲染，pmon原文在run_v3/gpu_activity_samples.jsonl。不声称物理跨两GPU或两卡负载相等。
