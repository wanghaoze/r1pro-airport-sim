# Proposed specification insertion: preserve placement command-grasp reference

放置可选配置 `placement_preserve_command_grasp_enabled` 默认 `false`，仅用于 `fixed_primitives=true`。当且仅当本次 place 调用已实际执行独立 `transport_align`，其轨迹、稳定检查及动作预算检查全部成功完成，且当前持有目标匹配、左右手命令抓取关系均为有限有效刚体变换时，下降入口保留该次 alignment 建立的命令抓取关系，不再次依据实测托盘倾角重建。合并下降、没有成功完成独立 alignment 或关系无效时维持原重建流程。该选项不修改真实托盘/机器人状态、实际水平放置目标、原 Cartesian 起点语义、触桌高度、相机及碰撞规则、真实支撑/双侧接触/倾斜验收或动作预算。独立 alignment 与 place 各自仍按原 3 秒上限和原稳定预留计时，导航及后续释放/撤臂/任务稳定验收仍按原计时契约记录。

私有放置预测器在成功规划并投影独立 alignment 后应用相同开关及关系有效性条件，保持与执行分支的参考更新语义一致；预测仍只表示几何与轨迹可行性，不认证物理导航、伺服跟踪或接触成功。

事件字典新增：`placement_command_grasp_preserved`（source=`completed_independent_alignment`，target_tray，qualification）记录复用本次命令关系；`placement_command_grasp_rebuilt`（target_tray，reason=`no_completed_independent_alignment` 或 `invalid_command_relation`）记录开关开启但仍走原重建分支。默认关闭时不增加上述事件。没有新增/放宽失败验收规则，对齐失败原样抛出，不进入下降。

变更记录：新增默认关闭的放置命令抓取关系保留实验选项及预测语义同步。冻结 v19 case 218 的私有原样对照精确复现录制 alignment 前缀及相机规划拒绝；单候选取消下降前第二次重建后通过原局部 place→push→release→retreat→verify（使用原有 supported_release_retreat_fallback）。该证据不是完整 Episode 成功；完整同场景回归及成功率待独立新运行目录验证，不改变 v20 冻结运行。

## Local validation

`.conda/experiment/python.exe -m pytest -q tests/test_placement_planner.py tests/test_fixed_primitives.py tests/test_placement_reachability.py tests/test_command_reference.py tests/test_placement_arrival_rescreen.py tests/test_placement_screen_integration.py`

Result: **93 passed in 13.12 s**. Tests cover default-off, boolean/config dependency validation, successful alignment, unstable alignment that must never enter descent, combined descent, invalid relation fallback, unchanged level touchdown XY/height, predictor reference-update consistency, and existing camera/path/control contracts. Specification edit/sync is delegated to root coordinating concurrent source changes; this file is exact insertion text, not a replacement for the unified spec.

补充守卫与审计：保留关系分支仍通过与原 continue_loaded_reference 共享的 checked_command_tcp 执行左右 TCP 实测—指令距离检查；任一侧大于 0.05 m 时原样抛出 primitive_excess_servo_deflection。预测器保留分支也执行此检查。placement_command_grasp_preserved 额外记录 tcp_deflection_m、actual_tray_pose、gripper_contact_force_n，不省略既有负载偏差守卫。新增测试确认 0.05 m 通过而 0.05001 m 拒绝，且 preserve 分支必调用该守卫。
