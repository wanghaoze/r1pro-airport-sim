# 文档导航

- [Scene Studio 网页](https://r1pro-scene-agent-haoze.exactmyna128.chatgpt.site) · [项目说明](../apps/scene-agent/PROJECT.md) · [英文与自动评测发布](../runs/web_english_autoeval_20261019_v1/auto_deployment.json)：2026-10-19全英文/最新最终检查点自动VLA和MSE/结果回显；保留平台当前受众，GPT接口仍未配置。评测启动、完成和模型成功分别见实测报告。

- [网页场景 Agent：prompt 与执行代码](../exports/web_scene_agent_v1/README.md)：2026-10-17，用户选择Isaac32房间Pick/Place；草稿/数据选择/计划已实现，网页和原生训练接入另行实施。

**2026-10-16 交接入口：** [根 README](../README.md) → [服务器、生成、训练与机器人运行手册](handoff/README.md) → [交接脚本/配置索引](handoff/SCRIPTS.md)。服务器统一直接登录 `michelle@xinmatrix` 或 `michelle@100.104.0.108`；密码仅交互输入。命令按实际源码核对；服务器状态仅为注明时间的只读快照。

**英文版交付：** [项目探索汇总与运行交接 PDF（43页）](../output/pdf/R1Pro_Project_Review_and_Operations_Handover_EN.pdf) · [英文源稿](handoff/README_EN.md) · [PDF检查收据](../output/pdf/R1Pro_Project_Review_and_Operations_Handover_EN.validation.json)。

整理日期：2026-10-09。保留原文档位置和历史证据；以下按用途组织，不改变任何运行数据。

| 需要了解 | 首要文档 | 说明 |
|---|---|---|
| 项目协作约定 | [AGENTS.md](../AGENTS.md) | 实施、确认边界、后台与memory维护 |
| 当前任务要求 | [当前要求](project/CURRENT_REQUIREMENTS.md) → [统一规范](SCENE_TASK_SPEC.md) | 摘要是导航，精确合同以统一规范为准 |
| 模块/入口/测试 | [模块地图](project/MODULE_MAP.md) | 当前三桌单盘与旧控制分开 |
| 数据、split、片段、视频 | [数据目录](project/DATA_CATALOG.md) | 三动作、独立拿取、诊断及历史数据分开 |
| 模型、实验结果与阻塞 | [实验状态](project/EXPERIMENT_STATUS.md) | 只标最后核验快照，不能当实时服务器状态 |
| 真机MSE与混合训练 | [真机/仿真迁移](project/REAL_SIM_TRANSFER.md) | 用户授权离线真机数据；单位、时间轴、split、采样和sim评测scope |
| 真机示范real2sim | [独立回放与引擎适配](project/REAL2SIM.md) | 原时间轴20通道、独立全关节模型、MuJoCo实测与Isaac/Genesis适配边界 |
| Isaac原速快速取放视频 | [多位姿取放](project/ISAAC_FAST_PICKPLACE_20261016.md) | MuJoCo视觉一致、各3秒、真实物理/速度域差异；不是正式完整来源 |
| 快速接手 | [memory/CURRENT.md](../memory/CURRENT.md) | 当前目标、边界、待处理事项 |
| 用户决定及替代关系 | [memory/DECISIONS.md](../memory/DECISIONS.md) | 历史约束如何变为当前要求 |
| 会话原文 | [交互档案](../memory/interactions/README.md) | 实际本机日志导出、按日浏览、来源及覆盖范围 |
| 记录/去重/更新规则 | [Memory治理](governance/MEMORY_POLICY.md) | 权威层次、证据、隐私与刷新命令 |

## 现有文档按模块分组

- 场景与控制：[SCENE_TASK_SPEC.md](SCENE_TASK_SPEC.md)、[ARCHITECTURE.md](ARCHITECTURE.md)、[CONSTRAINTS.md](CONSTRAINTS.md)。ARCHITECTURE中的多托盘循环描述历史基线；当前路径见模块地图。
- 安装、环境与执行：[WORKFLOW.md](WORKFLOW.md)、[SERVER_20260928.md](SERVER_20260928.md)。历史服务器PID/命令不是最新部署依据。
- 数据/媒体/来源：[PROVENANCE.md](PROVENANCE.md)、[FAILURE_VIDEOS.md](FAILURE_VIDEOS.md)、[数据目录](project/DATA_CATALOG.md)。根目录 *_LOCATION.txt / *_PATHS.txt 保留兼容，不迁移媒体。
- 实验优化与修复：[EXPERIMENTS.md](EXPERIMENTS.md)、[EXPERIMENTS_SERVER_20260928.md](EXPERIMENTS_SERVER_20260928.md)、[FAILURE_REPAIR_20260928.md](FAILURE_REPAIR_20260928.md)、[ROBUSTNESS_20260929.md](ROBUSTNESS_20260929.md)。
- VLA：[VLA_TRAINING_20261001.md](VLA_TRAINING_20261001.md)、[实验状态](project/EXPERIMENT_STATUS.md)、[AFFORD_PI05_120_TRAINING.txt](../AFFORD_PI05_120_TRAINING.txt)。训练完成、评测完成和物理任务成功分开。

本次只整理文档与记录，不重新训练、停止服务或修改验收规则。最新远程状态需要重新实测。

2026-10-12：[纯真机π0.5微调、留出评测与失败诊断](project/REAL_ONLY_PI05_20261012.md)，替代本轮混合采样；Afford不训练。

- [真机双模型配置与键盘命令停止](project/REAL_ROBOT_DEPLOYMENT_20261013.md)：2026-10-13新增授权，workstation server/robot client；当前传感器阻塞，尚无真机动作结果。

- [50/50新混合模型](project/PI05_MIX50_20261015.md)：2026-10-15独立数据采样、后台训练、checkpoint和实时进度。

- [Isaac Sim原生迁移](project/ISAACSIM_MIGRATION_20261015.md)：已启动6.0.1、独立USD及100步原生实测；完整任务/模型闭环未通过。

- [三托盘Isaac新流程与训练数据](project/ISAACSIM_THREE_TRAY_20261015.md)：旧193源定位、新三文本带载交接、独立资产预检、重复切片与未完成项。
