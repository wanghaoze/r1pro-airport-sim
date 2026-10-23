# 网站策略约束分析与强制 filter 验证报告

日期：2026-10-21。范围：Workstation 网站策略模拟和云端任务在服务器上的执行入口；不含真机控制、重训或修改历史成功标签。

## 结论

原系统已有机械限位检查和可选的 robot_limits，但未统一覆盖所有执行入口。批量/自动评测、文件通道及旧请求可能进入仅检查机械范围的 strict 路径，不能保证每帧速度、跟踪偏差与反馈时效统一受控。用户提出的 filter 必须放在服务器模型输出和每帧执行入口，不能只靠前端开关。

已实施强制过滤并部署新服务器 release `scene_studio_robot_filter_20261021_v15`。工作站网站与云端任务 worker 均指向该版本。原生闭环实测 200 帧 / 5,000 物理子步，所有实际下发目标通过限位审计；模型没有完成 Pick，不能将 filter 的通过等同于策略任务成功。

## 主要问题与处理

| 优先级 | 原问题 | 影响 | 本次处理 |
|---|---|---|---|
| P1 | robot_limits 可选，手动、批量、自动和传输路径不一致 | 同一模型可能因入口不同而缺少速度/反馈保护 | 所有新 VLA/live 执行强制 robot_limits；旧 strict/clip_diagnostic 请求也不能绕过 |
| P1 | 先裁剪后检查有限性 | 正负无穷可能被变成有效边界值 | HTTP、ROS2、文件及最终执行均先验证有限值和通道结构；失败拒绝执行 |
| P1 | 最终执行未统一取配置范围与当前场景机械限位交集 | 仅凭某一侧范围不能证明下发值符合二者 | 逐帧重新求交集，空交集/无效限制拒绝 |
| P1 | 缺失反馈时间被当作当前时间、负年龄被归零 | 缺失或未来时间戳可能通过保护 | 缺失、未来、非有限、超过 0.5 秒均拒绝 |
| P1 | 旧模型服务复用未核验过滤合同 | 新任务可能复用旧实现 | 健康状态及 ready 回执必须匹配过滤合同哈希 |
| P2 | protected 报告的 successRate=null 被 UI 重新计算 | 容易误读为纯模型成功率 | 显示 filtered task passes，排除纯模型率；历史报告不改 |
| P2 | 以测量状态初始化“上一指令” | 夹爪物理微小超调会导致第一帧错误拒绝 | 改用运行时真实保持指令 r.command；测量值仍用于跟踪检查 |
| P2 | float32 转换可能把精确边界向外舍入 | 数值上微小越过配置边界 | 使用向区间内部舍入的 float32 可表示边界，不放宽物理容差 |

代码入口：[统一 filter](../r1pro_teleop/real2sim/robot_action_filter.py)、[逐帧控制](../r1pro_teleop/real2sim/isaac_policy_pickplace.py)、[HTTP](../scripts/studio_model_http.py)、[ROS2](../scripts/studio_ros2_transport.py)、[评测](../scripts/studio_vla_evaluate.py)、[请求合同](../apps/scene-agent/lib/training.ts)、[自动评测](../apps/scene-agent/gpu/auto_evaluation.py)。

## 执行合同

执行链：原始模型预测 → 显式单位/19 通道映射 → 结构与有限性校验 → 机械/夹爪限幅及底盘屏蔽 → 每帧机械交集与速度约束 → 反馈检查 → 原生物理执行。

| 约束 | 当前值与行为 |
|---|---|
| 双臂 14 关节 | 登记机械范围与当前模型 XML 交集，逐关节校验 |
| 关节单步 | 最大 0.1 rad，并与速度界取更严者 |
| 关节指令速度 | 最大 1.5 rad/s；20 Hz 下每帧不超过 0.075 rad |
| 夹爪总开口 | 0–0.08 m；每侧两指各使用一半开口量 |
| 关节跟踪偏差 | 超过 0.25 rad 拒绝下一帧 |
| 测量年龄 | 0–0.5 秒；无时间戳、未来时间戳、非有限时间均拒绝 |
| 底盘 | 忽略策略移动输出，保持本 episode 已确定的固定指令 |
| 缺失通道/非法数值/非法配置 | 拒绝；不补夹爪、不调用教师或 IK 回退 |

原始预测仍作为证据保存，不要求原始神经网络值本身已经合法；送往执行器的应用值必须合法。HTTP 的 `checkpoint_limit_events.jsonl` 保留 raw/bounded；文件回复保留 raw_actions；执行日志记录过滤前目标、应用值、反馈、年龄与合同。运行时 model_actions.npz 中 raw_chunks 是接收到的上游输出，不应误称为所有路径的原始网络输出。MSE 继续评价原始预测，未用 filter 美化误差。

机械 XML SHA 已与服务器源文件核对一致。真机 TOML 原路径 `runs/galaxea_robot_deploy_20261013_v3_reference/config_pi05_mixed_gripper80_lan_20261013.toml` 当前缺失，因此本次沿用 `gpu/robot_action_limits.json` 中已归档参数。**尚不能声明与当前真机控制器配置完全一致。** 本 filter 没有实现独立的加速度、力矩、碰撞预测或真机急停认证，也不保证实际物理反馈绝不超调。

## 验证结果

- 本机及服务器 Python 合同测试各 52 项通过：所有关节、1/20/40 帧输出、非有限输入、随机连续指令、过期反馈、机械交集、HTTP 三类模型适配器、旧请求强制过滤及初始测量/指令区分。三模型 HTTP 测试使用合成适配器，不代表三个真实模型都完成物理测试。
- 服务器 training 请求测试 4 项通过；本次最终 UI 静态渲染回归通过，确认 filtered pass 不转成纯模型百分比。
- 服务器 offline build 通过；仍有原有 CSS at-rule 和大 bundle 警告。没有进行完整浏览器交互回归。
- 原生闭环：Room 000，最新 50/50 π0.5 checkpoint `cp_8788068a6984a796aed42ef1`，ROS2，GPU0，200 帧/action，旧请求明确设置 strict；实际执行合同强制 robot_limits。
- 完成 200 帧、10 秒仿真、5,000 真实子步；Pick 预算耗尽，任务通过 0/1，Place 未执行。controller/native/media 实际退出记录保留，流程退出 0 不代表任务成功。原生总状态仍有 `model_executed=false` 与房间结果 `true` 的历史聚合元数据不一致，本结论以 200 帧轨迹及房间结果为准，建议后续修复该展示字段。

| 实测指标 | 结果 |
|---|---:|
| 帧级目标越界数 | 0 |
| 5,000 子步目标越界数（按实际 float32 下发格式复核） | 0 |
| 最大双臂单帧指令变化 | 0.0749999999825377 rad |
| 最大夹爪总开口目标 | 0.07999999821186066 m |
| 最大反馈年龄 | 0.09570 s |
| 最大双臂跟踪偏差 | 0.12848 rad |
| 最终逐帧目标发生限幅/限速的帧数 | 54 / 200 |
| 底盘目标 | 全程固定 |
| 实际手臂反馈越关节界最大值 | 0 rad |
| 实际夹爪反馈越 80 mm 最大值 | 0.43756 mm |

夹爪反馈越界共 349 个采样通道值（不是 349 帧），包括初始化后的微小超调。指令限幅不能被描述为实际运动的绝对保证。未调整物理门、位置容差、训练权重或成功标准。

失败现场保留：v1 验证脚本缺少 checkpoint contentBindings，未执行动作；v2 使用 GPU1 时相机初始化返回空，未执行动作；v3 初始反馈被误当指令导致保护拦截，未执行动作；修复实现并使用原有 GPU0 配置后 v4 执行 200 帧。前三次均不计策略成功率，没有覆盖旧现场。

完整审计见 [command_audit.json](../runs/mandatory_robot_filter_20261021/command_audit.json)；[原生评测结果](../runs/mandatory_robot_filter_20261021/evidence/report.json)、[执行合同](../runs/mandatory_robot_filter_20261021/evidence/execution_contract.json)、[最终测试日志](../runs/mandatory_robot_filter_20261021/evidence/check_0.log)、[UI 回归](../runs/mandatory_robot_filter_20261021/evidence/check_ui-test.log)。视频与轨迹留服务器，仅同步 JSON/TXT 等元数据。

## 部署状态与剩余问题

服务器新目录：`/home/michelle/haoze/r1pro-airport-sim/releases/scene_studio_robot_filter_20261021_v15`。核对 PID、启动时间与目录后，仅优雅停止旧网页监督器及两个所属 worker，保留退出回执；旧模型服务和无关服务未停止。SQLite、历史数据与旧 release 保留。新网页健康检查、首页、bootstrap 均返回正常；工作站和云端 worker 均使用 v15 且 heartbeat=polling。证据：[部署回执](../runs/mandatory_robot_filter_20261021/evidence/deployment.json)、[上线核验](../runs/mandatory_robot_filter_20261021/evidence/post_deployment.json)。

云端托管页面本身未重新发布，可能仍显示旧的策略开关或旧结果呈现；其服务器执行入口已经强制过滤，UI 旧选项无法绕过。工作站网页 UI 已更新。所有结论是本次核验时刻的状态，不代表后台持续监控。

后续按优先级处理：

1. 补齐当前真机控制器/驱动实际生效的限制文件，对照归档参数；目前没有现行来源就不能宣称完成真机约束一致性验收。
2. 调查夹爪物理微小超调，并决定是否需要控制器层面的速度、加速度、力矩、接触保护；不得通过扩大限位掩盖超调。
3. 分析 200 帧 Pick 未完成的模型/接触行为；filter 解决非法命令，不保证抓取成功。后续应扩大房间和任务覆盖，但不能拿本次单房间推断泛化。
4. 同步云端前端并修复 model_executed 聚合元数据；G0.5 缺夹爪输出、GR00T 缺可验证权重仍独立未解。
5. 原网站审阅中的草稿保存竞态、陈旧状态处理和列表截断等源码风险尚未修复，见 [网站分析报告](SCENE_STUDIO_REVIEW_20261021.md)，不要将本次 filter 上线理解为全站问题均已解决。
