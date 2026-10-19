# MuJoCo 实验与优化工具

这是 EmbodiedSWE 实验流程的原生 MuJoCo 适配。正式 FSM 与物理守卫保持原样，
实验策略通过 `ExperimentMachine` 扩展站位候选和抓取路径预览。
工具负责执行和记录实验；编码 Agent 阅读 prompt、提出假设并修改代码。
没有内置第三方模型调用，也不会未经配置持续消耗模型 API。

## 架构

```text
Codex + prompts/airport_experiments/{contract,tool_router,tools}.md
  -> diagnose / assess / history
  -> immutable campaign (完整来源 split + code/assets/packages 指纹)
  -> sweep / CMA-ES search
       -> 有限 worker -> 独立 MuJoCo 进程 -> ExperimentMachine -> 原 Runtime guards
       -> result / events / trace / checkpoint / native scene_view
  -> 冻结候选 -> fresh regression + holdout verify
  -> 人工审阅/Agent集成新版本 -> 原生产 collection + 独立视频/LeRobot验收
```

检查点使用 `mjSTATE_INTEGRATION`，包括控制输入、warmstart 等物理状态；同时保存
运行时接触上下文、目标、FSM标签、预算进度、调度映射、随机状态和阶段上下文。
只能在新的诊断进程恢复，不能在正式 Episode 内回退。它不恢复 Python 调用栈；
阶段函数明确从哪个已完成阶段继续。诊断 trace 是独立片段，不冒充完整 Episode。
恢复必须匹配配置、场景、XML、代码、依赖版本及 campaign 资产指纹。

与上游差异：Isaac 的 GPU tensor 批处理改为 MuJoCo 进程隔离；checkpoint 的 torch
序列化改为无 pickle 的 JSON/NPZ；搜索沿用 CMA-ES；移除了上游环境专用对象操作。
不移植 grasp weld、不改变接触和动作验收，不保证提高机场任务成功率。

## 环境与首次运行

```bash
conda activate r1pro-tray
python -m pip install -r requirements-experiments.txt
python -m pytest tests/test_experiments.py -q
python scripts/sync_task_spec.py --check
python -m r1pro_teleop.experiments --help
```

以已有 collection 的来源为输入，**新建** campaign。source 不会被写入；其完整
manifest 和 split 被重新登记，只有选择的场景执行新版本 preflight。
SOURCE 的场景及资产必须已经在当前项目中自包含；不能引用 humanvideo。
开发、回归、留出三组不能重叠。正式比较建议至少2–3个留出场景。

```bash
python -m r1pro_teleop.experiments init --source SOURCE --output runs/experiment_001 \
  --development airport_0006_20270922 airport_0007_20270923 \
  --regression airport_0004_20270920 airport_0016_20270932 \
  --holdout airport_0218_20271134 airport_0310_20271226
python -m r1pro_teleop.experiments launch --root runs/experiment_001 --name first_sweep -- \
  sweep --root runs/experiment_001 --candidates configs/experiment_candidates.json --workers 2
python -m r1pro_teleop.experiments status --root runs/experiment_001
python -m r1pro_teleop.experiments report --root runs/experiment_001
```

上面的场景ID适用于服务器v7来源；本地来源不能直接套用。所有命令均在最终 release
目录运行。源码/配置改变就建立新 campaign；不刷新旧 campaign 指纹绕过检查。
每个 worker 有独立 HDF5/events/result/log；父进程只写实验汇总，不覆盖旧尝试。

## 阶段实验与参数搜索

`sweep --stage settled` 生成经过原守卫和静止检查的起始检查点。随后用新的 run ID
运行 `sweep --checkpoint PATH --stage approach`；再从 approach 检查点运行 lift。
当前内置阶段覆盖静置、接近和抬升；放置等自定义阶段需在新版本中显式实现。
无法通过静止/阶段检查时保留失败，不强制保存。`scene-view` 输出四路原尺寸PNG，
是诊断状态快照，不能替代连续物理回放或原生视频导出验收。

```bash
python -m r1pro_teleop.experiments search --root runs/experiment_001 \
  --seed-summary runs/experiment_001/experiments/RUN/summary.json \
  --space configs/experiment_search_space.json --generations 2 --population 4 --workers 2
python -m r1pro_teleop.experiments verify --root runs/experiment_001 --candidate WINNER.json --workers 2
```

仅 fresh 开发集上有完整干净成功的候选才允许 CMA-ES。每代重跑 incumbent，
相同场景/attempt seed成对比较。成功数优先，其次成功 Episode 总时长；失败走得更远
没有成功奖励。只有参数允许列表可搜索，接触/速度/相机/3秒预算均不开放。
随机重试与固定首个候选的区别沿用原 FSM attempt 语义，不伪称不同 seed 完全独立同分布。

verify 固定候选后只运行一次；比较原始 baseline 与候选，要求保护回归组及 baseline
成功场景，并在留出组至少有成功。它是小样本门槛，不是整体成功率提升的统计证明。
试验成功仍 `training_candidate=false`，没有自动导出或部署为生产控制器。

## 时间和证据

3秒是单原语仿真预算，不含初始抓取、底盘导航、推后释放撤离、最终稳定检查或CPU
规划时间；普通末端对齐另计。完整 Episode 时长仍包含这些物理动作。
`physics_success`、`complete_episode_verified`、`stage_passed`、`verification.passed`
分别记录；`diagnostic_only` 和 `origin` 始终显式保存。

上游来源及许可证见 `licenses/EmbodiedSWE-NOTICE.md`。
