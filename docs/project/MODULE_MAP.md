## 2026-10-19 离线与 ROS2

`apps/scene-agent/offline/` 提供Node24/SQLite/本地artifact无登录服务与单实例监督器；`app/Help.tsx`、`BatchCatalog.tsx`、`ModelConfig.tsx`、`lib/reset.ts` 为界面入口。`scripts/studio_{configure_model,model_http,ros2_service,ros2_transport}.py` 提供路径登记、显式单位/时序适配与隔离ROS2图像/状态/动作通信；GR00T未提供权重不标实测。说明[WORKSTATION](../site/WORKSTATION.md)。

## 2026-10-19 网站使用入口

[Scene Studio使用 README](../site/README.md)按英文界面说明MSE图表与下载入口、场景编辑、训练配比、自动最终检查点评测、手动MSE/VLA和常见状态。维护时对照`apps/scene-agent/app/{page,TrainingPanel,AutoEvaluations,MseFigures}.tsx`及`lib/{core,training}.ts`，不要将历史截图当作当前运行状态。

## 2026-10-19 MSE科学图表

`scripts/studio_mse_plots.py`只读推理NPZ/报告，验证SHA/逐channel统计后输出5类汇总与每episode 4×4曲线；`gpu/plot_runner.py`保留actual wait，`gpu/mse_artifacts.py`独立CPU派生与有界R2发布。`app/MseFigures.tsx`切图/PNG/CSV/ZIP，`api/artifacts`校验worker写/owner读和SHA不可变对象。源推理与自动VLA/MSE队列不修改。

## 2026-10-19 英文与训练后自动评测

`apps/scene-agent/lib/display.ts`翻译历史系统回执展示，`core.ts`支持英文明确指令；网页全英文，原记录不改。`gpu/auto_evaluation.py`在scheduler.lock内核训练目标/闭合最终checkpoint/actual wait0，冻结最新checkpoint并幂等派生VLA与MSE。`app/AutoEvaluations.tsx`展示进程状态、成功分母/基础设施失败/覆盖率、固定Test的MSE与baseline差异。`studio_vla_evaluate.py`修复原生引擎bootstrap环境并区分初始化/实际执行。服务器独立release/run，失败旧job保留；证据目录`runs/web_english_autoeval_20261019_v1`。

## 2026-10-17 训练控制台扩展（替代下方旧固定配方网页范围）

`apps/scene-agent/app/TrainingPanel.tsx`提供10秒进度/ETA、配比、队列和评测；`lib/training.ts`验证可配置训练与登记检查点请求。`gpu/studio_backend.py`负责来源登记、逐步状态采样、GPU单任务调度；`studio_job_runner.py`保留实际子进程退出回执。项目`studio_prepare_training.py`与`train_pi05_parallel_real_mix.py`支持端点/任意配比和精确步数；`studio_mse.py`固定真机配对；`studio_vla_evaluate.py` + `real2sim/isaac_policy_pickplace.py`提供无教师的Isaac纯策略诊断。独立release/run，不改当前训练输入；历史v1导出范围保持。证据 `runs/web_training_console_20261017_v1/`。

## 2026-10-17 Scene Studio 原材质默认显示

`apps/scene-agent/app/SceneViewport.tsx`保留来源room背景、原黑银/酒红材质、托盘标识与受保护机器人部分；`lib/core.ts`提供默认sRGB色板和恢复原色指令，`app/page.tsx`提供按房间恢复入口。纯浏览器静态展示，不改变GPU物理流程。正式登录→队列→GPU回执已验收；证据见`runs/web_scene_agent_materials_20261017_v1/verification.json`。

# 模块地图

2026-10-17网页项目：[apps/scene-agent](../../apps/scene-agent/PROJECT.md)。`app/page.tsx`/`SceneViewport.tsx`提供32房间编辑与原CAD预览；`lib/core.ts`限制指令/训练配方；`app/api`提供用户隔离D1、revision版本、队列和worker回执；`gpu/worker.py`主动连私有Sites、单实例/身份/心跳/有限重试，不启动任意任务。GPU配置为新草稿，真实执行需独立原生门。证据`runs/web_scene_agent_deploy_20261017/{deployment,bridge_probe_result,api_smoke_result}.json`。

2026-10-17网页agent导出：`exports/web_scene_agent_v1/{executor,isaac_adapter}.py`与prompts/schema，独立JSON指令执行器只写新草稿/冻结计划；不修改当前native入口。入口见[导出说明](../../exports/web_scene_agent_v1/README.md)，回归`tests/test_web_scene_agent_export.py`，验证见`runs/web_scene_agent_export_20261017_v1/validation.json`。后续混合训练复用DEC-055的`parallel_pickplace_training.py`与`train_pi05_parallel_real_mix.py`，不使用三动作trainer承接两动作。

英文技术交接：[43页PDF](../../output/pdf/R1Pro_Project_Review_and_Operations_Handover_EN.pdf) · [可编辑源稿](../handoff/README_EN.md) · [构建/检查说明](../handoff/PDF_BUILD.md)。文档构建工具在`docs/handoff/`，只读解析与排版，不调用项目运行模块。

启动/安装/后台/训练/机器人操作顺序统一查 [交接 README](../handoff/README.md)，全部脚本与 configs 查 [静态目录](../handoff/SCRIPTS.md)。目录由 `scripts/build_handoff_catalog.py` 生成，仅静态解析，不执行历史诊断；冻结 run/release 不作为新运行入口。

当前三桌单盘流程：场景/父split登记→真实可达性预检→完整物理采集→来源资格→四相机原生闭合→三动作导出→训练缓存/BC→纯模型评测。装载在环境阶段，排除训练片段。

| 模块 | 源码/入口 | 主要合同与证据 |
|---|---|---|
| 独立Isaac快速取放 | `real2sim/{isaac_lab_visuals,isaac_fast_pickplace}.py`、`scripts/{run,supervise,audit}_isaacsim_fast_pickplace.py`、`finalize_isaac_fast_pickplace.py` | [多位姿专题](ISAAC_FAST_PICKPLACE_20261016.md)；原速各3秒，预备另计、5路媒体，独立复核，不进BC |
| 三桌单盘场景/视觉 | `r1pro_teleop/single_tray_lab/three_table_scene.py`、`camera_visuals.py`、`resources/` | 初始pose/seed、桌尺寸、XML、视觉版本；碰撞/惯量/相机不可偷偷变 |
| 旧控制原语 | `r1pro_teleop/airport_fsm/{runtime,machine,primitives,trajectory,reachability_planner}.py` | 复用抓放、桌前站位、IK可行性；教师采集与learned执行区分 |
| 当前三桌控制/采集 | `r1pro_teleop/single_tray_3table/{control,collect,campaign,initial_pose_preflight,placement_scope,loaded_bridge,observer}.py` | 双长边/前向、交接实测3cm、whole result/trace/events |
| 原生回放 | `single_tray_3table/replay.py`、`scripts/render_three_table_single_tray.py` | 四路原分辨率、ffprobe/SHA、连续/terminal六误差、实际exit |
| 真机示范real2sim | `real2sim/{trajectory,mapping,runner,backends,model,registration,mujoco_registration,collision}.py`、`scripts/replay_real2sim.py`、`scripts/audit_real2sim.py` | 独立原时间轴20通道/具名映射；MuJoCo实测，Isaac/Genesis接口测试；[边界与迁移](REAL2SIM.md) |
| 数据资格与导出 | `r1pro_teleop/vla/{data_three_table_single_tray,data_three_table_lerobot,completed_dataset_import}.py`、`scripts/export_three_table_single_tray_actions.py` | 完整来源、精确三文本、时间窗、manifest和split |
| 缓存与π0.5 BC | `vla/{training,training_cache,training_accelerated,three_table_single_tray_pipeline,three_table_recovery}.py`、`scripts/train_pi05_accelerated.py` | train-only norm、uint8RGB/FP32数值、BF16/FP32 PEFT、检查点/优化器/真实步数 |
| 纯VLA执行/评测 | `single_tray_3table/{learned,evaluation_protocol,evaluation_batch}.py`、`vla/{policy,executor}.py` | 模型原始动作/实际ctrl、无教师回退、任务/严格结果分报 |
| 后台/恢复 | `single_tray_3table/{workflow,guardian,owned_command,campaign_recovery}.py`、`scripts/supervise_verified_three_action_training.py` | 锁、PID/birth/argv/cwd、健康复用、最多3次、stage/heartbeat/exit |
| 独立模型对比 | `scripts/compare_pickup120.py`、`resume_afford_pi05_comparison.py` | 120拿取源、50同父位姿、π10000与Aff1000+10000、独立GPU环境 |
| 进度查看 | `scripts/watch_vla_comparison.py` / `.ps1` | 只读，SSH `-T`；分阶段百分比和实测ETA；不停止训练 |
| 自由执行 | `single_tray_3table/{free_run,free_run_runtime,free_run_native}.py` | 独立600秒诊断，任务检查不终止、非有限真实停止 |
| 实验优化 | `r1pro_teleop/experiments/`、`prompts/airport_experiments/` | EmbodiedSWE迁移实验/参数搜索/检查点工具，开发与留出分开 |
| 文档/交互维护 | `scripts/sync_task_spec.py`、`export_project_interactions.py` | 规范同步、只读源日志、脱敏档案；不是服务器监控服务 |

测试入口：非base环境 `python -m pytest tests/<相关模块> -q`；控制修改需完整物理episode，数据修改需官方loader/帧对齐/来源资格验证。测试通过和实际部署分报。旧多托盘模块图见 [ARCHITECTURE.md](../ARCHITECTURE.md)，具体状态字典见 [统一规范](../SCENE_TASK_SPEC.md)。

服务器交接统一直接连接：`ssh michelle@xinmatrix` 或 `ssh michelle@100.104.0.108`，端口22，密码交互输入。操作顺序见[交接README](../handoff/README.md)，监控在服务器运行。

纯真机BC/离线评测：scripts/run_pi05_real_only.py；只读进度scripts/watch_pi05_real_only.py及.ps1；测试tests/test_pi05_real_only.py；规范1.122。

Isaac Sim原生迁移：scripts/isaacsim_scene_smoke.py，独立USD导入、相机补建、articulation审计和PhysX步进；详[迁移记录](ISAACSIM_MIGRATION_20261015.md)。尚非完整任务入口。


2026-10-15：Isaac迁移模块：scripts/isaacsim_control_preflight.py、isaacsim_deformable_coat.py、isaacsim_materials.py、isaacsim_reference_episode.py；r1pro_teleop/real2sim/isaac_mobile.py映射，vla/isaac_dataset.py数据门/切片/cache，scripts/prepare_isaacsim_dataset.py CLI。任务观察器/随机采集监督/原生模型闭环待完成。 详[Isaac专题](ISAACSIM_MIGRATION_20261015.md)。


2026-10-15：三托盘新增：real2sim/three_tray_migration.py；prepare_isaacsim_three_tray.py与supervise_isaacsim_three_tray_assets.py（仅资产）；isaacsim_base_drives.py与isaacsim_kinematic_audit.py；vla/isaac_dataset.py支持重复三动作、多盘状态及资格门。完整native控制/观察器待实现。 见[三托盘迁移](ISAACSIM_THREE_TRAY_20261015.md)。

2026-10-15 原生三盘执行新增：`real2sim/isaac_three_tray_runtime.py`负责SDK真实步进/四相机/接触/载荷；`isaac_three_tray_teacher.py`复用旧相对长边与单臂分离的私有运动学规划；`isaac_three_tray_observer.py`独立真实状态资格门。`scripts/run_isaacsim_three_tray_task.py`原生完整episode，`isaacsim_mass_properties.py`源质量/夹指联动转换，`probe_isaacsim_flush_path.py`只做失败终态的私有运动学检查。`supervise_isaacsim_three_tray_task.py`完整demo/数据/BC接线，`isaacsim_stage_runner.py`独立wait收据，`guard_isaacsim_three_tray_task.py`最多3次协调进程恢复。`train_pi05_isaac_three_tray.py`冻结原生缓存的双卡BC；模型评测不能调用教师，未接通前状态明确pending。

2026-10-15 native三托盘新增控制与后台模块：r1pro_teleop/real2sim/isaac_three_tray_{runtime,teacher,observer}.py；teacher只用于专家采集。scripts/run_isaacsim_three_tray_task.py是实际PhysX入口；scripts/supervise_isaacsim_three_tray_task.py串接真实demo退出→heldout源→冻结→分片/cache→BC，scripts/guard_isaacsim_three_tray_task.py外守护。scripts/expand_isaacsim_three_tray.py生成后续独立版本，scripts/guard_isaacsim_expansion.py防重复并有界恢复进程；scripts/audit_isaacsim_three_tray_demo.py独立只读闭合审计。scripts/watch_isaac_three_tray.ps1读取CURRENT_NATIVE_PIPELINE并核进程身份，只同步JSON/TXT。最新运行版本与证据以ISAACSIM_THREE_TRAY_20261015.md和实际报告为准；原生纯VLA模型评测仍待接通，不得调用teacher冒充。


2026-10-16 三盘原生流程新增独立只读媒体入口：scripts/serve_isaacsim_media.py（Range/HEAD、单实例、tailnet限定），不参与物理/验收；scripts/watch_isaac_three_tray.ps1核验当前指针与实际进程、同步JSON/TXT，不能以旧PID代替当前存活。最新控制版本和实测见[三盘专题](ISAACSIM_THREE_TRAY_20261015.md)。


2026-10-16 BC延期恢复入口：`scripts/resume_isaacsim_bc_after_video.py`，复用guard/stage_runner，等待原生视频审阅证据→新目录prepare/原采样归一化SHA一致→原冻结数据与配置的BC数量级保存。`watch_isaac_three_tray.ps1`分别显示旧协调器延期和新恢复阶段；本轮快视频不作为该批训练来源。


2026-10-16 DEC-048：FastPickPlace拆成prepare_pick/pick/place，默认旧流程保持；fixed_base_world指定专项固定站位、lift_height_m调整登记采集候选。place直接消费实际持盘反馈并记录place_initial_state，不重置。collect_isaac_fixed_pickplace.py复用原生连续执行与分片入口，独立资格检查后按动作分目录/冻结每对batch；watch_isaac_fixed_pickplace.ps1只读显示源对/动作段/真实PID。当前专家来源，尚未有实际VLA持盘源。


### 2026-10-16 C32网格采集与初态多样性实施中

DEC-050/规范1.163。新模块`real2sim/isaac_parallel_collection.py`：独立房间坐标、批量18关节映射、父split检查、全180度对称区间的桌内采样（只是几何条件，不是可达性）、有界无丢帧编码。`scripts/probe_isaac_parallel_collection.py`及`supervise_isaac_parallel_probe.py`先做单engine实际PhysX与四相机逐级集成，probe明确不进训练；非批量自适应控制器或完整任务验收。服务器新run `runs/isaacsim_parallel_collection_20261016_v1`，初次4房间10帧/250真实全局子步/16视频actual wait0；完整4→8→16→32仍待实际产物。大初态单臂预调整与不同真实持盘Place资格尚待接通，不能称已支持或已批量生成。原固定底盘串行两对4片段已正常闭合；BC0更新初始化按用户C资源安排暂缓，无更新丢失，原数据权重保留。


2026-10-16最新补充（覆盖前述待完成快照）：规范1.164。32v1句柄耗尽失败保留；新v2/code44仅本进程65536软额、显式双GPU相机分配/房间材质引用、复用4/8/16真实审计后重跑32。单臂准备code43真实碰撞足迹纠正矩形代理误判；case_004仍抬升/倾18度并实际外伸5.11cm，失败未进训练，姿态泛化尚未通过。可变长度Pick分片已接end−start，含预调整；Place保留实际连续末态。代码/数据/原生与模型成功分开，C32自适应批量控制仍待接通；旧2对4片段和旧BC保留。新scope与阻塞见memory/CURRENT.md及server实际报告。

2026-10-16 DEC-051：`episode_front_stations`复用旧桌前距离/横移并补充长轴对齐候选，按原桌前区域过滤；DiversePickPlace选择后冻结目标。显式固定旧站位行为不变。export_pair新allow_episode_front_station_search读取选定站位，继续检查目标恒定/连续实际状态。该模块是专家采集，不是VLA回退。

2026-10-16：scripts/prepare_isaac_reachable_pickplace.py生成有限直接可达候选及预检登记；collect_isaac_fixed_pickplace.py增加全初始底盘轨迹校验与显式partial_complete。调盘独立研究见ISAAC_ADJUSTMENT_RESEARCH_20261016.md，不作为生产准入条件。

2026-10-16 方案C反馈采集：scripts/run_isaac_parallel_pickplace.py（唯一World/PhysicsScene及32房间主线程物理）、real2sim/isaac_parallel_runtime.py（房间私有运动学与命令/反馈同步）、isaac_parallel_contacts.py（真实房间局部接触）、scripts/supervise_isaac_parallel_pickplace.py（4房间验证→32房间→实际exit/导出）、export_isaac_parallel_pickplace.py（冻结合格pair）。旧probe保持非训练scope。

2026-10-17：`supervise_isaac_pickplace300.py`/`prepare_isaac_parallel_candidates.py`新增300完整固定底盘Pick/Place对的有界生产；`vla/parallel_pickplace_training.py`冻结原生对与Cache适配/源级耗时采样，`train_pi05_parallel_real_mix.py`双卡耗时加权BC，`supervise_parallel_real_mix.py`完整300门后接cache/BC/真机test MSE；`watch_pickplace300_mix.py`只读进度。暂不做RL，纯Isaac模型闭环仍待接通。

## 2026-10-19 Single-policy live evaluation

PolicyEvaluation.tsx, api/live, gpu/live_publication.py and studio_live_view.py connect native body poses/cameras to per-run website monitoring and video artifacts. Guide: [Policy evaluation](../site/POLICY_EVALUATION.md). Evidence: [measured runs](../../runs/web_live_policy_20261019_v1/verification.json). Room001 pi05 executed 15 frames then mechanical-limit failure (0/1); room000 zero frames; G0.5 adapter HTTP500. No policy success claimed. CPU duration-budget tests passed. Workstation release scene_studio_live_policy_20261019_v5 active at deployment receipt time.
