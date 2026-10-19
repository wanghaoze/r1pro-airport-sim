# Isaac Sim实验迁移（2026-10-15）

用户要求把实验接到Isaac Sim。当前仅资产/原生引擎接入，**没有完整任务或VLA模型成功**，不改既有MuJoCo数据、模型、真机服务。

## 实核结果

- 服务器已有env_isaaclab（5.1.0）和env_isaaclab6（6.0.1），无需安装。5.1在启动RTX模块时崩溃；根因未确认，保留v1日志。
- 6.0.1实际启动成功，按已安装源码使用MJCFImporter/MJCFImporterConfig新接口。独立转换副本只处理discrete字段旧解析器不识别问题，目标原生物理为PhysX，不声称动力学等价。
- 输入V4 val proposal_000245/scene/mobile.xml，三桌/单盘/机器人与载荷资源不改。源XML及include SHA落盘。
- v5完整导入并完成100步，但退出清理阶段SIGSEGV（exit -11），保留证据，不称成功退出。
- v7/v8完成100×2ms PhysX步进并实际exit0。原始任务四相机及三个辅助相机按安装body、局部位姿和FOV补建，四任务原分辨率1920×1536头部双路/1280×720腕部双路；图像渲染与对齐未验证，不能当视频闭合。
- v8实际Articulation有18个具名DOF（双臂14+四指4），初始化反馈有限。三个底盘自由度转换为独立世界D6 joint（agent_base_x，transX/transY/rotZ drive），不在Articulation DOF中，不能复用旧数组序号或直接忽略底盘；原生驱动及坐标映射尚未验证。

## 当前阻塞与边界

外套MuJoCo flex尚未转换成经验证PhysX软体；导入日志显示多个滑动关节被合并D6，部分细长网格GPU碰撞烘焙回退CPU，不能与particle/deformable交互。四相机没有自动导入，已补建但未验图像。源碰撞/摩擦/惯量、驱动增益/力限、home状态、底盘D6及真实载荷生成须逐项核验。没有擅自把外套改刚体、删除碰撞或冻结底盘，没有重新训练或隐式教师。

当前run：
`/home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_migration_20261015_v8`

- `native_smoke/airport_scene.usda`：含补建相机的独立场景（依赖同项目v5转换资源，不能仅拷一个usda当独立包）。
- `native_smoke/{source_inventory,conversion_changes,usd_inventory,camera_mapping,articulation_mapping,report,status}.json`：源身份、转换/映射/报告。
- `child.json`：PID/birth/argv/cwd以实际文件为准，旧PID不代表当前存活。
- `native.log`、`exit.json`：实际日志与wait退出码0。作业已完成，不是后台继续迁移程序。
- v5转换资产：`runs/isaacsim_migration_20261015_v5/native_smoke/converted/import_only/import_only.usda`。

下一步为原生底盘/关节/相机与接触验证、PhysX软体与载荷阶段、同一已保存模型的纯VLA闭环。现有50/50 checkpoint保持原样；未做Isaac闭环，不用MuJoCo成绩替代。

## 入口与检查

项目源码`scripts/isaacsim_scene_smoke.py`；独立输出目录必须不存在，支持`--usd`复用旧资产但不回写。使用服务器非base Python：
```
/home/michelle/miniconda3/envs/env_isaaclab6/bin/python scripts/isaacsim_scene_smoke.py --xml <source/mobile.xml> --usd <converted/import_only.usda> --output <new_run/native_smoke> --steps 100
```

每个native job由独立session的父进程实际wait并写exit.json，冻结脚本副本、PID/birth/argv/cwd；不是完善后台任务迁移监督器。报告要求status与exit双重核验；migration_complete=false、training_eligible=false、task_success=null。Native API依据服务器已安装6.0.1源码及[NVIDIA MJCF导入说明](https://docs.isaacsim.omniverse.nvidia.com/6.0.1/importer_exporter/ext_isaacsim_asset_importer_mjcf.html)。

## v9相机出图实测

v9已实际exit0；100步检查后额外执行8次渲染推进，四任务相机输出原分辨率PNG，记录实际sim时间0.6020000286s、图像SHA和像素统计。新增600强度诊断DomeLight，仅用于渲染核验，图像不进训练。不是视频、不是模型执行、未验证初始姿态或完整光学对齐。证据：runs/isaacsim_migration_20261015_v9_reference/verified_snapshot.json。

最新run：/home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_migration_20261015_v9。native_smoke/airport_scene.usda为该run场景；旧v5资源仍为依赖。HTTP实测200：http://100.104.0.108:8775/ ，viewer PID59003，仅预览静态产物；原生child PID56352已实际exit0，不是仍在跑模型。底盘D6、原生接触、软体与模型闭环尚未完成。open_in_codex返回queued，不声称用户已看到页面。


## 2026-10-15 完整实验迁移进展（取代上述未验证项的对应状态）

用户确认包括训练数据。服务器非base env_isaaclab6实际完成GPU原生双臂/四指/底盘映射预检，PhysX surface-deformable外套63节点有限；原开口0.1m未套用硬件80mm限幅。原生参考完整执行1381帧、四路20Hz视频实际ffprobe/SHA闭合，episode01_exit实际0；但Pick末盘高约0.7999m，旧参考约0.9765m，未拿起，任务失败、不进训练。不是VLA执行。不能将相机/控制预检称为全实验成功。

本轮根：/home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_full_experiment_20261015_demo01。
- control/validation.json、control_exit.json：首轮源特定驱动与原生外套预检。
- native_episode_01：四路mp4、native_trace_partial_or_complete.npz、diagnostic_result.json、video_closure.json；取盘失败证据。
- episode01_exit.json：实际wait0。旧episode00初始化失败证据保留。
- material_candidate02：发现导入动态摩擦1.2但静摩擦0，在新scene_v3.usda按源系数恢复静/动与max合并；修正USD实例代理名称误配，材料668项。是否解决取盘失败尚未验证，不能称根因已解决。
- material_candidate02/control：第二候选原生控制预检passed；实际退出与完整尝试以该目录收据为准。

预览：http://100.104.0.108:8775/native_demo01/viewer.html （HTTP200，诊断失败）。新预览链接指向新产物，没有改历史视频。视频/轨迹不下载本机。

新增数据模块r1pro_teleop/vla/isaac_dataset.py及scripts/prepare_isaacsim_dataset.py：完整原生成功收据门、父split隔离、不可变清单、三动作精确帧裁剪/文本、H20不跨动作边界、float32/uint8缓存。新训练入口接受显式Isaac绑定及完整性哈希，旧默认配方不变。native任务观察器/随机采集监督/模型闭环尚未完成；当前合格Isaac来源0、片段0、新Isaac训练waiting_for_data，不能用旧MuJoCo数据填充冒充迁移完成。

本机新增核心测试13项通过；部署code_v1先代码-only23通过/1资源缺失，绑定项目只读资产后24项通过。后续最终检查见本轮记录。独立代码release：releases/isaacsim_full_experiment_20261015_code_v1，当前健康作业使用冻结代码副本；不覆盖旧训练release。

最新核验 2026-10-15T16:17:45.650191+08:00：第二候选control实际exit0；完整参考重执行后台监督PID221900、子PID221901/start_ticks26510323与argv/cwd吻合，421/1381帧、Place阶段；Pick同样未抬盘，修正静摩擦不足以解决问题。保留该健康诊断继续录制，不启动第三个盲目完整候选。源码release code_v2在服务器25项测试通过；需继续定位接触/几何映射并实现原生任务观察器，未开始训练。
