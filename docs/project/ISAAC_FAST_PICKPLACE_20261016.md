# 原生 Isaac 快速取放与多位姿视频

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



### 最新补充：v7失败定位与v8有限候选

v7/code32私有路径预检通过，但真实PhysX合夹结束左手0N、右手5.18N，actual exit1；没有抬升，不算平稳通过。源凸体z=75mm截面实核长壁y=±199.365至209.597mm，厚10.232mm；旧12mm开度目标及实际15.24/15.54mm反馈造成接触不足。不能以零接触增大摩擦代替修复。

v8/code33新目录`runs/isaacsim_fast_stability_20261016_v8_preload_probe`，保留法向对齐、原两长边，目标8mm预压，8帧渐闭后2帧响应，末尾持稳6→4帧，总Pick仍60帧/3秒；无新物理容差/几何/驱动。实际后台runner2934197，native身份以launch/proc核；初态seed800，不重复健康case、不隐藏失败，当前无视频、非训练。27项相关控制测试及规范1.159同步通过。全过程平稳和原生视频尚待验证，原BC仍用户授权延期0更新。


## 2026-10-16 最新资源决定与平稳性真实状态（DEC-046）

用户授权先平稳取放再恢复BC。已核本项目BC0更新后停止初始化与对应监督/守护，GPU中该训练PID已消失；其他服务未停。服务器收据`runs/isaacsim_three_tray_workflow_20261015_v1/pipeline_v15/user_deferred_initialization_20261016.json`，pipeline标deferred_by_user_for_stable_demo，不能继续称训练中。恢复保留原冻结数据/父模型/配置，修复子进程PATH误用系统CUDA12.0而非现成Conda CUDA12.9 ptxas的编译环境问题。

v5已exit0且端点通过，但Pick全过程最大27.50度、角速度99.55度/s，仍不平稳。v6纯物理探针exit1：Pick3秒抬15.14cm、倾角31.57度；Place释放高度超过2cm失败，无视频、非训练。所有旧证据不变。当前新v7/code32仅修正同相对长边夹垫旋转组合Rz Ry Rx→Rz Rx Ry，消除法向沿边分量，保留−30度pitch/±10度roll、几何/驱动/摩擦/时长；取消未奏效4cm偏移。私有13路径节点/原桌前站位预检通过，不算物理通过。

新v7物理探针实际后台runner启动2923797，身份须实时再核；目录`runs/isaacsim_fast_stability_20261016_v7_pad_normal_probe`，日志case_000.log，launch/exit收据及native_steps/result/path_stability。尚无新平稳视频，不能说修好。watch_isaac_fast_pickplace.ps1新增active_probe，旧v5视频与当前无视频探针分开；BC恢复仍等待真实录制验证。


## 最新用户纠正：全过程平稳优先（DEC-045）

旧v3首例虽然端点通过，但完整过程最大倾角37.5°、pitch范围56.2°、角速度172.5°/s，不能交付为平稳演示。已在旧页面添加历史警告，原结果标签不改。旧派发/守护/只读汇编已核身份停止，最后已启动原生case未被signal，实际6例闭合：4例端点通过、−10°Place IK失败、+20°站位预检失败，完整证据保留。`path_stability_review_summary.json`重算全过程指标。

四夹指原生静/动摩擦已经1.2，源condim4还含0.005m抗扭，原PhysX碰撞体抗扭半径默认0，迁移丢了软夹指接触的一部分。v4先修20Hz目标突跳：真实500Hz子步插值、8帧80→12mm闭合预压/8帧释放、共同关节进度限速、去掉固定18°前馈；单例两段各3秒且端点通过，峰值接触力从约1268N降约55N，但Pick倾角仍27.27°、相对夹持变化4.2cm，尚未解决平稳性。FK实测手腕变化不足0.4°，托盘在接触中转动，不把它归因于已确认的网络延迟。

新候选`runs/isaacsim_fast_stability_20261016_v5` / `releases/isaacsim_fast_stability_20261016_code_v29`：由原夹指碰撞盒中心计算TCP偏移，保持两长边抓法；恢复有限抗扭接触，名义有效半径0.005/1.2=4.167mm。仅四碰撞体接触属性变更，原几何/质量/滑动摩擦不变，未实测硬件材料，无附着/外力。记录`rubber_pad_contact_translation.json`及`rubber_contact_override.usda`，源USD身份与接触override分报，不能说源物理完全未变。新灯光Dome600/四面光2500一并独立验证，旧视频不重新标记。

当前v5为一个中心姿态候选；实际状态/进程身份/视频索引由`watch_isaac_fast_pickplace.ps1`读取服务器`runs/ISAAC_FAST_PICKPLACE_CURRENT.json`。入口：<http://100.104.0.108:8776/fast_stability_20261016_v5/index.html>。只在真实退出、视频闭合、全过程指标和画面审阅后报告结果；暂未通过时不说已修好。完整三盘旧BC独立继续，不用快速短片冒充其训练源。新接触/时序实现26项核心测试通过，规范1.155同步。

原理依据：[MuJoCo软夹指抗扭接触](https://mujoco.readthedocs.io/en/3.2.0/computation/index.html)、[PhysX有限抗扭接触半径](https://nvidia-omniverse.github.io/PhysX/physx/5.2.1/_build/physx/latest/class_px_shape.html)。这支持恢复缺失的接触机制，不证明当前材料系数等于真机橡胶。

以下为此前版本记录，最新scope以上述纠正为准。

范围为 DEC-044：机器人银黑配色、复用 MuJoCo/Blender 实验室资产，真实物理 Pick / Place 各约3秒，多位姿视频及真机域差异诊断。它独立于三盘完整任务和正式BC，不覆盖原有数据、检查点或失败。

## 时间与执行口径

每个计时动作60帧、20Hz、每帧25个2ms PhysX真实子步，原速播放。Pick从盘沿上方12cm的预备臂姿开始，包含下降、合夹、抬升及短稳；Place包含下降、释放、退出、稳定支撑。完整视频记录并单独报告站位搜索、导航与预备臂姿时间，不能称从任意姿态出发全部仅3秒。

双臂各夹一条相对长边，桌前联合搜索站位和托盘yaw，不走桌侧。空盘取放；本次短片不包含带载Flush，不是完整三盘任务。初态覆盖9个登记XY/yaw，yaw为0、±10、±20、±28度；只在第一次物理步前设置初态，执行中不改盘位、不绑定、不补外力。

## 版本与真实证据

服务器项目根 B=`/home/michelle/haoze/r1pro-airport-sim`。

| 版本 | 真实结论 | 证据与处置 |
|---|---|---|
| `runs/isaacsim_fast_pickplace_20261016_v1` | 首例Pick3秒抬17.3cm；Place角点先触桌，实际中心松手gap6.3cm，未满足2cm | 保留原result及`case_000/independent_review.json`，不改旧标签；停止派发，已启动原生case正常闭合 |
| `runs/isaacsim_fast_pickplace_20261016_v2` | 首例Pick3秒抬18.0cm，Place3秒松手4.9mm、双手释放且稳定，独立物理复核通过；目标速度存在尖峰 | Place目标99.9分位16.1rad/s，实测99分位3.22rad/s，不混入训练；旧视频保留 |
| `runs/isaacsim_fast_pickplace_20261016_v3` | 连续SE3参考＋已有真机client目标变化率1.5rad/s；首例独立复核通过，各3秒抬17.5cm，实际释放gap约−0.08mm | 其余位姿后台执行，最终总量以`audit_summary.json`为准，不把当前单例扩大为9例 |

V3启动身份：外守护PID1740285/start_ticks30613624，producer1740287/start_ticks30613626，独立只读复核/汇编器1756256；这是启动记录，当前存活须由 `/proc` 的birth、argv、cwd重核，不能把此表当实时状态。健康原生case不重启。最多3个连续物理失败停止，不自动放宽要求；独立复核普通读写/探测故障最多重试3次，保留各次错误。

控制为教师/专家采集，不是π0.5执行。`model_executed=false`、`training_eligible=false`。多位姿专家通过只说明该控制器在这些初态可行，不证明训练后的模型泛化提高。

## 视觉与真机差异

复制本项目已有Blender实验室45个背景物体、银黑机器人材质、地板纹理，原位置/比例保留。银色PBR roughness0.22/metallic0.78，黑色roughness0.55；原生RTX灯光与新增1920×1080外部展示相机。原4相机保持原朝向与分辨率，碰撞、质量、惯量、关节和原相机前后指纹相同。保留夹爪本体，只沿用既有指定腕部纯视觉壳处理。`visual_translation.json`记录逐项映射；`render_diagnostics.json`为像素统计，不代替人工视觉审阅，不宣称画质主观验收已完成。

只用真机train的102条（Pick60、Place42）统计，无val/test调参。`real_train_motion_reference.json`给出实测关节速度Pick99分位0.772rad/s、Place0.600rad/s，99.9分位1.691/1.292；真机完整录制包含等待，不能直接与3秒主动动作比总时长。V3首例实测99分位仍为1.480/1.386，说明快速目标仍带速度域差异。1.5rad/s仅限制目标变化率，不保证实际反馈上限，更不构成真机安全认证。夹爪总开口0–80mm，仿真命令单位m。

真机train三相机缓存224像素亮度分布留在`real_train_image_reference.json`。不强行改输入相机朝向或全局亮度去贴统计；新增外部相机不进训练输入。本轮没有重新训练、没有修改正式三盘训练数据。

## 入口、产物与查看

- 当前可播放入口：<http://100.104.0.108:8776/fast_pickplace_20261016_v3/index.html>。
- 全部结束后的独立审阅页：`audited_viewer.html`；仅实际存在后才交付。汇编包括`multi_pose_pickup.mp4`、`multi_pose_place.mp4`、`multi_pose_audited_pair.mp4`，按各3秒原速直接拼接，无加速。
- 每例`case_NNN/{presentation,head_left,head_right,left_wrist,right_wrist}.mp4`，`native_trace.npz`、`native_steps.jsonl`、`native_mapping.json`、`result.json`、`independent_audit_v2.json`；原始IK目标与真正提交目标限速事件在原生事件记录内。
- `case_NNN/clips`：两动作×5相机文件及6秒展示对，时间窗与完整轨迹一致；10个视频文件不是10条来源。
- 实际退出收据`case_NNN.exit.json`，守护/监督日志`guardian.log`、`producer_attempt_0.log`，独立复核`finalizer.log`、`finalizer_exit.json`、`audit_summary.json`。
- 本机只读监控：`powershell -ExecutionPolicy Bypass -File .\scripts\watch_isaac_fast_pickplace.ps1 -Watch`。JSON快照位于`runs/isaacsim_fast_pickplace_20261016_v3_reference`，TXT为`ISAAC_FAST_PICKPLACE_STATUS.txt`和`ISAAC_FAST_PICKPLACE_VIDEO_PATHS.txt`。每个实际视频位置占一行，媒体和轨迹留服务器。

## 代码与检查

`isaac_lab_visuals.py`负责视觉等价检查，`isaac_fast_pickplace.py`复用旧教师取放并实现连续参考和目标变化率限制；`run_isaacsim_fast_pickplace.py`真实SDK采集，`supervise_isaacsim_fast_pickplace.py`按登记位姿有限派发/五路媒体闭合和分片，`finalize_isaac_fast_pickplace.py`只读独立复核、带首帧过渡速度核验及原速汇编。运行代码冻结于`releases/isaacsim_fast_pickplace_20261016_code_v27`，后续仅独立复核器在项目scripts入口，不修改健康物理执行版本。

24项核心测试通过，包含14臂关节变化率限制、不改夹爪/底盘、不改原始IK目标及OBJ索引。规范1.152已人工审阅并同步；追加复核器后须再次`sync_task_spec --write`及`--check`。独立复核从真实状态、控制、接触、支撑、退出、视频ffprobe和SHA重算，不以result字段单独替代证据。

## 2026-10-16 13:18 SGT 并行采集方案待选择

用户要求估算单engine、网格实验室、多机器人各自托盘、并行录像的加速方案，允许降低画质，先给方案选择。本轮只读核服务器与源码/官方文档，不安装、不停止健康作业、不改变训练。首固定底盘对实际exit0且分片导出2段，第二对运行中；首例原生启动到退出744.69秒。GPU2×96GB/CPU32核64线程/RAM251GiB/磁盘约550GiB空闲，Isaac6.0.1已装但IsaacLab未装。当前每子步CPU接触回读、逐相机get_rgba、同步ffmpeg pipe均是待分项计时/批量化的成本；100%GPU利用率时功耗仅约103/101W，不能认定算术吞吐已满。

提案A8房间单GPU、B16房间单GPU（建议）、C32房间双GPU渲染/单GPU物理，单engine共享资源、环境碰撞/视觉隔离、GPU批量控制与接触归约、相机合并渲染、异步有界编码；保留500Hz物理、20Hz记录、原抓取/稳定控制。低清头320×256、腕320×180保持原比例/FOV/朝向；不在本轮实际修改相机。所有速度为预算场景，假设完整成功率80%非实测，A/B每批5–15分钟、C每批8–20分钟，则200动作段预计A80–240分钟/B40–120/C32–80；不是跑分或承诺。建议基准/大批采集时暂缓原双卡BC、完成恢复原配置，这项资源变更待用户选择。视频轨迹预算1–3GB/200段，若保存224四相机uint8缓存额外约6.73GiB，共预留10–15GB。详细公式和假设runs/isaac_parallel_collection_plan_20261016_v1/estimate.json。
