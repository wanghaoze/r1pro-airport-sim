# 项目运行与交接手册

更新：2026-10-16，Asia/Singapore。面向接手开发、数据生成、训练与现场部署的同事。根目录 [README](../../README.md) 是总入口；本页提供执行顺序，本次交接的脚本和配置见 [SCRIPTS.md](SCRIPTS.md)，参数默认值、源码位置和 SHA 见 [script_catalog.json](script_catalog.json)。

本轮只整理文档并做只读核验，没有启动训练、仿真或机器人动作。命令分为可直接进行的检查、填写路径后执行的新实验模板、需要现场操作的真机流程。历史目录用于定位证据，不能直接作为新实验输出。

**英文交付版：** [Project Review and Operations Handover PDF](../../output/pdf/R1Pro_Project_Review_and_Operations_Handover_EN.pdf)；[英文源稿](README_EN.md)。PDF先介绍探索与实验，再给操作步骤，附232个脚本和132个配置的冻结目录。按2026-10-16 13:16 SGT证据截点编写，正文区分后续BC恢复与旧协调器延期快照。

## 1. 先选对任务

| 目标 | 入口 | 范围和完成标志 |
|---|---|---|
| 三桌单托盘 MuJoCo 数据 | 本页第 4 节 | 完整 Pick→Place→环境装载→Flush 成功，四相机闭合，才能切三动作 |
| 三托盘 Isaac 原生数据/BC | 第 5、6 节 | 每盘三动作，完整三盘来源、三 split、原生媒体和退出收据闭合 |
| 原速 3 秒取放、平稳性 | 第 5.5 节 | 独立教师诊断；准备/导航另计，不自动进入训练 |
| 纯真机、90/10、50/50 离线训练 | 第 6 节 | 三个独立实验；MSE、梯度更新、保存检查点与任务成功分开 |
| workstation 推理服务 + robot client | 第 7 节 | 现场人员操作；原过滤器、录制、键盘停止和硬件急停保留 |
| 真机示范 real2sim | 第 8 节 | 离线轨迹回放，不连接或控制机器人 |
| 旧 400 场景/八文本/拿取对比 | 第 9 节 | 历史或独立 scope，不能当作当前整体任务数据 |

任务文本严格为 `Pick up the tray`、`Place the tray`、`Flush tray to the left`。单盘和三盘、教师和模型、真机与仿真、完整来源与动作段分别报告。动作、接触、位置与时间门的唯一合同是 [SCENE_TASK_SPEC.md](../SCENE_TASK_SPEC.md)，本手册不新增阈值。

## 2. 机器、路径、网络和环境

### 2.1 机器分工

| 机器 | 工作目录/作用 | 连接 |
|---|---|---|
| Windows 本机 | `C:\Users\HAOZEW\Documents\code\r1pro-airport-sim`；文档、代码、JSON/TXT 索引 | PowerShell、OpenSSH；本机非 base Python：`.conda\experiment\python.exe` |
| GPU workstation `xinmatrix` | `/home/michelle/haoze/r1pro-airport-sim`；仿真、数据、训练、模型 server | 直接 SSH：`michelle@xinmatrix` 或 `michelle@100.104.0.108`，端口22 |
| 机器人 | `/home/nvidia/GalaxeaVLA/experiments/r1pro`；现场 client/ROS/SDK | 已登录机器人终端执行；本轮未重新核验机器人 SSH 地址或现场状态 |

本机连接 GPU：

```powershell
Set-Location C:\Users\HAOZEW\Documents\code\r1pro-airport-sim
ssh michelle@xinmatrix
# 主机名不能解析时使用 IP：
# ssh michelle@100.104.0.108
```

用户名 `michelle`，主机名 `xinmatrix`，地址 `100.104.0.108`，SSH 默认端口22。客户端须能访问该地址所在网络；主机名不能解析时使用 IP。在 SSH 提示时交互输入由负责人单独提供的密码，文档、命令和配置示例不保存密码。第一次连接先核对主机身份，不关闭 host-key 检查。连不上时区分名称解析、网络不可达与认证失败；不能据此宣称服务器进程停止。本次仅调整交接说明，没有重新测试密码登录。

### 2.2 GPU 服务器通用变量

以下 Bash 示例先执行此块。`B` 是资源/数据根；`CODE` 是本次冻结或已审阅的代码根，继续旧实验时按 launch 收据取值。

```bash
export B=/home/michelle/haoze/r1pro-airport-sim
export CODE="$B"
export SIM_PY=/home/michelle/miniconda3/envs/r1pro-tray/bin/python
export VLA_ENV=/home/michelle/miniconda3/envs/r1pro-vla
export VLA_PY="$VLA_ENV/bin/python"
export ISAAC_PY=/home/michelle/miniconda3/envs/env_isaaclab6/bin/python
export AIRPORT_PROJECT="$B"
export PYTHONPATH="$CODE${PYTHONPATH:+:$PYTHONPATH}"
cd "$B"
```

2026-10-16 **12:44 SGT** 只读实核版本（不是建议把三个环境装到一起）：

| 环境 | Python | 已核关键包 | 用途 |
|---|---|---|---|
| `r1pro-tray` | 3.11.16 | MuJoCo 3.13.0、torch 2.8.0+cu129、LeRobot 0.4.4 | MuJoCo、场景/数据准备、媒体验收 |
| `r1pro-vla` | 3.11.16 | JAX/jaxlib 0.5.3、torch 2.7.1、LeRobot 0.1.0 | 既有 OpenPI 训练/推理；不要用仿真安装脚本覆盖 |
| `env_isaaclab6` | 3.12.13 | Isaac Sim 6.0.1.0、MuJoCo 3.8.0、torch 2.11.0+cu130 | 原生 PhysX；其中 MuJoCo 仅供教师私有运动学/资产读取 |

版本与配置证据：[server_inventory.json](../../runs/documentation_handoff_20261016/server_inventory.json)。这是取样快照，不是持续监控。机器人依赖用原 `start.sh`，没有本轮重新安装/验证。

### 2.3 新机器安装与迁移

MuJoCo 新环境的已维护安装入口：

```bash
conda create -n r1pro-tray python=3.11 -y
conda activate r1pro-tray
cd /path/to/r1pro-airport-sim
bash scripts/setup_r1pro_server.sh --with-lerobot
python -m pip install -r requirements-experiments.txt
python -m pip check
python scripts/project.py check --compile
```

安装只在非 base Conda 内进行。`requirements-r1pro-sim.txt` 不是 OpenPI/Isaac 的通用锁文件，`pip install -e .` 也不会自动装齐本项目运行依赖。Windows 可做资源检查/部分测试，正式后台采集使用 Linux `/proc`、`fcntl` 和 EGL。

OpenPI 需要项目内 `third_party/openpi`、其中 `src` 和 `packages/openpi-client/src`、匹配的 JAX 环境、`resources/models/pi05_base` 或已校验父 checkpoint。Isaac 需要既有 `env_isaaclab6` 与已转换 USD/原生驱动审计产物；没有“一条 setup 命令能重建全部服务器”的证据。迁移前在原机非 base 环境保存 `conda list --explicit`、`python -m pip freeze`、OpenPI commit（有 Git 元数据时）、模型/数据清单和 SHA；按这些证据在新前缀重建，不直接搬 Conda 文件夹或修改 vendor。

必须带走/另行取得：项目源码与 configs、`outputs/r1pro_tray_scene`、`resources`、OpenPI 源码、合法数据及其父 split/manifest、训练父权重及 norm、实际冻结 release、当前 run 的配置/退出收据。大视频默认留服务器。不要依赖旧 humanvideo 路径。已登记 collection 含绝对路径，换服务器后新建 collection，不能改旧来源指纹冒充同一数据。

## 3. 每次启动前与后台作业

### 3.1 只读检查

```bash
"$SIM_PY" scripts/project.py check
"$SIM_PY" scripts/sync_task_spec.py --check
nvidia-smi
ps -eo pid,lstart,etime,args | grep -E 'python|isaac|train|supervise'
ss -ltnp
```

对某个已有 PID，结合其 launch JSON 核对 `/proc/<PID>/stat` 的 start_ticks、`/proc/<PID>/cmdline`、`readlink /proc/<PID>/cwd`，再读对应日志、heartbeat、stage 和实际 exit 收据。PID 存在、GPU 占用或状态文件存在，单独都不能证明作业健康。没有网络时保留最后核验时间；健康作业不重复启动，不停止无关服务。

### 3.2 新独立阶段的真实退出收据

Isaac 阶段使用 [isaacsim_stage_runner.py](../../scripts/isaacsim_stage_runner.py)，其 JSON 字段是 `argv`（数组）、`cwd`、`log`、`launch`、`receipt`、可选 `environment`。可复制 [stage_job.example.json](examples/stage_job.example.json) 到新 run，替换全部 `REPLACE_`，并事先创建日志父目录。

```bash
# JOB 指向本次已审阅的新 job.json；不是历史 job 文件。
: "${JOB:?set JOB to the reviewed new job.json}"
"$SIM_PY" "$CODE/scripts/isaacsim_stage_runner.py" --job "$JOB"
```

前台适合首个诊断。需要脱离 SSH 时，使用已有 supervisor/guardian 和单实例锁，在新 run 中保存监督进程 launch 身份；外层可用 `nohup ... > 新日志 2>&1 < /dev/null &`，但 `$!` 或 `nohup` 返回成功不是实际任务成功。runner 只负责 `wait()` 收据，**没有自动防重复/业务成功判断**，不能同时派发相同 job。新终态失败留原目录；普通恢复最多三次按各守护实现退避，物理候选不得无限重试。

### 3.3 JAX/CUDA 路径问题

当前 Isaac BC 曾因子进程漏传非 base CUDA 12.9 的 `ptxas`，误用系统 CUDA 12.0。恢复前在相同 shell 和 job 的 `environment` 中显式保留 VLA 环境路径：

```bash
export PATH="$VLA_ENV/bin:$PATH"
command -v ptxas
ptxas --version
"$VLA_PY" -c 'import jax; print(jax.devices())'
```

必须从输出确认预期编译器；路径不对就定位已有 Conda CUDA 工具链，不能修改系统 CUDA。`CUDA_VISIBLE_DEVICES` 与 JAX/XLA 内存分配按原 launch/config 保留。不要把双卡 Isaac trainer 改成单卡或为 OOM 自动更改 batch/训练方案。

## 4. 三桌单托盘 MuJoCo：生成到训练来源

当前对应长边抓放和带载交接流程。`run_three_table_single_tray.py` 只是早期空盘 Pick/Place 诊断，**完整数据入口是 `collect_three_table_full_source.py` 或 campaign/workflow**。

### 4.1 新场景与一条完整来源

```bash
# 使用新的输出目录；这些命令会生成/运行仿真。
"$SIM_PY" scripts/generate_three_table_single_tray.py \
  --output "$B/runs/NEW_SINGLE_SCENE" --seed 42

# SCENE 是上一命令产出的实际 scene JSON。
# TASK_CONFIG、PUSH_REFERENCE 必须取本次批准配置/参考场景，不使用随意猜测的旧配置。
: "${SCENE:?set SCENE}" "${TASK_CONFIG:?set TASK_CONFIG}" "${PUSH_REFERENCE:?set PUSH_REFERENCE}"
"$SIM_PY" scripts/collect_three_table_full_source.py \
  --scene "$SCENE" --config "$TASK_CONFIG" \
  --push-reference-scene "$PUSH_REFERENCE" --output "$B/runs/NEW_SINGLE_SOURCE"
```

生成器默认父来源在 `resources/single_tray_three_table_v1/source_registry`，父 manifest 和 canonical split registry 共同决定 split。更换父来源必须显式传 `--parent-scene`、`--parent-manifest`、`--split-registry`。同父场景不能跨 train/test；`seed` 不是随意改 split 的手段。

### 4.2 批量与流水线

| 入口 | 必需输入 | 执行与输出 |
|---|---|---|
| `plan_three_table_reachable_initial_poses.py` | inventory、来源/split、候选配置（见全量参数表） | 登记可达性候选；规划可达不算物理成功 |
| `collect_three_table_campaign.py` | `--selection --inventory --parent-manifest --split-registry --output` | 默认只落 plan；加 `--execute --config --push-reference-scene` 才跑物理，恢复另加 `--recover` |
| `supervise_three_table_workflow.py` | `--options` | 完整 workflow；复用必须核 options、原身份、运行阶段 |
| `guard_three_table_workflow.py` | 见源码参数 | 外部有界恢复；不是可随意叠加的第二个生产者 |
| `supervise_three_table_single_tray_training.py` | `--options`，可选 `--data-only` | 数据/训练流水线；options 由 `vla/three_table_single_tray_pipeline.py` 解释 |
| `supervise_verified_three_action_training.py` | `--options`，可选 `--guardian --recover` | 已校验 V4 三动作接 BC；不能混用 action8 旧源 |

selection 结构为 `{"schema":"airport_three_table_campaign_selection/1","variants":[{"parent_scene_id":"已登记ID","variant_seed":42}]}`。各 options JSON 不是通用同构配置；使用对应 run 的冻结版本，复制到新 run 并人工核输入/输出、source domain、相机、split、解释器与 checkpoint。不要仅改一个 output 就复用旧流程。

### 4.3 视频与导出

`render_three_table_single_tray.py` 委托 `single_tray_3table/replay.py`，原生四路回放必须验证帧/时间/轨迹误差。`records` 是完整来源资格验证后产生的 JSONL，不是任意 episode 路径列表。

```bash
: "${QUALIFIED_RECORDS:?set validated records JSONL}"
"$SIM_PY" scripts/export_three_table_single_tray_actions.py \
  --records "$QUALIFIED_RECORDS" --destination "$B/runs/NEW_ACTION3_TRAIN" \
  --repo-id airport/new_action3_train --split train
```

val/test 分别导出到新目录。检查完整来源数、三动作数、四相机文件数、ffprobe 帧数/FPS/尺寸、SHA、train-only norm 和官方 loader。环境装载不切成训练动作。完整来源和导出方法详 [数据目录](../project/DATA_CATALOG.md)、[模块地图](../project/MODULE_MAP.md)。

## 5. 三托盘 Isaac 原生流程

### 5.1 当前交接位置

令 `W=$B/runs/isaacsim_three_tray_workflow_20261015_v1`。12:44 SGT 读取的 `CURRENT_NATIVE_PIPELINE.json` 指向 `pipeline_v15`，demo 为 `demo_candidate_12`；来源为 train/val/test 共 3 条，pipeline 状态为 `deferred_by_user_for_stable_demo`、更新 0。**先真实平稳视频验证，再恢复原 BC（DEC-046）**，不能因这份启动文档自动恢复。

| 要找什么 | 位置（相对 W） |
|---|---|
| 当前指针 | `CURRENT_NATIVE_PIPELINE.json` |
| 当前流水线配置 | `pipeline_config_v15.json` |
| 阶段/守护/日志 | `pipeline_v15/pipeline_status.json`、`guardian_status.json`、`logs/`；先核文件是否存在 |
| 三 split 完整来源 | `pipeline_v15/first_batch_sources.json` |
| 冻结来源/片段/缓存 | `pipeline_v15/dataset_v1`、`three_actions_v1`、`cache_v1` |
| 训练输入/状态 | `pipeline_v15/training/inputs.json`、`training_status.json` |
| 首完整 demo 的原生记录 | `demo_candidate_12/{episode.json,qualification.json,native_trace.npz,process_exit.json}` |

`CURRENT` 指针和本页日期不是永久版本号。正式任务/训练仍引用自己的 release，不把快速接触候选替换进旧正式代码。

### 5.2 准备资产

旧 MuJoCo 三盘来源位于 `$B/runs/vla_20261005/task_complete_actions_v1`；193 条旧来源不是新 Isaac 数据。`prepare_isaacsim_three_tray.py` 负责发现旧源、父 split 和带载模板；`supervise_isaacsim_three_tray_assets.py` 串接新资产导入/检查，不会产生完整任务成功数据。

```bash
: "${PAYLOAD_TEMPLATE:?set reviewed payload-template JSON}"
"$SIM_PY" scripts/supervise_isaacsim_three_tray_assets.py \
  --run "$B/runs/NEW_ISAAC_ASSETS" --project "$B" \
  --legacy-root "$B/runs/vla_20261005/task_complete_actions_v1" \
  --payload-template "$PAYLOAD_TEMPLATE" \
  --isaac-python "$ISAAC_PY" --source-python "$SIM_PY"
```

具体子步骤：`isaacsim_scene_smoke.py --xml ... --output ...` 导入/原生步进，`isaacsim_control_preflight.py --usd ... --xml ... --output ...` 检查关节映射与驱动；质量/惯量、夹指 mimic、桌体接触过滤、相机与载荷必须审计。`--restore-source-base-drives`、`--native-coat` 等只按已登记资产方案使用。资产成功不等于控制/数据成功。

### 5.3 完整原生 episode

```bash
# ISAAC_SCENE_ROOT 必须是完成原生导入/驱动审计的 scene root。
: "${ISAAC_SCENE_ROOT:?set verified native scene root}"
"$ISAAC_PY" "$CODE/scripts/run_isaacsim_three_tray_task.py" \
  --scene-root "$ISAAC_SCENE_ROOT" --output "$B/runs/NEW_ISAAC_EPISODE" \
  --seed 42 --episode-id new_unique_episode_id
```

正式收集用第 3.2 节 runner 包裹该命令，将 receipt 写入 episode 的 `process_exit.json`；父目录事先存在、episode 输出目录由任务新建。需要接受 Isaac EULA 时沿用已批准环境设置，不把安装成功当成任务成功。`--no-video-diagnostic` 跳过媒体，仅控制诊断，验收器必须拒绝其进入训练。

任务输出 `status.json/progress.json`、`native_trace.npz`、原生接触/子步日志、`observer_events.json`、`episode.json`、`qualification.json`、四路 MP4、encoder 退出信息与失败证据。教师只私有 IK 规划，实际动作和力来自 PhysX；不得用教师代替模型评测。

```bash
: "${NATIVE_REGISTRY:?set parent split registry}"
"$SIM_PY" scripts/audit_isaacsim_three_tray_demo.py \
  --case "$B/runs/NEW_ISAAC_EPISODE" --registry "$NATIVE_REGISTRY" \
  --output "$B/runs/NEW_ISAAC_AUDIT.json"
```

### 5.4 冻结、三动作分片、缓存和监督

```bash
# EPISODES_JSON：完整闭合 episode 绝对路径的 JSON 数组，含合法 train/val/test。
: "${EPISODES_JSON:?set qualified episode-list JSON}" "${NATIVE_REGISTRY:?set registry}"
"$SIM_PY" scripts/prepare_isaacsim_dataset.py --mode freeze \
  --registry "$NATIVE_REGISTRY" --episodes "$EPISODES_JSON" --output "$B/runs/NEW_ISAAC_DATA"
"$SIM_PY" scripts/prepare_isaacsim_dataset.py --mode clips \
  --registry "$NATIVE_REGISTRY" --manifest "$B/runs/NEW_ISAAC_DATA/manifest.json" \
  --output "$B/runs/NEW_ISAAC_CLIPS"
"$SIM_PY" scripts/prepare_isaacsim_dataset.py --mode cache \
  --registry "$NATIVE_REGISTRY" --manifest "$B/runs/NEW_ISAAC_DATA/manifest.json" \
  --output "$B/runs/NEW_ISAAC_CACHE"
```

完整三盘每来源 9 动作段；当前 3 来源应按 manifest 核 27 段，四相机文件数是另一种计数。`export_isaac_episode_preview.py` / `watch_isaacsim_episode_preview.py` 的单来源预览不等于三 split 训练批次。

自动流程：`supervise_isaacsim_three_tray_task.py --config <新pipeline_config>`，外守护 `guard_isaacsim_three_tray_task.py --config <同配置> --adopt <真实supervisor_launch.json>`。配置字段含 `run/project/demo/demo_exit/demo_identity/registry/isaac_python/source_python/vla_python/parent_checkpoint/parent_status/cases`，可选 `reuse_validated_episodes/evaluation_command`。真实参考见 [服务器快照](../../runs/documentation_handoff_20261016/server_inventory.json) 中 pipeline_config_v15；不得直接重放该旧配置。

监督链：实际 demo wait0 → validate_episode → held-out 完整源 → 三 split → freeze → clips → cache → train prepare → 10/100/1000/10000/100000 更新里程碑。`expand_isaacsim_three_tray.py` 和 `guard_isaacsim_expansion.py` 管后续独立扩量版本；不改正在训练的数据。没有合格 `evaluation_command` 时状态明确待模型评测，不能调用 NativeTeacher 补出“模型成功”。

### 5.5 快速取放/平稳性单独运行

`run_isaacsim_fast_pickplace.py --config <case.json>` 为一例，`supervise_isaacsim_fast_pickplace.py --config <campaign.json>` 为预登记多位姿，`audit_isaacsim_fast_pickplace.py --case ... --output ...` 独立复核，`finalize_isaac_fast_pickplace.py` 汇编已闭合片段。不同脚本 config 结构不同，完整参数看目录。

case 配置必须核 `output/scene_root/seed/case_id/tray_pose/lab_assets`，控制候选额外字段按登记版本保留。`record_cameras=false` 是无视频物理探针；不能称视频完成。各动作 60×20Hz 原生帧/各 3 秒，预备站位与双臂准备另计；报告全过程倾角、角速、滑移和接触，不只看 `passed` 端点。当前指针 `$B/runs/ISAAC_FAST_PICKPLACE_CURRENT.json` 的 active_probe 与旧视频版本分开，详 [平稳性专题](../project/ISAAC_FAST_PICKPLACE_20261016.md)。

## 6. 训练与模型评测

### 6.1 环境与输入约定

所有训练使用 non-base VLA 环境，真机数据来源 `real_world/user_provided`，仿真来源 `simulation/program_generated`。`mobile19` 为 14 臂关节 + 2 夹爪 + 3 底盘通道；模型夹爪单位 m，真机接口总开口 mm，绝不能做 100→80 比例缩放。norm 只用 train，父场景/原录制哈希 split 保持隔离。

| 训练入口 | 输入/启动方式 | 输出与限制 |
|---|---|---|
| `train_pi05_airport.py` | `--config <TrainingSpec.json>`；`--normalize-only` 只计算归一化 | 通用旧 OpenPI mobile19 LoRA；历史 action8/skillmerged 配方按原 scope |
| `train_pi05_accelerated.py` | `--spec ... --parent-status ... --prepare-cache`，再 `--stop-after N`，恢复可 `--resume` | 项目缓存与里程碑；父权重、新 optimizer/恢复语义明确 |
| `train_pi05_isaac_three_tray.py` | `--run <training> --mode prepare/train --stop N` | 原生冻结缓存，**两张可见 GPU**；10/100/1000/10000/100000 |
| `run_pi05_real_only.py` | `--run <新目录> --mode prepare/train/evaluate/supervise` | 纯真机 102/13/19、10000 更新；初始化为 `resources/models/pi05_base` |
| `run_real_sim_pickplace.py` | `--run ... --mode prepare/mse/train/simulate/supervise`，MSE 加 `--model pi05/affordvla/mixed_pi05` | 历史 90/10；supervise 含旧 Afford 评测步骤，不作为当前默认训练流程 |
| `train_pi05_real_sim50.py` | `--run <新目录> --mode prepare/train/evaluate/supervise` | 每 batch8 真4/仿4，10000 更新，supervise 固定 GPU0；要先确认 GPU0 可用 |
| `compare_pickup120.py` / `resume_afford_pi05_comparison.py` | 旧比较专用，见目录/源码 | 120 拿取 scope，含固定服务器路径；不是三动作整体训练 |

配置全集见 [SCRIPTS.md](SCRIPTS.md)。纯真机、90/10、50/50 脚本仍引用既有服务器缓存/父模型，`--run` **不是自带新数据路径的通用训练接口**；迁移先核源码常量和 `inputs/integrity/frozen_data_selection`。不修改原模型、旧数据或已保存 optimizer。

### 6.2 新纯真机或 50/50 实验模板

以下是人工选择新实验时的命令，不是对现有已完成实验的重启指令。先核 GPU 空闲、原缓存存在且 SHA 一致。

```bash
export PATH="$VLA_ENV/bin:$PATH"
export XLA_PYTHON_CLIENT_PREALLOCATE=false
export WANDB_MODE=disabled
# GPU_ID 由本次资源核验确定，纯真机路径可用此选择。
: "${GPU_ID:?set the allocated GPU}"
export CUDA_VISIBLE_DEVICES="$GPU_ID"
"$VLA_PY" scripts/run_pi05_real_only.py --run "$B/runs/NEW_REAL_ONLY" --mode supervise
```

50/50 脚本内部固定 GPU0；确认允许使用 GPU0 后，在**新的已创建 run** 使用：

```bash
mkdir "$B/runs/NEW_MIX50"
"$VLA_PY" scripts/train_pi05_real_sim50.py --run "$B/runs/NEW_MIX50" --mode supervise
```

supervisor 自带子阶段日志、launch/exit 和有限恢复，但并非所有 supervisor 都有外层 guardian。50/50 既有历史实验实际 10000 步完成，细节见 [50/50专题](../project/PI05_MIX50_20261015.md)。不得因为本页有命令而重新跑已完成训练。

### 6.3 原生 Isaac BC 的输入与恢复

`training/inputs.json` 包含 `cache/manifest/registry/parent_checkpoint/parent_status` 五项绝对路径。准备阶段验证三 split/三动作和父权重，写 `norm.json/sample_indices.npy/integrity.json/preparation_status.json`。

```bash
# TRAIN_RUN 为新 run 的 training 目录，inputs.json 已绑定合法冻结输入。
: "${TRAIN_RUN:?set reviewed training directory}"
"$VLA_PY" scripts/train_pi05_isaac_three_tray.py --run "$TRAIN_RUN" --mode prepare
# 确认两张 GPU 按原配置可见、CUDA 编译器正确，且恢复前置条件已满足。
"$VLA_PY" scripts/train_pi05_isaac_three_tray.py --run "$TRAIN_RUN" --mode train --stop 10
```

后续 100/1000/10000/100000 沿用同一训练 run 的已保存 state；保留原 data integrity 与 optimizer。checkpoint 数字一般从 0 开始，目录 `9999` 对应 10000 更新，核对应状态/元数据而非仅看目录名。当前 pipeline_v15 尚等待平稳视频；恢复须新阶段执行收据、原数据/权重/配置保持，不删除旧失败日志来骗监督器跳过失败。

整理期间源码新增了 `resume_isaacsim_bc_after_video.py --config <恢复配置>`：等待真实视频审阅文件、验 evidence SHA、核同一冻结 inputs/norm/sample_indices、用独立阶段收据恢复。配置必须含 `run/training/original_training/review/project/compiler_bin/vla_python/training_code`。这是当前源码入口的静态核对，不代表本轮已经部署或通过恢复；不要人工伪造 `approved_for_original_BC_resume`，也不要以无视频探针代替审阅。

### 6.4 测试不是训练 loss

MuJoCo 模型批评测入口 `evaluate_three_table_single_tray_pi05_batch.py` 配套 protocol、checkpoint identity、sim/model Python 和输出目录，默认计划与 `--execute` 区分。固定场景诊断用 `run_vla_fixed_scene.py` 或 `run_three_table_pi05_free_run.py`；只测独立动作或 free_run 的结果不能作为三动作全程成功率。`compare_pi05_closed_loop.py` 是已登记两模型比较；不要随意换模型却保留旧身份。

原生三盘纯模型评测未闭合前明确 pending。禁止 IK、逆动力学、教师或自动纠正回退。未执行 DAgger 不得将 BC 命名为 DAgger。检查 checkpoint 存在/有限 loss/MSE 只能证明对应阶段，物理成功要有真实执行、资格结果、视频和实际退出。

## 7. 真机：workstation server → 停止控制 → robot client

### 7.1 当前实核与拓扑

12:44 SGT 的进程/端口只读快照：LAN relay PID2686671（start_ticks8719820）监听 `10.42.0.191:8095/8096`；**未发现 `serve_pi05_galaxea_robot.py` 模型进程、键盘控制进程或 `100.104.0.108:8095/8096` 后端监听**。因此不能写“两个模型已经在线”。本轮没有尝试模型推理/机器人动作；后续启动先重新检查。

| 服务 | workstation 地址/配置 | robot 配置 |
|---|---|---|
| mixed，旧 90/10 完成模型 | `100.104.0.108:8095`，`runs/galaxea_robot_deploy_20261013_v3/mixed/server_config.json` | `config_pi05_mixed_gripper80_lan_20261013.toml` → `10.42.0.191:8095` |
| real-only | `100.104.0.108:8096`，同 run 的 `real_only/server_config.json` | `config_pi05_real_only_gripper80_lan_20261013.toml` → `10.42.0.191:8096` |
| 共享命令停止 gate | `runs/galaxea_robot_deploy_20261013_v2/operator_control.json` 与同目录 heartbeat | server 每次请求检查，失联/锁定拒绝 |
| LAN relay | `runs/galaxea_robot_lan_transport_20261013_v1/forward_galaxea_lan.py` | 透明转发；TCP 可通不代表模型 ready |

新训练的 50/50 模型未自动替换 mixed 端点。robot 的基频配置 20Hz、action_steps5 只是配置，实际控制周期须读录制时间戳。

机器人 LAN 配置历史核验副本：[mixed TOML](examples/mixed.robot.lan.example.toml)、[real-only TOML](examples/real_only.robot.lan.example.toml)。它们来自2026-10-13已部署记录；本轮未声称已与机器人当前文件重新逐字比对。

### 7.2 启动 workstation 模型服务

旧 release `releases/galaxea_robot_deploy_20261013_v3` 为已部署模型适配器。`serve_pi05_airport.py` 是仿真协议，不能替代真机的 `serve_pi05_galaxea_robot.py`。旧 v3 run 内已有 raw_chunk 和 commands 日志，**不要原样重启进旧目录**：序号会从 0 开始，可能覆盖 raw_chunk。给每个模型创建新的运行子目录，复制并核对 JSON 配置；权重及训练状态仍只读引用原路径。

```bash
export DEPLOY_CODE="$B/releases/galaxea_robot_deploy_20261013_v3"
export ROBOT_RUN="$B/runs/galaxea_robot_REPLACE_NEW_ID"
mkdir "$ROBOT_RUN"
mkdir "$ROBOT_RUN/mixed" "$ROBOT_RUN/real_only"
cp "$B/runs/galaxea_robot_deploy_20261013_v3/mixed/server_config.json" "$ROBOT_RUN/mixed/server_config.json"
cp "$B/runs/galaxea_robot_deploy_20261013_v3/real_only/server_config.json" "$ROBOT_RUN/real_only/server_config.json"
```

完整配置样例：[mixed](examples/mixed.server.example.json)、[real-only](examples/real_only.server.example.json)。保持 `training_status` 指向已验证 10000 更新的模型，`execute_steps=5`、`gripper_range_mm=[0,80]`、host/port 与 robot/relay 一致。停止 gate 沿用原 v2 绝对路径；如果另建 gate，两个 server 和操作终端必须一起改，不混用旧终端。

在前台终端分别启动**需要使用的模型**，GPU 由本次资源核验指定；同时加载两个模型须确认显存，不能停止其他训练来腾资源：

```bash
: "${GPU_ID:?set allocated GPU}"
CUDA_VISIBLE_DEVICES="$GPU_ID" "$VLA_PY" "$DEPLOY_CODE/scripts/serve_pi05_galaxea_robot.py" \
  --config "$ROBOT_RUN/mixed/server_config.json"
# 另一模型在另一个终端，或前一个完全退出后启动：
# CUDA_VISIBLE_DEVICES="$GPU_ID" "$VLA_PY" "$DEPLOY_CODE/scripts/serve_pi05_galaxea_robot.py" \
#   --config "$ROBOT_RUN/real_only/server_config.json"
```

成功标准：预热结束、`server_status.json` 写出 checkpoint/norm 身份与 `ready_operator_stop_latched`，实际地址监听且进程身份匹配。`ready_operator_stop_latched` 表示就绪但仍锁定，不能用启动 server 代替现场解锁。后台运行时也要按第 3 节保存独立日志与真实退出收据。

### 7.3 保持键盘停止控制终端

本机新开一个交互终端，直接登录服务器：

```powershell
ssh -t michelle@xinmatrix
# 或：ssh -t michelle@100.104.0.108
```

在该服务器终端执行（使用绝对路径，不依赖其他终端的变量）：

```bash
/home/michelle/miniconda3/envs/r1pro-vla/bin/python \
  /home/michelle/haoze/r1pro-airport-sim/releases/galaxea_keyboard_control_20261013_v3/control_galaxea_servers.py \
  --control-file /home/michelle/haoze/r1pro-airport-sim/runs/galaxea_robot_deploy_20261013_v2/operator_control.json
```

只开一个控制终端。默认 STOP；现场准备完毕才人工按 `R`。`E`/空格锁定，`Q`/退出锁定；心跳超 1 秒 server 拒绝命令。拒绝后不自动恢复，按 R 后需重启 client。该功能是命令停止，不能撤回在途或最后目标，硬件急停独立保留。

### 7.4 LAN relay

若已有健康 relay，直接复用。只有确认 relay 已退出、地址属于 workstation、端口空闲时才新建 run 启动；脚本把 lock/status 写在**脚本所在目录**，所以用新 run 中的副本：

```bash
export RELAY_RUN="$B/runs/galaxea_robot_lan_REPLACE_NEW_ID"
mkdir "$RELAY_RUN"
cp "$B/scripts/forward_galaxea_lan.py" "$RELAY_RUN/forward_galaxea_lan.py"
"$SIM_PY" "$RELAY_RUN/forward_galaxea_lan.py"
```

源码固定监听 `10.42.0.191:8095/8096` 并转发 `100.104.0.108` 同端口。换网段应新版本显式配置并重新做协议/时延检查，不直接沿用旧 IP。此次发现历史 relay 使用系统 Python3 运行，仅记录现状；本手册新启动使用非 base Python，不修改其旧进程。

### 7.5 机器人本体启动

机器人 SDK/驱动和相机使用现场原有流程；本项目并未提供一个已核实的“机器人开机→全硬件驱动启动”脚本。`source start.sh` 是环境入口，不保证驱动启动。接手现场需确认原厂驱动/相机启动入口，不能用 VLA client 去猜测发布硬件指令。

在机器人已登录终端，只读检查环境：

```bash
cd /home/nvidia/GalaxeaVLA/experiments/r1pro
source ./start.sh
export FASTRTPS_DEFAULT_PROFILES_FILE=/opt/galaxea/find_server/super_client_configuration_file.xml
ros2 topic list --no-daemon
./vla status
```

此前 fresh shell 漏 DDS 配置会看不到话题，不能直接判定 SDK 未运行。核现场反馈/相机有效、模型后端 ready、原 filter 开启、初态和工作空间准备好，保持停止终端及现场急停可用。一次只运行一个 client/一个模型。

当前需要 SDK 故障反馈时优先：

```bash
./vla_sdk_diagnostics pick        # mixed：Pick up the tray
./vla_sdk_diagnostics place       # mixed：Place the tray
./vla_sdk_diagnostics pick real   # real-only
./vla_sdk_diagnostics place real
```

常规录制兼容 v4 入口仍保留：`./vla pick`、`./vla place`、`./vla pick real`、`./vla place real`。这些是机器人目录内的部署脚本，**不是本项目根 scripts/galaxea_client_oneclick.sh 的就地执行命令**；后者部署后根据自身目录寻找 start.sh/config/run wrapper。不要在本机或服务器项目的 scripts/ 下运行它来控制机器人。

若一键别名缺失，先核部署文件，再使用对应 wrapper：

```bash
python run_pi05_record_compat_20261013_v5.py \
  --config config_pi05_mixed_gripper80_lan_20261013.toml --record
```

直接 wrapper **不负责切换任务文本**；在没有其他 client 时，将 `scheduler/instruction/instruction.txt` 明确设为所需精确文本。更推荐一键入口先检查单实例再写文本。不要在活动 client 执行期间改 instruction。

换模型/任务：原 client `Ctrl+C` 并等录制收尾 → 核旧进程结束 → 核停止状态和新任务 → 人工决定是否 R → 启动新 client。filter 拒绝或 SDK 异常后保留日志，不无人自动重跑。

### 7.6 真机合同与留证

原 `run.py`、`scheduler/scheduler.py`、`scheduler/joint_command_filter.py` 不改。当前限值来自已批准配置：max_step0.1rad、velocity1.5rad/s、tracking0.25rad、观测年龄0.5秒，夹爪0..80mm。server 保存 raw m 值和提交 mm/限幅证据；client 原 filter 继续生效。记录：`commands.jsonl/raw_chunk_*.npz/server_status.json`、client 录制目录、`joint_filter_diagnostics.jsonl`、v5 `sdk_fault_window.json`、异常与真实退出。SDK effort 单位未标定，不能直接叫力矩。现有历史尝试不代表真机完整任务通过。

部署历史与失败原因见 [真机部署专题](../project/REAL_ROBOT_DEPLOYMENT_20261013.md)。本轮未在机器人上重新核验 v5 文件或发控制命令；现场文件缺失时从原部署记录恢复/对比 SHA，不能默默退回已知录制失败的原 run.py。

## 8. real2sim 离线示范回放

入口 `replay_real2sim.py` 要求 `--source-manifest --scene-xml --urdf --output`，可选 `--per-task 1 --video`。配准用已批准、来源绑定的 `--registration <目录>`；四指凸体包用 `--finger-collision-bundle`。不要为了回放成功私自调托盘宽度、驱动增益或换握法。

```bash
: "${REAL_MANIFEST:?set source manifest}" "${SCENE_XML:?set scene XML}" "${ROBOT_URDF:?set source URDF}"
"$SIM_PY" scripts/replay_real2sim.py --source-manifest "$REAL_MANIFEST" \
  --scene-xml "$SCENE_XML" --urdf "$ROBOT_URDF" \
  --output "$B/runs/NEW_REAL2SIM_REPLAY" --per-task 1 --video
```

`validate_real2sim.py/audit_real2sim.py`、`fit_real2sim_registration.py/fit_real2sim_torso.py`、`diagnose_real2sim_held_pose.py` 为配套检查/拟合；具体默认值见脚本表。summary 的 replay_completed 和 exit0 不是成功抓放。视频可能是 640×360/30fps 预览，不能称四路原生训练视频。源时间轴、20 通道与域标记见 [REAL2SIM](../project/REAL2SIM.md)。

## 9. 历史入口和独立对比

旧多盘 400 场景在 [WORKFLOW.md](../WORKFLOW.md) 保留完整命令：`project.py fourcam` → `python -m r1pro_teleop.airport_fsm prepare/preflight/generate/export/report`，config 为 `airport_primitives3(_smoke).json`，smoke12/formal400。该命令不是当前三动作新训练来源的自动入口。旧 v50 历史结果和 `resources/scenes` 本地副本不是同一验证版本。

`python -m r1pro_teleop.experiments` 与 `control_regression.py/control_ablation.py` 用于隔离控制实验，文档 [EXPERIMENTS.md](../EXPERIMENTS.md)。`scripts/diagnose_* / probe_* / diagnostic_* / analyze_* / inspect_* / test_diagnostic_*` 中许多绑定旧 case/version，有的导入/运行就写产物；仅按 catalog 定位后读源码，不批量执行或拿 `--help` 探测。

`generate_pickup_lerobot.py`、`compare_pickup120.py` 和 `resume_afford_pi05_comparison.py` 是独立 pickup200/120。`supervise_action8_training.py/evaluate_action8_checkpoint*.py`、`materialize_complete_task_actions*.py` 保留旧八文本实验；`native32_expansion_pipeline.py` 保留旧数据扩量。它们不是当前 Isaac 三盘采集/训练的同义入口。

历史本机计划任务不作为交接依赖；是否存在必须现场查，文档不宣称自动常驻刷新。进度统一按下一节在服务器查询。

## 10. 查看进度、媒体、停止与交付

先通过 `ssh michelle@xinmatrix` 或 `ssh michelle@100.104.0.108` 登录，设置第2.2节的变量，再运行服务器端 Python 监控。不传 `--watch` 查询一次；需要持续刷新时加 `--watch 10`（秒）。

```bash
"$SIM_PY" scripts/watch_pi05_mix50.py --run "$B/runs/real_sim50_pi05_20261015_v1"
"$SIM_PY" scripts/watch_pi05_real_only.py --run "$B/runs/real_only_pi05_20261012_v1"
"$SIM_PY" scripts/watch_real_sim_transfer.py --run "$B/runs/real_sim_pickplace_20261009_v3"
"$SIM_PY" scripts/watch_vla_comparison.py --run "$B/runs/afford_pi05_pickup120_20261008_v2"
```

Isaac 当前流程、BC恢复和快速视频通过实际指针定位，避免把旧协调器延期状态当作当前训练。以下在服务器读取一次，只输出状态文件：

```bash
"$SIM_PY" - <<'PY'
import json
from pathlib import Path
b = Path('/home/michelle/haoze/r1pro-airport-sim')
w = b/'runs/isaacsim_three_tray_workflow_20261015_v1'
def read(path):
    return json.loads(path.read_text()) if path.is_file() else None
pipeline = read(w/'CURRENT_NATIVE_PIPELINE.json')
resume = read(w/'CURRENT_NATIVE_BC_RESUME.json')
fast = read(b/'runs/ISAAC_FAST_PICKPLACE_CURRENT.json')
result = dict(pipeline_pointer=pipeline, resume_pointer=resume, fast_pointer=fast)
if pipeline:
    result['pipeline_status'] = read(w/pipeline['pipeline']/'pipeline_status.json')
if resume:
    root = Path(resume['root'])
    result['resume_status'] = read(root/'pipeline_status.json')
    result['training_status'] = read(root/'training/training_status.json')
if fast:
    root = Path(fast['run'])
    result['fast_status'] = read(root/'status.json')
    result['fast_audit'] = read(root/'audit_summary.json')
print(json.dumps(result, indent=2))
PY
```

`Ctrl+C` 只停止当前监控，不等于停止远程作业。只同步 JSON/TXT；视频与轨迹留服务器。根 `*_STATUS.txt`、`*_LOCATION.txt`、`*_VIDEO_PATHS.txt` 是最近一次快照，每个实际视频路径单独一行；失败、诊断、历史视觉版本分清。

只读媒体 `serve_isaacsim_media.py --root <允许浏览的run根> --state-dir <新状态目录> --bind 100.104.0.108 --port <空闲端口>` 支持 Range/HEAD。不要使用项目根或 `.secrets` 为媒体根，不擅自公开到公网；已有健康8776复用。网页能播放并不等于媒体验收或模型成功。

| 阶段 | 需要核对的证据 |
|---|---|
| 初始化/等待 | phase/heartbeat、真实进程身份；没有实际梯度更新就报告 0 |
| 数据就绪 | 完整来源资格、原生媒体/轨迹帧对齐、三 split、冻结 manifest/SHA |
| 训练发生 | actual_updates/updates>0、有限指标、实际进程/日志时间 |
| 保存模型 | checkpoint 元数据/params、norm、optimizer 及保存收据 |
| 物理模型测试通过 | 无回退的实际执行，分母/任务定义、result/视频/exit 闭合 |
| 进程结束 | 实际 child wait 返回码；`complete` 仍需单独检查 task success |

常见故障：

| 现象 | 先查什么 | 正确后续 |
|---|---|---|
| 锁冲突或日志 already exists | 原 PID/birth/argv/cwd、日志是否仍增长 | 健康作业复用，终态另建 run；不删锁掩盖活进程 |
| LAN TCP 通但模型无响应 | 后端 tailnet 端口/server_status，而非只看 relay | 按第7节核模型是否 ready，勿让 robot 盲目重试 |
| STOP/stale heartbeat | 唯一操作终端、control generation、heartbeat | 现场确认后 R 并重启 client，不跳过 gate |
| ROS 话题空 | source start.sh、FASTRTPS 配置、真实 SDK/相机状态 | 先排发现环境；不宣称机器人已坏或直接发控制 |
| JAX 初始化报 ptxas 错误 | 子进程 PATH 和编译器版本 | 修环境传递，新执行收据，原数据/模型不改 |
| 数据 freeze 拒绝 | exit、qualification、原生视频、父 split、重复 episode_id | 保留失败源；修普通实现问题后新目录执行 |
| PhysX 动作终点通过但盘不稳 | 全程姿态/滑移/接触/视频 | 仍按平稳性未通过报告，不恢复等待中的 BC |

运行结束交接至少提供：scope、版本/配置/来源 SHA、完整来源/动作/相机数量、split、实际步数和 checkpoint、无回退评测、失败现场、PID 最后核验时间、日志/产物目录与 TXT 视频索引。禁止把计划、缓存、loss 或历史小样本当新任务成功。

## 11. 文档维护与验证范围

本轮验证范围：本机源码静态清单、链接/配置示例/命令参数核对、非 base 资源与规范检查、服务器只读环境/配置/端口取样。静态检查报告见 [validation.json](../../runs/documentation_handoff_20261016/validation.json)。没有通过重跑全实验验证所有历史入口；机器人侧启动命令来自既有部署证据，现场 SDK 启动入口仍待现场确认。

本机 `project.py check` 实际检查12 smoke/400 formal、121952条资源引用，通过；`sync_task_spec.py --check` 通过。结果摘录见 [local_check_receipt.json](../../runs/documentation_handoff_20261016/local_check_receipt.json)，不含模型编译或物理预检通过的声明。

```powershell
.\.conda\experiment\python.exe scripts/build_handoff_catalog.py --write
.\.conda\experiment\python.exe scripts/build_handoff_catalog.py --check
.\.conda\experiment\python.exe scripts/sync_task_spec.py --check
# 新聊天加入交互档案时显式追加本线程并保留 manifest 已有父线程：
.\.conda\experiment\python.exe scripts/export_project_interactions.py --thread EXISTING_PARENT_ID --thread THIS_THREAD_ID
```

修改控制/场景/数据导出/相机或任务合同后，还须人工更新统一规范对应步骤、状态与失败规则，再 `sync_task_spec.py --write` 和 `--check`。本次仅文档/静态目录生成器，不改上述行为，不刷新规范指纹来掩盖其他未核改动。
