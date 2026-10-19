# R1 Pro Airport Tray：项目交接与启动

机场安检托盘仿真、数据生成、π0.5 训练和 Galaxea R1 Pro 部署项目。保留三桌单托盘 MuJoCo 主线、独立三托盘 Isaac 原生流程，以及真机示范离线训练/回放。不同来源、任务范围和实验版本分别验收。

**接手先读 [完整运行与交接 README](docs/handoff/README.md)**：包含服务器直接连接、环境、启动顺序、生成/导出、训练、模型服务、机器人 client、停止与故障处理。本次交接入口见 [脚本与配置索引](docs/handoff/SCRIPTS.md)，参数默认值和源码 SHA 见 [机器可读目录](docs/handoff/script_catalog.json)。

整理日期：2026-10-16（Asia/Singapore）。本轮核对代码、配置和服务器只读状态，没有重启训练/仿真或执行机器人动作。

**英文交接版：** [专业英文 PDF（43页）](output/pdf/R1Pro_Project_Review_and_Operations_Handover_EN.pdf)，先总结探索、实验与证据边界，再列服务器、生成、训练和机器人操作；[可编辑英文源稿](docs/handoff/README_EN.md)。PDF采用注明时间的证据截点，不覆盖下方或其他线程后续实测。

## 快速导航

**网页使用：** [Scene Studio 使用 README](docs/site/README.md) — MSE 图表入口、场景编辑、训练配比、自动 VLA/MSE、下载与常见问题。

**零基础详细教程：** [从场景到训练和评估的完整操作手册](docs/site/USER_GUIDE_ZH.md) — 每一步点哪里、填什么、怎么看成功；讲清新场景进入训练集还需哪些服务器操作。

| 要做的事 | 阅读入口 |
|---|---|
| 在新机器安装、连接 GPU 服务器 | [交接手册第2节](docs/handoff/README.md#2-机器路径网络和环境) |
| 检查进程、GPU、单实例、后台退出与 CUDA | [第3节](docs/handoff/README.md#3-每次启动前与后台作业) |
| 生成单托盘 MuJoCo 场景/完整任务/三动作数据 | [第4节](docs/handoff/README.md#4-三桌单托盘-mujoco生成到训练来源) |
| Isaac 三托盘原生任务、媒体、冻结与缓存 | [第5节](docs/handoff/README.md#5-三托盘-isaac-原生流程) |
| π0.5 三动作、纯真机、混合训练与评测 | [第6节](docs/handoff/README.md#6-训练与模型评测) |
| workstation 模型服务与机器人启动 | [第7节](docs/handoff/README.md#7-真机workstation-server--停止控制--robot-client) |
| real2sim 示范回放 | [第8节](docs/handoff/README.md#8-real2sim-离线示范回放) |
| 历史400场景、action8、pickup120/200实验 | [第9节](docs/handoff/README.md#9-历史入口和独立对比) |
| 看进度、日志、视频，交付与排障 | [第10节](docs/handoff/README.md#10-查看进度媒体停止与交付) |
| 查交接脚本、子命令、配置 | [交接索引](docs/handoff/SCRIPTS.md) |

## 接手时的实际状态

2026-10-16 **12:44 SGT** 只读服务器取样，证据见 [server_inventory.json](runs/documentation_handoff_20261016/server_inventory.json)：

- Isaac 正式三盘指针是 `pipeline_v15`，已登记3条完整来源；状态 `deferred_by_user_for_stable_demo`，本轮实际梯度更新0。按用户决定，先验证平稳取放视频，再恢复原 BC。
- 快速取放旧视频指针和当前无视频 `active_probe` 分开；端点通过不等于全过程平稳，也不能混入正式训练来源。
- 机器人 LAN relay 仍监听 `10.42.0.191:8095/8096`；本次未发现两个模型后端服务和键盘控制进程。TCP 端口可连接不等于模型在线，实际启动顺序见手册第7节。
- 机器人本体驱动/相机与现场状态本轮没有重新核验。历史真机尝试、离线 MSE 和训练完成都不代表完整真机任务通过。

这些是最后取样，不是常驻监控。实时查询先直接登录服务器，再按[交接手册第10节](docs/handoff/README.md#10-查看进度媒体停止与交付)执行只读命令；更细实验结果见 [实验状态](docs/project/EXPERIMENT_STATUS.md)、[当前 memory](memory/CURRENT.md) 和实际运行产物。

## 最小只读接手操作

Windows 项目目录：

```powershell
Set-Location C:\Users\HAOZEW\Documents\code\r1pro-airport-sim
.\.conda\experiment\python.exe scripts/project.py check
.\.conda\experiment\python.exe scripts/build_handoff_catalog.py --check
.\.conda\experiment\python.exe scripts/sync_task_spec.py --check
ssh michelle@xinmatrix
# 主机名不能解析时：ssh michelle@100.104.0.108
```

使用 SSH 默认22端口，在提示时交互输入由负责人提供的密码。密码不保存在项目文档或命令中；客户端须能访问 `100.104.0.108` 所在网络。

GPU 服务器（已连接的 Linux shell）：

```bash
cd /home/michelle/haoze/r1pro-airport-sim
/home/michelle/miniconda3/envs/r1pro-tray/bin/python scripts/project.py check
nvidia-smi
ss -ltnp
```

安装只用非 base Conda。`r1pro-tray` 用于 MuJoCo/数据，`r1pro-vla` 用于 OpenPI，`env_isaaclab6` 用于 Isaac；三者版本不同，不能用一个安装脚本覆盖所有环境。首次新机器迁移还需要项目内资源、OpenPI、数据和模型，详手册第2节。

## 三条动作与验收边界

训练文本仅 `Pick up the tray`、`Place the tray`、`Flush tray to the left`。取放由双臂分别夹两条相对长边，在桌前联合搜索底盘站位/朝向与抓姿；可桌间移动，禁止桌侧操作。空盘放下后由环境装载书包、外套、笔记本；Flush 为右推→左稳定夹持→右松→真实托盘左移至少3cm→左松与稳定支撑。装载不进训练。

精确流程、已有5cm/2cm容差的适用范围、失败门和计时边界见 [统一规范](docs/SCENE_TASK_SPEC.md)，不从旧文档推导新阈值。保留真实接触动力学、碰撞、相机方向、原生视频、split 和失败证据。模型评测禁止隐式教师/IK/逆动力学回退；BC 不称 DAgger。

完整来源数、动作片段数、相机文件数分别统计。旧 collection、冻结 release、清单、checkpoint 保持不变；新代码/配置/资源用新 run。视频与轨迹默认留服务器，本机只同步 JSON/TXT。真机操作按现场授权和第7节流程，不能把过去实验授权当成无人控制授权。

## 项目结构

| 路径 | 内容 |
|---|---|
| `scripts/` | 项目、生成、训练、评测、服务、监测与诊断入口；用途见全量索引 |
| `r1pro_teleop/single_tray_3table/` | 三桌单盘控制、采集、观察器、模型执行、监督与恢复 |
| `r1pro_teleop/real2sim/` | 真机回放与 Isaac 资产/原生运行/三盘教师与观察器 |
| `r1pro_teleop/vla/` | 数据资格、三动作切片、缓存、训练、模型协议与执行 |
| `r1pro_teleop/airport_fsm/`、`experiments/` | 历史多盘基线、复用原语与隔离实验 |
| `configs/` | 场景/控制/训练配置；包含历史候选，不全部适用于当前任务 |
| `resources/`、`outputs/r1pro_tray_scene/` | 项目内场景、模型/标定/视觉/网格资源；不依赖原 humanvideo |
| `tests/` | 核心逻辑与数据/部署接口回归 |
| `runs/`、服务器 `releases/` | 独立运行、实测证据与冻结代码；非通用启动目录 |
| `docs/handoff/` | 可交接运行文档、全量脚本/配置目录与配置示例 |
| `docs/project/`、`memory/` | 模块/数据/实验专题、当前快照、决策和交互归档 |

## 维护与历史

协作规则：[AGENTS.md](AGENTS.md)。开始工作按 [docs/INDEX.md](docs/INDEX.md)、[统一规范](docs/SCENE_TASK_SPEC.md)、[CURRENT](memory/CURRENT.md)、[DECISIONS](memory/DECISIONS.md) 读取当前边界。模块、数据和证据入口：[MODULE_MAP](docs/project/MODULE_MAP.md)、[DATA_CATALOG](docs/project/DATA_CATALOG.md)、[EXPERIMENT_STATUS](docs/project/EXPERIMENT_STATUS.md)。

新增/修改脚本后运行 `python scripts/build_handoff_catalog.py --write` 和 `--check`。控制/场景/相机/数据导出变化还要人工同步规范再执行 `sync_task_spec.py --write/--check`。每轮结束按 [Memory规则](docs/governance/MEMORY_POLICY.md) 显式保留本项目线程并刷新交互档案。

旧安装/400场景流程保留于 [WORKFLOW.md](docs/WORKFLOW.md)，旧 README 的实验说明保留于 [整理前归档](docs/governance/README_20261016_BEFORE.md)。历史通过率、PID 和旧启动记录不能替代当前实测。
