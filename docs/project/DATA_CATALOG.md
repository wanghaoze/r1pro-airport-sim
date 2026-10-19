## 2026-10-19 MSE图表派生数据

参考本机test_last仅图型，旧G05数值未并入本项目。派生bundle `runs/web_mse_figures_20261019_v1/<jobId>` 从现有episode NPZ计算，无新增推理/训练数据。首次实测24 PNG=5汇总+Test19曲线，另CSV/provenance/ZIP；源是旧100步新300混合与real-only10000的配对评测，不是新10000结果。manifest与原report SHA绑定，图表可传Sites，原NPZ/视频留GPU。证据`runs/web_english_autoeval_20261019_v1/figure_render_status.json`。

## 2026-10-19 自动评测数据范围

自动评测保持固定Test19、3653个20Hz观测、69450个有效H20目标的配对协议，不扩展数据或重划split。比较新300对+真机50/50最终10000步与纯真机10000步baseline。VLA默认batch_001的32登记房间，仍为train父场景诊断；successRate=passed/(passed+modelFailures)，基础设施失败独立计数并展示覆盖率。旧100步MSE已于服务器完成，不能充作最新10k比较；旧VLA因原生初始化EOF且frames0失败，不是0%模型成功率。13:00只读证据`runs/web_english_autoeval_20261019_v1/initial_server_status.json`；新评测实际结果以该目录后续回执为准。网页“新增300”数据卡使用冻结300，不把生产多余13对显示为正在训练来源。

## 2026-10-17 自选配比登记与固定评测数据

DEC-WEB-004授权网页按0–100%选择真机/仿真域。登记的新增300对、旧窄30对、宽29对和真机134条来源不变，保留各父split，合并重复source_room拒绝；0%域不进训练/归一化。只读新300原冻结缓存，不纳额外13对。固定真实Train102/Val13/Test19，Val/Test不参与norm。配对MSE使用全部20Hz帧、H20有效目标及相同seed42000+frame噪声，按关节rad²、夹爪mm²分开，不与旧stride5报告混排。VLA32房间是train父场景诊断，不建立伪sim holdout。服务器33%/67%、500步输入准备和CPU官方transform实测通过，实际梯度更新0；这只是预检，不是新模型训练完成。证据 [CPU预检](../../runs/web_training_console_20261017_v1/cpu_preflight_result_v2.json)。此条替代下方“其他组合blocked”的旧网页边界，不改历史数据。

## 2026-10-17 17:18:52 SGT 新300来源已冻结且投入实际训练

DEC-055生产manifest ready：新合格来源313完整Pick/Place对，冻结300对/600动作段，额外13对未使用；history_pairs_included=0，sim全部train。混合BC的preparation ready，真机102/13/19不变、真机/仿真50/50采样；服务器实际153梯度更新。本条替代此前网页64/300或253/300快照作为当前导航；不改旧清单。证据[training_detail.json](../../runs/gpu_status_20261017_1718/training_detail.json)。

# 数据与媒体目录

2026-10-17网页数据选择scope：当前登记`isaac300_20261017`新增64/300完整对、128动作段（14:56服务器取样）、`real_pickplace_v2`真机134轨迹（102/13/19）、旧窄30/宽29完整对。三个sim来源均`simulation/program_generated`，真机`real_world/user_provided`；不改旧清单/标签/split。网页仅新300+真机的DEC-055配方可关联监督器，其余选择blocked计划；网页3D/草稿/服务器smoke不计训练数据。详见`runs/web_scene_agent_deploy_20261017/bridge_probe_result.json`。

2026-10-17网页agent仅登记本机`runs/isaac_parallel_live_deploy_20261016/closed32/{narrow,wide}_catalog.json`历史快照，ID为`isaac32_narrow_20261016`/`isaac32_wide_20261016`；30+29完整对、60+58片段、472四相机片段文件，均simulation/program_generated/train，非实时服务器总数。本轮只冻结选择到新run，不复制媒体或启动训练。只选旧59对的纯sim计划与DEC-055的新300对+真机50/50路线分开；后者保留真实val/test、sim仅作train。接口及限制见[网页agent导出](../../exports/web_scene_agent_v1/README.md)。

整理：2026-10-09，后续条目按日期更新。以下数量来自对应核验快照；D01–D08为 `simulation/program_generated`，D09/D11为真机来源，D10混合域必须分报。

服务器项目根 **B**：`/home/michelle/haoze/r1pro-airport-sim`。下表相对路径均在B内；实际数据不搬移、不合并、不改标签。

| ID / scope | 服务器run或数据根 | 数量 / split | 当前用途与限制 |
|---|---|---|---|
| 独立快速取放诊断 | `runs/isaacsim_fast_pickplace_20261016_v3` | 登记9个XY/yaw，实际闭合数见`audit_summary.json`；每来源2段×5相机 | [专题](ISAAC_FAST_PICKPLACE_20261016.md)，教师/非完整任务/非训练来源；原4相机保留，展示相机不作为模型输入，v1/v2历史失败与速度诊断保留 |
| D01 三动作V4完整任务 | `runs/three_actions_gripper_preserved_20261007_v4/data_batch_v1/datasets/{train,val,test}` | 120完整来源；train100/val10/test10；动作段300/30/30 | 正式三动作来源，完整任务成功门控；视觉保留夹爪本体；可达性预筛子集 |
| D01按动作媒体 | `runs/three_actions_gripper_preserved_20261007_v4/by_action/{pick_up_the_tray,place_the_tray,flush_tray_to_the_left}/{train,val,test}` | 360动作段、1080三相机文件 | 三相机不是三个独立episode；每源三段、环境装载排除 |
| D02 独立pickup200 | `runs/pickup200_20261007_v1/lerobot` | 200拿取episode、45223帧、600视频；全继承train | 拿取局部任务，不是完整三动作来源 |
| D03 pickup200相机壳隐藏版 | `runs/pickup_camera_shells_hidden_20261007_v2/lerobot` | 原200episode对应新视觉/官方导出 | 保留原状态/动作时间轴，临时视觉隐藏；不是新的物理成功采集；证据见专用TXT |
| D04 Afford/π pickup120对比 | `runs/afford_pi05_pickup120_20261007_v1/data/airport/pickup120_no_camera_shell_v1` | 固定前120训练episode、27135帧；编号120..169共50位姿留出 | 同父scene/原train谱系；留出不改标canonical test，不能称跨场景泛化 |
| D05 对比v2数据复用 | `runs/afford_pi05_pickup120_20261008_v2/{data,cache,models,source,pi05}` | 对D04旧run只读链接；新Afford训练与新评测另存 | 不重复计算已完成π训练，不修改旧评测基础失败 |
| D06 free_run诊断 | `runs/three_table_single_tray_20261006/free_run_diagnostic_20261007_v2` | 600秒/12000帧/四路原生；任务失败 | 检查关闭提前结束，不能进训练或成功率 |
| D07 旧action8 | `runs/vla_20261005/task_complete_actions_v1` | 历史193完整来源计划拆train149/val22/test22；当时数据闭合需看原快照 | 旧八类动作，不作为现三动作新规则数据；不要凭计划称全量ready |
| D08 历史v50/400 | `evidence/v50`（本机）；`resources/scenes`（本机） | 历史验收与本地来源分别登记 | 不是相同scene版本；历史70%目标未达证据不扩大 |
| D09 真机Pick/Place | 原件`/home/michelle/GalaxeaVLA/lerobot_data/*.tar.gz`；项目导入`runs/real_sim_pickplace_20261009_v1/real_sources_v2` | Pick79/Place55；30Hz，134episode；raw录制hash划102/13/19 | real_world/user_provided；单位/时间轴已核，不能标sim完整任务 |
| D10 混合BC/MSE | `runs/real_sim_pickplace_20261009_v3` | real train102＋V4sim10完整来源/30片段；固定90/10采样 | v2闭合cache/MSE只读导入；独立新πoptimizer。见[迁移实验](REAL_SIM_TRANSFER.md) |

## 帧、片段与来源

- 正式来源：完整物理result/trace/events/scene/XML，source qualification及父split绑定。
- 原生视频：四相机，原分辨率/20Hz，ffprobe、SHA、连续与terminal回放误差及实际退出码闭合。
- 训练视频：导出所需三视角，状态、动作、文本、半开时间窗对齐；train-only归一化。预调整在Pick、桌间搬运在Place、完整交接在Flush。
- 检查点训练输入冻结，不在读训练时增加来源；扩量另版本。失败、未闭合和free_run诊断排除。

## 本机兼容索引

| 内容 | 文件 |
|---|---|
| D01按动作路径与状态 | [THREE_ACTION_DATA_LOCATION.txt](../../THREE_ACTION_DATA_LOCATION.txt)、[THREE_ACTION_V4_VIDEO_PATHS.txt](../../THREE_ACTION_V4_VIDEO_PATHS.txt)、[THREE_ACTION_EXPANSION_STATUS.txt](../../THREE_ACTION_EXPANSION_STATUS.txt) |
| D02/D03独立拿取 | [PICKUP200_DATA_LOCATION.txt](../../PICKUP200_DATA_LOCATION.txt)、[PICKUP_CAMERA_VIDEO_LOCATION.txt](../../PICKUP_CAMERA_VIDEO_LOCATION.txt) |
| D04/D05对比 | [AFFORD_PI05_120_TRAINING.txt](../../AFFORD_PI05_120_TRAINING.txt) |
| D06诊断 | [FREE_RUN_DIAGNOSTIC_STATUS.txt](../../FREE_RUN_DIAGNOSTIC_STATUS.txt)、[FREE_RUN_VIDEO_PATHS.txt](../../FREE_RUN_VIDEO_PATHS.txt)、[FREE_RUN_TRAJECTORY_PATHS.txt](../../FREE_RUN_TRAJECTORY_PATHS.txt) |
| 早期失败归类 | [SCENE_VIDEO_INDEX.txt](../../SCENE_VIDEO_INDEX.txt) |
| 旧八类快照 | [TRAINING_DATA_LOCATION_ACTION8_HISTORICAL_20261005.txt](../../TRAINING_DATA_LOCATION_ACTION8_HISTORICAL_20261005.txt) |

这些TXT保留历史多段快照。以其时间/运行scope和实际manifest识别版本，不能只读旧头部就称实时结果。

D11（2026-10-12）纯真机：runs/real_only_pi05_20261012_v1/cache/{train,val,test}只读链接已核real cache；102/13/19动作episode、18853/2461/3653帧，训练采样与norm只real train。原始录制split沿用；详见[纯真机实验](REAL_ONLY_PI05_20261012.md)。

2026-10-12 新增评测产物（不是新训练集）：`runs/pi05_real_mixed_comparison_20261012_v1`，共19真机test来源/3653观测帧，纯真机与混合模型各69450有效H20目标；104PNG+104PDF。服务器保留两模型完整预测NPZ，本机图包及JSON/CSV/TXT可复核，入口[index.html](../../runs/pi05_real_mixed_comparison_20261012_v1/index.html)。原train/val/test与checkpoint未改。

2026-10-12 real2sim独立诊断：`runs/real2sim_pickplace_20261012_v3`。源为real_world/user_provided的test Pick5/Place3，439/195原始帧，20通道（16臂夹爪＋4腰）；执行产物simulation/real_command_replay，2轨迹/8预览，不入训练，不是三动作完整成功。全量原来源审计134episode/37447帧，split不改；[校验](../../runs/real2sim_pickplace_20261012_v3_reference/delivery_validation.json)、[媒体路径](../../REAL2SIM_VIDEO_PATHS.txt)。

2026-10-12配对闭环评测产物：服务器run pi05_real_mixed_closed_loop_20261012_v1，40个独立Pick/Place轨迹、160路224视频（均失败证据，不自动进训练）。模型、trace、raw决策留服务器，本机只有JSON/TXT；最终delivery_report和comparison_summary位于同名_reference目录，视频和轨迹完整路径见根PI05_CLOSED_LOOP_*_PATHS.txt。

## D14 real2sim配准与碰撞诊断（2026-10-12）

B/runs/real2sim_pickplace_20261012_v4…v8，均复用原test中的Pick episode5和Place episode3，各两个动作、每run8预览；不是新增独立真机来源，不能累计成多录制成功率。v8最后完整回放仍未通过Place初态验证，全部为诊断，不进入训练。来源real_world/user_provided、执行simulation/real_command_replay。B/resources/real2sim_finger_convex_20261012_v1为源URDF四指332凸体资源，B/resources/real2sim_registration_20261012_v3为候选配准，estimated_not_measured。[专题](REAL2SIM.md)。

2026-10-15 D15 新50/50采样版本：runs/real_sim50_pi05_20261015_v1/cache，原real102/13/19与sim V4 train10完整源/30片段只读链接，新冻结batch schedule80000次抽样（各40000）和train-only norm。不是新增独立轨迹或视频，原父split不变。[训练方案](PI05_MIX50_20261015.md)。


2026-10-15：Isaac新数据scope：runs/isaacsim_full_experiment_20261015_demo01/native_episode_01是失败诊断，不是训练collection。合格来源0、动作片段0；旧V4仍MuJoCo来源。新三动作冻结/分片/cache入口已实现，须原生完整任务观察器与split验收后放行。 详[Isaac专题](ISAACSIM_MIGRATION_20261015.md)。


2026-10-15：D17三托盘Isaac新规则：runs/isaacsim_three_tray_loaded_20261015_v2，三split各一个暂存场景（非合格来源），三盘共九载荷。旧D07实核193源、train149/val22/test22、旧八类2654/390/381，不能当新版三类带载数据；新合格来源/片段0。 见[三托盘迁移](ISAACSIM_THREE_TRAY_20261015.md)。

2026-10-15 原生三盘新控制：`runs/isaacsim_three_tray_workflow_20261015_v1`存放真实PhysX候选和失败证据；demo04首盘三个动作物理执行后边界失败，不是合格来源，不能拆其Pick/Place进正式训练。新数据仍0完整来源/0训练动作段。pipeline_v4在demo05闭合后自动原生采集预登记val/test父场景、冻结dataset_v1、three_actions_v1和cache_v1，再BC；这些名字当前是目标位置，不能据空目录称就绪。旧193/3425不变、不重标。详[专题](ISAACSIM_THREE_TRAY_20261015.md)。

2026-10-15 最新执行版本：code_v16、demo08/pipeline_v8；旧demo07因下一Pick收臂击落前两只完成盘而整体失败，九段局部通过不入库。新撤离路径仍在Pick准备内，不新增动作文本或容差。数据当前0合格源、0训练步，后台生成导出训练门已接通，等待真实完整成功；后续expansion_v3独立批次不修改首批。状态证据见ISAACSIM_THREE_TRAY_20261015.md与根TXT索引。

2026-10-16 原生三盘本轮出口：pipeline_v12/数据版本v1，首源通过即可单独发布demo10_action_preview_v1（三文本九段，非三split训练批次）；正式dataset_v1/three_actions_v1/cache_v1仍要求真实train/val/test完整来源闭合。不能用目录存在、预览schema或旧MuJoCo193宣称新数据ready。原始视频留各native case；分片每源九段/36相机文件，数量不混称。路径与实测证据见ISAACSIM_THREE_TRAY_20261015.md及根THREE_TRAY_ISAAC_*TXT。


## 2026-10-16 最新实测：demo11 / pipeline_v13

三托盘原生完整任务仍在运行，尚未完成验收。2026-10-15T17:20:33Z核验frame3640，第二盘Flush；demo PID1347151、监督1347188、外守护1347189均以birth/argv/cwd核验存活。完整合格来源0，训练waiting_for_data、无本轮新梯度/检查点。视频轨迹保留服务器，新目录demo_candidate_11；旧失败不改。

上个demo10第三盘接管后实际左移1.050cm即被旧桌侧门中断，不能作为成功。只读复核该时刻底盘相对合法桌前参考漂移0.9914cm，越旧切线约0.118mm，属于用户已允许5cm受力漂移。code_v22保留严格桌前规划，仅运行时从固定合法参考计算5cm欧氏漂移、不随目标蠕动重锚；trace和独立验收记录实际参考/漂移。末次Flush在实际松手后先抬离邻盘再全开，原交接顺序、长边和真实接触验收不变；旧qualification不改。22项相关核心测试通过。

当前监督已接demo实际wait0和视频/轨迹验收→新val/test完整来源→冻结dataset_v1→三动作three_actions_v1→cache_v1→双卡BC。首批是计划train1/val1/test1共3完整来源/27动作段，未就绪不得称已有数据。独立expansion_v8守护1347190等待首批，后续版本不修改训练读取清单；demo11_preview_watch_v1守护1347191仅在完整源通过后导出九段预览，不能充当三split训练批次。纯VLA原生闭环入口仍待接通，不用教师demo或loss称模型成功。

本轮根W=/home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_three_tray_workflow_20261015_v1。实际状态W/pipeline_v13/pipeline_status.json、guardian_status.json；日志W/demo11.log、pipeline_v13_supervisor.log、guardian_v13.log。数据目标W/pipeline_v13/{dataset_v1,three_actions_v1,cache_v1,training}。只读媒体新入口http://100.104.0.108:8776/demo11_v13.html，PID1390518，Range实际校验通过，旧8775保留，未中断健康demo。当前视频尚未全部闭合，不宣完整demo通过。后续状态以实时快照和真实产物为准。



## 2026-10-16 最新验收：三托盘原生 demo12 已完整通过，后台已进入采集

本轮首次完整原生三盘demo通过（code_v23，任务容差不变），不是模型执行。独立审计实际exit0，完整来源1、9动作段；四路原生各5462帧/20Hz，136550个真实PhysX子步；左右手交接后真实左移3.248/3.120/3.359cm。最终六个手盘接触力0N、桌面支撑29.40/29.70/29.31N，三盘各三件载荷仍在盘、边界通过。放置轴误差3.499/3.155/0.376°；操作时固定合法桌前参考的最大真实底盘漂移1.169cm（授权5cm）。独立证据：[完整审计](../../runs/isaacsim_three_tray_workflow_20261015_v1_reference/demo12_independent_closure_audit_v1.json)、[退出收据](../../runs/isaacsim_three_tray_workflow_20261015_v1_reference/demo12_audit_exit.json)。

demo11仍为失败：第二盘已左移4.708cm，但低位全开碰到邻盘，实际开口27.15mm对比命令100mm，目标/邻盘接触约10.41/49.66N，exit1未重标。code_v23改为每盘Flush先有限解夹、竖直退出12cm、再全开并过原真实释放门；原动作、抓法和验收不变。22项相关测试通过；根规范1.148（控制冻结release内1.147，后续仅补只读监测说明）。

2026-10-15T18:05:37Z实核后台：pipeline_v14监督PID1416209、外守护1416210，实际val采集PID1505047，case_0000已运行到首Pick frame280；不是只挂等待进程。运行器/监督/守护均无TTY、stdin=/dev/null、独立session，SSH退出后仍存活。首批计划train1/val1/test1共3完整来源/27动作段；当前仅1来源通过，正式三split冻结清单/缓存尚未就绪，training=waiting_for_data、实际本轮更新0、无新检查点。新val/test原生通过后自动freeze→三动作完整视频/状态/控制切片→基本检查/缓存→已验证父模型、新优化器、双卡BF16/FP32 PEFT BC。不是DAgger，纯VLA原生评测入口仍待接通。

服务器根W=/home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_three_tray_workflow_20261015_v1。已合格源W/demo_candidate_12；后台当前W/pipeline_v14/episodes/case_0000；状态W/pipeline_v14/pipeline_status.json、guardian_status.json；日志W/pipeline_v14_supervisor.log、guardian_v14.log、pipeline_v14/logs/episode_0000.log。未来正式批次W/pipeline_v14/{dataset_v1,three_actions_v1,cache_v1,training}。即时三动作预览W/demo12_action_preview_v1已闭合9段/36视频，不是合法三split训练批次；export_progress逐段计真正闭合的四路视频。expansion_v9守护1416213等待首批后生成小XY/yaw同父train来源变体，目标≥200 train动作段，后续另冻结版本，不覆盖训练读取清单。

[完整四相机视频与实时状态](http://100.104.0.108:8776/demo12_v14.html)已实际发布、应用打开请求已排队；只读Range服务PID1390518，旧8775保留。视频/轨迹均留服务器，只同步JSON/TXT。当前进程与采集进度用scripts/watch_isaac_three_tray.ps1 -Watch重新实核；本地TXT是最近查询快照，不是永久后台同步。单条通过不是泛化成功率或训练模型成功。


2026-10-16 02:10 SGT更新：demo12三动作预览已全部闭合，1完整合格来源、Pick3/Place3/Flush3共9段、36相机文件（不是36条轨迹）。视频/轨迹/精确文本对应的三个目录为demo12_action_preview_v1/by_action/{pick_up_the_tray,place_the_tray,flush_tray_to_the_left}。manifest schema=airport_isaac_episode_action_preview/1，ready=true，training_cache_ready=false，仍不是合法三split训练批次。入口http://100.104.0.108:8776/demo12_action_preview_v1/index.html，实际HTTP200。val原生采集PID1505047健康，首Place frame1020；监督1416209、外守护1416210存活，training仍waiting_for_data。证据本地runs/isaacsim_three_tray_workflow_20261015_v1_reference/demo12_action_preview_manifest.json。


## 2026-10-16 02:58 SGT 当前实测：完整demo与val通过；test修复版后台运行

本轮scope为原生Isaac三托盘新版带载交接、仅三条精确文本；不是单托盘或模型执行。完整demo12通过，实际exit0，独立审计四相机各5462帧/20Hz、136550真实PhysX子步、9动作段；三盘实测左移3.248/3.120/3.359cm，最终双手全部释放、各盘及三件载荷稳定支撑、边界通过。证据本地runs/isaacsim_three_tray_workflow_20261015_v1_reference/demo12_independent_closure_audit_v1.json。三动作预览全部闭合：Pick3/Place3/Flush3、36相机文件；36不是轨迹数。网址http://100.104.0.108:8776/demo12_action_preview_v1/index.html。视频和轨迹留服务器。

val原生完整来源也已实际exit0并通过validate_episode，证据val_complete_validation.json/val_complete_exit.json。当前合格完整来源train1/val1/test0，共18个源动作span；当前已导出的即时预览仍只有train来源9段，不是三split批次。training=waiting_for_data，实际本轮更新0，无新checkpoint。首批3合法完整来源/27动作段闭合后自动冻结→三个动作目录导出/基本检查/缓存→已验证父模型+新优化器+双卡BF16/FP32 PEFT BC。未执行DAgger，纯VLA原生评测入口仍待接通。

旧pipeline_v14的test首Pick站位搜索失败，真实失败和视频保留在pipeline_v14/episodes/case_0001，不改标签。确认旧选择器固定face、窄横移，未联合底盘yaw；同一实际初态yaw0.395378rad，私有源探针找到3个严格桌前双臂长边/9点下降可达候选（仅规划证据，不是物理通过）。code_v24保留旧成功候选优先，补充合法桌前联合yaw/横移/距离搜索；不扩大桌前活动范围、不换抓法、不加容差。22项核心测试通过、规范1.149，完整demo12和val不重复生成。

新的pipeline_v15实际复核复用2条成功源，只重跑同父test、同seed44到新目录pipeline_v15/episodes/case_0000，唯一episode_id避免与旧val同名。实核新test PID1629246已执行首Pick到frame300，监督1623767/外守护1623768均birth/argv/cwd存活；expansion_v10守护1623769等待首批缓存后继续同父小XY/yaw随机变体，目标≥200 train动作段，后续数据另版。旧v14监督/守护已终态退出，不再称存活。完整任务通过、数据就绪、训练启动分别验收，当前不是训练中。

服务器W=/home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_three_tray_workflow_20261015_v1。当前状态W/pipeline_v15/pipeline_status.json、guardian_status.json；日志W/pipeline_v15_supervisor.log、guardian_v15.log、pipeline_v15/logs/episode_0000.log。合格源W/demo_candidate_12与W/pipeline_v14/episodes/case_0000。未来正式数据W/pipeline_v15/{dataset_v1,three_actions_v1,cache_v1}，未来训练/检查点W/pipeline_v15/training（当前未创建checkpoint）。全视频路径每个一行见THREE_TRAY_ISAAC_VIDEO_PATHS.txt，位置/状态见THREE_TRAY_ISAAC_DATA_LOCATION.txt、THREE_TRAY_ISAAC_WORKFLOW_STATUS.txt。实时入口http://100.104.0.108:8776/demo12_v15.html；旧v14页为历史协调器状态。watch_isaac_three_tray.ps1 -Watch只读同步JSON/TXT；本地文件是最近查询快照，不是永久常驻同步。



2026-10-16 单例平稳短片v9：`runs/isaacsim_fast_stability_20261016_v9_recorded`，真实五路259帧/20Hz、两个3秒动作，原生exit/独立审计闭合；专家诊断非正式完整来源，training_eligible=false。原BC恢复仍引用pipeline_v15冻结train1/val1/test1三个完整来源/27动作span，不把五路文件数当来源数，不将快视频混入。最新恢复阶段见BC resume监控。


2026-10-16 固定底盘两动作新专项（DEC-048）：服务器runs/isaacsim_fixed_pickplace_20261016_v1/dataset/{pick_up_the_tray,place_the_tray}/train/case_NNN，四训练相机＋一展示/trajectory.npz/segment.json。每对完整Pick→Place闭合后导出，Place起点是真实Pick末态；batch manifest逐对冻结，dataset_catalog动态索引但不直接作为训练读取中的可变清单。原父airport_0004_20270920/train不拆到val/test；当前只有2个登记验证候选、尚待原生出口，不是200条/VLA来源/完整三盘训练数据。状态ISAAC_FIXED_PICKPLACE_STATUS.txt，视频每行路径ISAAC_FIXED_PICKPLACE_VIDEO_PATHS.txt。


### 2026-10-16 C32网格采集与初态多样性实施中

DEC-050/规范1.163。新模块`real2sim/isaac_parallel_collection.py`：独立房间坐标、批量18关节映射、父split检查、全180度对称区间的桌内采样（只是几何条件，不是可达性）、有界无丢帧编码。`scripts/probe_isaac_parallel_collection.py`及`supervise_isaac_parallel_probe.py`先做单engine实际PhysX与四相机逐级集成，probe明确不进训练；非批量自适应控制器或完整任务验收。服务器新run `runs/isaacsim_parallel_collection_20261016_v1`，初次4房间10帧/250真实全局子步/16视频actual wait0；完整4→8→16→32仍待实际产物。大初态单臂预调整与不同真实持盘Place资格尚待接通，不能称已支持或已批量生成。原固定底盘串行两对4片段已正常闭合；BC0更新初始化按用户C资源安排暂缓，无更新丢失，原数据权重保留。


2026-10-16最新补充（覆盖前述待完成快照）：规范1.164。32v1句柄耗尽失败保留；新v2/code44仅本进程65536软额、显式双GPU相机分配/房间材质引用、复用4/8/16真实审计后重跑32。单臂准备code43真实碰撞足迹纠正矩形代理误判；case_004仍抬升/倾18度并实际外伸5.11cm，失败未进训练，姿态泛化尚未通过。可变长度Pick分片已接end−start，含预调整；Place保留实际连续末态。代码/数据/原生与模型成功分开，C32自适应批量控制仍待接通；旧2对4片段和旧BC保留。新scope与阻塞见memory/CURRENT.md及server实际报告。

2026-10-16 DEC-051：新增75度桌前联合站位候选case_005，不是已就绪数据。旧固定两动作集仍2完整对/4片段，train-only；Place来自实际专家Pick，不称VLA源。32房间v3仅integration，qualified=0。失败case_003/004与v2真实wait=-11不改标签。新来源须完整取放、媒体与实际退出审计后另冻结，不替换旧BC数据。

14:31 SGT：C32 v3实际exit0/128视频闭合，但仍integration非训练。case_005失败，code47/case_006已选单臂准备站位、验收未闭合。新数据0，旧固定取放仍2对/4段。原BC新恢复输出bc_resume_after_parallel_20261016_v2，只读复用原三盘3完整来源/27片段，不用新候选。

2026-10-16 新直接可达固定底盘生产：服务器runs/isaacsim_reachable_private_candidates_20261016_v2；production_config.json冻结64个私有路径候选，非64成功源。数据按dataset/pick_up_the_tray/train与dataset/place_the_tray/train导出，完整对数以dataset_catalog.json为准。当前只原父airport_0004_20270920/train，不能声称合法三split训练就绪。独立fixedbase_v1中心验证已原生完整通过，不计批量产量。

## 2026-10-16 方案C两批32房间实际闭合

2026-10-16: Scheme C actual closed results.
32 rooms, one engine/PhysicsScene/shared clock, GPU0 physics + two-GPU rendering.
Scope: expert fixed-base empty Pick/Place, not VLA execution or three-action full task.
narrow: 30/32 qualified complete pairs; 60 segments; simulation/record+export 1246.983s; 86.61 pairs/hour (initial load excluded).
wide: 29/32 qualified complete pairs; 58 segments; simulation/record+export 1260.709s; 82.81 pairs/hour (initial load excluded).
Both batches completed, native/export actual wait exit0. Historical native PIDs3813001/3879610 are not reported as live.
59 pairs /118 segments across these two batches, all train. Four-room validation overlaps narrow batch and is not added.
Training paused; no legal val/test in these batches.
Server narrow: /home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_parallel_live_20261016_v3/native
Server wide: /home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_parallel_wide_station_20261016_v1/native
Wide viewer: http://100.104.0.108:8776/parallel_wide_station_32_20261016_v1/native/dataset_viewer.html
Evidence: runs/isaac_parallel_live_deploy_20261016/closed32/{narrow_catalog,wide_catalog}.json

更分散批初始tray y约[-.303,.301]m，32不同初态及不同桌前base，动作期间命令固定。5个失败源保留排除：3个实际初态路径预检失败、1个Pick物理终态失败、1个持续抓取接触丢失。未改变任务门；不把原生进程exit0等同全部成功。27测试通过/1平台skip；规范sync和handoff check通过。

## 2026-10-17 新300来源与耗时加权混合BC已接通后台

2026-10-17 14:18 SGT verified snapshot (not a permanent local monitor).
Scope: 300 NEW complete fixed-base Pick/Place pairs, 600 action segments, previous59 excluded.
Collection guard1996949/start43047257; supervisor1996950/start43047260; native2006582/start43059320.
Current first batch:32 rooms,20 actual shared frames/500 native substeps; complete new pairs0/300.
Production root: /home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_parallel_pickplace300_20261017_v1
Final data manifest (only after ready): dataset_v1/manifest.json
Production logs: guard.log, supervisor_attempt_0.log, batch_000/native.log; status production_status.json.
Training root: /home/michelle/haoze/r1pro-airport-sim/runs/real_isaac300_timeweighted_pi05_20261017_v1
Training guard2020466/start43087432; supervisor2020468/start43087434; stage waiting_for_data, verified gradient updates0.
Training release: real_isaac300_timeweighted_training_20261017_v3.
Automatic sequence:300 qualified frozen pairs -> verified cache -> official input conversion -> two GPU BC10/100/1000/10000 -> original real test19 offline MSE.
Method: duration-weighted sampling BC; NOT RL/DAgger. Per batch real4/sim4; each domain Pick2/Place2.
Within domain/action source weight clip(median duration / source duration,0.5,2); source-first then uniform frame sampling. Full source frames retained.
Sim state base relative to original measured episode origin; action zero hold. Arm radians and gripper meters unchanged. Real split102/13/19 preserved; sim train only, no synthetic holdout.
Expected checkpoint root: pi05/checkpoints/pi05_parallel_pickplace_real50/training/ (none saved for this run yet).
CPU smoke2 complete sources/4 segments/240 frames and official Observation conversion passed; no GPU gradient smoke yet.
Native pure VLA rollout and faster/stabler execution are pending and not established by offline MSE.
Estimated collection4-5h from prior batches, not current measured ETA; monitor reports stage-specific actual throughput/ETA.
Monitor: powershell -ExecutionPolicy Bypass -File .\scripts\watch_pickplace300_mix.ps1

实际部署证据：runs/real_isaac300_timeweighted_reference_20261017/{deployment_receipt,pipeline_status}.json；服务器CPUsmoke real_isaac300_timeweighted_adapter_smoke_20261017_v2。旧smoke父status/metadata兼容失败保留，新v3已修，不能把CPU验证称梯度已开始。
