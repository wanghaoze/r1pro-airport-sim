## 2026-10-19 实际相机→模型→Isaac 诊断与录像

scope=DEC-WEB-009。新release studio_live_inference_20261019_v3，GPU0独立执行，未停止GPU1 Ollama。π0.5最新50/50 10000检查点在live_pi05_20261019_v2实际收5次原生相机观测、执行20帧(1.00s仿真)，墙钟12.5738s，后续left_arm_joint4输出越机械限位停止，PickPlace0/1；非持续20Hz实时。首推理4.002s，后续约0.439s；无裁剪/IK/教师。原生overview+3输入相机导出16.60s墙钟版视频(含4s结果页)，等待未隐藏，SHA在video receipt。视频本次用户明确授权同步本地。

G0.5 last.pt真实加载并根据Isaac相机推理约9.88s，AR输出缺左右夹爪，严格完整动作拒绝，0执行帧/1基础设施失败；不能报0%模型成功率。已异步询问是否允许明确的arms-only measured-gripper-hold，尚待答复，未启用隐式补齐。注册中unconfirmed状态按本轮及既有100%=80mm明确授权重新登记percent80，旧registry保存在失败v1目录。

π0.5持久服务runs/live_pi05_server_20261019_v1，G0.5持久服务runs/live_g05_20261019_v2，本轮实核心跳/进程身份存[servers.json](../../runs/realtime_inference_20261019_v1/servers.json)，PID不当永久存活保证。前者HTTP /health通过；后者v2无GET health，真实权重加载/推理日志与进程证据保留。GR00T缺兼容权重。启动/服务/导出说明[指南](../site/LIVE_INFERENCE.md)，交付[ZIP](../../output/live_inference_20261019.zip)。30项回归通过，旧v1检查点绑定缺失启动失败保留，新v2补冻结后实测。

## 2026-10-19 ROS2诊断状态

π0.5和G0.5独立单房间200帧/action诊断已登记，当前waiting_gpu；另一个Ollama GPU服务占用约36GB，未停止。G0.5 last.pt解析step51810，100%=80mm，30Hz训练/20Hz诊断用户批准。ROS2 domain86图像/19通道/动作H1回环合成测试通过（实际退出0），不包含权重推理或物理成功；GR00T权重待配置。证据[verification](../../runs/web_offline_ros2_20261019_v1/verification.json)。

## 2026-10-19 13:32 SGT 英文网站、自动最终检查点评测与MSE图表

## 2026-10-19 English PPT and full-frame MSE delivery

scope=DEC-PPT-001. Delivered 22-slide English PPT v2 with two embedded English-captioned videos, three editable MSE charts, five tables and a portable ZIP. Incorporated the user-shared latest website record, including MSE/RMSE, 4x4 episode traces, downloads and precise navigation. [Delivery evidence](../../runs/presentation_20261019_v1/DELIVERY.md) and [manifest](../../runs/presentation_20261019_v1/delivery_manifest.json).

Fresh Real50/Sim50 10000-update full Test19 MSE completed 13:37:20 SGT, actual child wait exit 0: 3653 frames / 69450 valid horizon targets, truth/mask identities matched baseline. Arms 0.0072298731 rad² (+6.80% vs real-only); grippers 356.79582 mm² (-12.20%). Archived Real90/Sim10 improves arms 4.04% and grippers 7.86%. Different initializations/data recipes prevent causal attribution to ratio alone; offline MSE is not task success. This supersedes only the earlier snapshot saying presentation job a66d9401 was still running, not other automatic queued jobs. [Full result](../../runs/presentation_20261019_v1/full_mse_progress.json).

User real-video recipe remains Real10/Sim90, 10000 updates, with exact hash/execution mode unverified. No physical robot control or additional training. PPT package/layout/media checks and ZIP CRC pass; native PowerPoint playback untested. Current website/GPU status is limited to timestamped evidence.

scope=DEC-WEB-005/006，替代下方10月17日训练仍运行/未评测的当前状态，旧记录保留。英文首版Sites v5已交付，自动评测v6已启用，含图表与下载的v7于13:26:40发布成功，commit `d35f8d2f42fd7c2023cc248b5d7c4e0afed8421b`；站点public受众保持，GPU提交与图表文件读取限owner。

- 新300对+真机50/50训练实际10000/10000，最终检查点`cp_8788068a6984a796aed42ef1`已闭合且actual child wait=0。自动parent `1f8985e7-4295-485e-8ea3-303844a8de41`冻结选择最新10000步；VLA `avla_c9c6f69c3fa6b0bd34dde0b2`、配对MSE `amse_c9c6f69c3fa6b0bd34dde0b2`已登记并waiting_gpu。当前先提交MSE `a66d9401-410c-4d2e-a609-457c07fe9e23`仍健康运行，13:28:01为2401/3653、剩余推理约558秒，排除初始化/出图；未停止/重复启动。
- 自动VLA为32训练父场景诊断、每动作200帧/20Hz、纯模型/固定底盘mask；无教师/IK回退。自动MSE为最终10000与real-only10000固定Test19配对。网站显示分子/分母、基础设施失败、覆盖率、MSE与baseline变化；当前新评测尚无数值结果，不能称验证成功。旧VLA100步room0的EULA EOF/原生frames0仍是基础设施失败，继承既有启动环境的修复尚待新job实际启动验证。
- 已完成旧MSE `8c9bed41`（100步mixed对10000步real-only）实测报告保留，3653帧/69450有效H20目标。独立CPU派生24张PNG（5汇总+19episode）、CSV、provenance、ZIP，actualwait0；数值、valid/truth SHA与原report核对通过。示例test_last仅参考图型，未混入别的模型数值。13:31:57图表27/27对象已上传Sites R2、无错误，ZIP CRC通过且含24 PNG/CSV/provenance、不含原始NPZ；正式网页Ready、24选项、PNG/CSV/ZIP入口、柱状图/4×4切换及2700×1755曲线加载已核验；后续MSE完成后同流程自动出图，原数组/视频仍留GPU。
- GPU release `web_studio_auto_20261019_v2`，bridge `web_scene_agent_bridge_20261019_v2` PID3479057/start60061960于13:28实核polling/last_error=null；只替换核验身份的自身bridge，旧bridge实际exit0，原当前MSE仍用v1release且健康。新自选训练默认autoEvaluate=true，可关闭；确定性任务ID与成功训练退出门避免提前/重复评测。
- 本机与GPU各52项Python测试，既有9项Node、4条英文解析断言、类型检查、构建、规范1.176与catalog check通过。英文UI/历史回执/基础指令可用；GPT API未配置。当前仅本机可用1会话源，显式4线程导出79条，不能声称恢复了所有历史档案；导出脚本非自动常驻。

证据：../../runs/web_english_autoeval_20261019_v1/verification.json、../../runs/web_english_autoeval_20261019_v1/final_deployment.json、../../runs/web_english_autoeval_20261019_v1/final_server_status.json、../../runs/web_english_autoeval_20261019_v1/final_queue_status.json、../../runs/web_english_autoeval_20261019_v1/figure_publication_status.json、../../runs/web_english_autoeval_20261019_v1/production_mse_ready.png。

## 2026-10-17 17:52 SGT 网页训练控制台与评测队列已发布

scope=DEC-WEB-004。用户批准真机/仿真0–100%采样配比、登记数据集/步数、独立新任务、Isaac纯模型闭环与固定真机Val/Test MSE。Sites版本4已成功发布，commit `ea9df936fded6a4bf2a0bd6c93d38e29472213b7`。本轮读取站点实际access_mode=public并保持，替代下方owner-private作为当前状态的说法；未变更受众。GPU提交由平台登录身份及服务器owner配置限制。

- 正式网页每10秒更新实际梯度、阶段、loss、下一检查点和剩余梯度ETA。17:51:31服务器451/10000，17:51:59网页466/10000（4.7%），当前50/50训练仍运行于原release，PID2455853/start44123269，双GPU均100%。窗口ETA约5.1–6.5小时，仅剩余梯度计算，排除初始化/保存/MSE/VLA；10/100更新检查点已保存。曾在327步短暂不推进，证据保留，随后自行恢复，未重启或认定死锁。
- 新GPU backend release `web_studio_training_20261017_v5`，bridge run `web_scene_agent_bridge_20261017_v6`，17:51:31核PID2538408/start44331550、polling、last_error=null；仅替换自身bridge，当前训练/冻结300对600段/检查点未修改。网页显示排队和过期状态，无法实测时不伪造进度。
- 两项真实网页请求已在GPU落盘且waiting_gpu：VLA `dcb77b17-5e87-4d9a-aeda-ddc0fac0bc94` 用新300混合100步checkpoint、room0、200帧/动作；MSE `8c9bed41-8042-4f81-8d9b-7768c9c6f8ba` 比较该checkpoint与真机10000步checkpoint，固定Test19全部20Hz/H20。不同训练预算须保留；当前没有评测结果。VLA是train父场景诊断，显式固定底盘执行掩码，无教师/IK回退，不称held-out泛化。
- 新真机33%/sim67%、500步配方的独立准备与官方CPU输入转换实际exit0；zero gradient updates/model_initialized=false。首个预检warmup失败现场保留，新v2验证短步数warmup修复；不把CPU预检称新模型训练成功。
- 本机与GPU40项Python测试通过，9项Node测试、类型检查、构建通过，正式网页动态445→458→466、配方、两项排队回执已核验。规范1.174人工更新后同步检查通过。完整自选GPU训练和VLA/MSE数值结果仍待队列实际执行。GPT API仍未配置，基础指令模式保持。

证据：[交付核验](../../runs/web_training_console_20261017_v1/verification.json)、[服务器快照](../../runs/web_training_console_20261017_v1/final_server_status.json)、[正式发布](../../runs/web_training_console_20261017_v1/deployment.json)、[正式画面](../../runs/web_training_console_20261017_v1/production_training.png)、[队列](../../runs/web_training_console_20261017_v1/production_queue.png)。

## 2026-10-17 17:18:52 SGT 服务器实际梯度训练已开始

scope=DEC-055 新300来源+真机50/50耗时加权BC。只读实查，不重启或修改作业。替代此前waiting_for_data/0updates的历史快照。

两次采样143→153实际梯度步，当前training，监督阶段train_1000，总目标10000。训练PID2455853/start44123269，既有监督器2020468/start43087434；两张RTX PRO6000 Blackwell实际cuda:0/cuda:1，17:18:31 GPU利用率各100%，该训练进程各约17.6GiB显存。10/100步阶段实际exit0，检查点9/99的params与train_state目录已存在（对应10/100次更新）。最新loss0.08964仅训练指标，未代表模型测试成功。

新来源实际313完整对，冻结选择300对/600段、额外13对未入此次训练，旧59对未混入；sim全部train。preparation ready，真机train102/val13/test19，50/50按域采样。生产complete且原生产监督器PID已不存在；其历史training_started=false只属于生产记录。训练pipeline的complete_source_pairs=283仍为先前等待快照；以独立冻结manifest300与training_status实际梯度为准。日志有Orbax metrics附属文件缺失及PTX驱动编译回退提示，检查点恢复后实际步数继续增长，未据此重启健康任务。当前非训练结束、非模型测试通过。

证据：[服务器/GPU快照](../../runs/gpu_status_20261017_1718/status.json)、[梯度与检查点](../../runs/gpu_status_20261017_1718/training_detail.json)。

## 2026-10-17 网页正式链路与材质修复验收

2026-10-17T16:48:41.420127+08:00，scope=web。正式登录后，网页产生两个真实队列请求，GPU分别返回draft_synced与attached_existing，现场JSON与网页均核验。16:34:57采样253/300、训练waiting_for_data/0updates，不代表当前持续状态或训练成功。实验室背景原先被隐藏、默认灰色覆盖源材质，现已修复并发布；正式草稿恢复原色保存，保留三桌单盘和静态初态。源码6项CPU指令、2项恢复范围、类型/构建与浏览器画面通过。原生episode/相机等价、GPT接口仍未由此验证。[回执](../../runs/web_scene_agent_deploy_20261017/production_e2e_20261017_1635.json) / [视觉发布证据](../../runs/web_scene_agent_materials_20261017_v1/verification.json)。

## 2026-10-17 网页agent第一阶段导出

## 2026-10-17 14:56 SGT 网页项目部署实测

Sites私有发布succeeded；GPU主动连接API200，服务器smoke新32房间草稿draft_synced、既有监督器attached_existing。19项新增CPU/API检查和本地构建通过；网页基础指令模式，GPT API未配置。正式网页在独立浏览器登录等待用户，尚未宣称浏览器→正式队列全链路通过。原生物理/颜色适配没有运行。服务器同期新300路线64/300完整来源、training waiting_for_data、actual_completed_updates0，不计为训练成功。初次bridge配置错误exit1保留于v1，修正新run v2，未停止其他服务。[部署](../../runs/web_scene_agent_deploy_20261017/deployment.json) / [服务器回执](../../runs/web_scene_agent_deploy_20261017/bridge_probe_result.json)。

scope=prompt_and_instruction_export。用户选择Isaac32房间Pick/Place。导出system/build/turn模板、JSON schema、4个示例、标准库执行器及尚未接入native的配置/视觉函数；20项初始CPU回归通过，最终报告`runs/web_scene_agent_export_20261017_v1/validation.json`。示例真实落盘draft_saved和blocked计划；未建立HTTP/LLM服务，未执行USD、完整物理或梯度训练。当前数据选择仅10/16的59对历史快照，不覆盖同日DEC-055新增300对/混合训练工作。

## 2026-10-16 用户要求停止现有串行采集，已执行

本条替代此前保持串行健康作业继续的要求。已核PID/start/argv/cwd并停止queue3691948、collector3699346、native3771140及所属runner/encoder，复核remaining=[]。自动恢复BC的queue先停止，未自动拉起训练。已导出10完整Pick/Place来源、20动作片段保留，case_011未闭合现场保留、不计合格。未动无关服务。实际证据runs/isaac_serial_stop_20261016_v1/result.json（服务器同相对路径）；32房间正式并行仍待接通与验证，不称已经运行。

# 实验状态与证据

## 2026-10-16 用户再次纠正：并行是32房间单engine采集

用户“我不是让你并行生成么？”重申DEC-050方案C。核对实际入口：supervise_isaacsim_fast_pickplace.py按case逐个等待真实退出，是串行；已有probe_isaac_parallel_collection.py/supervise_isaac_parallel_probe.py明确scope=parallel_engine_integration_probe、training_eligible=false，只验证共享时钟/渲染/命令批处理，尚未接好各房间独立反馈控制与成功数据出口。不能把调盘研究与数据生成并行、CPU筛选或128路录像probe当正式32房间采集已交付。上一轮用串行生产代替C是执行偏离，已向用户承认。保持健康已有采集，不盲目重跑旧probe或将其改标签。正式并行仍待实施和原生验证；当前不报告已切换。

## 2026-10-16 17:57 SGT 用户质疑视频差异小，实查覆盖

已核64候选配置：同base[.3,0,0]/同房间桌相机，tray x0.82516~0.85960m（跨度3.44cm）、y−0.03448~0.03442m（跨度6.89cm）、yaw−7.915~4.920deg、lift目标12.50~18cm。实际前8源7通过1失败、7对14片段已导出；初始native_trace确有不同XY/yaw，真实lift12.15~17.47cm，Place反馈臂姿确有变化；8个presentation文件SHA不同，viewer引用独立case路径，无重复链接。问题是首批覆盖范围窄、同站位同视角让差异不显著，不是已证明大范围泛化。只读审计保留runs/isaac_reachable_diversity_review_20261016_v1/report.json，未改冻结清单/停止健康采集。后续若扩大应新批次分层覆盖、保留动作内底盘固定和真实成功门，不能用单纯数量冒充覆盖。

2026-10-16 17:41 SGT: first production source actual wait0, full Pick/Place passed and exported. dataset_catalog complete_source_pairs=1, action_segments=2, export_errors={}. 64 candidates total; not64 successful sources. Native batch continues. Viewer http://100.104.0.108:8776/reachable_production_20261016_v2/index.html


## 2026-10-16 17:39 SGT 可达生产实际启动，调盘独立研究

最新用户DEC-052/053：所有动作底盘固定，初态桌前靠近面向桌；调盘松手/稳定/撤离后双臂真实回本轮待机姿态、不动盘/底盘，准备纳入Pick。直接可达泛化先生产，调盘单独研究不阻塞。代码v57/v58服务器27测试通过；runtime初始站位只首次物理步前设置，之后逐tick拒绝底盘命令变化；导出核全准备段原5cm漂移及实际命令恒定。

新初始固定底盘中心case真实wait0、完整Pick/Place通过、独立audit通过：186帧/20Hz、4650真实子步，Pick60帧3秒升17.47cm；Place60帧3秒、松手4.70mm、10帧稳定支撑。全程底盘最大XY漂移0.4529mm。该验证是专家单对，不是VLA测试或总体成功率。服务器runs/isaacsim_reachable_fixedbase_20261016_v1/case_000/independent_audit.json；viewer http://100.104.0.108:8776/reachable_fixedbase_20261016_v1/case_000/viewer.html。

后台生产已实际启动：queue3691948，collector3699346/start35647766，code_v58；runs/isaacsim_reachable_private_candidates_20261016_v2/production_config.json。CPU兼容环境预检93个候选64通过，非64物理来源；最多64对128动作片段，初态XY/yaw/抬升多样，固定base[.3,0,0]，仅父airport_0004_20270920/train，未伪造val/test。dataset/pick_up_the_tray/train及place_the_tray/train只接纳完整成功/对齐闭合源；失败留证，partial_complete不冒充全成功。此单场景可靠出口不是32房间并行完成。旧预检v1因MuJoCo版本不兼容flex，非不可达；留证并在新v2使用env_isaaclab6的3.3重做。

BC先前200步长等待约6分钟后自行恢复223，非确认死锁；已更正此前10分钟说法。用户随后明确结束训练优先生成，核身份后停止本项目guard/coordinator/trainer，实际停止时248步，仅100步已保存，未保存148步放弃；未动无关服务。证据BCv5/production_priority_20261016/{before_stop,stopped}.json。queue在采集结束或真实失败收尾后恢复原BC/原数据/检查点99，不把新train-only数据注入旧训练。当前不是训练中。

调盘研究文档docs/project/ISAAC_ADJUSTMENT_RESEARCH_20261016.md：释放复位不能保证消除21cm漂移造成的几何不可达，需初始站位/支持路径/末态双抓联合预检；新复位支路仅单元测试，未完整原生验证。优先不再新增GPU难例。


## 2026-10-16 17:20 SGT 本轮最终物理证据与实际训练恢复

替代上方此前运行快照：diverse v4实际wait1，转角仅−2.08度后双臂路径失败；v5/code55实际wait1、294帧/20Hz，单臂准备阶段75.0003→15.2238度，桌面方向实际平移21.006cm，最大倾角0.533度、最大抬升1.855mm。左臂目标[0.702348,0.438434,0.866678]私有IK无解而停止；全Pick/Place未通过、新多姿态合格来源仍0。原5cm边界门、抓法、固定段内底盘和摩擦未改。确认预检仅覆盖原中心参考弧，运行允许的实际沿桌长轴漂移未纳入完整预检；并非整个任务不可达。因果推断：沿桌长轴中心反馈抵消旋转的判断得到本次实际旋转改善支持，但还不能声称独立校准。下一修复方向为初始站位、可达中心轨迹和末态双臂路径联合预检，不放宽任务条件。本轮三候选已结束，未再盲目物理重跑。

证据：[独立指标](../../runs/isaacsim_diverse_pickplace_20261016_v5_reference/repair_result_metrics.json)、同目录result.json；服务器runs/isaacsim_diverse_pickplace_20261016_v5/case_000/{native_trace.npz,native_steps.jsonl,native_contacts.jsonl}。五路原速视频ffprobe均294帧/20Hz，编码exit0，失败不会进入训练。已发布 http://100.104.0.108:8776/diverse_repair_20261016_v5/case_000/viewer.html 。

BC v5/code54实际train_10和train_100 wait0、已保存100步/检查点99，20个LoRA数组独立比较全部更新且有限。restore_v3 PID3591964已完成恢复并退出，不能再当等待进程；guard3616725/start35522784、coordinator3617151/start35523786、trainer3617181/start35523795为恢复身份。17:19:26实查已实际更新132步，stage training、gradient_dispatch_132，确从100步与优化器续跑，下一目标1000。该BC仅原冻结三盘3完整来源/27片段，非新多姿态数据、非DAgger、非模型评测成功。数据/配置未改，无关服务未停。


## 2026-10-16 双卡真实训练恢复并保存100步

BC v5/code54已通过真实10步及100步：train_10_attempt_0.exit.json与train_100_attempt_0.exit.json均actual wait0；100步loss0.0458951/grad_norm0.297700/param_norm1803.338，权重params、优化器train_state、assets完整。10步独立CPU读取保存权重和父模型，20个LoRA数组全部变化且有限，最大差2.7502e−6，证据training/checkpoint_000010_adapter_verification.json。不是仅计数或loss；仅原三盘3来源/27片段BC，不是新多姿态数据训练，不是模型任务成功。

按既有资源授权，仅停止guard/coordinator在数量级间续跑，健康train_100子进程正常完成且未发signal。当前100步已保存，checkpoint_resource_yield/restore_v2.py PID3580840启动身份实查存活，状态checkpoint_100_saved_waiting_native；等待diverse v4实际exit后恢复同run/config并从已保存优化器继续。原restore.py因生成源码含NUL语法失败已保留worker.log，v2已compile及实际存活核验，不用旧死PID报运行。无关服务未停。检查点路径：runs/isaacsim_three_tray_workflow_20261015_v1/bc_resume_after_parallel_20261016_v5/training/pi05/checkpoints/pi05_isaac_three_tray/training/99。

调盘v3实际wait1，0.01rad参考下未完成转向。v4/code53已独立启动3558742/start35386609，放大至有限0.12rad参考提前量、保留真实反馈和旧门，仍待完整结果。监控已读ISAAC_DIVERSE_CURRENT指针、保留所有旧候选视频路径，增加已闭合checkpoint数量级，避免下阶段初始化0冒充全部历史进度归零。


## 2026-10-16 首步GPU执行根因与修复

训练诊断v3确认state初始化ready，卡首步execute_sharded；独立双卡4096元素求和默认P2P35秒未返回，禁P2P3.3秒exit0/8386560正确。v4仅禁P2P后报1计数但loss/grad/param norm全0，下一批device_put CUDA WaitFor fatal实际−6；这是无效训练结果、无checkpoint，不改旧文件。旧成功BC源码已有完整Socket/NCCL/XLA兼容环境，新Isaac入口漏传。新v5/code54恢复相同环境，完整state/info同步及参数范数检查后才记更新，双卡/数据/样本/父权重/优化器不改。guard3554127是启动身份，当前prepare尚0有效更新。证据training_transport_diagnostic_v1/results.json、BC v4日志/invalid_update_evidence.json。

调盘v3/code51已保持平面且中心误差小，但0.01rad提前量下实际yaw约75度停滞，不是成功。v4/code53将参考提前逐帧爬升至0.12rad上限，仍按实际yaw反馈、原轮廓和原验收；新queue3554242等待v3实际退出后执行一次，非无限重试。尚无新合格来源。未改任务要求、物理摩擦或失败标签；其他服务未停。


## 2026-10-16 双阻塞修复进行中

用户授权继续实际修复两处阻塞，保持任务。旧BC v2零更新/无checkpoint，存活身份核验后停止仅本项目guard3206683、coordinator3206684、train3221074，diagnostic_restart_receipt.json保留依据；旧输出未清理。新BC v3/code50 guard3507966，training3516779为启动身份，已确认父权重加载及state初始化ready，当前首个gradient_dispatch_0：此前笼统initializing掩盖首步阶段。60秒定时栈用于进一步定位；尚未实际梯度更新，不称训练成功。

新调盘v3/code51原生3519438/start35304523（启动身份），22服务器测试通过/1pxr跳过、规范1.167check通过。真实碰撞网格75→0度151点轮廓可行，参考中心不强制跟base前55cm；按真实tray yaw逐帧推进0.01rad，保留平面pitch及有界纠偏，原5cm门/双臂核心不变。仅启动实际验证，未通过不导出；新多姿态来源0。


## 2026-10-16 16:29 SGT 状态复核

服务器实查：diverse v2仍仅case_000实际wait1，无新候选/通过产物；上次失败后未启动下一轮，不能称仍在生成。新多姿态合格0。倾斜抬升改善只属上例局部结果，完整Pick/Place未通过。原BC3221074/start34557948、guard3206683与协调3206684 argv/cwd核验存活，pipeline心跳更新；14:36起初始化约1小时53分钟仍0更新、无checkpoint收据，日志只有原Orbax警告。此为长时间无可见训练进展，根因待定位，不称健康训练或给无据ETA。本次只读核查，未重启/停止/改条件。


## 2026-10-16 15:35 SGT 修复版实际结果

v2/case_000真实wait1（258帧），diverse_preadjustment_boundary_failed；未完成Pick/Place，不进训练。native_trace独立复算repair_result_metrics.json：夹持后最大倾角0.026°、最大抬升0.116mm，末yaw49.044°（初75°）、实际中心向+x17.63mm/+y9.90mm；旧候选约18°倾斜/6.3cm抬升明显缓解，但站位也变化，不能当单变量因果结论。当前仍是旋转/平移路径导致边界门触发，具体接触滑移原因未证实；没有扩大5cm容差。优先继续修复桌面内旋转和平移联合路径，保持初态覆盖。五路编码exit0，完整物理demo失败。原BC状态initializing/0更新，PID3221074存在，未新检查点核验。

服务器证据：runs/isaacsim_diverse_pickplace_20261016_v2/case_000/{result.json,native_trace.npz,repair_result_metrics.json}及case_000.exit.json。本次只读检查及派生指标写入，未重跑。


## 2026-10-16 单臂准备控制修复验证启动

用户要求“继续修吧”，维持初态覆盖/流程/容差。已确认case_006登记0→−30度夹持腕pitch及XY积分累积约14cm，机械贡献待验证；code49改为保持取得夹持时pitch、平面纠偏泄漏0.9/增益0.35/2cm控制向量限幅（非验收门），不改双臂成功原语。服务器19项测试/规范1.166检查通过。

新run `/home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_diverse_pickplace_20261016_v2`，case_000沿用75度/seed2026101605，独立后台runner3272162、原生3272163/start34678163是启动身份须实时核；日志case_000.log、case_000.launch.json、case_000.exit.json实际wait、case_000/progress.json与result.json。当前仅验证启动，未通过、不导出；旧case_006失败保留。原BC状态文件仍initializing/0更新，本轮未停止或重启。未改变数据分布为仅直接可达，未修改物理/碰撞或标签。


## 2026-10-16 14:49 SGT 只读状态复核

case_006已实际wait1，原生PID3198601不存活；未完成Pick/Place，无新合格来源。独立真实碰撞顶点复算actual_failure_geometry.json：末帧277，yaw50.9608°、roll−17.9259°、中心抬6.3356cm、真实轮廓外伸5.1039cm，终止diverse_preadjustment_boundary_failed。不是单纯1mm精度问题；明显抬升和倾斜已复现，腕姿/接触耦合等机械根因尚未证明。未重跑相同候选、未改容差/标签。建议先在现有任务要求内修复单臂调盘稳定性；如选择只收直接可达姿态，会缩小覆盖，须用户决定。

C32 v3仍已闭合257帧/128相机视频，但自适应批量控制与相机隔离/任务资格未接通，不是量产数据。旧两动作专项仍2对/4段train-only，新多姿态合格0。

原BC新恢复bc_resume_after_parallel_20261016_v2已进入初始化，训练子3221074/start34557948、guard3206683身份核验存活，两GPU该训练各约17.5GiB，实际梯度0，新checkpoint收据0。初始化已约12分钟，日志只有Orbax retention警告，尚无已确认错误或可用ETA，不把GPU占用说成梯度训练。它复用原三盘3完整来源/27片段，绝非本批新多姿态数据。此次只读服务器/重算证据及JSON/TXT同步，未重启健康作业。


## 2026-10-16 14:31 SGT 最新实测（替代下方启动快照）

用户批准的跨episode桌前底盘XY/yaw变化已接入（DEC-051）。case_005实际wait1：直接双臂候选耗尽后，旧fallback错误地又要求双臂可达，未进入允许的单臂准备。code47修为按单臂接近/受支撑调盘路径选准备站位，选定后才导航并冻结；新case_006/native3198601/start34506514（启动身份须再核）已实际选定[0.300005,0.039993,0]，写episode_station.json，未见failure/exit，仍在真实验证，不能称完整取放通过。75度直接候选耗尽不是全局不可达；完整Pick包含准备，Place继续真实状态，无VLA源。

C32 v3/code45已actual wait0：257帧、6425共享子步/12.85仿真秒，128视频全部ffprobe20Hz/257帧通过，integration_audit.json闭合。共享负载elapsed555.39秒，不当独占数据吞吐；未实现批量自适应控制/完整接触资格与相机隔离审计，新合格来源0。旧固定取放数据仍2对/4片段train-only，未扩充冒充新数据。

原BC恢复失败：0更新初始化残留checkpoint目录，三次尝试FileExistsError，旧run/收据/目录完整保留。新`bc_resume_after_parallel_20261016_v2`/code48只改输出及资源等待，原冻结输入/父权重/采样/精度/PEFT/数量级不变。实际守护3206683/start34522895已起，状态waiting_for_native_resource_release、0更新，等待case_006实际wait；尚未训练。CURRENT_NATIVE_BC_RESUME及ISAAC_BC_RESUME_CURRENT指向新恢复，监控不再混读旧PID/状态。新候选不进这轮旧BC。

最终相关测试本机43通过/3平台跳过，服务器45通过/1平台跳过，统一规范1.165 check通过。项目依赖检查412场景/121952资产引用通过，但不是物理验收。证据release code48/source_checks.json与P3/integration_audit.json；本机只同步JSON/TXT，实际媒体轨迹仍服务器。


## 2026-10-16 最新：跨episode桌前站位已获用户批准并实际启动验证

DEC-051取代“底盘变化待答”：新例可在桌前联合选择XY/yaw与双臂相对长边抓姿，进入动作后目标固定，Place继承实际Pick末态。新release `isaacsim_diverse_pickplace_20261016_code_v46`，case `runs/isaacsim_diverse_pickplace_20261016_v1/case_005`（75度初态，seed2026101605）；启动runner3186257/native3186258/start34478586，必须实时重核。episode_station.json保存选定站位/初态/桌；私有路径预检不是物理成功。尚未闭合、不计数据；源/结果/失败文件均保留服务器。

C32 v2在128编码器完成后Kit清理真实wait=-11，旧失败不改；v3使用SDK支持的关闭模式，32房间10帧预检actual wait0，257帧完整测试仍运行。守护3166542/监督3166544/native3170729为启动身份，非当前存活承诺。此scope仅共享引擎命令物理重放集成，不是自适应批量采集，合格新来源仍0；原固定集2对/4片段保持。

原BC资源恢复v3/guard3166543等待所有本轮实际native退出后恢复原冻结BC；未核实梯度前不得说训练。最新watch优先v3状态。规范1.165，本机42通过/2平台跳过、服务器43通过/1平台跳过，服务器规范check通过；证据release_v46/source_checks.json。未停止健康32、其他作业或服务。


## 2026-10-16 13:18 SGT 并行采集方案待选择

用户要求估算单engine、网格实验室、多机器人各自托盘、并行录像的加速方案，允许降低画质，先给方案选择。本轮只读核服务器与源码/官方文档，不安装、不停止健康作业、不改变训练。首固定底盘对实际exit0且分片导出2段，第二对运行中；首例原生启动到退出744.69秒。GPU2×96GB/CPU32核64线程/RAM251GiB/磁盘约550GiB空闲，Isaac6.0.1已装但IsaacLab未装。当前每子步CPU接触回读、逐相机get_rgba、同步ffmpeg pipe均是待分项计时/批量化的成本；100%GPU利用率时功耗仅约103/101W，不能认定算术吞吐已满。

提案A8房间单GPU、B16房间单GPU（建议）、C32房间双GPU渲染/单GPU物理，单engine共享资源、环境碰撞/视觉隔离、GPU批量控制与接触归约、相机合并渲染、异步有界编码；保留500Hz物理、20Hz记录、原抓取/稳定控制。低清头320×256、腕320×180保持原比例/FOV/朝向；不在本轮实际修改相机。所有速度为预算场景，假设完整成功率80%非实测，A/B每批5–15分钟、C每批8–20分钟，则200动作段预计A80–240分钟/B40–120/C32–80；不是跑分或承诺。建议基准/大批采集时暂缓原双卡BC、完成恢复原配置，这项资源变更待用户选择。视频轨迹预算1–3GB/200段，若保存224四相机uint8缓存额外约6.73GiB，共预留10–15GB。详细公式和假设runs/isaac_parallel_collection_plan_20261016_v1/estimate.json。


## 2026-10-16 13:14 SGT 固定底盘采集效率只读实测

守护/监督/原生身份均存活，首例Pick阶段，最近公开progress180帧；13:13:54实际journal175帧，尚0完整对/0导出片段，计划2对。40→175实际进度时间差374.03秒，观测0.36094原生帧/墙钟秒（20Hz仿真约0.018实时率）。按本例约257帧估算仅采集11.9分钟/对，另加媒体闭合/导出，粗估13–16分钟/对、约8–9个动作片段/小时；200段理想外推约22–27小时，不含失败，不能当作已完成吞吐或承诺。两GPU利用率均100%，显存仍有余量；原BC仍initializing/0更新，与采集并行。未分解物理/取图/编码耗时，不能声称已确认单一瓶颈。证据runs/isaacsim_fixed_pickplace_20261016_v1_reference/efficiency_snapshot_20261016T131354.json与monitor_latest.json。此次只读查询/元数据刷新，未重启或停止作业。


## 2026-10-16 最新要求：固定底盘采集Pick与非固定初态Place（DEC-048）

新独立分支runs/isaacsim_fixed_pickplace_20261016_v1/code35。底盘预先到[0.3,0,0]桌前站位，正式片段内命令固定（真实漂移仍按原5cm）；每对先Pick再Place物理续接，分别输出dataset/pick_up_the_tray/train/case_NNN和dataset/place_the_tray/train/case_NNN。双臂姿态/盘XY/yaw/实际抬升高度变化；Place记录当前真实19通道、盘7D、夹持力和帧号，无标准持盘姿态复位。初批14cm/18cm抬升两个候选，固定站位整段预检通过；原+5度/升20cm候选预检右臂路径失败保留，不称任务不可达。

当前是专家连续采集，尚无VLA Pick末态来源；不声称模型执行或DAgger。原BC未停止、未换数据，最后核训练子2963662为双卡initializing/0更新，当前值须重查。新数据仅两动作专项，不是含Flush的完整三盘来源；独立审计后每对冻结batch，父airport_0004_20270920/train继承，不人为划成val/test，当前不启动新的两动作训练。

已实际后台启动守护2981948（启动身份，实时须核birth/argv/cwd），collection_status.json/native_producer实际wait收据/日志/单实例；先核两个完整物理对及分片出口，当前尚0对闭合，不说数据就绪。30项核心测试通过。只读watch_isaac_fixed_pickplace.ps1；本机ISAAC_FIXED_PICKPLACE_STATUS.txt与VIDEO_PATHS.txt，媒体轨迹留服务器。入口http://100.104.0.108:8776/fixed_pickplace_20261016_v1/dataset_viewer.html，仅真实导出后显示视频。


## 2026-10-16 最新实测：平稳原生取放视频闭合，原BC恢复准备中

DEC-046已执行：旧BC0步初始化终止且训练显存释放，旧冻结数据/权重不改，其他服务未停。v8法向对齐+8mm预压+2帧响应纯物理通过后，v9/code33另目录完整重新执行录制并真实exit0。五路各259帧/20Hz、6475真实PhysX子步，独立audit与finalizer exit0；Pick/Place各60帧/3秒（导航/预备另计6.95秒），Pick升17.4806cm、最大倾角1.259°/角速度10.50°每秒；Place最大1.407°/17.05°每秒，在4.674mm松手，末10帧双手释放/桌面支撑，最大末速度1.25e-6m/s。相对夹持变化4.75/5.33mm包含滑移与顺应，不能称材料滑移精确识别。

仅中心姿态单例专家控制通过，不是多位姿鲁棒性、完整三盘或VLA模型成功；没有硬角度验收门变更。画面只读查看起止关键帧，浏览器有人操作未完整连续观察全段；全过程运动用真实trace量化复核，不能称逐帧人工看完。审阅依据及此限制写在stable_video_review.json。银黑机器人/实验室已原生录制，原4相机朝向/尺寸不改；8mm为仿真控制目标，不是实测真机橡胶标定。

视频：http://100.104.0.108:8776/fast_stability_20261016_v9/audited_viewer.html。服务器`runs/isaacsim_fast_stability_20261016_v9_recorded`，case_000原四相机/展示、native_trace.npz及真实接触，原速3秒Pick、3秒Place、6秒对照视频。源错误v3/v4/v5/v6/v7全部保留，不改标签。可点击证据：[独立闭合](../../runs/isaacsim_fast_stability_20261016_v9_recorded_reference/audit_summary.json)、[全过程指标](../../runs/isaacsim_fast_stability_20261016_v9_recorded_reference/case_000/path_stability.json)。

BC新恢复目录W/bc_resume_after_stable_20261016_v1，W=`/home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_three_tray_workflow_20261015_v1`。外守护2947626/监督2947627是启动身份，当前必须实核。视频审阅门已释放，最后真实阶段prepare、实际梯度0；新prepare仅引用原pipeline_v15冻结cache/manifest/父模型，并要求norm和sample_indices与原件SHA相同，快速视频不进训练。之后同原双卡BF16/FP32 PEFT BC/新优化器与10/100/1000/10000/100000检查点，训练子PATH修正既有Conda CUDA12.9 ptxas。单实例重复启动真实拒绝、未额外启动训练，证据single_instance_validation.json；最多3次保存失败attempt，无隐藏评测回退，模型原生评测仍pending。

监控：watch_isaac_fast_pickplace.ps1显示本单例闭合；watch_isaac_three_tray.ps1新增BC resume实际阶段/目录和实际更新数，旧pipeline延期状态是历史协调器，不冒充当前训练。所有视频轨迹留服务器，只同步JSON/TXT。


## 2026-10-16 交接文档的只读取样（非新实验）

12:44 SGT读取服务器配置、环境、进程与端口，记录在[server_inventory.json](../../runs/documentation_handoff_20261016/server_inventory.json)。当时三盘pipeline_v15为deferred_by_user_for_stable_demo/0更新；仅见LAN relay监听8095/8096，未见对应模型后端/键盘控制进程。不是当前实时状态，不据此停止或重启任何作业。启动顺序与未验证项见[交接README](../handoff/README.md)，全部入口见[静态目录](../handoff/SCRIPTS.md)。本轮未跑新物理、训练或真机动作，下面实验结果和后续记录仍以真实产物为准。


### 最新补充：v7失败定位与v8有限候选

v7/code32私有路径预检通过，但真实PhysX合夹结束左手0N、右手5.18N，actual exit1；没有抬升，不算平稳通过。源凸体z=75mm截面实核长壁y=±199.365至209.597mm，厚10.232mm；旧12mm开度目标及实际15.24/15.54mm反馈造成接触不足。不能以零接触增大摩擦代替修复。

v8/code33新目录`runs/isaacsim_fast_stability_20261016_v8_preload_probe`，保留法向对齐、原两长边，目标8mm预压，8帧渐闭后2帧响应，末尾持稳6→4帧，总Pick仍60帧/3秒；无新物理容差/几何/驱动。实际后台runner2934197，native身份以launch/proc核；初态seed800，不重复健康case、不隐藏失败，当前无视频、非训练。27项相关控制测试及规范1.159同步通过。全过程平稳和原生视频尚待验证，原BC仍用户授权延期0更新。


## 2026-10-16 最新资源决定与平稳性真实状态（DEC-046）

用户授权先平稳取放再恢复BC。已核本项目BC0更新后停止初始化与对应监督/守护，GPU中该训练PID已消失；其他服务未停。服务器收据`runs/isaacsim_three_tray_workflow_20261015_v1/pipeline_v15/user_deferred_initialization_20261016.json`，pipeline标deferred_by_user_for_stable_demo，不能继续称训练中。恢复保留原冻结数据/父模型/配置，修复子进程PATH误用系统CUDA12.0而非现成Conda CUDA12.9 ptxas的编译环境问题。

v5已exit0且端点通过，但Pick全过程最大27.50度、角速度99.55度/s，仍不平稳。v6纯物理探针exit1：Pick3秒抬15.14cm、倾角31.57度；Place释放高度超过2cm失败，无视频、非训练。所有旧证据不变。当前新v7/code32仅修正同相对长边夹垫旋转组合Rz Ry Rx→Rz Rx Ry，消除法向沿边分量，保留−30度pitch/±10度roll、几何/驱动/摩擦/时长；取消未奏效4cm偏移。私有13路径节点/原桌前站位预检通过，不算物理通过。

新v7物理探针实际后台runner启动2923797，身份须实时再核；目录`runs/isaacsim_fast_stability_20261016_v7_pad_normal_probe`，日志case_000.log，launch/exit收据及native_steps/result/path_stability。尚无新平稳视频，不能说修好。watch_isaac_fast_pickplace.ps1新增active_probe，旧v5视频与当前无视频探针分开；BC恢复仍等待真实录制验证。


2026-10-16新增[原速快速取放独立scope](ISAAC_FAST_PICKPLACE_20261016.md)：v3首例3秒Pick/3秒Place已独立物理/五路媒体复核通过，其余登记位姿后台运行；实际数量与速度统计见`ISAAC_FAST_PICKPLACE_STATUS.txt`及`runs/isaacsim_fast_pickplace_20261016_v3_reference/monitor_latest.json`。教师控制器，不称VLA通过或鲁棒性提升，不自动训练。原正式三托盘pipeline_v15已有train1/val1/test1完整来源，19:44 UTC实核仍在三动作分片，`waiting_for_data`，不是训练中。

## 2026-10-12 real2sim实测（独立scope）

当前v8：已估计初态、按授权重建四夹指碰撞并完成1Pick+1Place原命令物理回放/8视频核验。Pick盘底升14.95cm；Place末端释放/桌面支撑正常，但0.068s提前触桌（原松手3.267s），完整复现未通过、task_success=null。v7相同问题0.134s触桌。v9仅宽度静态候选，未物理执行。详见[真实证据与限制](REAL2SIM.md)。

`real2sim_pickplace_20261012_v3`：真实Pick/Place各1条连续原命令仿真回放、8预览与完整physics trace已核实际exit0/ffprobe/SHA/误差复算；Pick/Place双臂RMSE2.779°/0.315°，夹爪31.813/15.788mm。新20通道/腰部关节/URDF范围模型独立于旧三桌控制；真实环境配准未完成，task_success=null，不计托盘成功率。IsaacSim/Genesis只有适配器与接口测试，未原生物理验收。[结果与下一步](REAL2SIM.md)。

整理日期：2026-10-09。最后远程核验快照主要为2026-10-08；本页不是实时监控。本轮仅文档治理，没有确认今天服务器作业存活。

## E01 独立拿取：AffordVLA vs π0.5

运行：`/home/michelle/haoze/r1pro-airport-sim/runs/afford_pi05_pickup120_20261008_v2`。

| 项目 | π0.5 | AffordVLA |
|---|---|---|
| 实际训练 | 10000动作BC更新，复用旧v1完成检查点 | 1000区域预热+10000动作BC更新，v2真实退出0 |
| 基模型/适配 | 官方pi05_base /视觉冻结LoRA | Qwen3-VL-4B /视觉区域池化+flow动作头+Qwen文本LoRA，非论文全参复现 |
| 实际拿取评测 | 50/50 | 0/50 |
| 18cm/5°严格终态检查 | 0/50 | 0/50 |
| 行为证据 | 平均8.59秒仿真；实际双握/离桌；1738次总推理 | 每case500帧/25秒/100推理；5000次总推理，没有有效抬升 |
| 教师/逆解回退 | 0 | 0 |
| 评测基础错误 | 新v2没有捕获到基础错误 | 新v2没有捕获到基础错误 |

共同输入固定120训练拿取episode，固定50同父位姿留出。结果只证明该scope下的行为，不证明完整三动作或全场景70%达标；严格终态检查不等于全程严格成功检查。

旧v1 π评测50次首帧`KeyError('gripper_force')`保留，不当模型0%能力结果；v2改读真实`gripper_contact_force[0]`并重测。旧Afford PyTorch cu126不支持sm120导致训练前失败；新非base cu128环境实际CUDA有限梯度检查通过。Afford失败根因仍未确认，需要核对mask预测、训练/推理归一化、动作接入与离线拟合，不能直接归因架构。

- 总结：服务器 `comparison.json` 与 `evaluations/{pi05,affordvla}/summary.json`。
- 每case：`result.json`、`attempt/trace.h5`、`decision_*.npz`、`videos/*.mp4`、`viewer.html`。
- Afford最终：`affordvla/stage2_010000.pt`；π最终：旧v1 `pi05/checkpoints/pi05_pickup120/training/9999`。
- 本机证据：[最终轨迹审计](../../runs/afford_pi05_pickup120_20261008_v2_reference/final_motion_audit.json)、[训练完成快照](../../runs/afford_pi05_pickup120_20261008_v2_reference/training_complete_evaluation_progress.json)、[路径与历史核验](../../AFFORD_PI05_120_TRAINING.txt)。训练完成快照的11/50是中间进度，不能覆盖最后50/50。
- 视频：[π目录](http://100.104.0.108:8767/afford_pi05_pickup120_20261008_v2/evaluations/pi05/)、[Afford目录](http://100.104.0.108:8767/afford_pi05_pickup120_20261008_v2/evaluations/affordvla/)。
- 本机进度：项目根执行 `powershell -ExecutionPolicy Bypass -File .\scripts\watch_vla_comparison.ps1`。SSH `-T`适配restrict密钥；已完成时ETA为空是正常行为，Ctrl+C只停止查看。

## E02 V4三动作双卡BC

运行：`/home/michelle/haoze/r1pro-airport-sim/runs/three_actions_bc_20261008_v1`；输入D01，train100完整源/300片段，val/test各10源/30片段。视觉保留夹爪外观。

实际累计新更新10，checkpoint9保存；随后第10步评测报`actual_zero_frame_initialization_evidence_required`，管道失败并保留检查点。100/1000/10000/100000尚无闭合结果；不能写成仍健康训练或100000完成。该问题与E01独立对比不是一个故障。

证据：[最后实测状态及区别](../../VLA_TRAINING_PROGRESS.txt)、[本机11:27初始缓存快照](../../runs/three_actions_bc_20261008_v1_reference/verified_snapshot.json)。后者只是较早snapshot；第10步结论来自后续会话/服务器状态核验记录，追溯见交互档案2026-10-08。今天继续时应先重新读取服务器状态、子退出与完整初始化日志。

## E03 自由执行诊断

`free_run_diagnostic_20261007_v2`实际600秒/12000帧/2400推理/300000子步录制、四native闭合；托盘落地、没有对向长边双握、底盘XY最大漂移约0.952m。诊断完成但任务失败，不计训练或正式评测。

证据：[FREE_RUN_DIAGNOSTIC_STATUS.txt](../../FREE_RUN_DIAGNOSTIC_STATUS.txt)。

## 下一步事项（未执行）

2026-10-09新增 **E04真机/少量sim迁移** 已实际执行两旧模型real test MSE，混合π0.5 BC v3真实开始并最后核验324/10000步。不是E02自动恢复或Afford混合训练；后测MSE与sim20独立动作case仍待完成。见 [迁移实验](REAL_SIM_TRANSFER.md)、[实时进度与路径](../../REAL_SIM_TRANSFER_STATUS.txt)。下列旧事项不因此自动标完成。

1. 若用户要求继续模型修复，先查E01 Afford离线误差/区域mask/动作及标准化一致性，普通bug自行修复；训练方案取舍先报告用户。
2. E02定位评测初始化实际异常，保留旧零帧证据，新评测目录实跑；通过原评测门后才能续已保存优化器。
3. 后续预调整、其他桌间路线、更多父scene覆盖与DAgger均需独立阶段与新数据版本，不冒称已完成。

## 2026-10-09 AffordVLA 标注方式复核
本轮只读重新连接服务器，实际 v1 `affordvla/mask_status.json` 为 ready/27135 帧、method=simulation_visible_target_tray_silhouette、not_RAGNet=true；v2 `affordvla/training_status.json` 为 trained/120 episodes/11000 updates（1000 mask warmup +10000 action BC），监督字段 sim_target_silhouette_not_RAGNet。源码 scripts/compare_pickup120.py:144 的 masks() 从 MuJoCo tray geom segmentation 生成三视角可见轮廓，不调用 RAGNet，不是专门的长边抓取区域标签。训练为 Qwen LoRA 两阶段项目适配，不能称为已执行指定模块标注或完整原方法复现。当前可用用户交互档案未找到更早指定标注模块的原文；不猜测原文。此前 Afford 0/50 的根因尚未定位，不能单凭标注差异认定原因。本轮未改训练/数据/检查点，未启动训练。

## E05 2026-10-12纯真机π0.5
已实部署real_only_pi05_20261012_v1；prepare实际exit0，训练179/10000有限梯度（00:40 +08:00快照），GPU1。官方base初始化、sim训练0；自动val13/test19离线评测尚未执行，checkpoint首1000待保存。监督PPID1/单实例/3次有限恢复；本地服务器各7项测试通过。详细协议、已核数据诊断及论文依据见[纯真机实验](REAL_ONLY_PI05_20261012.md)，实时状态以pipeline/training_status为准。

2026-10-12 00:56:33 +08:00实核：纯真机π0.5健康训练1447/10000（14.47%），EMA剩余106分钟仅训练；1000步checkpoint training/999及保存receipt已存在。监督4030115/start168239999、训练4030264/start168242009身份与cwd/argv匹配，无重启attempt0；评测尚未开始。证据runs/real_only_pi05_20261012_v1_reference/latest_status.json。

2026-10-12最终闭合（本轮重新连接核验）：纯真机π0.5完成10000/10000；prepare/train/evaluate实际exit0，pipeline于02:45:23 +08:00完成，监督已正常退出。最终training/9999的params/manifest、train_state、assets存在。val13与test19分别保存498/739次预测，32个NPZ实查形状/有限/valid长度及报告调用数一致。test Pick11：关节MSE0.00830720 rad²（RMSE5.22°），夹爪MSE215.2064 mm²（RMSE14.67mm）；Place8：0.00170777 rad²（2.37°）、808.0354 mm²（28.43mm）。与旧混合结果总体接近，不证明纯真机全面更优，旧新noise/初始化不同不可作严格因果消融。val Place关节MSE0.0099785，比保持state0.0080524差，不能隐藏验证问题。val52个固定噪声配对亮度测试：0.7/1.0/1.3倍亮度关节MSE0.0057928/0.0059131/0.0060317；相对原图约-2.0%/+2.0%，未支持亮度是唯一主因；夹爪分别408.23/420.78/450.32mm²。仅离线动作预测，无实机执行、无任务成功率。本地证据runs/real_only_pi05_20261012_v1_reference/latest_status.json及final_closure.json。

2026-10-12用户请求按本机test_last样例生成纯真机与混合π0.5全部对比图。样例为另一frontloader模型8条数据，仅作格式参考。本轮拟同test19/3653帧逐帧H20固定noise重新推理，104组PNG/PDF（两模型各34、叠加36），原预测留服务器；scripts/compare_pi05_real_mixed_plots.py与2项指标/通道单元测试已通过，尚未部署推理。
连接阻塞实核：GPU100.104.0.108:22可达、EC2正常登录；EC2旧r1pro-tunnel session2508启动Oct9，2222连接8秒无SSHbanner且CLOSE-WAIT堆积。核uid/argv后只终止该异常隧道session以尝试现有守护恢复，未操作GPU训练服务；未自动恢复，2222现拒绝连接。旧experiments密钥登录被拒；已向用户请求在GPU现有终端执行systemctl --user restart r1pro-public-ssh.service，仅一次。等待期间制作现有已核离线汇总预览，明确旧noise不同，不伪造逐关节曲线；新的配对评测与完整图尚未完成。

2026-10-12 配对全帧绘图评测启动：服务器反向隧道恢复，新run/release `pi05_real_mixed_comparison_20261012_v1`，监督PID32298/start_ticks211586。GPU0限制显存比例0.40，顺序pure/mixed后matplotlib绘图；19条相同真机test、同seed全帧H20。此处仅启动证据，不代表新评测完成。2项指标/维度测试通过。

## 2026-10-12 全帧配对对比已完成

新运行 `runs/pi05_real_mixed_comparison_20261012_v1`，pure/mixed/plots三个阶段真实exit0。两个既有10000步检查点各对同19条真机test、3653帧进行全帧H20推理；相同帧级噪声种子、真实目标与时间索引，69450个有效预测时距目标/模型。不是闭环执行，不重新训练。104 PNG +104 PDF全部生成并校验，独立复算指标一致。

| 模型 | Pick关节RMSE° | Place关节RMSE° | Pick夹爪RMSE mm | Place夹爪RMSE mm |
|---|---:|---:|---:|---:|
| 纯真机 | 5.349 | 2.431 | 15.213 | 29.209 |
| 混合 | 5.235 | 2.405 | 14.118 | 28.666 |

此处使用全部帧，不能与此前stride5结果混写。当前固定测试分布上混合四项均略低，未作统计显著性检验；初始化也不同，不是仅数据混合比例的因果消融。首次曲线仅显示每帧预测第一步，柱状图统计有效H20全时距，定义明确分开。

[全图目录](../../runs/pi05_real_mixed_comparison_20261012_v1/index.html)、[完整图包](../../runs/pi05_real_mixed_comparison_20261012_v1/pi05_real_vs_mixed_all_plots.zip)、[数值复算](../../runs/pi05_real_mixed_comparison_20261012_v1/numerical_validation.json)、[交付校验](../../runs/pi05_real_mixed_comparison_20261012_v1/delivery_validation.json)。服务器路径同项目根下run；预测NPZ留服务器，仅图和JSON/CSV/TXT等元数据同步本机。图包38,880,898字节，SHA256 d5e81ac45d290f4ca3a0230f42a6f9a792ae18dc0a6d27de1ee318edcc7fa25a。

## 2026-10-12 配对闭环仿真正在运行
新run/release `pi05_real_mixed_closed_loop_20261012_v1`，监督PID124686/start843607、媒体检查131243/start876725；独立后台，单实例锁，GPU0，未停其他服务。共40次独立动作测试：每模型test10场景Pick10/Place10，50秒模型预算，固定配对初态和flow种子，无教师/IK/逆动力学回退，非全任务。实际已完成纯真机3/20（Pick2、Place1均未达到稳定完成），0实现异常；混合尚未开始，不报告最终成功率。
首例四视频ffprobe1000帧/20Hz/224方图，与trace1000控制帧、25000子步一致，真实50秒，失败证据保留；这只是现场预览，不冒称原生分辨率。媒体检查在主评测完成后核全部40trace/160视频并形成delivery_report。私有Tailscale视频服务PID126848，http://100.104.0.108:8771/real_only/case_000/viewer.html 已可访问，最终目录index.html待全部评测完成。
证据：[最新启动/进度快照](../../runs/pi05_real_mixed_closed_loop_20261012_v1_reference/latest_snapshot.json)，根PI05_CLOSED_LOOP_VIDEO_PATHS.txt与TRAJECTORY索引只包含当时已闭合case。完成跟进自动任务0-5-2已创建，每10分钟只读，正常进度静默，全闭合/真实故障才通知；旧0-5和0-5-600仍暂停。视频和轨迹留服务器。

## 2026-10-12 18:13 +08 配对闭环与媒体全部完成
运行 `pi05_real_mixed_closed_loop_20261012_v1` 的pure/mixed实际子exit均0，40次独立动作测试闭合，160路224×224/20Hz视频及40个轨迹已由delivery_report核帧数、SHA、完整真实子步、有限raw chunk和相同配对初态；主监督与媒体核验均已退出，无实现异常，teacher/IK/inverse/在线reset为0。两个已保存10000步checkpoint身份和各自norm已核，原训练/检查点未改。

| 模型 | Pick | Place | 独立动作合计 |
|---|---|---|---|
| 纯真机 | 0/10 | 0/10 | 0/20 |
| 混合 | 0/10 | 0/10 | 0/20 |

纯真机10个Pick均未形成稳定对向长边抬升、10个Place未满足组合终态；混合10个Pick同类，Place9例终态触地、1例未满足组合终态。这些是实际失败现象，不是已证明训练失败根因。固定50秒预算、独立阶段快照初始化，不是完整三动作任务或实机成功率；初始化不同也不是数据比例单变量因果消融。旧混合2/10结果的噪声/版本不同，本次配对结果不覆盖旧标签。

完整视频入口 http://100.104.0.108:8771/index.html 已HTTP200验证；各case/viewer.html同样可访问，视频未下载。本机证据[delivery_report](../../runs/pi05_real_mixed_closed_loop_20261012_v1_reference/delivery_report.json)、[comparison_summary](../../runs/pi05_real_mixed_closed_loop_20261012_v1_reference/comparison_summary.json)，根目录PI05_CLOSED_LOOP_VIDEO_PATHS.txt共160路径、PI05_CLOSED_LOOP_TRAJECTORY_PATHS.txt共40路径。服务器视频及HDF5/raw decision保持在run/{real_only,mixed}/case_XXX/。本次完成跟进0-5-2已暂停，旧任务不变。

## 2026-10-12：19条真机测试104图的解释

完成既有全帧配对结果的只读诊断，无新训练/控制实验。图像第一步预测与汇总H20误差分别解释，补核服务器NPZ前5步误差和右臂通道贡献。跨域闭环失败结合已确认机器人接口差异分析，因果贡献仍待验证。报告：[PI05_PAIRED_FAILURE_ANALYSIS_20261012.md](PI05_PAIRED_FAILURE_ANALYSIS_20261012.md)。

2026-10-12 本线程新增原命令回放 `real2sim_execution_alignment_20261012_v1`：夹指URDF执行语义修正后两例exit0及8视频校验，Pick出现19.55cm抬升，Place0.102s提前触桌仍失败；非VLA、无训练、无新成功数据。[详情](REAL2SIM.md)。

2026-10-12 real2sim_held_contact_20261012_v2：接触方向及全凸体穿透诊断后两例完整回放与8视频校验，Pick抬升19.55cm，Place仍起始失夹落盘；未训练，未修复成功。详见REAL2SIM.md最新段及同名_reference报告。

2026-10-13 E08 真机双模型部署：mixed与real-only最终10000权重服务8093/8094后台实际ready、PID/birth/argv/cwd核验，默认operator停止锁定。机器人原脚本/config SHA未变，新配置与Pick指令已写；键盘STOP/心跳失效两端点经真实robot网络拒绝，0控制发布。5核心测试、规范write/check通过。当前live camera/feedback话题缺失，blocked_live_sensors，不是任务成功。详[真机部署](REAL_ROBOT_DEPLOYMENT_20261013.md)；[实核快照](../../runs/galaxea_robot_deploy_20261013_v1_reference/deployment_verified_v2.json)。

2026-10-15 E09 新增real_sim50_pi05_20261015_v1：首次46/10000有限更新、GPU0独立后台。50/50每batch4+4，不覆盖既有模型；10k每1k保存后真机test19离线MSE。细节及scope见[50/50实验](PI05_MIX50_20261015.md)，实时步数读取真实status。

2026-10-15 本轮实核完成：real_sim50_pi05_20261015_v1 已训练10000/10000步，prepare/train/evaluate实际子进程退出码均0，pipeline complete。最终loss0.0034330213。现存checkpoint仅pi05/checkpoints/pi05_real_sim50/training/9999（旧周期检查点已按保留策略清理）。真机test19离线H20 MSE：Pick11条 arm0.0086941904 rad²/gripper199.7232532 mm²；Place8条 arm0.0018802719 rad²/gripper755.9309904 mm²。未做此模型仿真闭环或真机执行，不能称任务成功。证据：runs/real_sim50_pi05_20261015_v1_reference/latest_status_snapshot.json；服务器同名run mse_mixed_pi05.json。

2026-10-15 E10 Isaac Sim迁移v8：6.0.1原生100×2ms步进、四任务相机补建、18DOF初始化有限，实际exit0。底盘D6/驱动、软体/碰撞和VLA闭环未验收；非任务成功，不进训练。详[迁移记录](ISAACSIM_MIGRATION_20261015.md)。

E10补充v9：四任务相机原分辨率PNG实际出图，新增诊断DomeLight，不进训练；HTTP8775已实测200，native exit0。模型/完整任务未运行。


2026-10-15：Isaac完整迁移：原生控制/软体预检通过；第一轮参考执行1381帧四路闭合、实际exit0，但Pick未抬盘，任务失败。第二个源摩擦修正资产候选独立验证中。原生合格来源0、新训练waiting_for_data、无纯模型PhysX测试。 详[Isaac专题](ISAACSIM_MIGRATION_20261015.md)。


2026-10-15：E11三托盘Isaac资产v2：原生导入/材料/控制实际exit0，双臂、夹爪、X/Y/yaw与三件63节点GPU外套通过预检。v1缺transY失败保留；不是完整demo/数据就绪/训练启动/模型成功。新三盘新版带载控制器和全任务观察器尚未完成。 见[三托盘迁移](ISAACSIM_THREE_TRAY_20261015.md)。

2026-10-15 E12：三盘新版原生执行与验收已接入；demo03实际首盘空Pick/Place通过，Flush右下降IK失败；demo04实际右推/左接管/右松/左移3.154cm/左松与桌面支撑，但角点越界6.171cm超过5cm门，actual exit1，0完整合格来源。demo05在现有位置容差内预留4.2cm推动空间，新目录实测中；后台pipeline_v4与外层guardian已启动，waiting_for_data。17项核心测试及隔离进程异常/防重复/一次恢复测试通过。未开始新BC，未完成原生纯VLA测试。[三盘专题](ISAACSIM_THREE_TRAY_20261015.md)。

2026-10-15 最新demo08/code_v16：修复后续Pick直接收臂碰落已完成盘，先抬手/桌前后退；两处真实失败状态私有IK通过、18测试通过，完整物理待实测。pipeline_v8已部署真实后台，当前demo/waiting_for_data，不是训练。demo07完整失败记录保留；详见ISAACSIM_THREE_TRAY_20261015.md。


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



### 2026-10-16 C32网格采集与初态多样性实施中

DEC-050/规范1.163。新模块`real2sim/isaac_parallel_collection.py`：独立房间坐标、批量18关节映射、父split检查、全180度对称区间的桌内采样（只是几何条件，不是可达性）、有界无丢帧编码。`scripts/probe_isaac_parallel_collection.py`及`supervise_isaac_parallel_probe.py`先做单engine实际PhysX与四相机逐级集成，probe明确不进训练；非批量自适应控制器或完整任务验收。服务器新run `runs/isaacsim_parallel_collection_20261016_v1`，初次4房间10帧/250真实全局子步/16视频actual wait0；完整4→8→16→32仍待实际产物。大初态单臂预调整与不同真实持盘Place资格尚待接通，不能称已支持或已批量生成。原固定底盘串行两对4片段已正常闭合；BC0更新初始化按用户C资源安排暂缓，无更新丢失，原数据权重保留。


2026-10-16最新补充（覆盖前述待完成快照）：规范1.164。32v1句柄耗尽失败保留；新v2/code44仅本进程65536软额、显式双GPU相机分配/房间材质引用、复用4/8/16真实审计后重跑32。单臂准备code43真实碰撞足迹纠正矩形代理误判；case_004仍抬升/倾18度并实际外伸5.11cm，失败未进训练，姿态泛化尚未通过。可变长度Pick分片已接end−start，含预调整；Place保留实际连续末态。代码/数据/原生与模型成功分开，C32自适应批量控制仍待接通；旧2对4片段和旧BC保留。新scope与阻塞见memory/CURRENT.md及server实际报告。

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

## 2026-10-19 HTTP UUID fix and website downloads

User requested website downloads and reported Create VLA evaluation crypto.randomUUID error. Both client submit paths now use UUID v4 with getRandomValues fallback for HTTP. Native/fallback/1000 uniqueness/error tests passed. Offline release scene_studio_offline_20261019_v3 deployed after supervisor identity verification; Sites v9 deployed. Browser submitted room 0 / 20 frames latest pi05 job 98f3e9bd-0a27-40be-92ee-f1063c280663 successfully; waiting_gpu, not completed evaluation. Help and Data & training include MP4, ZIP, launch guide. Workstation HTTP files matched SHA; hosted ZIP downloaded through browser and matched SHA (direct Python hosted fetch returned 403). Evidence: [verification](../../runs/web_uuid_downloads_20261019/verification.json), [deployment](../../runs/web_uuid_downloads_20261019/switch_receipt.json). No model policy change; G0.5 missing-gripper approval still pending.

## 2026-10-19 Single-policy live evaluation

PolicyEvaluation.tsx, api/live, gpu/live_publication.py and studio_live_view.py connect native body poses/cameras to per-run website monitoring and video artifacts. Guide: [Policy evaluation](../site/POLICY_EVALUATION.md). Evidence: [measured runs](../../runs/web_live_policy_20261019_v1/verification.json). Room001 pi05 executed 15 frames then mechanical-limit failure (0/1); room000 zero frames; G0.5 adapter HTTP500. No policy success claimed. CPU duration-budget tests passed. Workstation release scene_studio_live_policy_20261019_v5 active at deployment receipt time.

## 2026-10-19 17:52 SGT Workstation connection restored

User reported 100.104.0.108:9080 refused connection. SSH remained reachable. Previous v5 bridge received HTTP413 three times; supervisor recorded child_exited:bridge and stopped web (actual exit evidence retained in runs/web_connection_recovery_20261019/before.json). Deployed new immutable release scene_studio_live_policy_20261019_v6: authenticated worker JSON limit 4MiB (other routes stay250000 characters); bridge failure no longer closes healthy web. No unrelated/model services stopped. Verification actual payload194894 bytes HTTP200, 300KB payload200, >4MiB413, invalid token403; fresh bridge heartbeat no error, bootstrap live=true/32 rooms; browser Policy evaluation displays GPU connected. Evidence runs/web_connection_recovery_20261019/verification.json and restored.png. This supersedes v5 website process status only, not model success results. Source package from prior turn remains v5; deployed recovery is v6.

## 2026-10-19 18:05 SGT Policy stop diagnosis and explicit clipping diagnostic

User reported runs 997b6e1d and 0dcd95a4 stopping at5 frames. Actual reports show right_arm_joint4 model target -1.764047265 rad below source XML lower -1.7453 rad; not wall timeout. Source units radians, right channel11 maps joint4 directly. No mapping bug established. Native timing baseline5frames: physics/contact1.28s, first inference~4s,next~0.44s. Evidence runs/web_policy_stop_20261019/before.json,detail.json,limits.json.

After offered strict vs explicit clipping diagnostic, user answered “最快的解决修复方法”; implemented opt-in clip_diagnostic, strict remains default. Raw and applied chunks plus each correction retained; no gripper completion/IK/teacher, existing model mechanical bounds unchanged; diagnostic successRate=null and pureModelSuccessEligible=false. Source spec1.180 and sync checks current. Four CPU tests including nonfinite rejection and float32 boundary roundoff passed. Offline release scene_studio_live_policy_20261019_v8 deployed; hosted Site not updated this turn.

UI displays Running/Initializing/Ended and stop reason above3D, terminal model reply labelled historical, no growing pose age for finished runs. Local publisher0.1s/browser0.25s, duplicate pre-physics policy render removed without changing25substeps/frame or contacts/cameras. Native run4201ad6f-da32-43ed-8684-7296a1cb9525 same room0/real90sim10 checkpoint executed40frames/2s and stopped at configured budget. Not task success. Total native rollout19.262s incl planning7.190s,physics step9.049s,contacts0.744s,postrender0.941s; overall45.544s incl init/media. Smooth20Hz wall-time remains unachieved: underlying physics step and synchronous inference are bottlenecks; no claim performance fixed. Four videos/report produced; actual UI verified ended/time limit/diagnostic label. Evidence verification.json,profile.txt,ended_diagnostic.png under runs/web_policy_stop_20261019.

## 2026-10-19 Workstation runtime optimization and protected model output

Scope DEC-WEB-013. User explicitly requested actual physics/synchronous-inference speed improvements, reuse of prior real-robot joint restrictions on checkpoint inference, same-room/checkpoint before/after measurements and website videos/results. Implemented one in-flight asynchronous request with frame-aligned prediction-prefix skipping; single-room CPU PhysX with GPU inference/render and Fabric. Original 0.002 s x25 substeps/frame, contacts, cameras and task gates retained. Warmup is outside rollout and does not execute actions. Reused real-robot configured caps (source SHA in gpu/robot_action_limits.json): step0.1rad, velocity1.5rad/s =>0.075rad/20Hz frame, tracking0.25rad, feedback-age0.5s, gripper0..80mm. Mechanical bounds at model endpoint; rate/tracking guard per executed command. Original outputs/logs retained, weights unchanged; protected diagnostic not pure-model success or training.

Actual paired benchmark Room000 / cp_d0c1ec449340c22c344ee87c /40frames/2simseconds: baseline3056577e-54e0-45fd-9b49-9c0533cccdf6 15.870699s rollout, physics9.136041s, wait3.648970s; optimized02237d37-2fe8-42fb-81f5-574e42b6d924 4.744614s rollout, physics1.940640s, wait0.522161s. Speedup3.34499x; realtime factor0.12602 to0.42153, still below real time. Both completed1000substeps, duration stop, successRate=null, no Pick/Place success claim. Protected command audit maxstep0.075rad, tracking0.06615/0.12846rad, measured movement0.71673/0.54230rad. Native media exit0. One short pair, CPU/GPU trajectories differ; no long-run stability or generalization claim.

Evidence: runs/web_realtime_optimization_20261019/comparison.json, audit.json, check_v10.json. Server videos at runs/web_runtime_comparison_20261019_v1/{baseline,realtime}; website artifacts referenced by JSON. Wall-time videos retain inference waits; normal native videos use20Hz simulated timeline. Offline releasev11 adds comparison/video panel and Help; physics measured on identical backendv10. Cloud workerbridgev7 uses same backendv10 after oldv5 dispatcher unexpectedly grabbed first baseline with obsoletev4 code; failed85467e04 run preserved and excluded. Hosted Site frontend not republished this turn. Six CPU contract tests and offline build passed; spec1.181 sync current. Remaining: 1x real-time unachieved; GPU dynamics slower for this single-room case; G0.5 missing gripper and GR00T weights remain separate unresolved scopes.
