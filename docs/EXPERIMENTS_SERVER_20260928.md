# 2026-09-28 实验工具服务器验证

部署目录：`/home/michelle/haoze/r1pro-airport-sim/releases/experiments_v1_20260928`。
运行目录：`runs/smoke_001`。环境：`/home/michelle/miniconda3/envs/r1pro-tray`。
部署基于当前本地v8候选控制代码；场景/资产复制自项目内v4 release的server_v7来源。
不是v50历史场景，也没有改写v4生产collection。原始split完整保留。

工具、实验架构与prompt已部署。服务器相关测试136通过、1既有xfail；本地另验证
diagnostic_only即使误标physics_success也不能被正式导出选择器接受。
服务器Conda环境仅新增cma 4.4.0；原MuJoCo和控制依赖未升级。没有使用base或vendor。

已完成工具验证：
- 对旧v4 collection只读审计，复核400次尝试、22成功、378失败。
- 场景4/6静置检查点通过；场景4从检查点恢复后接近通过，再恢复后抬升通过。
- 四路原尺寸诊断PNG生成：双头1920×1536、双腕1280×720；这是状态快照，
  不是连续视频/LeRobot验收。诊断结果全部禁止训练导出。
- 场景4完整fresh基线复现153.65秒成功；场景6基线仍IK不可达。

开发组：4、6；保护回归组：16；首次留出组：7、218。只用于本次小规模工具验证，
不能推断400总体成功率。策略为baseline、靠近2cm、反转候选、完整下降闭爪预览。
随后执行一代CMA-ES（4个候选，另含重跑incumbent），再冻结候选做fresh对照验证。
最终结果：策略8次仅baseline场景4成功；CMA新增4个候选均未完成任一开发场景，incumbent仍仅场景4成功。
fresh验证baseline与冻结候选均为1/3（16成功，7/218失败），verification_passed=false，无回归也无提升。
阶段检查点通过不计完整成功。未自动修改生产控制器。

```bash
conda activate r1pro-tray
cd /home/michelle/haoze/r1pro-airport-sim/releases/experiments_v1_20260928
cat runs/smoke_001/optimization_status.json
python -m r1pro_teleop.experiments status --root runs/smoke_001
python -m r1pro_teleop.experiments report --root runs/smoke_001
```

时间契约：单primitive≤3秒；初始抓取、底盘导航、推动后释放撤离、最终稳定及CPU
规划不计入该原语预算；普通对齐另计，完整Episode仍计入物理动作。检查点阶段输出
的simulation_seconds保留来源的累计仿真时钟/预算进度，不等于本阶段单独耗时。
不承诺所有场景在3秒内可行，也不把局部成功算成完整任务成功。
