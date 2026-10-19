# 三托盘新流程迁移与训练数据

2026-10-15用户授权：找回旧三托盘管线，迁移Isaac并拆分训练；随后明确只保留三个原文文本，推动改为新版带载左右手交接。旧数据只作参考，不直接重标。

## 已定位的旧资产与数据

服务器根B=/home/michelle/haoze/r1pro-airport-sim。

| 项目 | 服务器路径/数量 |
|---|---|
| 旧完整三盘任务控制 | releases/robust_v64_20260930/runs/v64_approximate_400/approximate_completion |
| 来源/动作计划 | runs/vla_20261005/task_complete_actions_v1/plans/all193_v4.jsonl |
| 旧官方八类数据 | 同数据根action8_export_{train,val,test}_parallel_v2/dataset |
| 完整来源 | train149 / val22 / test22，共193 |
| 旧八类动作片段 | train2654 / val390 / test381，共3425（不是新三类片段） |
| 历史训练 | runs/vla_20261005/action8_accelerated_v1，实际旧10步checkpoint；后来任务替换停止，旧pipeline_status非实时 |

旧FSM控制入口airport_fsm/{machine,runtime,primitives,geometry}.py。旧导出data_task_labels.py与data_task_lerobot.py按八类；旧cache/pipeline不能直接用于新流程训练。新发现通过导出manifest/plan比对父scene split，非宣称已重新hash全部193源；首批选中的train/val/test逐一核trace/result/scene/segments SHA。

## 新任务与数据

profile isaac_three_tray_loaded_action3_v1；rule 20261015_three_tray_loaded_handover_left_motion3cm_v1。

精确文本只有 Pick up the tray、Place the tray、Flush tray to the left。旧调度与槽位元数据保留，新推动需要乘客装载、右实际推→左稳定夹持→右松→tray真实左移≥3cm→左松及稳定支撑。没有推到最左端的要求。沿用当前相对长边/桌前/前向/容差；装载不进训练。每个三盘完整来源可以有多组动作段，三目录不是全任务仅三个片段；记录cycle/tray/父scene，不跨split。

目录格式：by_action/{pick_up_the_tray,place_the_tray,flush_tray_to_the_left}/{train,val,test}/<episode>/cycle_<id>_<tray>/。每片段四相机、trace、instruction.txt、帧范围/哈希；Cache三task id，float32数值、uint8图像、H20不越动作边界。新资格门要求三盘native状态及真实载荷/交接证据，旧push或TCP移动不能代替实际tray位移。

## 本轮服务器实测

新run runs/isaacsim_three_tray_loaded_20261015_v1：旧193源目录确认，选中三个split各一场景增加九件载荷，原生导入100步exit0；材料转换exit0；控制预检缺D6 transY exit1，失败保留。v1含旧视觉相机壳，只是资产诊断，不训练。

新run runs/isaacsim_three_tray_loaded_20261015_v2：仅去掉指定腕相机纯视觉壳，保留夹爪壳/手指/碰撞/惯量/相机。按源参数恢复缺失transY驱动，原X/yaw不改。原生双臂/夹爪/X/Y/yaw预检通过且实际wait0；三件PhysX GPU外套各63节点、有限且落地，未验证负载交互或任务成功。supervisor PID279583为历史启动身份，已正常退出，不能称仍在后台生成数据。

关键产物：preparation/legacy_inventory.json、parent_split_registry.json、scenes/{train,val,test}/*/scene.json；asset/airport_scene.usda；control/validated_scene.usda、validation.json、base_drive_translation.json、coat_native_probe.json；各阶段_child/_exit.json、pipeline_status.json与日志。

最新源码release isaacsim_three_tray_20261015_code_v4：服务器30项测试通过。v3曾遇NumPy/pybind enum标量比较兼容错误，测试失败证据保留；修成显式int，未启动失败测试版本的物理诊断。额外FK诊断位于v2/fk_diagnostic01，实际状态另核。

## 上轮资产阶段尚未完成项（历史快照，本轮进展见末节）

新完整三盘带载交接控制器、native全任务观察器与自动采集/训练/模型评测监督未完成。当前新完整合格来源0、训练片段0，training=waiting_for_data。单盘原生参考拿取也存在未抬盘失败，共同接触/几何映射仍须核对。不能拿资产预检或旧3425片段开始新规则训练。

新数据就绪后使用π0.5成功轨迹BC、冻结批次和train-only norm；未做DAgger不称DAgger。模型测试无教师/IK回退。视频和轨迹留服务器，本地只JSON/TXT。

## 最后核验 2026-10-15T16:53:04.333684+08:00

额外FK诊断fk_diagnostic01因晚创建articulation link RigidPrim GPU view失败，actual exit1保留；改为复用已有articulation tensor的get_link_transforms（安装源码确认XYZ+XYZW）后fk_diagnostic02实际exit0。八个腕/夹爪/指爪body相对base与源模型offline mj_forward对照，最大位置差0.00012679595m、朝向差约0.000210rad；只排除该probe位形下明显FK映射错误，不证明抓取或完整任务成功。没有MuJoCo步进或在线纠正。

服务器code_v5 30项测试通过；root/data_catalog_v1建立三动作空索引，每类0段并明确dataset_ready=false。该目录不是合格数据集。预览http://100.104.0.108:8775/three_tray_loaded_v2/index.html。正式训练未启动，资产监督已退出；不可称后台在继续生成或训练。真实快照：[verified_snapshot.json](../../runs/isaacsim_three_tray_loaded_20261015_v2_reference/verified_snapshot.json)。本机路径索引：[THREE_TRAY_ISAAC_DATA_LOCATION.txt](../../THREE_TRAY_ISAAC_DATA_LOCATION.txt)。

## 本轮原生控制与后台接线（2026-10-15，未全任务通过）

新增run runs/isaacsim_three_tray_workflow_20261015_v1，NativeRuntime实际PhysX/25×2ms/20Hz四相机，NativeTeacher只用私有mj_forward/IK规划、不执行mj_step；ThreeTrayObserver按真实接触和tray位移验收。第一轮Warp转NumPy错误修正；第二轮抓持失败；新质量检查发现导入tray27.733kg而源1.2kg，在新资产恢复237个body的源质量/质心/惯量，SDK逐项核对tray/刚性载荷通过。源夹指identity equality恢复到被动指NewtonMimicAPI，没有增加第二执行器；桌面过滤从不支持的碰撞叶子改为真实桌RigidBody，支撑力实际记录约11.77N/空盘。

demo03：实际完成第一盘空Pick/Place，支持分离真实tray移动11.28cm、双臂相对长边力26.72/126.63N、tray抬至约0.974m；实际Place[0.87368,0.35517,0.79991]，相对目标误差约2.4cm、长轴误差约3.6°，环境加载三件物品且机器人/trays位姿未变。Flush右下降中间姿态IK失败，actual exit1，保留全四视频/trace/contacts/错误；不是完整成功，不能进训练。

demo04/code_v6：复用以上取放，新增Flush桌前站位/13点右下降路径联合搜索，失败终态私有运动学预检选中base[0.32368,0.27517,0]；这只是规划证据，不能代替物理成功。完整demo正在服务器实测，后续更新以实际快照为准。

pipeline_v3/code_v7已独立session实际启动，外层guardian核验PID/birth/argv/cwd，普通协调进程退出最多3次10/30/90秒退避恢复，真实物理失败停止并保留；独立阶段runner落盘actual_wait和exit，协调器恢复可识别已有阶段子进程，不因长规划超时重启。隔离恢复测试、真实子任务exit3、防重复flock测试通过；17项观察器/数据/三盘测试通过。本轮只安全更换了等待协调器，没有向健康demo发signal。新BC入口使用冻结原生manifest和cache、train-only norm、三动作均衡、旧验证父权重、新优化器、双卡、冻结视觉/BF16+FP32、10/100/1000/10000/100000保存；关闭JAX默认预占，不停止无关GPU服务。数据就绪前waiting_for_data。

流水线第一批预登记train airport_0004_20270920（demo）、val airport_0028_20270944、test airport_0011_20270927，各自使用原父split和原生新scene；旧193源仅来源参考。新完整来源目前仍0，只有部分动作通过；未配置合格原生纯VLA评测时明确model_evaluation_pending，不让教师充当模型。首批若三源通过，仅是3完整源/27动作段的小样本，不能宣称200训练视频或总体成功率。

实时页：[demo04与流水线](http://100.104.0.108:8775/three_tray_native_workflow_v1/demo04_v3.html)。上一失败候选视频：[demo03原始证据](http://100.104.0.108:8775/three_tray_native_workflow_v1/index.html)。服务器日志demo04.log、pipeline_v3_supervisor.log、guardian_v3.log；状态pipeline_v3/pipeline_status.json、guardian_status.json，数据/检查点在该pipeline子目录，未生成前不能说目录中有数据。

## 后续实测：demo04失败与demo05新候选

demo04：首盘空取放、真实装载、右推、左稳定接管、右松、左手真实tray左移0.031538208m、左松均已发生；最终双手0N、桌面29.5043N。最终角点最大Y=0.66171234m，桌边Y=0.6m，即越界6.1712cm，超过5cm门1.1712cm；actual exit1，不入训练。新独立demo04_postmortem_v1.json绑定原trace SHA，未修改原失败记录。四原生视频各1755帧20Hz，head1920×1536/wrist1280×720，ffprobe闭合。

demo05/code_v9把Place预留从2.5cm调至4.2cm，利用既有位置容差预留后续真实推动空间，边界仍5cm、左接管后真实移动门仍3cm。新运行目录demo_candidate_05，原生完整任务重新实测；新qualification保存incomplete_cycle/终态诊断，trace增加payload_speed/payload_on_tray/boundary_ok/axis_error_rad/front_region_ok供失败定位。并未对旧04补成功标签。

最新后台pipeline_v4，启动身份coordinator620659、guardian620660、demo supervisor620654；这些是启动记录，当前存活须读/proc及状态再核。root为同一workflow_v1，日志pipeline_v4_supervisor.log/guardian_v4.log/demo05.log；pipeline_v4/pipeline_status.json与guardian_status.json。四阶段数据输出目标dataset_v1/three_actions_v1/cache_v1/training均在pipeline_v4内，当前未形成合格数据，不称已经训练。val/test资产预准备独立进行，split_asset_prestage_status.json明确qualification=false。旧失败作业已终态退出，不恢复旧任务条件。

最新实时页：[demo05](http://100.104.0.108:8775/three_tray_native_workflow_v1/demo05_v4.html)。正式模型原生闭环入口尚未完成；训练脚本不会调用教师补模型演示，也不能用小批训练loss代替任务成功。批次首三源若通过是train1/val1/test1、每源九段，总27段的小样本，仍不是200训练视频。

## 本轮继续：最新demo07与pipeline_v7（2026-10-15）

demo05在Place低位右臂IK失败；demo06补齐基于实测双臂抓持关系的14点下降站位预检，Pick/Place通过，真实右推5.6106cm、左接管/右松后tray左移3.2199cm、最终松手与载荷支撑，但末态仍超5cm边界，actual exit1。旧标签不改。demo07/code_v14仅把Flush桌前站位横向候选优先序改为-10/-12/-8cm等，在相同右手软工作区交接点和5cm边界内减少不必要右推；不改交接流程或3cm门。完整三盘demo仍待闭合。

主监督pipeline_v7与guardian、demo07均已独立后台启动。val scene_val_v2与test scene_test_v1控制/软体预检actual exit0；v1预检曾有无效USD joint路径错误，v2预准备监督曾遇exec瞬时/proc/cmdline空值，原失败保留。最新helper短暂重读后记录真实argv，20个隔离进程身份回归通过，18项核心测试通过；不能把这些称为完整任务通过。

expansion_v1已实际部署独立guard+producer，首批native合法三split/corpus/cache闭合后才启动新随机train来源，目标至少200个train动作片段（按9段/三盘完整源计，不按四相机文件数膨胀）；有限80个预登记seed，连续3个真实物理失败停止诊断。当前随机覆盖为同train父场景的小XY/yaw变体，不能称200个独立场景。只接受完整成功，dataset_v2/three_actions_v2/cache_v2不改v1；完成后排队等待首轮BC结束，再启动独立v2 BC，不竞争两个训练器。未接通原生纯模型评测时仍明确pending，禁止教师替代。

最新状态、PID/启动时间/argv/cwd及真实视频路径：[本轮快照](../../runs/isaacsim_three_tray_workflow_20261015_v1_reference/verified_snapshot.json)、[TXT索引](../../THREE_TRAY_ISAAC_WORKFLOW_STATUS.txt)。实时页http://100.104.0.108:8775/three_tray_native_workflow_v1/demo07_v7.html，根下CURRENT_NATIVE_PIPELINE.json只是派生指针，不是验收收据。

## 2026-10-15 最新实测：demo07整体失败，demo08物理验证中

九段局部动作完成不等于整体成功。demo07下一次Pick直接收臂击中已完成带载tray，frame1690/3477有实际接触（后者左指约1476N），前两盘最终落地，实际exit1/complete_task_success=false。保留全部失败视频和trace，合格新来源0，梯度训练0。证据runs/isaacsim_three_tray_workflow_20261015_v1/demo07_fall_postmortem_v1.json（服务器）。

code_v16/demo_candidate_08：在下一Pick准备中复用抬手12cm、桌前后退28cm后收臂，张爪保持既有0.1命令；不改变抓法、文本、容差。两个失败状态的8点私有IK路径通过，仅为运动学，不作物理通过结论。18项核心测试通过。独立后台demo启动PID1042812，pipeline_v8 PID1042847，外守护1042849，扩展守护1047541；启动身份见相应launch.json，存活须实时核验。pipeline_v8当前demo/waiting_for_data；demo全通过后才允许heldout源→冻结三split→三动作分片/cache→双卡BC。expansion_v3等待第一批合法数据，后续独立版本目标≥200 train动作段。视频入口http://100.104.0.108:8775/three_tray_native_workflow_v1/demo08_v8.html，视频未闭合不称完整交付。原生纯模型闭环评测入口仍待接通，不能把专家demo称模型演示。

2026-10-15 后台交接补充：pipeline_v9/code_v17在demo实际exit0之后复制独立真实wait receipt到数据验收路径，防止缺收据误阻塞；仅替换等待协调进程，demo08 PID1042812全程未发signal。主监督1060285、外守护1060286、expansion_v4守护1060287/producer1060288是启动记录，真实存活见monitor_latest。扩展守护隔离单实例/物理失败不重试测试通过，日志服务器expansion_guard_regression_v1/report.json。规范1.141，本地和服务器root --check通过，18核心测试通过。独立审计脚本反例检查准确拒绝demo07终态丢失载荷，不改旧标签。

### 2026-10-15 code_v18 / bootstrap09

demo08非完整成功：首两盘完成且未掉落（左移3.469/4.036cm），第三盘右推8.377cm时IK失败，未接管，actual exit1；视频和trace保持原失败，合格新源仍0。新候选联合桌前x/y/yaw搜索，持盘增量IK沿用旧配置而非额外严格2mm；对新候选预检完整交接路径，未改变验收。已部署真实无视频PhysX整任务回归PID1136581、wait1136580，bootstrap1139577/外守护1145558。无视频回归execution_mode=controller_diagnostic，不入数据。通过后自动起demo09四原生相机、pipeline_v10与expansion_v5；全部配置在workflow_v1，bootstrap09/status.json记录当前阶段。新候选完整物理结果、视频闭合、数据与训练均待实测，不用预计状态冒充成功。

## 2026-10-16 最新实际启动：demo10 / pipeline_v11

无视频reg09真实失败于第三Flush左手下降；目标盘右推1.39cm已完成，左指同时接触邻盘143.6N，邻盘z升至0.8611m，左TCP误差0.0531447m。保持5cm停止门，未训练。私有源几何复现left_handover_opening_clearance_v1.json：同抓点/姿态100mm开口对邻tray_1侵入12.809mm，40mm开口无该接触；不是物理通过。

code_v19仅在Flush左接管预测邻盘干涉较小时选择40mm接近开口，仍原长边/手姿/交接流程；无干涉和并列继续100mm。18项核心测试通过，规范1.143。已直接实际启动四相机demo_candidate_10 PID1224871、pipeline_v11监督1224911/外守护1224912、expansion_v6外守护1224914，均有birth/argv/cwd启动记录。00:07SGT/16:07UTC实测demo frame380第一Pick，三者identity_alive=true。root CURRENT_NATIVE_PIPELINE已更新，CURRENT_NATIVE_BOOTSTRAP旧失败指针存档，不再遮盖当前作业。无视频reg09不入训练，拟定demo09/pipeline_v10从未启动，不能报告为实际作业。

服务器路径W=/home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_three_tray_workflow_20261015_v1。状态W/pipeline_v11/pipeline_status.json；日志W/demo10.log、pipeline_v11_supervisor.log、guardian_v11.log。后续实际检查通过才生成W/pipeline_v11/{dataset_v1,three_actions_v1,cache_v1,training}；当前未就绪、0本轮梯度更新/检查点。视频页http://100.104.0.108:8775/three_tray_native_workflow_v1/demo10_v11.html。新GPU接触归约试验100个原生状态数值一致但更慢（约6.09ms vs原完整3.24ms），未采用，正式保留原逐2ms读取；性能失败证据保留。

## 2026-10-16 数据出口与监督最新核验

demo10原生进程仍为code_v19/PID1224871，全程未重启或发signal。data-only code_v21与v19 runtime/teacher/observer字节一致，监督pipeline_v12 PID1275481、外守护1275482，扩展expansion_v7守护1275483，首源三动作预览守护1275484/worker1275485均实际启动。W/pipeline_v12_handoff.json保存身份前后与只停止等待协调器证据；v20在部署前规范源清单检查失败，未启动或打断demo，历史重复scripts/isaac_mobile.py与包模块字节相同已同步本机后--check通过，新v21保留正确清单。

实际demo10第3700帧第三Pick，前两盘局部完整通过；完整源仍0。原100mm开口在前两盘预测无邻盘干涉，实际保留原100mm，未任意改变旧成功控制。第三盘40mm候选的实际效果仍待完整结果。即时预览只接收完整合格源并按三个动作分目录，不等待另两split；schema与正式训练批次分开，缺val/test不能启动训练。正式pipeline_v12三split冻结门不变。剪辑精确输入寻时+固定帧数已在head/wrist14个真实首尾/中间帧用RGB MD5逐个与旧帧索引解码完全一致，实际wait0；旧失败08标签不改。视频原分辨率20Hz与轨迹raw/submitted/time片段不缩减。

最新HTTP页http://100.104.0.108:8775/three_tray_native_workflow_v1/demo10_v12.html，成功后自动挂三动作预览链接。数据目标W/pipeline_v12/{dataset_v1,three_actions_v1,cache_v1,training}当前未就绪。预览W/demo10_action_preview_v1，仅源通过后才创建；W/demo10_preview_watch_v1/preview_status.json为真实等待状态。原生纯VLA闭环评测仍未接通，不把教师demo/训练loss称模型成功。


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

