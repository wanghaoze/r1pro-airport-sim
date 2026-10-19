> 2026-10-16 交接整理前的 README 历史说明。相对链接已按归档位置调整；不是当前启动指令。当前入口见 [README](../../README.md)。

# R1 Pro Airport Tray Simulation

独立的机场安检三桌单托盘仿真项目，保留历史多托盘基线。Agent/FSM 使用仿真真值规划双臂与平面底盘动作，通过 MuJoCo 接触动力学执行，并导出 LeRobot 数据。不是实机驱动，不是人工遥操数据。

**文档与交接入口（2026-10-09整理）：** [文档索引](../../docs/INDEX.md)、[当前要求](../../docs/project/CURRENT_REQUIREMENTS.md)、[模块地图](../../docs/project/MODULE_MAP.md)、[数据目录](../../docs/project/DATA_CATALOG.md)、[实验状态](../../docs/project/EXPERIMENT_STATUS.md)。协作规则见 [AGENTS.md](../../AGENTS.md)，当前memory见 [memory/CURRENT.md](../../memory/CURRENT.md)，历史决定与会话原文见 [决策账本](../../memory/DECISIONS.md) 和 [交互档案](../../memory/interactions/README.md)。实验状态注明最后核验时间，不能当作实时服务器状态。

**独立三托盘 Isaac 迁移分支（2026-10-16）：** 用户已授权恢复旧三托盘场景并改用新版带载交接与三动作训练，详见[三盘专题](../../docs/project/ISAACSIM_THREE_TRAY_20261015.md)。该分支与下述单盘基线分开，不混用来源或成功率；实时只读状态与视频入口由 `THREE_TRAY_ISAAC_WORKFLOW_STATUS.txt`、`THREE_TRAY_ISAAC_VIDEO_PATHS.txt` 维护。完整任务、数据闭合、训练更新分别验收。

**独立原速快速取放视频（2026-10-16）：** [多位姿视频专题](../../docs/project/ISAAC_FAST_PICKPLACE_20261016.md)，复用MuJoCo银黑机器人/Blender实验室，Pick与Place各3秒，站位和臂姿预备另计。真实PhysX、4原相机＋外部展示相机，原速分片；教师短片不算完整三盘来源或模型鲁棒性。实时只读入口 `scripts/watch_isaac_fast_pickplace.ps1 -Watch`，媒体索引 `ISAAC_FAST_PICKPLACE_VIDEO_PATHS.txt`。

**当前任务为三桌布局、单托盘、三动作。** 沿用前面两桌/后面一桌的布局与尺寸，随机刷新托盘初始桌面位置和水平朝向。拿起和放下必须双臂分别抓两条相对长边，禁止同边/短边；机器人在对应桌的正面操作，规划源/目标桌前底盘位置、朝向与双臂抓姿，放下时托盘长轴近似平行机器人面对桌子的水平前向；取消固定终点站位与强制夹持转盘。初态不能直接双臂抓取时允许单臂调整XY/yaw，该准备过程包含在 Pick 片段并由模型学习执行。空盘放下后生成乘客载荷，右臂真实夹持左推、左臂稳定接管、右手松开后托盘实测左移至少3cm，再松手稳定支撑；新规则取消必须推到桌左端。推动位置/桌边偏差采用用户授权的总5cm容差，推动阶段底盘受力漂移也允许5cm（桌前区域和真实碰撞检查保留），真实有接触时据实际支撑判定；瞬时失去接触沿原0.3秒宽限。最终仍须三件载荷留盘、真实稳定支撑、双手松开且满足实测左移门槛；严格结果与近似完成分报。训练文本仅为 `Pick up the tray`、`Place the tray`、`Flush tray to the left`，仅接受完整任务成功后的三个片段，装载不进训练。优先复用旧双臂取放原语；单桌同边抓取的已验证demo现属历史，不符合新规则，不能作为新训练来源。最新实测与服务器路径见 [VLA_TRAINING_PROGRESS.txt](../../VLA_TRAINING_PROGRESS.txt) 和 [TRAINING_DATA_LOCATION.txt](../../TRAINING_DATA_LOCATION.txt)。

基线：已部署的 `primitives3_v50_20260923`。本次整理保留控制行为，补充注释、资源、入口及文档。原 humanvideo 目录保持不变。

后续可选改动：`configs/airport_reach_pull.json` 开启有界任务DAG记录和“单臂拉近再抓取”；详见统一规范5.3节。该分支已做逻辑测试与MuJoCo接口核验，尚未完成实际接触拉动/成功率验证，不能套用v50的历史成功结论。

## 从这里开始

**统一维护文件：[场景生成与任务完整规范](../../docs/SCENE_TASK_SPEC.md)**。按生成/执行顺序解释每个步骤、动作约束、失败判定、状态/phase/事件字典，并附当前配置与错误码。之后相关代码改动必须同步更新该文件；`python scripts/sync_task_spec.py --check` 检查是否遗漏同步。

1. [安装与运行](../../docs/WORKFLOW.md)：Conda、预检查、场景准备、生成、导出、质量验收。
2. [约束与已知限制](../../docs/CONSTRAINTS.md)：3 秒计时边界、18 cm 抬升、物理与相机约束。
3. [代码与数据说明](../../docs/ARCHITECTURE.md)：模块、状态机、数据语义和修改入口。
4. [资源与版本来源](../../docs/PROVENANCE.md)：哪些内容已经验证、哪些必须重新预检。

```bash
conda activate r1pro-tray
cd /path/to/r1pro-airport-sim
python scripts/project.py check
python -m r1pro_teleop.airport_fsm --help
```

目录：

| 路径 | 内容 |
|---|---|
| r1pro_teleop/airport_fsm/ | 主状态机、运动原语、碰撞/接触验证、批处理和导出 |
| r1pro_teleop/ | 场景生成、仿真核心、Recorder 与可选 Quest/HTTP 兼容模块 |
| configs/ | 400 场景固定动作配置、12 场景 smoke 配置、真实参数模板 |
| resources/scenes/ | 本地生成的 12 smoke + 400 formal 场景，普通/复杂分目录 |
| resources/calibration/ | 四相机审计输入，含未验证项 |
| outputs/r1pro_tray_scene/ | 独立复制的机器人/桌面/托盘网格、碰撞资源与模板；保留旧相对路径兼容 |
| scripts/ | 项目入口、GPU 选择、诊断、校验、预览 |
| tests/ | 回归测试 |
| evidence/v50/ | 历史服务器验收报告，不是新项目重新运行的结果 |
| runs/ | 新运行输出（不提交版本库） |

**能力边界：**历史三个完整场景通过两个（147.8 / 144.8 秒），一个在最后放置时因 3 秒路径不可行失败。尚未做到全部 400 场景成功或完整任务两分钟。新项目附带的是本地场景副本，不能把历史通过率直接套用到这些场景。

## 2026-09-28 服务器续跑

实验与优化工具见 [EXPERIMENTS.md](../../docs/EXPERIMENTS.md)：MuJoCo阶段检查点、策略对比、CMA-ES参数搜索、失败评估及独立留出验证。Agent入口为 `prompts/airport_experiments/contract.md`，命令入口为 `python -m r1pro_teleop.experiments --help`。实验输出不自动进入训练集。

9月29日起完整轨迹修复及双头视频整理进度见 [ROBUSTNESS_20260929.md](../../docs/ROBUSTNESS_20260929.md)。冻结v36固定400场景完成180例（45.0%）；v46独立16例开发实验没有新增完成案例。70%是待实测目标，不能把小规模局部通过当作400场景已达标。

9月30日起成功和失败视频的服务器位置按场景类别、失败原因汇总于根目录 [SCENE_VIDEO_INDEX.txt](../../SCENE_VIDEO_INDEX.txt)；每个已存在视频单独一行，缺失视频明确列待生成目录，本机停止批量下载。历史Windows任务`CodexAirportVideoIndex`曾配置每5分钟刷新，2026-10-05核查当前未登记；本轮由Codex训练跟进同步元数据与索引，不宣称仍有5分钟刷新。旧登记入口为`scripts/register_video_index_task.ps1`；SSH授权失效时保留最后核验结果。

v38 候选配置 `configs/airport_completion_stage_priority_retry3.json` 将带载放置改为原0.05rad完整规划优先，只有零运动IK拒绝才在隔离副本尝试0.12rad；`transport_align` 保持原判定，实际接触和最终任务验收不变。该开关默认关闭，服务器物理验证及全400通过率以独立新运行结果为准。

v53 接触交接候选配置 `configs/airport_completion_handoff_clearance_retry3.json` 仅在放置后真实保留单手接触时启用：自由爪静止全开并验证低力/桌面支撑，再从实测状态垂直撤手并验证手指净空，最后才推动。原接触、相机、碰撞和最终任务守卫保留；开关 `completion_handoff_clearance_enabled` 默认关闭，与旧同步自由手撤离实验互斥。该分支新增一个5秒动作预算，规划墙钟和最终稳定时间按原排除项分别报告。只有新物理 Episode 完整完成后才计为成功。

v53 的110/118两场景6次物理尝试均在真实自由指净空<5mm处安全终止，完整成功0/2。v54把规划预测净空要求提高至20mm；新6次物理尝试均完成撤手交接，但后续IK或碰撞使完整成功仍为0/2。真实5mm门槛和所有物理守卫不变；局部交接通过不计作完整任务成功。

9月30日用户进一步允许较长生成时间、近似精度、中途有限碰撞，以及离桌2cm内松手。新配置 `configs/airport_approximate_completion_retry3.json` 显式开启近似完成模式：时间作为诊断记录，最终按三盘大致目标布局、实际落桌、松手及稳定检查完成；碰撞/穿透和旧严格偏差仍保留证据。新模式的成功率须另做完整物理实验，不能与45%旧配置直接混作控制提升。详情见统一规范6.1节。

用户于9月29日指定任务完成优先后，新增 `configs/airport_completion_first.json`：允许有界的短暂运行偏差和较宽位置/朝向容差，以实际旋转托盘轮廓及稳定支撑验收；原 `strict` 默认保留。结果分别记录 `task_completed` 与 `strict_success`，不把更改验收标准描述成控制精度提升。完整流程和参数见统一规范6.0节，400场景目标仍须新运行实测。

后续独立候选可采用5秒动作预算和最多3次从初态开始的完整尝试，首个完成即停止；报告首轮与预算内唯一场景完成率，保留每次失败视频。直接临时buffer与80mm带载IK候选分别开关验证，实际接触、抬升及最终任务验收继续执行。较长预算不满足原3秒要求，配置与计时排除项须一起报告；通过 `scripts/control_regression.py` 运行，原固定3秒实验campaign入口不变。

本轮部署与验收记录见 [SERVER_20260928.md](../../docs/SERVER_20260928.md)。包含堆叠调度、实测载荷扫掠、IK 区间细分修复；不是对全部400场景成功的承诺。原 v50 结果只作为历史基线。


2026-10-01新增π0.5 VLA训练与DAG learned-motion入口，见[训练和执行](../../docs/VLA_TRAINING_20261001.md)及统一规范9.2。原几何DAG保留，推理阶段用checkpoint动作替代IK/逆动力学；BC与simulation-expert DAgger分开记录，训练数据须native视频/帧对齐和scene split核验。v64全400实际193/400完成（48.25%）；尚未达到70%，不能将训练启动或接口测试当模型闭环成功。
