# 交接脚本与配置索引

由 `scripts/build_handoff_catalog.py` 静态读取源码生成；不会 import 脚本、调用 `--help` 或启动任务。

共 **260 个入口/辅助脚本**、**132 个 configs 配置文件**。机器可读参数/默认值/来源 SHA 见 [script_catalog.json](script_catalog.json)。

操作顺序见 [交接 README](README.md)。本索引包含历史诊断；有文件不等于支持当前任务，也不等于已实测成功。

连接方式统一为 `ssh michelle@xinmatrix` 或 `ssh michelle@100.104.0.108`。索引只收录本次交接适用的执行入口，不收录机器专用的远程访问包装器；监控直接在服务器运行。

`runs/`、服务器 `releases/` 内的冻结副本/一次性 bootstrap、third_party/vendor 不重复计入；其部署身份见 README 和服务器快照。不要把旧运行目录中的脚本直接当新任务入口。

参数取自 AST 调用点，可能属于不同子命令或辅助函数；请按源码上下文使用，不要把一行列出的所有参数组合运行。Shell 参数见源码；“无 argparse”不是无参数，更不表示只读。尤其诊断脚本可能在模块顶层直接执行，不能批量运行 `--help`。

更新：`python scripts/build_handoff_catalog.py --write`；检查：`python scripts/build_handoff_catalog.py --check`。

## Isaac 原生仿真、数据与训练

| 脚本 | 用途（源码说明） | CLI 线索 |
|---|---|---|
| [scripts/audit_isaacsim_fast_pickplace.py](../../scripts/audit_isaacsim_fast_pickplace.py) | Independent read-only check of physical timing, release and video closure. | 参数：--case, --output |
| [scripts/audit_isaacsim_three_tray_demo.py](../../scripts/audit_isaacsim_three_tray_demo.py) | Independent read-only closure audit of a completed native three-tray demo. | 参数：--case, --registry, --output |
| [scripts/bootstrap_isaac_three_tray_demo.py](../../scripts/bootstrap_isaac_three_tray_demo.py) | Resume a real controller regression into recorded demo and existing pipeline. | 参数：--config |
| [scripts/check_isaacsim_clip_seek.py](../../scripts/check_isaacsim_clip_seek.py) | Compare accurate input seeks with decoded frame indices; no task labels. | 参数：--case, --output |
| [scripts/collect_isaac_fixed_pickplace.py](../../scripts/collect_isaac_fixed_pickplace.py) | Separate fixed-base Pick/Place data from physically continuous native pairs. | 参数：--config |
| [scripts/expand_isaacsim_three_tray.py](../../scripts/expand_isaacsim_three_tray.py) | Qualified native variants -> version-2 action3 data -> queued independent BC. | 参数：--config |
| [scripts/export_isaac_episode_preview.py](../../scripts/export_isaac_episode_preview.py) | Export only a real fully-qualified source; this is not a training batch. | 参数：--episode, --registry, --output |
| [scripts/export_isaac_parallel_pickplace.py](../../scripts/export_isaac_parallel_pickplace.py) | Qualify per-room native pairs using one real engine exit receipt. | 参数：--run, --receipt, --parent-splits |
| [scripts/finalize_isaac_fast_pickplace.py](../../scripts/finalize_isaac_fast_pickplace.py) | Audit closed native cases and concatenate original-speed action previews. | 参数：--run |
| [scripts/guard_isaacsim_expansion.py](../../scripts/guard_isaacsim_expansion.py) | Detached bounded recovery for the native variant producer, not physics retries. | 参数：--config |
| [scripts/guard_isaacsim_three_tray_task.py](../../scripts/guard_isaacsim_three_tray_task.py) | Outer guard: bounded coordinator recovery, never retries physical failures. | 参数：--config, --adopt |
| [scripts/isaac_mobile.py](../../scripts/isaac_mobile.py) | Native mobile19 / PhysX articulation + world D6 drive routing. | 无静态 argparse；先读源码 |
| [scripts/isaacsim_base_drives.py](../../scripts/isaacsim_base_drives.py) | Restore missing D6 drive instances from named source position actuators. | 无静态 argparse；先读源码 |
| [scripts/isaacsim_control_preflight.py](../../scripts/isaacsim_control_preflight.py) | Native PhysX control calibration probe, never a task or training source. | 参数：--usd, --xml, --output, --native-coat, --coat-name, --restore-source-base-drives, --kinematic-audit |
| [scripts/isaacsim_deformable_coat.py](../../scripts/isaacsim_deformable_coat.py) | Translate the source flex surface to a native PhysX surface-deformable body. | 无静态 argparse；先读源码 |
| [scripts/isaacsim_kinematic_audit.py](../../scripts/isaacsim_kinematic_audit.py) | Compare measured native body-relative FK with the source joint convention. | 无静态 argparse；先读源码 |
| [scripts/isaacsim_mass_properties.py](../../scripts/isaacsim_mass_properties.py) | Restore compiled source mass/COM/principal inertia on a NEW native asset. | 参数：--usd, --xml, --output |
| [scripts/isaacsim_materials.py](../../scripts/isaacsim_materials.py) | Restore nominal source sliding friction in a NEW PhysX USD layer. | 参数：--usd, --xml, --output |
| [scripts/isaacsim_reference_episode.py](../../scripts/isaacsim_reference_episode.py) | Re-execute a registered historical expert reference in native PhysX. | 参数：--root, --output, --frames |
| [scripts/isaacsim_scene_smoke.py](../../scripts/isaacsim_scene_smoke.py) | Native Isaac Sim scene import audit; never labels import as task success. | 参数：--xml, --output, --steps, --usd, --capture |
| [scripts/isaacsim_stage_runner.py](../../scripts/isaacsim_stage_runner.py) | Independent actual wait receipt for one native-workflow child. | 参数：--job |
| [scripts/prepare_isaac_parallel_candidates.py](../../scripts/prepare_isaac_parallel_candidates.py) | CPU-only, finite private path registry; never marks physical data ready. | 参数：--output, --seed；含服务器固定路径 |
| [scripts/prepare_isaac_reachable_pickplace.py](../../scripts/prepare_isaac_reachable_pickplace.py) | Freeze a bounded direct-reachable candidate batch for native collection. | 参数：--template, --code, --run, --seed, --target-pairs, --max-candidates, --precheck-python, --base |
| [scripts/prepare_isaacsim_dataset.py](../../scripts/prepare_isaacsim_dataset.py) | Validate native completed sources and freeze their three-action index. | 参数：--registry, --episodes, --output, --mode, --manifest |
| [scripts/prepare_isaacsim_three_tray.py](../../scripts/prepare_isaacsim_three_tray.py) | Discover the legacy three-tray branch and stage new loaded-handover assets. | 参数：--legacy-root, --output, --payload-template |
| [scripts/prestage_isaacsim_three_tray.py](../../scripts/prestage_isaacsim_three_tray.py) | Prepare registered held-out assets while a native demo runs independently. | 参数：--config, --code-dir, --output |
| [scripts/probe_isaac_parallel_collection.py](../../scripts/probe_isaac_parallel_collection.py) | One-engine grid integration probe, never a qualified training collection. | 参数：--config |
| [scripts/probe_isaacsim_flush_path.py](../../scripts/probe_isaacsim_flush_path.py) | Private kinematic regression at an actual failed native state; no physics. | 参数：--scene-root, --case, --output, --frame, --shift-y, --tray, --handover, --mode |
| [scripts/probe_isaacsim_pad_station.py](../../scripts/probe_isaacsim_pad_station.py) | Private geometry-only pad-normal station check; never steps physics. | 参数：--project, --code, --output, --aligned-legacy, --case-config |
| [scripts/restore_bc_after_isaac_parallel_probe.py](../../scripts/restore_bc_after_isaac_parallel_probe.py) | Restore the unchanged original BC between exclusive probe and collection. | 参数：--config |
| [scripts/resume_isaacsim_bc_after_video.py](../../scripts/resume_isaacsim_bc_after_video.py) | Resume unchanged frozen Isaac BC only after an explicit native video review. | 参数：--config |
| [scripts/run_isaac_parallel_pickplace.py](../../scripts/run_isaac_parallel_pickplace.py) | Independent feedback teachers in one shared PhysX clock; no command replay. | 参数：--config |
| [scripts/run_isaacsim_fast_pickplace.py](../../scripts/run_isaacsim_fast_pickplace.py) | Native, original-speed three-second Pick/Place visual benchmark. | 参数：--config |
| [scripts/run_isaacsim_three_tray_task.py](../../scripts/run_isaacsim_three_tray_task.py) | Actual native three-tray expert episode; success comes from measured observer. | 参数：--scene-root, --output, --seed, --episode-id, --place-flush-reserve-m, --no-video-diagnostic |
| [scripts/serve_isaacsim_media.py](../../scripts/serve_isaacsim_media.py) | Read-only, single-instance byte-range media service on the existing tailnet. | 参数：--root, --state-dir, --bind, --port |
| [scripts/supervise_isaac_parallel_pickplace.py](../../scripts/supervise_isaac_parallel_pickplace.py) | Single-instance detached feedback collection and qualified export pipeline. | 参数：--config |
| [scripts/supervise_isaac_parallel_probe.py](../../scripts/supervise_isaac_parallel_probe.py) | Bounded, single-instance integration staircase; not a data producer. | 参数：--config |
| [scripts/supervise_isaac_pickplace300.py](../../scripts/supervise_isaac_pickplace300.py) | Bounded, detached 32-room production. Does not train or alter physical gates. | 参数：--config, --guard |
| [scripts/supervise_isaacsim_fast_pickplace.py](../../scripts/supervise_isaacsim_fast_pickplace.py) | Detached bounded multi-pose fast video benchmark; never feeds BC implicitly. | 参数：--config |
| [scripts/supervise_isaacsim_three_tray_assets.py](../../scripts/supervise_isaacsim_three_tray_assets.py) | Detached, single-instance asset migration stages; not a task/train supervisor. | 参数：--run, --project, --legacy-root, --payload-template, --isaac-python, --source-python |
| [scripts/supervise_isaacsim_three_tray_task.py](../../scripts/supervise_isaacsim_three_tray_task.py) | Detached native task -> immutable action3 corpus -> BC supervisor. | 参数：--config |
| [scripts/train_pi05_isaac_three_tray.py](../../scripts/train_pi05_isaac_three_tray.py) | BC on frozen, qualified native three-tray sources; no policy execution here. | 参数：--run, --mode, --stop；含服务器固定路径 |

## 单托盘场景、控制与数据

| 脚本 | 用途（源码说明） | CLI 线索 |
|---|---|---|
| [scripts/build_single_tray_lab_blender.py](../../scripts/build_single_tray_lab_blender.py) | Run with Blender 5.2 --background --python this.py -- --output DIR. | 参数：--output, --render, --render-width |
| [scripts/collect_three_table_campaign.py](../../scripts/collect_three_table_campaign.py) | Plan or explicitly collect new complete three-table sources, never train. | 参数：--selection, --inventory, --parent-manifest, --split-registry, --output, --scene-options, --execute, --recover, --release, --sim-python, --config, --push-reference-scene, --workers |
| [scripts/collect_three_table_full_source.py](../../scripts/collect_three_table_full_source.py) | Collect a fresh observed three-table task; no training/model launch. | 参数：--scene, --config, --push-reference-scene, --confirmation-rule, --no-axis-feedback, --output |
| [scripts/export_single_tray_actions.py](../../scripts/export_single_tray_actions.py) | Export the new single-tray three-action demonstrations; never starts training. | 参数：--records, --destination, --repo-id, --split |
| [scripts/export_three_table_single_tray_actions.py](../../scripts/export_three_table_single_tray_actions.py) | New mobile/opposed three-table dataset export; no training or relabeling. | 参数：--records, --destination, --repo-id, --split |
| [scripts/generate_single_tray_lab.py](../../scripts/generate_single_tray_lab.py) | Generate a new single-tray photo-reference scene without touching old collections. | 参数：--output, --seed, --split, --robot-x, --tray-y, --loaded, --payloads, --physics-only |
| [scripts/generate_three_table_single_tray.py](../../scripts/generate_three_table_single_tray.py) | Generate a fresh registered three-table/one-tray variant; no success claim. | 参数：--output, --seed, --parent-scene, --parent-manifest, --split-registry, --source-base-distance, --target-base-standoff, --target-tray-x, --target-base-yaw, --target-yaw-offset |
| [scripts/guard_three_table_workflow.py](../../scripts/guard_three_table_workflow.py) | Run a bounded outer guardian of an explicitly reviewed workflow process. | 参数：--options |
| [scripts/plan_three_table_reachable_initial_poses.py](../../scripts/plan_three_table_reachable_initial_poses.py) | Explicit bounded random-initial-pose qualification; never starts physics/training. | 参数：--options |
| [scripts/prepare_single_tray_evaluation_protocol.py](../../scripts/prepare_single_tray_evaluation_protocol.py) | CPU prepare by default. New formal scenes require --generate and full success. | 参数：--training-seeds, --success-case, --output, --generate |
| [scripts/probe_single_tray_front_workspace.py](../../scripts/probe_single_tray_front_workspace.py) | Private static workspace evidence, never a task-success or live-control test. | 参数：--output, --robot-xs, --tray-ys, --lateral-offsets, --seeds, --separations |
| [scripts/refine_single_tray_lab_robot_visual.py](../../scripts/refine_single_tray_lab_robot_visual.py) | Blender-only visual face partition; original geometry/collision/inertia untouched. | 参数：--output, --render |
| [scripts/render_single_tray_lab.py](../../scripts/render_single_tray_lab.py) | Render a new raw2 replay; failed prefixes remain nontraining evidence. | 参数：--case, --output, --max-frames, --expected-profile |
| [scripts/render_three_table_free_run.py](../../scripts/render_three_table_free_run.py) | Diagnostic-only native4 continuous replay; never counts as task evaluation. | 参数：--case, --output, --audit-only |
| [scripts/render_three_table_original_trace.py](../../scripts/render_three_table_original_trace.py) | Native four-camera continuous replay of original raw Trace diagnostics. | 参数：--case, --output, --audit-only |
| [scripts/render_three_table_single_tray.py](../../scripts/render_three_table_single_tray.py) | Render actual mobile three-table source; old one-table traces are rejected. | 委托：scripts.render_single_tray_lab |
| [scripts/repair_three_table_source_qualification.py](../../scripts/repair_three_table_source_qualification.py) | Additive qualification of closed physically complete sources; no physics rerun. | 参数：--campaign, --output, --projection-cache |
| [scripts/run_single_tray_lab.py](../../scripts/run_single_tray_lab.py) | Generate a new, recorded physical single-tray candidate; never train failures. | 参数：--output, --seed, --robot-x, --robot-y, --tray-y, --split, --rigid-coat, --grasp-half-separation, --lift-clearance, --gripper-kp, --arm-kp, --noslip-iterations, --friction-impratio, --lift-stop-margin, --place-release-clearance, --follow-tray-pose, --soft-payload-penetration, --grasp-mode, --rim-height, --held-tracking-tolerance, --push-command-reference, --push-reference-lead, --hard-penetration-limit, --place-inboard-slow-recipe, --push-vertical-relief, --push-table-contact-grace-frames, --push-lead-frame, --push-right-outward-release, --handover-left-tangent |
| [scripts/run_single_tray_lab_campaign.py](../../scripts/run_single_tray_lab_campaign.py) | Durable physical candidate campaign; preserve every failure, never relabel old data. | 参数：--output, --workers, --candidates |
| [scripts/run_three_table_full_candidate.py](../../scripts/run_three_table_full_candidate.py) | Continuous old empty primitives + registered passengers + loaded controller. | 参数：--scene, --config, --push-reference-scene, --output, --transient-boundary-extra, --no-axis-feedback |
| [scripts/run_three_table_owned_command.py](../../scripts/run_three_table_owned_command.py) | Run one explicit command with durable actual PID and exit evidence. | 参数：--options |
| [scripts/run_three_table_single_tray.py](../../scripts/run_three_table_single_tray.py) | First continuous legacy opposed-pick/place diagnostic; not training data. | 参数：--scene, --output, --grasp-stagger, --approximate-planning, --config |
| [scripts/summarize_single_tray_contact.py](../../scripts/summarize_single_tray_contact.py) | Audit complete-task counts and the new single-tray 3mm/5mm contact gate. | 参数：--case, --output |
| [scripts/supervise_three_action_expansion.py](../../scripts/supervise_three_action_expansion.py) | Independent, bounded source expansion; no training or task-rule changes. | 参数：--options, --guardian |
| [scripts/supervise_three_table_free_run.py](../../scripts/supervise_three_table_free_run.py) | Independent diagnostic-only model -> timed run -> native media pipeline. | 参数：--options |
| [scripts/supervise_three_table_workflow.py](../../scripts/supervise_three_table_workflow.py) | Detach externally once; this durable workflow waits for actual sources. | 参数：--options, --recover |

## 历史控制实验、诊断与审计

| 脚本 | 用途（源码说明） | CLI 线索 |
|---|---|---|
| [scripts/analyze_contact_substeps.py](../../scripts/analyze_contact_substeps.py) | Audit contact chatter by exact private replay of recorded raw/1 controls. | 参数：--root, --cases, --output-directory, --estimator |
| [scripts/analyze_contact_substeps_raw2.py](../../scripts/analyze_contact_substeps_raw2.py) | Audit contact chatter by exact private replay of recorded raw/1 or raw/2 controls. | 参数：--root, --cases, --output-directory, --estimator |
| [scripts/analyze_retained_support_structure.py](../../scripts/analyze_retained_support_structure.py) | Read existing private force CSVs; no simulation or collection writes. | 无静态 argparse；先读源码 |
| [scripts/analyze_support_forces.py](../../scripts/analyze_support_forces.py) | Read-only force reconstruction from complete frozen MuJoCo trace states. | 参数：--root, --cases, --output-directory, --estimator, --compare |
| [scripts/audit_case60_sources.py](../../scripts/audit_case60_sources.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/audit_case60_third_stage.py](../../scripts/audit_case60_third_stage.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/audit_case60_v27_alignment.py](../../scripts/audit_case60_v27_alignment.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/audit_environment_guards.py](../../scripts/audit_environment_guards.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/audit_failures.py](../../scripts/audit_failures.py) | Read-only failure audit. Never changes a collection or labels. | 参数：--root, --output |
| [scripts/audit_fixed_primitives.py](../../scripts/audit_fixed_primitives.py) | Audit measured primitive timings; does not promote failed episodes. | 参数：--attempts, --output |
| [scripts/audit_handoff_causes.py](../../scripts/audit_handoff_causes.py) | Read-only nested failure audit using small result/event JSON, never HDF5. | 参数：--root, --output |
| [scripts/audit_historical_regression.py](../../scripts/audit_historical_regression.py) | Read-only historical baseline provenance and regression audit. | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/audit_load_transfer.py](../../scripts/audit_load_transfer.py) | Read-only command/measurement geometry around an existing push handoff. | 参数：--release, --collection, --case, --push-index, --output |
| [scripts/audit_normalized_scene.py](../../scripts/audit_normalized_scene.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/audit_regression_first_divergence.py](../../scripts/audit_regression_first_divergence.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/audit_yaw_feedback_scope.py](../../scripts/audit_yaw_feedback_scope.py) | Read-only stage audit of completed production feedback experiments. | 参数：--root, --output |
| [scripts/compare_force_diagnostics.py](../../scripts/compare_force_diagnostics.py) | Compare all variants over the same elapsed interval, never full-run averages. | 参数：--root, --output |
| [scripts/diagnose_additive_yaw.py](../../scripts/diagnose_additive_yaw.py) | Bounded private push rollout from frozen evidence; never an episode result. | 参数：--controller, --source, --case, --handoff-index, --output, --estimator, --command-reference, --preload-scale, --timestep, --arm-kv-scale, --cartesian-withdraw-middle, --full-push-operation, --push-compensation, --yaw-compensation-deg, --yaw-feedback-suffix, --force-feedback-suffix, --force-feedback-zero-gain, --place-retained-side, --free-retreat-rise, --withdraw-middle-progress, --duration-rejection-baseline, --planning-only, --yaw-backtrack-once, --yaw-normal-lift-once, --yaw-normal-lift-m |
| [scripts/diagnose_additive_yaw_certified.py](../../scripts/diagnose_additive_yaw_certified.py) | Bounded private push rollout from frozen evidence; never an episode result. | 参数：--controller, --source, --case, --handoff-index, --output, --estimator, --command-reference, --preload-scale, --timestep, --arm-kv-scale, --cartesian-withdraw-middle, --full-push-operation, --push-compensation, --yaw-compensation-deg, --yaw-feedback-suffix, --force-feedback-suffix, --force-feedback-zero-gain, --place-retained-side, --free-retreat-rise, --withdraw-middle-progress, --duration-rejection-baseline, --planning-only, --yaw-backtrack-once, --yaw-normal-lift-once, --yaw-normal-lift-m |
| [scripts/diagnose_alignment_reference.py](../../scripts/diagnose_alignment_reference.py) | Bounded private push rollout from frozen evidence; never an episode result. | 参数：--preserve-alignment-reference, --controller, --source, --case, --handoff-index, --output, --estimator, --command-reference, --preload-scale, --timestep, --arm-kv-scale, --cartesian-withdraw-middle, --full-push-operation, --push-compensation, --yaw-compensation-deg, --yaw-feedback-suffix, --force-feedback-suffix, --force-feedback-zero-gain, --place-retained-side, --free-retreat-rise, --withdraw-middle-progress, --duration-rejection-baseline, --planning-only, --yaw-backtrack-once, --yaw-normal-lift-once, --yaw-normal-lift-m |
| [scripts/diagnose_case60_full_open.py](../../scripts/diagnose_case60_full_open.py) | Bounded private push rollout from frozen evidence; never an episode result. | 参数：--controller, --source, --case, --handoff-index, --output, --estimator, --command-reference, --preload-scale, --timestep, --arm-kv-scale, --cartesian-withdraw-middle, --full-push-operation, --push-compensation, --yaw-compensation-deg, --yaw-feedback-suffix, --force-feedback-suffix, --force-feedback-zero-gain, --place-retained-side, --combined-full-open, --free-retreat-rise, --withdraw-middle-progress, --duration-rejection-baseline, --planning-only, --yaw-backtrack-once, --yaw-normal-lift-once, --yaw-normal-lift-m |
| [scripts/diagnose_fresh_case60_shortcut.py](../../scripts/diagnose_fresh_case60_shortcut.py) | Fresh frozen-v27 case60 episode, selected preflight and one worker only. | 参数：--release, --output, --reference, --confirmed-ready |
| [scripts/diagnose_late_suffix_reserve.py](../../scripts/diagnose_late_suffix_reserve.py) | Bounded private push rollout from frozen evidence; never an episode result. | 参数：--controller, --source, --case, --handoff-index, --output, --estimator, --command-reference, --preload-scale, --timestep, --arm-kv-scale, --cartesian-withdraw-middle, --full-push-operation, --push-compensation, --yaw-compensation-deg, --yaw-feedback-suffix, --force-feedback-suffix, --force-feedback-zero-gain, --place-retained-side, --free-retreat-rise, --withdraw-middle-progress, --duration-rejection-baseline, --planning-only, --yaw-backtrack-once, --yaw-normal-lift-once, --yaw-normal-lift-m |
| [scripts/diagnose_original_contact_kinematics.py](../../scripts/diagnose_original_contact_kinematics.py) | Bounded private push rollout from frozen evidence; never an episode result. | 参数：--controller, --source, --case, --handoff-index, --output, --estimator, --command-reference, --preload-scale, --timestep, --arm-kv-scale, --cartesian-withdraw-middle, --full-push-operation, --push-compensation, --yaw-compensation-deg, --yaw-feedback-suffix, --force-feedback-suffix, --force-feedback-zero-gain, --place-retained-side, --free-retreat-rise, --withdraw-middle-progress, --duration-rejection-baseline, --planning-only, --yaw-backtrack-once, --yaw-normal-lift-once, --yaw-normal-lift-m |
| [scripts/diagnose_production_additive.py](../../scripts/diagnose_production_additive.py) | Bounded private push rollout from frozen evidence; never an episode result. | 参数：--controller, --source, --case, --handoff-index, --output, --estimator, --command-reference, --preload-scale, --timestep, --arm-kv-scale, --cartesian-withdraw-middle, --full-push-operation, --push-compensation, --yaw-compensation-deg, --yaw-feedback-suffix, --force-feedback-suffix, --force-feedback-zero-gain, --place-retained-side, --free-retreat-rise, --withdraw-middle-progress, --duration-rejection-baseline, --planning-only, --yaw-backtrack-once, --yaw-normal-lift-once, --yaw-normal-lift-m |
| [scripts/diagnose_production_withdraw_feedback.py](../../scripts/diagnose_production_withdraw_feedback.py) | Bounded private push rollout from frozen evidence; never an episode result. | 参数：--controller, --source, --case, --handoff-index, --output, --estimator, --command-reference, --preload-scale, --timestep, --arm-kv-scale, --cartesian-withdraw-middle, --full-push-operation, --push-compensation, --yaw-compensation-deg, --yaw-feedback-suffix, --force-feedback-suffix, --force-feedback-zero-gain, --place-retained-side, --free-retreat-rise, --withdraw-middle-progress, --duration-rejection-baseline, --planning-only, --yaw-backtrack-once, --yaw-normal-lift-once, --yaw-normal-lift-m |
| [scripts/diagnose_push_duration.py](../../scripts/diagnose_push_duration.py) | Read-only constructor audit of original zero-motion push path durations. | 无静态 argparse；先读源码 |
| [scripts/diagnose_push_from_trace.py](../../scripts/diagnose_push_from_trace.py) | Bounded private push rollout from frozen evidence; never an episode result. | 参数：--controller, --source, --case, --handoff-index, --output, --estimator, --command-reference, --preload-scale, --timestep, --arm-kv-scale, --cartesian-withdraw-middle, --full-push-operation, --push-compensation, --yaw-compensation-deg, --yaw-feedback-suffix, --force-feedback-suffix, --force-feedback-zero-gain, --place-retained-side, --free-retreat-rise, --withdraw-middle-progress, --duration-rejection-baseline, --planning-only, --yaw-backtrack-once, --yaw-normal-lift-once, --yaw-normal-lift-m |
| [scripts/diagnose_reference_rotation.py](../../scripts/diagnose_reference_rotation.py) | Bounded private push rollout from frozen evidence; never an episode result. | 参数：--controller, --source, --case, --handoff-index, --output, --estimator, --command-reference, --preload-scale, --timestep, --arm-kv-scale, --cartesian-withdraw-middle, --full-push-operation, --push-compensation, --yaw-compensation-deg, --yaw-feedback-suffix, --force-feedback-suffix, --force-feedback-zero-gain, --place-retained-side, --free-retreat-rise, --withdraw-middle-progress, --duration-rejection-baseline, --planning-only, --yaw-backtrack-once, --yaw-normal-lift-once, --yaw-normal-lift-m |
| [scripts/diagnose_v19_camera_events.py](../../scripts/diagnose_v19_camera_events.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/diagnose_v19_camera_prediction.py](../../scripts/diagnose_v19_camera_prediction.py) | Read frozen integration states; terminal replay uses recorded per-substep controls. | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/diagnose_v19_camera_states.py](../../scripts/diagnose_v19_camera_states.py) | Read frozen integration states; terminal replay uses recorded per-substep controls. | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/diagnose_v19_camera_yaw.py](../../scripts/diagnose_v19_camera_yaw.py) | Read frozen integration states; terminal replay uses recorded per-substep controls. | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/diagnose_v28_buffer_yaw.py](../../scripts/diagnose_v28_buffer_yaw.py) | Bounded private push rollout from frozen evidence; never an episode result. | 参数：--controller, --source, --case, --handoff-index, --output, --estimator, --command-reference, --preload-scale, --timestep, --arm-kv-scale, --cartesian-withdraw-middle, --full-push-operation, --push-compensation, --yaw-compensation-deg, --yaw-feedback-suffix, --force-feedback-suffix, --force-feedback-zero-gain, --place-retained-side, --free-retreat-rise, --withdraw-middle-progress, --duration-rejection-baseline, --planning-only, --temporary-buffer-yaw, --yaw-backtrack-once, --yaw-normal-lift-once, --yaw-normal-lift-m |
| [scripts/diagnose_v28_preview_headroom_fresh.py](../../scripts/diagnose_v28_preview_headroom_fresh.py) | Authorized frozen v28 single-field headroom ablation, two fresh scenes. | 参数：--release, --output, --archive-sha |
| [scripts/diagnose_withdraw_feedback_runner.py](../../scripts/diagnose_withdraw_feedback_runner.py) | Bounded private push rollout from frozen evidence; never an episode result. | 参数：--controller, --source, --case, --handoff-index, --output, --estimator, --command-reference, --preload-scale, --timestep, --arm-kv-scale, --cartesian-withdraw-middle, --full-push-operation, --push-compensation, --yaw-compensation-deg, --yaw-feedback-suffix, --force-feedback-suffix, --force-feedback-zero-gain, --place-retained-side, --free-retreat-rise, --withdraw-middle-progress, --duration-rejection-baseline, --planning-only, --yaw-backtrack-once, --yaw-normal-lift-once, --yaw-normal-lift-m |
| [scripts/diagnose_withdraw_merge.py](../../scripts/diagnose_withdraw_merge.py) | One private withdrawal structure candidate; no production file edits. | 无静态 argparse；先读源码 |
| [scripts/diagnose_withdraw_merge_feedback.py](../../scripts/diagnose_withdraw_merge_feedback.py) | One private withdrawal structure candidate; no production file edits. | 无静态 argparse；先读源码 |
| [scripts/diagnostic_additive_certificate.py](../../scripts/diagnostic_additive_certificate.py) | Strict conservative Bernstein certificates for the SAME additive candidate. | 无静态 argparse；先读源码 |
| [scripts/diagnostic_additive_suffix.py](../../scripts/diagnostic_additive_suffix.py) | Private additive yaw correction over an existing validated blended curve. | 无静态 argparse；先读源码 |
| [scripts/diagnostic_contact_kinematics.py](../../scripts/diagnostic_contact_kinematics.py) | Read-only Jacobian point velocities and contact wrenches; private diagnostics. | 无静态 argparse；先读源码 |
| [scripts/diagnostic_force_suffix.py](../../scripts/diagnostic_force_suffix.py) | Private bounded real-contact force feedback; no production imports this file. | 无静态 argparse；先读源码 |
| [scripts/diagnostic_reference_rotation.py](../../scripts/diagnostic_reference_rotation.py) | Read the original planned push curve only; stop before any physical execution. | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/diagnostic_suffix_reserve.py](../../scripts/diagnostic_suffix_reserve.py) | One private C2 late-suffix budget allocation; no production import. | 无静态 argparse；先读源码 |
| [scripts/diagnostic_yaw_additive.py](../../scripts/diagnostic_yaw_additive.py) | Private one-step yaw amplitude backtracking, retaining every original guard. | 无静态 argparse；先读源码 |
| [scripts/diagnostic_yaw_additive_certified.py](../../scripts/diagnostic_yaw_additive_certified.py) | Private one-step yaw amplitude backtracking, retaining every original guard. | 无静态 argparse；先读源码 |
| [scripts/diagnostic_yaw_backtrack.py](../../scripts/diagnostic_yaw_backtrack.py) | Private one-step yaw amplitude backtracking, retaining every original guard. | 无静态 argparse；先读源码 |
| [scripts/diagnostic_yaw_suffix.py](../../scripts/diagnostic_yaw_suffix.py) | Private one-shot C2 feedback experiment. Never imported by production control. | 无静态 argparse；先读源码 |
| [scripts/inspect_fresh_case60_shortcut.py](../../scripts/inspect_fresh_case60_shortcut.py) | Read-only completed fresh case60 versus frozen historical/current baselines. | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/inspect_push_verification.py](../../scripts/inspect_push_verification.py) | Read-only release/settling metrics for a frozen final push failure. | 参数：--controller, --root, --output |
| [scripts/inspect_v14_grasp_failures.py](../../scripts/inspect_v14_grasp_failures.py) | Small read-only snapshots of the alternate-rim ablation failures. | 参数：--root, --output |
| [scripts/inspect_v21_case6_direct_geometry.py](../../scripts/inspect_v21_case6_direct_geometry.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/inspect_v21_case6_release.py](../../scripts/inspect_v21_case6_release.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/inspect_v21_other_rims.py](../../scripts/inspect_v21_other_rims.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/inspect_withdraw_geometry.py](../../scripts/inspect_withdraw_geometry.py) | Read-only final reserved footprint and gap audit. | 无静态 argparse；先读源码 |
| [scripts/probe_airport_motion.py](../../scripts/probe_airport_motion.py) | Isolated diagnostic attempt: never publishes a training dataset. | 参数：--source-root, --scene-id, --config, --output |
| [scripts/probe_alternate_rims.py](../../scripts/probe_alternate_rims.py) | Read-only failed-state qualification of both physical rim pairs. | 参数：--release, --module, --output, --max-probes |
| [scripts/probe_constant_push_height.py](../../scripts/probe_constant_push_height.py) | Private kinematic-only command-continuous retained-hand push candidate. | 参数：--release, --output |
| [scripts/probe_fixed_primitives.py](../../scripts/probe_fixed_primitives.py) | Snapshot-initialized physics FIXTURE, never a training episode or full-task success. | 参数：--source, --scene, --config, --kind, --occurrence, --chain-push, --output |
| [scripts/summarize_command_ablation.py](../../scripts/summarize_command_ablation.py) | Compact read-only completed-result comparison; never infer partial success. | 参数：--root, --groups, --cases, --output |
| [scripts/summarize_yaw_diagnostic.py](../../scripts/summarize_yaw_diagnostic.py) | Read frozen yaw trace and already completed private candidate geometry. | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/test_diagnostic_additive_certificate.py](../../scripts/test_diagnostic_additive_certificate.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码 |
| [scripts/test_diagnostic_additive_suffix.py](../../scripts/test_diagnostic_additive_suffix.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码 |
| [scripts/test_diagnostic_contact_kinematics.py](../../scripts/test_diagnostic_contact_kinematics.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码 |
| [scripts/test_diagnostic_force_suffix.py](../../scripts/test_diagnostic_force_suffix.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 无静态 argparse；先读源码 |
| [scripts/test_diagnostic_yaw_backtrack.py](../../scripts/test_diagnostic_yaw_backtrack.py) | Bounded retry semantics for the private candidate, without physical tuning. | 无静态 argparse；先读源码 |
| [scripts/test_diagnostic_yaw_suffix.py](../../scripts/test_diagnostic_yaw_suffix.py) | Standalone mathematical checks; no MuJoCo controller changes. | 无静态 argparse；先读源码 |

## 只读监测与索引（以脚本实际副作用为准）

| 脚本 | 用途（源码说明） | CLI 线索 |
|---|---|---|
| [scripts/collect_vla_training_status.py](../../scripts/collect_vla_training_status.py) | Read-only metadata snapshot; never starts training or downloads video. | 参数：--data-root, --training-root, --output, --text-output |
| [scripts/maintain_three_table_server_index.py](../../scripts/maintain_three_table_server_index.py) | Read-only run metadata index; never controls jobs or certifies media. | 参数：--root, --output, --once, --current-workflow |
| [scripts/register_video_index_task.ps1](../../scripts/register_video_index_task.ps1) | Shell/PowerShell 入口；参数和副作用见源码。 | 无静态 argparse；先读源码 |
| [scripts/watch_isaac_parallel_collection.py](../../scripts/watch_isaac_parallel_collection.py) | Read actual probe/demo receipts and emit metadata only; never launch jobs. | 参数：--project, --watch, --interval |
| [scripts/watch_isaacsim_episode_preview.py](../../scripts/watch_isaacsim_episode_preview.py) | Independently expose action clips as soon as a full native source closes. | 参数：--config |
| [scripts/watch_pi05_mix50.py](../../scripts/watch_pi05_mix50.py) | Read-only monitor of the frozen 50/50 run; no control or training commands. | 参数：--run, --watch |
| [scripts/watch_pi05_real_only.py](../../scripts/watch_pi05_real_only.py) | Read-only progress monitor for the isolated real-only experiment. | 参数：--run, --watch |
| [scripts/watch_pickplace300_mix.py](../../scripts/watch_pickplace300_mix.py) | Read-only progress for the new 300-pair collection and mixed BC. | 参数：--root, --watch；含服务器固定路径 |
| [scripts/watch_real_sim_transfer.py](../../scripts/watch_real_sim_transfer.py) | Read-only real/sim transfer stage, percent, actual MSE and measured ETA. | 参数：--run, --watch |
| [scripts/watch_three_table_data_version2.py](../../scripts/watch_three_table_data_version2.py) | Start independent dataset v2 export during actual milestone10 model evaluation. | 参数：--options, --training-run, --watch-dir |
| [scripts/watch_vla_comparison.py](../../scripts/watch_vla_comparison.py) | Read-only comparison progress; no model imports and no fabricated ETA. | 参数：--run, --watch, --json |

## 安装、项目维护与旧多托盘基线

| 脚本 | 用途（源码说明） | CLI 线索 |
|---|---|---|
| [r1pro_teleop/airport_agent.py](../../r1pro_teleop/airport_agent.py) | Callable simulation collection agent. Does not impersonate a human or navigate a fixed base. | 子命令：'init', 'run-base-smoke', 'run-arrangement', 'serve', 'status', name；参数：--source, --root, --mobile-base, --root, --scene-ids, --root, --scene-id, --root, --scene-id, --port, --token-file, --root, --root, --scene-ids, --seconds, --action-file |
| [r1pro_teleop/airport_arrange.py](../../r1pro_teleop/airport_arrange.py) | Closed-loop program-generated tray arrangement in simulation only. | 参数：--scene, --output, --only-first |
| [r1pro_teleop/airport_fsm/__main__.py](../../r1pro_teleop/airport_fsm/__main__.py) | python -m r1pro_teleop.airport_fsm --help | 子命令：'prepare', 'preflight', 'generate', 'export', 'report', 'render-diagnostic', name；参数：--manifest, --output, --config, --half-turn-equivalent, --root, --workers, --scene-ids, --root, --workers, --limit, --scene-ids, --root, --shard-size, --action-layout, --repo-prefix, --root, --require-all-exported, --require-all-physics, --require-all-attempted, --root, --scene-id, --attempt, --root, --scene-id, --attempt |
| [r1pro_teleop/airport_scenes.py](../../r1pro_teleop/airport_scenes.py) | Versioned, deterministic airport tray scene generation; no controller changes. | 参数：--output, --template, --seed, --workers, --max-attempts, --smoke-only |
| [r1pro_teleop/airport_service.py](../../r1pro_teleop/airport_service.py) | Airport Quest service: authenticated existing protocol, explicit episode lifecycle. | 参数：--root, --scene-id, --port, --host, --token-file |
| [r1pro_teleop/build_assets.py](../../r1pro_teleop/build_assets.py) | Build compound convex collisions and a dynamic MJCF, preserving source assets. | 参数：--scene-dir, --rebuild-collisions |
| [r1pro_teleop/dataset.py](../../r1pro_teleop/dataset.py) | Validate raw synchronized episodes; export through the official LeRobot API. | 参数：--raw, --output, --repo-id, --include-all, --require-task-checks |
| [r1pro_teleop/experiments/__main__.py](../../r1pro_teleop/experiments/__main__.py) | python -m r1pro_teleop.experiments --help | 子命令：'init', 'worker', 'diagnose', 'assess', 'scene-view', 'launch', 'job', cmd, cmd；参数：--source, --output, request, --source, --output, --root, --record, --root, --trace, --output, --frame, --root, --name, args, request, -- + group, --root, --workers, --repeats, --timeout, --root, --candidates, --run, --checkpoint, --stage, --seed-summary, --space, --generations, --population, --candidate |
| [r1pro_teleop/quality.py](../../r1pro_teleop/quality.py) | Offline data review and conservative tray-task checks; never relabel demonstrations. | 参数：--raw, --output |
| [r1pro_teleop/quest_bridge.py](../../r1pro_teleop/quest_bridge.py) | Forward fresh Oculus Reader APK packets via authenticated HTTP to simulation. | 参数：--server, --token, --serial, --adb, --check-only |
| [r1pro_teleop/quest_relay.py](../../r1pro_teleop/quest_relay.py) | Loopback-only authenticated USB relay for Quest Browser WebXR + video. | 参数：--server, --token-file, --session-file, --output, --port, --airport |
| [r1pro_teleop/replay.py](../../r1pro_teleop/replay.py) | Replay saved actions through physics, compare recorded states, and export a review video. | 参数：--raw, --scene, --output, --no-video |
| [r1pro_teleop/server.py](../../r1pro_teleop/server.py) | HTTP viewer/control service for MuJoCo only. No ROS or hardware outputs. | 参数：--scene, --raw, --host, --port, --token, --certfile, --keyfile |
| [r1pro_teleop/smoke.py](../../r1pro_teleop/smoke.py) | No-headset acceptance checks: physics, contact cavity, rendering and recording. | 参数：--scene, --output, --frames |
| [r1pro_teleop/vla/data_benchmark.py](../../r1pro_teleop/vla/data_benchmark.py) | Small isolated stage timings for native-to-training video conversion. | 参数：--release, --native, --output, --frames, --parallel-candidate |
| [r1pro_teleop/vla/data_lineage.py](../../r1pro_teleop/vla/data_lineage.py) | Read-only source and frame verification for additive BC warm starts. | 参数：--parent-dataset, --child-dataset, --output |
| [r1pro_teleop/vla/data_native_pipeline.py](../../r1pro_teleop/vla/data_native_pipeline.py) | Supervise a new immutable native-video training conversion on the server. | 参数：--base, --release, --collection, --python, --scenes, --tag |
| [r1pro_teleop/vla/data_quality_audit.py](../../r1pro_teleop/vla/data_quality_audit.py) | Read-only skill/qualification coverage audit for a prepared training manifest. | 参数：--manifest, --output, --contact-details |
| [r1pro_teleop/vla/data_skill_coverage.py](../../r1pro_teleop/vla/data_skill_coverage.py) | Full-frame source audit and immutable constituent coverage for skill merges. | 参数：--parent-dataset, --child-dataset, --output |
| [r1pro_teleop/workspace_check.py](../../r1pro_teleop/workspace_check.py) | Headless IK reachability probe; no contacts, task execution, or real robot control. | 参数：--scene, --output |
| [scripts/build_handoff_catalog.py](../../scripts/build_handoff_catalog.py) | Build a static handoff inventory without importing or executing project jobs. | 参数：--write, --check；含服务器固定路径 |
| [scripts/check_parallel_mix_cpu.py](../../scripts/check_parallel_mix_cpu.py) | CPU-only official transform and Observation contract; no model initialization. | 参数：--run |
| [scripts/check_r1pro_runtime.py](../../scripts/check_r1pro_runtime.py) | Record actual Linux GPU/runtime identities and test CUDA plus EGL rendering. | 无静态 argparse；先读源码 |
| [scripts/collect_airport_batches.py](../../scripts/collect_airport_batches.py) | Bounded, resumable generation -> native export -> report, using frozen code. | 参数：--root, --workers, --batch-size, --limit, --gpu |
| [scripts/collect_failure_videos.py](../../scripts/collect_failure_videos.py) | Bounded, resumable native failure evidence rendering and SSH collection. | 子命令：'index', name；参数：--root, --verify-hashes, --root, --scene-id, --attempt, --trial, --wait-existing-seconds, --host, --identity, --remote-project, --remote-script, --remote-python, --release, --run, --variant, --workers, --timeout, --scene-id；含服务器固定路径 |
| [scripts/control_ablation.py](../../scripts/control_ablation.py) | Same-code, same-seed fresh physical ablation; no cross-run state reuse. | 参数：--output, --variants, --config-prefix, --indices, --workers-per-variant, --parallel-variants |
| [scripts/control_regression.py](../../scripts/control_regression.py) | Fresh server control evaluation on the unchanged 400-scene source and split. | 参数：--output, --config, --workers, --all, --indices |
| [scripts/deploy_experiments.py](../../scripts/deploy_experiments.py) | Server-side fresh release deployment; invoke with a non-base Conda Python. | 参数：--archive, --asset-release, --destination |
| [scripts/experiment_server_smoke.py](../../scripts/experiment_server_smoke.py) | Bounded server smoke: core tests precede this script; always writes status/evidence. | 参数：--source, --output, --workers |
| [scripts/export_live_inference_video.py](../../scripts/export_live_inference_video.py) | Export an annotated wall-clock diagnostic from native frames; never hide waits. | 参数：--run |
| [scripts/export_project_interactions.py](../../scripts/export_project_interactions.py) | Export project conversation messages from local logs, never model reasoning/tools. | 参数：--source-root, --destination, --thread |
| [scripts/export_scene_studio_offline.py](../../scripts/export_scene_studio_offline.py) | Reproducible source/runtime export, excluding credentials, data and weights. | 无静态 argparse；先读源码 |
| [scripts/generate_airport_scenes.py](../../scripts/generate_airport_scenes.py) | 未提供模块说明；按文件名分类，运行前阅读源码。 | 委托：r1pro_teleop.airport_scenes |
| [scripts/guard_parallel_real_mix.py](../../scripts/guard_parallel_real_mix.py) | Bounded supervisor recovery with independent actual wait and single instance. | 参数：--config |
| [scripts/native32_expansion_pipeline.py](../../scripts/native32_expansion_pipeline.py) | Two independent native replay workers, immutable source/reuse, no training. | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/preview_airport_success.py](../../scripts/preview_airport_success.py) | Static inspection images of saved physics states; not a training replay. | 参数：--root, --scene-id, --attempt, --output |
| [scripts/project.py](../../scripts/project.py) | Portable project checks and immutable four-camera scene preparation. | 子命令：'check', 'fourcam'；参数：--compile, --report, --set, --output |
| [scripts/repair_airport_initial_settle.py](../../scripts/repair_airport_initial_settle.py) | Fork scenes; repair floating stacked initializations before collection only. | 参数：--root, --output |
| [scripts/run_r1pro_gpu.sh](../../scripts/run_r1pro_gpu.sh) | Shell/PowerShell 入口；参数和副作用见源码。 | 无静态 argparse；先读源码 |
| [scripts/run_real_sim_pickplace.py](../../scripts/run_real_sim_pickplace.py) | Offline real/sim transfer experiment; no real robot command interface. | 参数：--run, --mode, --model；含服务器固定路径 |
| [scripts/select_r1pro_gpu.py](../../scripts/select_r1pro_gpu.py) | Map nvidia-smi's physical GPU index to EGL's independent device enumeration. | 参数：--gpu, --fields |
| [scripts/setup_r1pro_server.sh](../../scripts/setup_r1pro_server.sh) | Shell/PowerShell 入口；参数和副作用见源码。 | 无静态 argparse；先读源码 |
| [scripts/smoke_fourcam_lerobot.py](../../scripts/smoke_fourcam_lerobot.py) | Stationary camera/loader integration fixture, never a task demonstration. | 参数：--root, --scene-id, --output |
| [scripts/studio_configure_model.py](../../scripts/studio_configure_model.py) | Local workstation model registration. Reads weights' metadata, never unpickles weights. | 无静态 argparse；先读源码 |
| [scripts/studio_live_inference.py](../../scripts/studio_live_inference.py) | Run a checkpoint server and camera-driven Isaac diagnostic; simulation only. | 参数：--run, --checkpoint-id, --room, --frames, --gpu, --keep-server, --serve-only；含服务器固定路径 |
| [scripts/studio_model_http.py](../../scripts/studio_model_http.py) | Loopback model process, separate from ROS's Python/ABI. NPZ, no pickle. | 参数：--run, --port |
| [scripts/studio_mse.py](../../scripts/studio_mse.py) | Paired all-frame fixed real Val/Test inference on registered checkpoints. | 参数：--run, --index；含服务器固定路径 |
| [scripts/studio_mse_plots.py](../../scripts/studio_mse_plots.py) | Render immutable MSE figures from saved inference arrays; never runs a policy. | 参数：--run, --output |
| [scripts/studio_reuse_service.py](../../scripts/studio_reuse_service.py) | Find an already-owned checkpoint service; never trust caller supplied URLs. | 无静态 argparse；先读源码 |
| [scripts/studio_ros2_service.py](../../scripts/studio_ros2_service.py) | Launch only owned model/ROS children; native evaluator manages this service. | 无静态 argparse；先读源码；含服务器固定路径 |
| [scripts/studio_ros2_transport.py](../../scripts/studio_ros2_transport.py) | Real ROS 2 topic transport for simulation only; no hardware topic aliases. | 参数：--run, --external-policy |
| [scripts/supervise_parallel_real_mix.py](../../scripts/supervise_parallel_real_mix.py) | Independent, single-instance conditional BC startup after 300 frozen pairs. | 参数：--config, --mode |
| [scripts/sync_task_spec.py](../../scripts/sync_task_spec.py) | Refresh/check the implementation appendix inside the single task specification. | 参数：--write, --check |
| [scripts/translate_scene_studio_en.py](../../scripts/translate_scene_studio_en.py) | One-time source migration to the English Scene Studio interface. | 无静态 argparse；先读源码 |
| [scripts/upgrade_airport_fourcam.py](../../scripts/upgrade_airport_fourcam.py) | Fork a scene manifest with four measured-intrinsic pinhole cameras. | 参数：--manifest, --audit, --output |
| [scripts/validate_fourcam_scene.py](../../scripts/validate_fourcam_scene.py) | Render four native views and verify camera-only upgrade preserves physics. | 参数：--scene, --source, --output |

## 数据、VLA 训练与模型评测

| 脚本 | 用途（源码说明） | CLI 线索 |
|---|---|---|
| [scripts/close_pi05_comparison_media.py](../../scripts/close_pi05_comparison_media.py) | Read-only validation of paired model videos/traces, then delivery metadata. | 参数：--run |
| [scripts/compare_pi05_closed_loop.py](../../scripts/compare_pi05_closed_loop.py) | Paired held-out simulation Pick/Place; direct model controls, no fallback. | 参数：--run, --mode；含服务器固定路径 |
| [scripts/compare_pi05_real_mixed_plots.py](../../scripts/compare_pi05_real_mixed_plots.py) | Paired all-frame real-test inference and scientific comparison plots. | 参数：--run, --mode；含服务器固定路径 |
| [scripts/compare_pickup120.py](../../scripts/compare_pickup120.py) | Isolated server BC comparison: exactly120 pickup episodes, same50 heldout poses. | 参数：mode, --model；含服务器固定路径 |
| [scripts/convert_vla_lerobot.py](../../scripts/convert_vla_lerobot.py) | Convert verified train spans to a new LeRobot v2 pi0.5 training dataset. | 参数：--manifest, --destination, --repo-id, --max-scenes, --include-reviewed-local |
| [scripts/diagnose_pi05_skills.py](../../scripts/diagnose_pi05_skills.py) | Isolated skill diagnostics from verified expert physics initial snapshots. | 参数：--dataset-manifest, --episode-indices, --output, --checkpoint-id, --host, --port, --max-skill-steps, --actuator-saturation, --collect-curriculum-dagger, --training-status, --round-index, --query-interval, --max-queries, --init-arm-tolerance, --init-gripper-tolerance, --initializer-base-hold, --grasp-base-hold, --private-oracle-contact-escape, --private-oracle-measured-tracking |
| [scripts/evaluate_action8_checkpoint.py](../../scripts/evaluate_action8_checkpoint.py) | Durable single-milestone evaluation; trainer owns the outer resume chain. | 参数：--completed-updates, --port, --minimum-free-mib, --resource-hours, -- + name |
| [scripts/evaluate_action8_checkpoint_dual.py](../../scripts/evaluate_action8_checkpoint_dual.py) | Optional static dual-GPU full-test evaluation. Serial supervisor is unchanged. | 参数：--completed-updates, --worker-index, --minimum-free-mib, --resource-hours, -- + name |
| [scripts/evaluate_pi05_airport.py](../../scripts/evaluate_pi05_airport.py) | Run fresh pi05 MuJoCo evaluations or train-only private expert DAgger queries. | 参数：--collection, --output, --scene-ids, --indices, --host, --port, --record-substep-controls, --checkpoint-id, --training-status, --collect-dagger, --round-index, --query-interval, --max-queries, --execute-steps, --max-skill-steps, --servo-projection, --actuator-saturation, --reference-rate-limit, --rate-fraction, --model-render-max-dim, --init-arm-tolerance, --init-gripper-tolerance, --initializer-base-hold, --grasp-base-hold, --private-oracle-contact-escape, --private-oracle-measured-tracking, --navigation-readiness, --navigation-bearing-max, --navigation-lateral-max, --navigation-forward-min, --navigation-stable-frames |
| [scripts/evaluate_single_tray_pi05.py](../../scripts/evaluate_single_tray_pi05.py) | Evaluate one existing single-tray scene with a real checkpoint service. | 参数：--scene, --output, --checkpoint-id, --host, --port, --action-horizon, --action-width, --execute-steps, --max-action-steps |
| [scripts/evaluate_single_tray_pi05_batch.py](../../scripts/evaluate_single_tray_pi05_batch.py) | Explicit new-task milestone protocol; GPU execution requires --execute. | 参数：--model-python, --sim-python, --gpu-uuid, --egl-device, --port, --startup-timeout, --execute-steps, --max-action-steps, --execute, -- + key |
| [scripts/evaluate_three_table_single_tray_pi05.py](../../scripts/evaluate_three_table_single_tray_pi05.py) | Pure model mobile19 evaluation of one new three-table scene. | 参数：--host, --port, --action-horizon, --execute-steps, --max-action-steps, --actuator-saturation, --reference-rate-limit, -- + k |
| [scripts/evaluate_three_table_single_tray_pi05_batch.py](../../scripts/evaluate_three_table_single_tray_pi05_batch.py) | Explicit new-task milestone protocol; GPU execution requires --execute. | 参数：--model-python, --sim-python, --gpu-uuid, --egl-device, --port, --startup-timeout, --execute-steps, --max-action-steps, --execute, -- + key |
| [scripts/generate_pickup_lerobot.py](../../scripts/generate_pickup_lerobot.py) | Independent parallel pickup-only teacher data, single-writer LeRobot v2.1. | 参数：--target, --workers, --max-attempts, --deadline-seconds, --seed, --worker, --sim-python, -- + key；含服务器固定路径 |
| [scripts/materialize_complete_task_actions.py](../../scripts/materialize_complete_task_actions.py) | Export complete action windows without starting training or a GPU model. | 参数：--plans, --label-spec, --destination, --repo-id, --native-references, --incremental, --poll-seconds, --split, --max-scenes |
| [scripts/materialize_complete_task_actions_parallel.py](../../scripts/materialize_complete_task_actions_parallel.py) | Bounded isolated CPU case exporters; reuse only independently verified cases. | 参数：--plans, --label-spec, --destination, --repo-id, --split, --native-references, --reuse-export, --workers, --camera-workers, --one-scene, --override-file |
| [scripts/merge_vla_skill_dataset.py](../../scripts/merge_vla_skill_dataset.py) | Create a new skill-contiguous derivative without rewriting source data. | 参数：--source-dataset, --destination, --repo-id, --manifest-output, --scene-id |
| [scripts/observe_task_complete_sources_parallel.py](../../scripts/observe_task_complete_sources_parallel.py) | Versioned router handoff around an existing owned native producer; no renderer signals. | 参数：--base, --run-root, --old-router-pid, --authorize-observer；含服务器固定路径 |
| [scripts/plan_complete_task_actions.py](../../scripts/plan_complete_task_actions.py) | Read-only CPU planning of whole actions from complete simulation tasks. | 参数：--inventory, --output, --label-spec, --limit |
| [scripts/plot_pi05_existing_summary.py](../../scripts/plot_pi05_existing_summary.py) | Plot verified existing aggregate reports while paired inference is pending. | 无静态 argparse；先读源码 |
| [scripts/prepare_action8_evaluation_protocol.py](../../scripts/prepare_action8_evaluation_protocol.py) | CPU-only immutable preregistration of all original held-out test scenes. | 参数：--collection, --successful-inventory, --output |
| [scripts/prepare_vla_dataset.py](../../scripts/prepare_vla_dataset.py) | Build frame-aligned pi0.5 supervision manifests without modifying collections. | 参数：--collection, --output, --video-references, --local-qualifications, --verify-videos |
| [scripts/prepare_vla_skill_dataset.py](../../scripts/prepare_vla_skill_dataset.py) | Exclusive new skill-derived dataset, quality/coverage audit and train preflight. | 参数：--source-dataset, --parent-dataset, --destination, --repo-id, --output-dir, --training-spec, --expected-scenes, --expected-lifts |
| [scripts/render_action8_evaluation.py](../../scripts/render_action8_evaluation.py) | Four native cameras beside a fresh VLA attempt's trace; inspection only. | 参数：--attempt, --source-collection, --controller-root, --recover-failed-tail |
| [scripts/render_task_complete_sources.py](../../scripts/render_task_complete_sources.py) | Render immutable complete source tasks; benchmark first, explicit batch dispatch later. | 参数：--inventory, --controller, --output, --one, --physical-gpu, --dispatch, --workers-per-gpu, --worker-cap-file, --allowed-compute-pid, --allow-low-texture, --reuse-manifest |
| [scripts/render_vla_native_sources.py](../../scripts/render_vla_native_sources.py) | Replay frozen successful episodes into new, verified native four-camera video files. | 参数：--one, --limit, --workers；含服务器固定路径 |
| [scripts/render_vla_rollout_videos.py](../../scripts/render_vla_rollout_videos.py) | Native diagnostic heads from actual learned-controller traces; no training export. | 参数：--runs, --one, --source-collection, --controller-root, --output, --workers |
| [scripts/rerender_pickup_camera_shells.py](../../scripts/rerender_pickup_camera_shells.py) | New video/data version of immutable pickup traces; renderer-only shell hide. | 参数：--worker, --workers, --limit, --render-only, -- + key |
| [scripts/resume_afford_pi05_comparison.py](../../scripts/resume_afford_pi05_comparison.py) | Continue the failed comparison in a new run, preserving the old evidence. | 参数：--run, --release；含服务器固定路径 |
| [scripts/run_pi05_real_only.py](../../scripts/run_pi05_real_only.py) | Real-only BC and offline held-out action evaluation; never controls a robot. | 参数：--run, --mode；含服务器固定路径 |
| [scripts/run_three_table_pi05_free_run.py](../../scripts/run_three_table_pi05_free_run.py) | Independent free-run diagnostic, never a formal evaluator or dataset source. | 参数：--host, --port, --action-horizon, --execute-steps, --stage-seconds, --egl-device, -- + name |
| [scripts/run_vla_fixed_scene.py](../../scripts/run_vla_fixed_scene.py) | One prompt, one fixed scene, timed pure-VLA simulation and native videos. | 参数：--source-case, --config, --identity-file, --command, --output, --host, --port, --seconds, --execute-steps, --native-images |
| [scripts/serve_pi05_airport.py](../../scripts/serve_pi05_airport.py) | Serve an actually saved airport pi0.5 fine-tune using official openpi. | 参数：--training-status, --host, --port, --denoising-steps, --identity-only |
| [scripts/serve_pi05_diagnostic.py](../../scripts/serve_pi05_diagnostic.py) | Explicit nonproduction pi05 checkpoint serving for diagnostic physics smoke. | 参数：--diagnostic-status, --identity-output, --host, --port |
| [scripts/studio_prepare_training.py](../../scripts/studio_prepare_training.py) | Resolve a frozen dataset selection into a new run; never mutate source data. | 参数：--run |
| [scripts/studio_vla_evaluate.py](../../scripts/studio_vla_evaluate.py) | Own policy service + native Isaac process, with actual child exit receipts. | 参数：--run, --serve, --native-python |
| [scripts/supervise_action8_training.py](../../scripts/supervise_action8_training.py) | Launch a durable complete-source-gated training/evaluation chain. | 参数：--options, --launch, --recover |
| [scripts/supervise_single_tray_training.py](../../scripts/supervise_single_tray_training.py) | Launch the independent new single-tray three-action data/BC pipeline. | 参数：--options, --launch |
| [scripts/supervise_three_table_single_tray_training.py](../../scripts/supervise_three_table_single_tray_training.py) | Explicit fresh three-table/mobile/opposed task pipeline. No old-task reuse. | 参数：--options, --recover, --data-only |
| [scripts/supervise_verified_three_action_training.py](../../scripts/supervise_verified_three_action_training.py) | Independent guardian for a frozen, completed three-action BC dataset. | 参数：--options, --guardian, --recover |
| [scripts/train_pi05_accelerated.py](../../scripts/train_pi05_accelerated.py) | Project cache and bounded milestone training; no automatic evaluation service. | 参数：--spec, --parent-status, --prepare-cache, --stop-after, --resume, --diagnostic-smoke |
| [scripts/train_pi05_airport.py](../../scripts/train_pi05_airport.py) | Run project-owned pi05 mobile19 LoRA extension inside a non-base Conda env. | 参数：--config, --normalize-only, --dagger-manifest, --parent-status, --dagger-ratio |
| [scripts/train_pi05_parallel_real_mix.py](../../scripts/train_pi05_parallel_real_mix.py) | Two-action configurable real/Isaac BC; no time reward or RL is enabled. | 参数：--run, --mode, --stop；含服务器固定路径 |
| [scripts/train_pi05_real_sim50.py](../../scripts/train_pi05_real_sim50.py) | Independent 50/50 BC release; reuses immutable validated real/sim caches. | 参数：--run, --mode；含服务器固定路径 |
| [scripts/transition_task_complete_sources_parallel.py](../../scripts/transition_task_complete_sources_parallel.py) | Reviewed live-publication transition; immutable source/video/per-case evidence retained. | 参数：--authorize-transition, -- + name；含服务器固定路径 |
| [scripts/vla_fixed_scene_commands.sh](../../scripts/vla_fixed_scene_commands.sh) | Run on the server after copying the standalone diagnostic files into project. | 无静态 argparse；先读源码；含服务器固定路径 |

## 真机示范离线回放与配准

| 脚本 | 用途（源码说明） | CLI 线索 |
|---|---|---|
| [scripts/audit_real2sim.py](../../scripts/audit_real2sim.py) | Audit every original real episode against an explicit simulation model. | 参数：--manifest, --model, --output |
| [scripts/build_real2sim_finger_collision.py](../../scripts/build_real2sim_finger_collision.py) | Decompose project-owned URDF meshes into portable convex collision parts. | 参数：-- + n |
| [scripts/diagnose_real2sim_held_pose.py](../../scripts/diagnose_real2sim_held_pose.py) | Bounded, offline Place registration diagnosis; never changes source commands. | 参数：--run, --output |
| [scripts/fit_real2sim_registration.py](../../scripts/fit_real2sim_registration.py) | Offline initial held-tray pose fit to native collision geometry, no dynamics. | 参数：--seed-z-shift, --max-roll-deg, --max-pitch-deg, -- + n |
| [scripts/fit_real2sim_torso.py](../../scripts/fit_real2sim_torso.py) | Finite offline free-space torso servo fit; never counted as task success. | 参数：-- + n |
| [scripts/replay_real2sim.py](../../scripts/replay_real2sim.py) | Replay original real Pick/Place in a separate full-joint model; simulation only. | 参数：--source-manifest, --scene-xml, --urdf, --output, --per-task, --video, --registration, --torso-kp, --torso-kv, --finger-collision-bundle, --tray-width-scale |
| [scripts/validate_real2sim.py](../../scripts/validate_real2sim.py) | Independently verify a completed replay's clocks, pose, trace and videos. | 参数：--run, --output |

## 连接与真机部署

| 脚本 | 用途（源码说明） | CLI 线索 |
|---|---|---|
| [scripts/control_galaxea_servers.py](../../scripts/control_galaxea_servers.py) | Workstation keyboard command-stop; NOT a hardware emergency stop. | 参数：--control-file, --stop |
| [scripts/forward_galaxea_lan.py](../../scripts/forward_galaxea_lan.py) | Private wired TCP relay; preserves existing model and robot safety protocol. | 无静态 argparse；先读源码 |
| [scripts/galaxea_client_oneclick.sh](../../scripts/galaxea_client_oneclick.sh) | New convenience entry; no changes to robot run/scheduler/filter. | 无静态 argparse；先读源码 |
| [scripts/run_galaxea_client_record_compat.py](../../scripts/run_galaxea_client_record_compat.py) | New robot entry; preserves original run/scheduler/filter/recorder files. | 参数：--config/-c |
| [scripts/serve_pi05_galaxea_robot.py](../../scripts/serve_pi05_galaxea_robot.py) | New workstation endpoint for unchanged Galaxea robot run.py. | 参数：--config；含服务器固定路径 |

## 全部配置

这里只登记文件身份。具体用途先查 README 的流程表；不要把旧八文本/单桌配置替换当前三动作配置。

| 文件 |
|---|
| [configs/airport_ablation_alternate.json](../../configs/airport_ablation_alternate.json) |
| [configs/airport_ablation_baseline.json](../../configs/airport_ablation_baseline.json) |
| [configs/airport_ablation_payload.json](../../configs/airport_ablation_payload.json) |
| [configs/airport_ablation_substep.json](../../configs/airport_ablation_substep.json) |
| [configs/airport_approximate_completion_conservative_ik_retry3.json](../../configs/airport_approximate_completion_conservative_ik_retry3.json) |
| [configs/airport_approximate_completion_legacy_handoff_retry3.json](../../configs/airport_approximate_completion_legacy_handoff_retry3.json) |
| [configs/airport_approximate_completion_retry3.json](../../configs/airport_approximate_completion_retry3.json) |
| [configs/airport_approximate_completion_supported_push_retry3.json](../../configs/airport_approximate_completion_supported_push_retry3.json) |
| [configs/airport_arrival_alternate_align.json](../../configs/airport_arrival_alternate_align.json) |
| [configs/airport_arrival_alternate_arrival.json](../../configs/airport_arrival_alternate_arrival.json) |
| [configs/airport_arrival_alternate_feedback.json](../../configs/airport_arrival_alternate_feedback.json) |
| [configs/airport_arrival_arrival.json](../../configs/airport_arrival_arrival.json) |
| [configs/airport_arrival_baseline.json](../../configs/airport_arrival_baseline.json) |
| [configs/airport_buffer_baseline.json](../../configs/airport_buffer_baseline.json) |
| [configs/airport_buffer_command_feedback.json](../../configs/airport_buffer_command_feedback.json) |
| [configs/airport_buffer_geometry.json](../../configs/airport_buffer_geometry.json) |
| [configs/airport_buffer_hybrid.json](../../configs/airport_buffer_hybrid.json) |
| [configs/airport_buffer_paths.json](../../configs/airport_buffer_paths.json) |
| [configs/airport_certified_additive.json](../../configs/airport_certified_additive.json) |
| [configs/airport_certified_baseline.json](../../configs/airport_certified_baseline.json) |
| [configs/airport_certified_combined.json](../../configs/airport_certified_combined.json) |
| [configs/airport_certified_geometry.json](../../configs/airport_certified_geometry.json) |
| [configs/airport_certified_guarded_reference.json](../../configs/airport_certified_guarded_reference.json) |
| [configs/airport_clock_float_baseline.json](../../configs/airport_clock_float_baseline.json) |
| [configs/airport_clock_step_baseline.json](../../configs/airport_clock_step_baseline.json) |
| [configs/airport_clock_step_preview.json](../../configs/airport_clock_step_preview.json) |
| [configs/airport_clock_step_shortcut.json](../../configs/airport_clock_step_shortcut.json) |
| [configs/airport_completion_direct_ik80_retry3.json](../../configs/airport_completion_direct_ik80_retry3.json) |
| [configs/airport_completion_direct_lift_nominal_retry3.json](../../configs/airport_completion_direct_lift_nominal_retry3.json) |
| [configs/airport_completion_direct_retry3.json](../../configs/airport_completion_direct_retry3.json) |
| [configs/airport_completion_first.json](../../configs/airport_completion_first.json) |
| [configs/airport_completion_flow_retry3.json](../../configs/airport_completion_flow_retry3.json) |
| [configs/airport_completion_free_open_retry3.json](../../configs/airport_completion_free_open_retry3.json) |
| [configs/airport_completion_handoff_clearance_retry3.json](../../configs/airport_completion_handoff_clearance_retry3.json) |
| [configs/airport_completion_ik.json](../../configs/airport_completion_ik.json) |
| [configs/airport_completion_ik40.json](../../configs/airport_completion_ik40.json) |
| [configs/airport_completion_ik40_retry3.json](../../configs/airport_completion_ik40_retry3.json) |
| [configs/airport_completion_ik80_retry3.json](../../configs/airport_completion_ik80_retry3.json) |
| [configs/airport_completion_lift_nominal_retry3.json](../../configs/airport_completion_lift_nominal_retry3.json) |
| [configs/airport_completion_lift_retry3.json](../../configs/airport_completion_lift_retry3.json) |
| [configs/airport_completion_nominal_retry3.json](../../configs/airport_completion_nominal_retry3.json) |
| [configs/airport_completion_orientation_retry3.json](../../configs/airport_completion_orientation_retry3.json) |
| [configs/airport_completion_priority_retry3.json](../../configs/airport_completion_priority_retry3.json) |
| [configs/airport_completion_priority_speed_retry3.json](../../configs/airport_completion_priority_speed_retry3.json) |
| [configs/airport_completion_release_orientation_retry3.json](../../configs/airport_completion_release_orientation_retry3.json) |
| [configs/airport_completion_release_retry3.json](../../configs/airport_completion_release_retry3.json) |
| [configs/airport_completion_reservation_retry3.json](../../configs/airport_completion_reservation_retry3.json) |
| [configs/airport_completion_retry3.json](../../configs/airport_completion_retry3.json) |
| [configs/airport_completion_stage_extended_base_retry3.json](../../configs/airport_completion_stage_extended_base_retry3.json) |
| [configs/airport_completion_stage_joint_endpoint_pos100_retry3.json](../../configs/airport_completion_stage_joint_endpoint_pos100_retry3.json) |
| [configs/airport_completion_stage_joint_endpoint_retry3.json](../../configs/airport_completion_stage_joint_endpoint_retry3.json) |
| [configs/airport_completion_stage_multistart_joint_endpoint_retry3.json](../../configs/airport_completion_stage_multistart_joint_endpoint_retry3.json) |
| [configs/airport_completion_stage_multistart_retry3.json](../../configs/airport_completion_stage_multistart_retry3.json) |
| [configs/airport_completion_stage_priority_retry3.json](../../configs/airport_completion_stage_priority_retry3.json) |
| [configs/airport_completion_stage_priority_speed_retry3.json](../../configs/airport_completion_stage_priority_speed_retry3.json) |
| [configs/airport_completion_stage_private_pos090_retry3.json](../../configs/airport_completion_stage_private_pos090_retry3.json) |
| [configs/airport_completion_stage_private_pos100_extended_base_retry3.json](../../configs/airport_completion_stage_private_pos100_extended_base_retry3.json) |
| [configs/airport_completion_stage_private_pos100_retry3.json](../../configs/airport_completion_stage_private_pos100_retry3.json) |
| [configs/airport_completion_stage_refit_free_first_retry3.json](../../configs/airport_completion_stage_refit_free_first_retry3.json) |
| [configs/airport_completion_stage_refit_retry3.json](../../configs/airport_completion_stage_refit_retry3.json) |
| [configs/airport_completion_stage_refit_subdivision_retry3.json](../../configs/airport_completion_stage_refit_subdivision_retry3.json) |
| [configs/airport_completion_stage_subdivision_retry3.json](../../configs/airport_completion_stage_subdivision_retry3.json) |
| [configs/airport_completion_stage_supported_combined_screen_retry3.json](../../configs/airport_completion_stage_supported_combined_screen_retry3.json) |
| [configs/airport_completion_stage_supported_staging_retry3.json](../../configs/airport_completion_stage_supported_staging_retry3.json) |
| [configs/airport_completion_task_retry3.json](../../configs/airport_completion_task_retry3.json) |
| [configs/airport_destination_combined.json](../../configs/airport_destination_combined.json) |
| [configs/airport_destination_push_command.json](../../configs/airport_destination_push_command.json) |
| [configs/airport_destination_push_zero.json](../../configs/airport_destination_push_zero.json) |
| [configs/airport_destination_screen_zero.json](../../configs/airport_destination_screen_zero.json) |
| [configs/airport_feedback_baseline.json](../../configs/airport_feedback_baseline.json) |
| [configs/airport_feedback_combined.json](../../configs/airport_feedback_combined.json) |
| [configs/airport_feedback_command_feedback.json](../../configs/airport_feedback_command_feedback.json) |
| [configs/airport_feedback_feedback.json](../../configs/airport_feedback_feedback.json) |
| [configs/airport_feedback_geometry.json](../../configs/airport_feedback_geometry.json) |
| [configs/airport_geometry_baseline.json](../../configs/airport_geometry_baseline.json) |
| [configs/airport_geometry_combined.json](../../configs/airport_geometry_combined.json) |
| [configs/airport_geometry_destination.json](../../configs/airport_geometry_destination.json) |
| [configs/airport_geometry_pickup.json](../../configs/airport_geometry_pickup.json) |
| [configs/airport_merge_additive.json](../../configs/airport_merge_additive.json) |
| [configs/airport_merge_baseline.json](../../configs/airport_merge_baseline.json) |
| [configs/airport_merge_combined.json](../../configs/airport_merge_combined.json) |
| [configs/airport_merge_combined_merge.json](../../configs/airport_merge_combined_merge.json) |
| [configs/airport_merge_preview_merge.json](../../configs/airport_merge_preview_merge.json) |
| [configs/airport_preview_baseline.json](../../configs/airport_preview_baseline.json) |
| [configs/airport_preview_combined.json](../../configs/airport_preview_combined.json) |
| [configs/airport_preview_geometry.json](../../configs/airport_preview_geometry.json) |
| [configs/airport_preview_guarded.json](../../configs/airport_preview_guarded.json) |
| [configs/airport_preview_paths.json](../../configs/airport_preview_paths.json) |
| [configs/airport_primitives3.json](../../configs/airport_primitives3.json) |
| [configs/airport_primitives3_smoke.json](../../configs/airport_primitives3_smoke.json) |
| [configs/airport_reach_pull.json](../../configs/airport_reach_pull.json) |
| [configs/airport_reference_baseline.json](../../configs/airport_reference_baseline.json) |
| [configs/airport_reference_command.json](../../configs/airport_reference_command.json) |
| [configs/airport_reference_command_substep.json](../../configs/airport_reference_command_substep.json) |
| [configs/airport_reference_geometry.json](../../configs/airport_reference_geometry.json) |
| [configs/airport_reference_geometry_preserve.json](../../configs/airport_reference_geometry_preserve.json) |
| [configs/airport_reference_paths_feedback.json](../../configs/airport_reference_paths_feedback.json) |
| [configs/airport_reference_preserve.json](../../configs/airport_reference_preserve.json) |
| [configs/airport_retiming_additive.json](../../configs/airport_retiming_additive.json) |
| [configs/airport_retiming_baseline.json](../../configs/airport_retiming_baseline.json) |
| [configs/airport_retiming_combined.json](../../configs/airport_retiming_combined.json) |
| [configs/airport_retiming_preview.json](../../configs/airport_retiming_preview.json) |
| [configs/airport_retiming_shortcut.json](../../configs/airport_retiming_shortcut.json) |
| [configs/airport_robust_v10.json](../../configs/airport_robust_v10.json) |
| [configs/airport_robust_v11.json](../../configs/airport_robust_v11.json) |
| [configs/airport_robust_v12.json](../../configs/airport_robust_v12.json) |
| [configs/airport_robust_v13.json](../../configs/airport_robust_v13.json) |
| [configs/airport_scoped_baseline.json](../../configs/airport_scoped_baseline.json) |
| [configs/airport_scoped_feedback_all.json](../../configs/airport_scoped_feedback_all.json) |
| [configs/airport_scoped_feedback_placement.json](../../configs/airport_scoped_feedback_placement.json) |
| [configs/airport_scoped_paths.json](../../configs/airport_scoped_paths.json) |
| [configs/airport_target_baseline.json](../../configs/airport_target_baseline.json) |
| [configs/airport_target_combined.json](../../configs/airport_target_combined.json) |
| [configs/airport_target_geometry.json](../../configs/airport_target_geometry.json) |
| [configs/airport_target_geometry_feedback.json](../../configs/airport_target_geometry_feedback.json) |
| [configs/airport_target_geometry_reference.json](../../configs/airport_target_geometry_reference.json) |
| [configs/experiment_candidates.json](../../configs/experiment_candidates.json) |
| [configs/experiment_search_space.json](../../configs/experiment_search_space.json) |
| [configs/r1pro_verified_limits_TEMPLATE.json](../../configs/r1pro_verified_limits_TEMPLATE.json) |
| [configs/vla_pi05_action8_accelerated_v1.json](../../configs/vla_pi05_action8_accelerated_v1.json) |
| [configs/vla_pi05_airport_bootstrap4_lora.json](../../configs/vla_pi05_airport_bootstrap4_lora.json) |
| [configs/vla_pi05_airport_bootstrap4_lora_v2.json](../../configs/vla_pi05_airport_bootstrap4_lora_v2.json) |
| [configs/vla_pi05_airport_native16_v3_lora.json](../../configs/vla_pi05_airport_native16_v3_lora.json) |
| [configs/vla_pi05_airport_native32_skill_only6_dualgpu_20261005.json](../../configs/vla_pi05_airport_native32_skill_only6_dualgpu_20261005.json) |
| [configs/vla_pi05_airport_native32_skillmerged_dualgpu_dp_20261005.json](../../configs/vla_pi05_airport_native32_skillmerged_dualgpu_dp_20261005.json) |
| [configs/vla_pi05_airport_native32_skillmerged_dualgpu_warmstart_20261005.json](../../configs/vla_pi05_airport_native32_skillmerged_dualgpu_warmstart_20261005.json) |
| [configs/vla_pi05_airport_native32_v2_warmstart_lora.json](../../configs/vla_pi05_airport_native32_v2_warmstart_lora.json) |
| [configs/vla_pi05_airport_native32_v3_warmstart_lora.json](../../configs/vla_pi05_airport_native32_v3_warmstart_lora.json) |
| [configs/vla_pi05_airport_native32_v4_skillmerged_warmstart_lora.json](../../configs/vla_pi05_airport_native32_v4_skillmerged_warmstart_lora.json) |
| [configs/vla_pi05_single_tray_action3_v1.json](../../configs/vla_pi05_single_tray_action3_v1.json) |
| [configs/vla_pi05_three_table_single_tray_action3_v1.json](../../configs/vla_pi05_three_table_single_tray_action3_v1.json) |
| [configs/vr_teleoperation_whole_body_launch.py](../../configs/vr_teleoperation_whole_body_launch.py) |
