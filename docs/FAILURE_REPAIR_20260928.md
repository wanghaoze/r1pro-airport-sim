# 2026-09-28 失败诊断与候选修复

## 已核实的基线

服务器 `coverage_v4_20260928/runs/firstpass`：400 个场景首轮全部执行，22 条干净物理成功，378 条失败，成功率 5.5%。这不是 LeRobot 导出成功率，也没有达到大多数场景成功。失败证据见 `evidence/project_validation/failure_repair_20260928/baseline400_failure_audit.json`。

| 首要失败码 | 数量 | 定位 |
|---|---:|---|
| no_feasible_grasp_approach | 119 | 初始底盘/悬停候选不可达 |
| contact_handoff_aborted | 85 | 56 条仍有夹爪力，但丢失桌面承载 |
| primitive_path_infeasible | 47 | 46 条发生在放置下降 |
| ik_unreachable | 45 | 40 条发生在接近托盘 |
| primitive_postcondition_failed | 42 | 36 条放置触桌未满足，6 条抬升验收失败 |
| 其他 | 40 | 连带抬升、恢复支撑、碰撞等 |

接触证据：56 条 retained_contact_lost 中夹爪仍有约 10–11 N 接触力，失败原因均包括 table_contact=0。示例托盘底部只高于桌面几十微米，但几何接近不能当作实际承载。没有放宽接触阈值或延长接触丢失宽限来虚构成功。

## 实验与限制

- support_v6：增加触桌等待和支撑预压，5 条测试全部失败，包含旧成功场景。已撤回，保留补丁和服务端记录。
- ik_v7：加入沿托盘朝向的站位和空载关节空间备选路径；7 条全部失败，3 条触发实测超速。未推广。
- ik_v8：仅对新增的大幅空载换姿按参考速度/加速度/jerk 的 50% 计算额外时长；实测上限不变。7 条完整任务中 2 条成功，场景4为153.65秒、场景16为151.05秒。场景1由初始不可达推进到真实抬升，但连带另一托盘，仍判失败。没有证明整体成功率提高，未达到120秒。
- ik_v9：仅在下降私有规划因 IK 不可达/分支跳变失败且空载无接触时重新选底盘；候选同时检查悬停和完整下降。97 项服务端测试通过。场景6/7/218分别在246.45/243.55/192.95秒仍以不可达失败，显著增加耗时而未增加成功；不采用，补丁保留。场景310也在286.4秒后失败；最终仍为2/7成功。本地工作代码回到v8候选，正式数据生产基线仍为v4。

全部实验在独立 release/collection，旧场景和成功数据没有覆盖。相机方向、四路原始分辨率、15–20 cm 抬升验收、3秒原语预算及物理守卫不变。空载换姿与导航不属于3秒原语，不能把这些时间排除在完整任务计时之外。

## 只读诊断命令

```bash
conda activate r1pro-tray
cd /home/michelle/haoze/r1pro-airport-sim/releases/ik_v9_20260928
python scripts/audit_failures.py --root runs/ik_smoke --output /tmp/r1pro_audit_$(date +%Y%m%d_%H%M%S).json
```

诊断脚本只读取 result/events，不修改状态或标签；输出使用独占创建，拒绝覆盖。`generate` 返回0只表示处理了所选场景，必须另外检查物理成功，不能当成全部成功。未经过完整回归，不自动展开新的400场景批次。

最终验证证据：`evidence/project_validation/failure_repair_20260928/failure_repair_evidence_20260928_1710.zip` 包含 v6–v9 的完整 result/events 与汇总。v8 服务端95项通过，本地最终相关回归30通过、1既有xfail；v9服务端97通过但完整物理无收益，已撤回。
