# 真机＋少量仿真迁移实验

用户授权2026-10-09：使用服务器 `/home/michelle/GalaxeaVLA/lerobot_data` 的真机Pick/Place数据，检查已有仿真模型离线MSE，然后混合训练并查看sim行为。本轮不操作真机。

当前运行根：`/home/michelle/haoze/r1pro-airport-sim/runs/real_sim_pickplace_20261009_v3`；v1/v2失败保留。5条轨迹夹爪实测反馈最大约102.7mm、命令仍0..100；适配检查只限制命令，保留未裁剪反馈，不删来源或放宽仿真验收。v2缓存与两份MSE已完成并真实exit0，v3按出口/产物SHA只读导入，不重复计算。v3补齐NumPy训练缓存的显式描述（不冒称标准LeRobot导出），修正sim桌子table_id字段；新optimizer训练实际已开始，后测结果仍待。

- 原件：Pick79/26507帧，Drop55/10940帧；30Hz、四相机、r1pro。原tar只读；两个包都有根`training_data_set_meta.json`，第一次共用解包目录冲突，保留失败；attempt01按归档命名空间独立解包完成。
- 用户确认：夹爪0～80为总开口mm，转为米；左右7关节目标/反馈直接使用rad。共同顺序L7/Lgrip/R7/Rgrip/base3。
- 所有原episode目标底盘速度0；派生hold目标0、实测odom减初始原点。MSE排除base3，非0速度阻止当前转换，不自动做速度/位姿或EE/IK转换。
- 30→20Hz对state/action/RGB用同一最近时间索引；head左＋两腕映射；RGB224等比补边；原件四路保留。
- v2使用8个并行episode解码工作者，各写缓存的不重叠帧区间，最终manifest保持原顺序；进度计数为已闭合episode，不冒充连续前缀。
- 真机按原MCAP文件名哈希分80/10/10策略，最终数量见`frozen_data_selection.json`；same recording不跨split，Pick/Place每split必须都有来源。范围是episode留出，不是新场景泛化。
- 实际冻结划分train102/val13/test19；test含Pick11、Place8。训练真机缓存18853个20Hz帧。
- sim取V4 train10完整成功源/30片段，不混test父；采样表80,000次固定72,000 real＋8,000 sim，domain内任务均衡；norm按训练抽样统计，不用val/test。
- 三原文本保持；真机只Pick/Place，sim还含Flush。训练π0.5从已训练sim10000步权重、新optimizer，batch8、H20、10000更新/每1000保存、原视觉冻结LoRA BF16/FP32方案、独立GPU1。

## 阶段与输出

| 阶段 | 产物 / 含义 |
|---|---|
| prepare | 原来源、真实split、帧对齐缓存、train-only norm；不是训练 |
| mse_pi05 / mse_affordvla | 两个仿真检查点在真实test的动作预测MSE；分Pick/Place、关节rad²/夹爪m²和mm²，首步与H20分报、排除末尾伪填充 |
| train | 真实π0.5混合BC更新、checkpoint、固定抽样表与domain |
| mse_mixed_pi05 | 同一真实test和指标的混合模型MSE |
| simulate | V4 test10×Pick/Place独立物理初态，各自纯模型测试、视频/trace/chunk/result；不等于完整三动作成功率 |
| complete / failed | 流程完成或真实失败保留；不等于任务成功 |

日志：`logs/<stage>.log`、`.launch.json`、`.exit.json`。状态：`pipeline_status.json`、`preparation_status.json`、`pi05/training_status.json`、`mse_*_progress.json`、`sim_evaluations/progress.json`。

MSE报告：`mse_{pi05,affordvla,mixed_pi05}.json`。离线误差不能当实机成功率；单次有种子flow采样不是多种子置信区间。当前只启动π混合，未称Afford混合或DAgger已经执行。

## 已完成的仿真模型→真机留出MSE（2026-10-09）

| 模型 | 动作 | 关节MSE rad²（14通道平均） | 夹爪MSE mm²（2通道平均） |
|---|---|---:|---:|
| π0.5 sim10000 | Pick | 0.0491940641 | 599.310014 |
| π0.5 sim10000 | Place | 0.0214130723 | 1009.699508 |
| Afford sim1000+10000 | Pick | 0.2218816（精确值见JSON） | 2352.94（精确值见JSON） |
| Afford sim1000+10000 | Place | 0.289961（精确值见JSON） | 1424.99（精确值见JSON） |

这些是每个有效H20目标向量的微平均，排除末尾填充和底盘；首步/每通道/每episode也存JSON，不能换算成实机任务成功率。π旧检查点主要接受拿取训练，Place离线MSE不表示已完成放下技能。

本机实时查看：`powershell -ExecutionPolicy Bypass -File .\scripts\watch_real_sim_transfer.ps1`。输出准备/MSE/训练/仿真测试阶段与实测百分比、当前训练ETA；Ctrl+C只退出查看。MSE报告未生成前不输出占位数冒充结果。

单位参考（本次已同时获用户确认）：[Galaxea R1 Pro软件接口](https://docs.galaxea-ai.com/Guide/R1Pro/software_introduction/R1Pro_Software_Guide_ROS2/) 的夹爪行程单位mm。实际数据转换依据仍是本run合同和原数据字段，而非通用模型名字。

## 5000步小样本预览（2026-10-09）

用户要求先看3–5个case：复用已完成保存的5000更新checkpoint（目录4999），训练继续；独立新目录 `runs/real_sim_pickplace_20261009_step5000_preview_v1`。冻结checkpoint receipt SHA与原评测代码SHA，固定原test来源前三个的3 Pick/2 Place，总5个独立动作case。只使用模型原始动作，原有真实动力学、限幅、接触和完成判定不变，无教师/IK/自动纠正。每case上限1000帧（50仿真秒），耗时不表示真实任务不可达。初始化来自原记录对应动作的物理初态，不是完整三动作连续演示。新运行输出progress、result、trace、三相机224视频和实际异常；小样本结果不外推总体成功率。训练与预览分别占用既有GPU1/GPU0空闲显存，不停止无关服务；预览OOM保留错误且不切换教师。
