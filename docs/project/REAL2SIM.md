# 真机 Pick / Place 的独立 real2sim

2026-10-12：用户授权先复现真机示范，并选择建立独立真机一致模型。此工作独立于 VLA 训练及模型闭环比较；不发出真机命令、不自动生成训练来源、不改变旧成功标签。


## 2026-10-12 估计配准与夹指碰撞验证（当前）

用户“这些你估计”取代实测标定限定（DEC-030），随后授权只在独立real2sim模型重建四夹指碰撞（DEC-031）。所有参数仍为estimated_not_measured，scene_registration_verified=false。当前最后完整物理run是`real2sim_pickplace_20261012_v8`，1 Pick＋1 Place已exit0；**完整Pick/Place复现尚未验收通过，不能进入成功数据或训练**。

原三桌布局和1.2×0.6×0.8m尺寸保留；托盘0.56×0.43×0.105m来自场景几何先验，不称实测。逐录制估计：

| 原录制 | 底盘world xyz (m)，yaw=0 | 初始托盘world xyz (m) | 说明 |
|---|---|---|---|
| Pick episode5 | (0.3500,-0.0081,0) | (0.8500,0,0.8010) | 置于front_left桌，长轴沿机器人前向 |
| Place episode3 | (0.2620,0.0260,0) | (0.7892,0.0143,0.8989) | 估计持盘姿态；实际初始持盘稳定性未通过 |

完整wxyz姿态、来源SHA、先验和拟合残差见[Pick配准](../../runs/real2sim_pickplace_20261012_v8_reference/case_000/registration.json)、[Place配准](../../runs/real2sim_pickplace_20261012_v8_reference/case_001/registration.json)。两个录制不是同一连续episode，不强拼成Pick→Place。

| v8实际证据 | Pick | Place |
|---|---|---|
| 源帧 / 物理子步 | 439 / 7301 | 195 / 3234 |
| 盘底初始→终态z | 0.801→0.9505m | 0.8989→0.8000m |
| 最后1秒31个样本 | 双手接触31/31，桌面接触0/31 | 双手接触0/31，桌面支撑31/31 |
| 过程结论 | 出现约14.95cm抬升，未据此声明全部抓法/稳定性验收通过 | 0.068s已触桌，原松手命令3.267s；提前掉盘，不能算正确Place |
| 双臂RMSE / 夹爪开口RMSE | 2.856° / 45.706mm | 0.336° / 41.011mm |

证据：[phase诊断](../../runs/real2sim_pickplace_20261012_v8_reference/phase_diagnosis.json)、[独立源码时间/命令/状态/视频校验](../../runs/real2sim_pickplace_20261012_v8_reference/delivery_validation_source_aligned.json)、[运行摘要](../../runs/real2sim_pickplace_20261012_v8_reference/summary.json)。旧v3是无配准诊断；v4误将世界位姿当成底盘关节偏移，v5修复场景body出生变换；v6有效腰部驱动拟合改善了抬升但Place会再次带起；v7重建夹指后末端释放恢复，但0.134s已触桌；v8只改初始拟合姿态仍提前掉盘。各目录和失败证据均保留，不改旧标签。

### 新模块和复现入口

`registration.py`只处理来源绑定、SI/wxyz位姿和解析估计；`mujoco_registration.py`处理原始反馈FK和初始home key转换，不改变运行中状态。`collision.py`仅接入来源URDF绑定的四指凸体资源，数据/回放/控制不依赖具体碰撞实现。`fit_real2sim_registration.py`只离线拟合托盘初始位姿，不改变机器人关节或真机命令；达到优化迭代上限的v3静态拟合明确converged=false，几何距离小不等于持盘稳定。

原指盒体替换为源URDF四指网格的332个凸体（80/86/80/86）；视觉、机器人惯量、相机与夹爪本体碰撞经前后模型比较不变。[资源清单](../../resources/real2sim_finger_convex_20261012_v1/manifest.json)含每凸片SHA和URDF身份，可由Isaac/Genesis场景导入器复用。采用[CoACD官方接口](https://github.com/SarahWeiii/CoACD)1.0.9、seed0、1mm几何近似参数；它是网格近似精度，不是任务容差，不能称精确CAD接触。仅在服务器非base `r1pro-vla`安装该新增包，无依赖升级。

```bash
python scripts/replay_real2sim.py \
  --source-manifest /project/runs/real_only_pi05_20261012_v1/cache/test/manifest.json \
  --scene-xml /project/path/to/original/mobile.xml \
  --urdf /project/resources/real2sim_20261012_v1/r1_pro_source.urdf \
  --registration /project/resources/real2sim_registration_20261012_v3 \
  --finger-collision-bundle /project/resources/real2sim_finger_convex_20261012_v1 \
  --torso-kp 10000 --torso-kv 400 \
  --output /project/runs/NEW_UNIQUE_RUN --video
python scripts/validate_real2sim.py --run /project/runs/NEW_UNIQUE_RUN
```

源网格模型使用预先保存的配准JSON；`--registration estimate`的解析FK适用于原盒体参考模型，不在更换碰撞后隐式重估指尖参考点。迁移时用同一JSON设置初始底盘与托盘world pose，按quaternion_order=wxyz处理，再调用原backend初始化一次；不把MuJoCo的agent_base关节偏移当成世界位置。两个目标引擎仍只有接口测试，尚未做原生物理验证。

`fit_real2sim_torso.py`预登记三组有效仿真servo参数，仅在首次闭爪前110帧空载片段比较，选10000/400；腰部RMSE从3.226°降至0.0529°。不改变力限，不是硬件辨识或训练。模型首帧速度零，缺少真实初始接触预载与物体速度；这是仍需校核的初态信息，不能通过在线绑定托盘掩盖。

另有一个宽度0.4601m（scale1.07）的**静态诊断候选**，基于夹指间距估计；视觉/碰撞一起缩放、保持源质量并按仿射变换重算托盘惯量，机器人惯量不变。它仍有约8.93mm单指间隙，未投入完整物理回放，不是当前采用的尺寸，也未修改旧托盘资产；[候选记录](../../runs/real2sim_width_estimate_20261012_v1_reference/pose_fit/summary.json)。不继续未登记的物理调参。

本机13项通过/1因缺pyarrow跳过，服务器9项新核心/Parquet测试通过；新指模型还实际验证质量/惯量/视觉数/相机不变及100ms有限物理预检。v8校验从HDF5重新取实际关节、从原source重算时间插值反馈/MSE，核原始命令、初始世界变换和8视频ffprobe/SHA。全场最大4.39cm穿透在未参与空盘动作的原场景flex载荷与地面，不应混称夹指穿透；保留原环境和证据，未删除碰撞。视频/完整轨迹留服务器，本机同步JSON/TXT和项目碰撞资源。

剩余问题：Place首帧双手稳定持盘与接触预载未复现。已确认提前触桌；对硬件URDF身份、掌部模型、接触参数和初始持物速度的影响尚未辨识，不能将某一项猜测写成根因。正式任务成功仍为null。

## 数据与执行

原始 Parquet → `Trajectory` → `JointMap` → `replay` → 仿真后端。数据、时间推进、名称/单位映射、模型构建、录像和实验报告分别维护；核心不依赖旧 FSM、策略网络、IK 或脚本模块。Isaac Sim / Genesis 只在边缘适配器接入已有 World/Scene。

- `r1pro_teleop/real2sim/trajectory.py`：核原 Parquet SHA，读取原始约30Hz时间戳，保留 L7/Lgrip/R7/Rgrip/torso4 共20通道。rad 与总开口 m；mm→m仅一次，反馈不裁剪。零底盘速度显式校验；未知移动底盘不默认为位置目标。保存可独立加载的 NPZ＋JSON来源包，split与原录制身份保留。
- `mapping.py`：按关节名绑定，支持轴向符号、零位偏置及两指各半开口。反馈通过反向映射还原逻辑通道，夹爪不与角度混算误差。
- `runner.py`：以原时间戳因果零阶保持命令，按后端固定物理步长推进；累计整步时钟避免30Hz/500Hz逐帧四舍五入漂移。每个源时刻在首个不早于它的物理tick记录，延迟小于一个dt；相应反馈线性插值到实测时间后计算误差。最后一个源时刻是端点，不额外执行一个伪造尾段。仅初始一次设关节位置/零速度；之后只发位置servo目标，绝不逐帧重设状态或移动托盘。
- `backends.py`：MuJoCo实际step/原生限幅保留；Isaac Sim `SingleArticulation.apply_action`；Genesis `control_dofs_position`。两个迁移后端要求已构建且未批量化的机器人实例，按名字解析DOF，不假定相同数组序号。调用方负责场景、相机、驱动增益、力限和接触配置，不能把接口测试当引擎物理复现验证。
- `model.py`：只向新路径生成模型，依据来源URDF恢复4腰部关节并同步18角关节的origin/axis/limit/effort。原桌、托盘、视觉/碰撞/惯量、相机局部朝向与FOV保留；原场景的具名和flex无名关节初态都迁移。新腰部PD默认kp250/kv25、gravcomp1，明确**未做真机辨识**；关节符合URDF不等于整机动力学一致。
- `scripts/replay_real2sim.py`：固定manifest顺序每动作前N条，独立目录，launch/status/exit、来源、限制审计、完整物理子步HDF5、反馈对比、每帧真实接触和四相机预览。`complete`只表示回放执行闭合，`task_success=null`。
- `scripts/audit_real2sim.py`：只读全来源的关节范围/腰部变化审计，不按范围删样本，不重分split。

## 模型版本与限制

来源为服务器 `/home/michelle/GalaxeaManipSim/galaxea_sim/assets/r1_pro/meshes/r1_pro_with_gripper.urdf` 的独立副本 `resources/real2sim_20261012_v1/r1_pro_source.urdf`。原项目右肘下限−1.7453；该来源为−2.0944。真实test首条Pick反馈含约−2.069。服务器另一个2026 URDF有不同结构/限制，不能仅按年份混用。所选源与实际录制硬件的完整身份仍待核对。

当前物理诊断复用原三桌单盘环境，**没有把它称为真机桌面/托盘标定结果**。真机来源没有直接提供物体世界位姿；尤其Place第一帧应有已经被握住的托盘。没有实测初始持物位姿、base坐标配准和物体尺寸之前，动作回放完成、低关节误差均不证明抓取/放置成功。不能用weld、每帧瞬移物体或隐藏IK填补这一缺口。

用户后续明确选择实测标定，并指定历史聊天《对比 EmbodiedSWE 代码》查找。该聊天可用4段来源中找到“沿用当前桌子”要求，项目当前桌1.2×0.6×0.8m、托盘0.56×0.43×0.105m可核；尚未找到这些尺寸的实测凭据、逐条录制base→table变换、Pick初态盘位姿、Place初态持物位姿。相机审计明确未验证标定。此结论限于已检索材料，不声称不存在其他附件。详见[标定来源追溯](../../runs/real2sim_pickplace_20261012_v3_reference/calibration_lookup_20261012.json)。不以视频估计替代用户选定实测来源。

## 使用

在非base Conda内运行；`--output`必须为新目录，原数据只读：

```bash
python scripts/replay_real2sim.py \
  --source-manifest /project/runs/real_only_pi05_20261012_v1/cache/test/manifest.json \
  --scene-xml /project/path/to/original/mobile.xml \
  --urdf /project/resources/real2sim_20261012_v1/r1_pro_source.urdf \
  --output /project/runs/real2sim_new_version --per-task 1 --video
```

本次视频是保留原相机姿态/FOV的640×360、30fps预览，源视频未动；不是原生分辨率导出。物理时间、源时间、视频帧数分别留证，视频轨迹留服务器。

## 迁移接口

导入完整机器人时保留URDF具名关节、两个夹爪滑动关节和腰部；转换后的mesh路径必须在项目内解析。源URDF使用package路径，需由导入器配置package根或生成本地路径副本，不能直接假设任意工作目录可解析。MuJoCo XML不是Isaac USD资产；软体外套等环境资产需另验证引擎支持，不能声称转换后接触行为自动相同。

```python
from r1pro_teleop.real2sim import Trajectory, r1pro_map, replay
from r1pro_teleop.real2sim.backends import IsaacSimBackend, GenesisBackend
t = Trajectory.load("/project/run/case_000/source")
mapping = r1pro_map()
# Isaac SimulationApp已启动，world.reset()后，articulation已初始化；stage单位为米。
backend = IsaacSimBackend(articulation, world, mapping)
# 或Genesis scene.build()后；dt必须是一次scene.step实际推进的时间。
# backend = GenesisBackend(robot, scene, mapping, timestep=0.002)
report = replay(t, mapping, backend)
```

参考并核对2026-10-12官方接口：[Isaac articulation控制](https://docs.isaacsim.omniverse.nvidia.com/6.0.1/robot_simulation/articulation_controller.html)、[Genesis RigidEntity](https://genesis-world.readthedocs.io/en/latest/api_reference/engine/entity/rigid_entity/rigid_entity.html)。Isaac/Genesis的状态设置仅用于一次初始化，其后调用原生位置控制器。SDK依赖延迟导入，NumPy核心和MuJoCo运行不要求安装另两个引擎。

测试 `tests/test_real2sim.py` 覆盖单位/夹爪映射、时间零阶保持、来源SHA、腰部保留、引擎控制API路由和MuJoCo真实子步。迁移后仍需分别验证真实引擎、资产、驱动和接触，当前不能宣称三引擎都已物理通过。

## 2026-10-12 已完成的实测

最终run/release `real2sim_pickplace_20261012_v3`，两个原始动作已完整物理执行并实际exit0；源选择为test manifest中每动作第一条，Pick episode5/439帧/7301物理子步/14.602秒；Place episode3/195帧/3234子步/6.468秒。来源域real、执行域simulation/real_command_replay。初始化之后0次状态重置，没有策略模型或教师回退。

| 对真机反馈的误差 | Pick | Place |
|---|---:|---:|
| 双臂14关节RMSE（°） | 2.779 | 0.315 |
| 双夹爪总开口RMSE（mm） | 31.813 | 15.788 |

这两例尚未完成真实桌/盘配准，夹爪误差不能解释成已成功握住托盘。腰部驱动也尚未辨识。回放流程完成不是托盘Pick/Place成功。

全量134条/37447原始帧完成Parquet SHA、时间轴、通道与关节范围核验，18角关节命令/反馈均在所选URDF范围内。134条中的零夹爪闭合命令低于旧场景的指关节最小开口，原生限幅保留并单列；7条反馈有夹爪超量程值，原值保留，不扩大关节限位。不能把两个物理指关节计数当成独立夹爪通道或独立episode。

8路预览ffprobe核帧数、30Hz、640×360、SHA；全轨迹有限/物理步长/terminal、误差独立复算、实际执行命令索引均闭合。视频轨迹留服务器。v1模型转换在flex无名joint处失败并保留；v2已闭合，v3修正PRE/Post-step命令索引元数据后另目录重跑，控制不变，旧记录不覆盖。

证据：[最终摘要](../../runs/real2sim_pickplace_20261012_v3_reference/summary.json)、[交付校验](../../runs/real2sim_pickplace_20261012_v3_reference/delivery_validation.json)、[全量来源审计](../../runs/real2sim_pickplace_20261012_v3_reference/source_audit.json)、[每视频一路径](../../REAL2SIM_VIDEO_PATHS.txt)。本机相关测试10通过/1因缺pyarrow跳过；服务器6项新核心/Parquet测试通过，本机真实MuJoCo场景测试通过（含无名环境joint）。两个迁移引擎仅接口测试，不计原生物理成功。

本机已完整核验332凸片SHA，并用项目本地原场景与源URDF实际编译新网格模型；几何301→629，质量/惯量/相机位置与方向保持一致，[本机资源验证](../../runs/real2sim_local_asset_validation_20261012_v1/summary.json)。不是新物理任务成功。

## 2026-10-12 本线程夹指执行语义修正与新回放

用户要求先执行一致性、暂不重训。新run/release `real2sim_execution_alignment_20261012_v1`复用v8碰撞、配准与腰部参数，未改桌盘尺寸/源命令。修复build_model遗漏的夹指origin/axis/限位：URDF指2负向行程转换为等价正向外张轴，逻辑总开口仍各半；旧2mm每指下限移除，驱动力按源100N。硬件身份和增益仍非实测辨识，不能称全动力学已一致。

实际exit0，两例7301/3234物理步，8路640×360/30fps预览、轨迹SHA/时间/命令/指标独立验证通过。命令限位违例两例均0。Pick双臂/腰RMSE2.856°/0.076°、夹爪26.915mm；盘z由0.801至0.99647m，末秒双手接触31/31、桌0/31。Place双臂/腰0.389°/0.251°、夹爪52.729mm，0.102s触桌早于原开爪3.267s；末秒桌支撑31/31不能抹去提前落盘，完整Place未通过。task_success仍null，不计训练。

初态由估计配准产生，尚未证明双臂真实持盘平衡；当前证据不能把失败全部归于摩擦或几何尺寸。建议下一步分离初始双手接触、夹爪反馈与掌体碰撞，再决定是否需要新配准候选；不擅自修改真机命令或加附着。旧失败保留。

[实测摘要](../../runs/real2sim_execution_alignment_20261012_v1_reference/execution_alignment_report.json)、[独立验证](../../runs/real2sim_execution_alignment_20261012_v1_reference/delivery_validation.json)、[视频路径](../../REAL2SIM_EXECUTION_ALIGNMENT_VIDEO_PATHS.txt)。浏览入口 http://100.104.0.108:8773/ ，case_000拿取/case_001放下；服务仅bind私有100.104.0.108，PID273691是启动快照。回放PID270926已exit0。本地9通过/1缺pyarrow跳过，服务器9通过（场景编译已本地验证，服务器全物理另实测）。未启动任何训练。

## 2026-10-12 持盘初态诊断（未修复成功）

用户要求保留轨迹、尺寸、验收、不训练。新增scripts/diagnose_real2sim_held_pose.py，3个有界离线种子只调整初态六维位姿。确认旧拟合只找最近点，未考虑夹持方向；第一轮内侧方向拟合又遗漏其他凸体穿透，导致最大9.7275mm指盘穿透。v2增加全指凸体与掌体距离残差，源命令、驱动、尺寸、摩擦不改。静态候选0最近内夹面间隙1.625/2.692/6.328/3.203mm，最大初始指盘穿透约0.01045mm；收敛不代表能持盘。这个局部范围内未找到稳定持盘方案，不能外推任务不可达。

驱动诊断：原Place左肘反馈−1.70468rad、命令−1.66593rad；仿真34ms反馈−1.67708，真机反馈直到166.7ms才首次变化。夹爪初始反馈18.2/19.5mm，命令0。响应差异已确认，但缺乏驱动力/传感时延的辨识，不能认定唯一根因或直接把原命令延后。报告仅建议后续独立辨识，不改时间轴。

实际完整回放real2sim_held_contact_20261012_v1/v2均2例exit0。v1 Place初始穿透、开爪后左指仍卡盘并把盘再次带起；v2消除大初始穿透及终态卡滞，但起始仍失夹落盘，末秒桌面支撑/双手释放不能当整个Place通过。Pick仍盘z0.801→0.99647m（19.55cm）。v2末态Place盘z0.79999m，双侧指力0、桌支撑11.772N；双臂RMSE约0.334°，夹爪约71.22mm。初始位姿与夹持/驱动一致性尚未闭合，不进训练。

更正：先前用“早于松手触桌”单独判失败不充分，正确放置可先触桌后松手；当前失败依据含原应持盘阶段失夹和落盘。第一轮临时probe用geom名字匹配手指导致force字段无效，probe_classification_correction.json保留更正，已用生产body-based诊断重新执行相同3候选并保存physical_probe_corrected.json；真实候选未改。原异常与报告保留。

[最新回放摘要](../../runs/real2sim_held_contact_20261012_v2_reference/summary.json)、[独立校验](../../runs/real2sim_held_contact_20261012_v2_reference/delivery_validation.json)、[静态诊断](../../runs/real2sim_held_pose_diagnosis_20261012_v2_reference/summary.json)、[驱动响应](../../runs/real2sim_held_pose_diagnosis_20261012_v1_reference/drive_response.json)。最新8视频路径REAL2SIM_HELD_CONTACT_VIDEO_PATHS.txt；入口8773/held_contact_v2/case_000/viewer.html与case_001/viewer.html，640×360/30Hz预览，真实轨迹在服务器。未训练。代码9测试通过/1本机依赖跳过、规范sync通过。
