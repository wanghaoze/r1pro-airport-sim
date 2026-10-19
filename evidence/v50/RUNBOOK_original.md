# 固定时长动作：R1 Pro 托盘仿真

本次为仿真程序生成控制，不是人类遥操，也没有向真机发送指令。

## 动作定义

- 抬升：名义 18 cm；以托盘碰撞网格最低点的实际离桌高度 15～20 cm 验收。工作空间边界使用预先验证的短水平补偿路径，不通过反复抓放处理。
- 放置：按桌面高度、托盘目标姿态和碰撞网格最低点计算终点。必要时把水平回收与下降合成同一段；桌面承重后才打开夹爪。
- 推动：按实际位置和目标间距规划完整路径；需要衔接时保留一侧夹持，另一侧张开并避让。接触手优先保持桌面法向高度，空闲手采用自由运动精度；接近下一次抓取时仍采用严格精度。
- 每个 primitive 最长 3 秒，包括该动作内的接触验证。不可达、失去接触、碰撞或超时均失败，不假装成功或自动切回慢速路径。
- 采用连续二阶轨迹并核对速度、加速度、jerk、逆动力学和现有碰撞/相机约束；不使用物体粘连、瞬移或视频加速。

**计时边界：**3 秒指仿真/控制时间，不包含 CPU 规划时间、初始抓取、底盘运输、推动后的松爪退出和最终 1 秒稳定验证。普通情况下的运输末端对齐有独立的 3 秒预算；工作空间边界的对齐合并在下降内。整项整理任务的耗时须另外查看结果，不能把局部 3 秒等同于全任务两分钟。

## 配置与接口

`configs/airport_primitives3.json` 显式开启 `fixed_primitives`。旧配置默认关闭，保留旧数据和已部署历史版本。

关键值：`primitive_seconds=3.0`、`primitive_lift_m=0.18`、`primitive_settle_s=0.1`、`primitive_release_clearance_m=0.02`、`primitive_touchdown_preload_m=0.003`。推动补偿是指令前馈，不是放宽实际位置或穿透验收。

验收仍使用位置误差 ≤3 cm、yaw/倾角 ≤5°、间隙 0～3 cm、稳定 ≥1 秒，无落地或非法碰撞。没有修改托盘质量/摩擦、夹爪参数或真机速度上限声明。

原生相机为 head_left/head_right 1920×1536，left_wrist/right_wrist 1280×720；20 fps，H.264 CRF 18，不裁剪或缩放。相机内参来源与先前一致，光学外参和真实畸变尚未完成真机验证。

## 验证记录

最终服务器版本、完整场景结果、每个动作的区间/耗时和实际抬升高度见同目录 `audit.json`。快照初始化的 fixture 仅用于诊断，不登记为完整成功 Episode，也不导入训练集。

模型的 `model80` 限制来源是既有仿真工程参数/URDF；不代表已测得真机最大机械或电气功率的 80%。

## 已部署结果（v50）

服务器目录：`/home/michelle/haoze/humanvideo/r1pro-tray-server/releases/primitives3_v50_20260923`。
本地冻结代码包为 `v50/validated_release_code.zip`，审计为 `v50/audit.json`。该冻结版本是服务器验证依据；工作区还包含其他并行工作的修改，不应把整个工作区直接覆盖到该版本。

| 场景 | 完整结果 | 仿真耗时 |
|---|---|---|
| airport_0004_20270920 | 成功，无恢复 | 147.80 s |
| airport_0132_20271048 | 成功，无恢复 | 144.80 s |
| airport_0005_20270921 | 最后放置无法满足 3 秒预算，明确失败 | 159.85 s |

两个成功 Episode 的实际离桌高度为 15.43～16.04 cm，抬升 1.45～2.55 秒、放置 2.70～2.90 秒、推动 2.55～2.90 秒。审计未发现动作超时或高度越界。服务器测试 104 passed、1 xfailed（已有临时缓冲区几何测试）。

这不是 400 场景全部通过，也尚未达到完整任务 120 秒。第三场景失败不进入成功训练集；不能通过放宽物理约束或重复抓放掩盖它。

## 运行命令

```bash
conda activate r1pro-tray
cd /home/michelle/haoze/humanvideo/r1pro-tray-server/releases/primitives3_v50_20260923
export PYTHONPATH=.
python scripts/probe_airport_motion.py \
  --source-root runs/airport_fsm_400_fourcam_v7_20260922 \
  --scene-id airport_0004_20270920 \
  --config configs/airport_primitives3.json \
  --output "runs/debug/primitives3_replay_$(date +%Y%m%d_%H%M%S)"
```

本轮数据根目录为 `/home/michelle/haoze/humanvideo/r1pro-tray-server/runs/airport_primitives3_v50_smoke_20260923`，成功数据使用官方 LeRobot 导出，`mobile19` 保留移动底盘动作；数据来源为 `program_generated` / `simulation`。

已完成两个成功 shard：`datasets/mobile19/train/shard_dc937a3932cababf`（2956 帧）与 `datasets/mobile19/train/shard_6ed30246bdf6d6f5`（2896 帧）。均通过官方 loader 首末帧读取，物理回放最大关节位置误差为 0，四路相机空白帧为 0；无导出失败、无 scene 泄漏。详见 `v50/export_summary.json` 和两个 `source_manifest.json`。本地 `v50/scene4_head_left_native.mp4` 为完整原速左头部相机视频，已核对 SHA256。

```bash
bash scripts/run_r1pro_gpu.sh -m r1pro_teleop.airport_fsm report \
  --root runs/airport_primitives3_v50_smoke_20260923
```
