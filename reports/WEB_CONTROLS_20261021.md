# 网站运行控制与关节插值验收 · 2026-10-21

六项功能已实施并发布：GPT Site v15，工作站新目录 `releases/scene_studio_web_controls_20261021_v17`。本报告替代本轮 v16 的中间结果；历史报告、模型、数据和失败现场保留。仅仿真，无真机控制。

## 交付

| 要求 | 实现与验证 |
|---|---|
| 网页显示错误 | 全局 Errors & diagnostics 收集当前浏览器的 JS、Promise、console.error、HTTP/网络及资源/媒体错误，合并重复次数；已加载作业显示结构化失败、traceback、服务日志。策略详情可下载脱敏 diagnostics.zip。长日志显示尾部与早期错误上下文并标注截断，原始完整日志留服务器。已实测未登录401、媒体失败在网页可见，以及服务器取消原因和日志归档。 |
| 10000秒 | 默认10000仿真秒，即20Hz下200000动作帧；overall wall-clock guard默认0，关闭总墙钟超时。10000仍是有限上限，任务终止、反馈门、单次推理或初始化超时可提前结束。并未完成10000秒耐久测试。 |
| Stop policy | 网页/API发出持久停止请求；等待模型及物理循环均检查，直到实际子进程退出才标cancelled。排队任务取消不启动GPU。真实运行停止约3.03秒，两个子进程实际wait返回0且退出。 |
| Isaac Sim | 原生日志加载 `isaacsim.exp.base.python-6.0.1`，PhysX 500Hz，25子步/20Hz动作。此次 `activeGpu=1`、`cudaDevice=1`、physics_device=cuda:1。浏览器Three.js只是预览；默认Realtime选项是CPU PhysX+所选GPU渲染，可切GPU PhysX。 |
| 可调filter | π0.5、G0.5、GR00T统一单位后经过同一必经filter；每次运行冻结参数及合同hash。步长、速度、跟踪误差、反馈时效可在登记上限内调整，机械范围和夹爪范围不能放宽。过滤端点再25子步线性插值；v2预留float32量化余量，修复相邻子步轻微超速。原始输出保留，过滤诊断不计纯模型成功率。 |
| GPU选择 | 仿真/渲染、模型推理分别选物理GPU；训练页多选GPU，显示空闲显存，队列检查实际可用性，环境及运行配置记录选择。GPU1真实推理与PhysX已实测；训练GPU1 JAX设备枚举/批量整除探针通过，未启动新梯度训练。 |

设置只对新任务生效，已有任务保留原合同。批量/自动评测同样强制filter；未填写设置采用登记默认值。GPU选择不代表独占：Isaac在另一张GPU创建了约314MiB上下文，但选中GPU1承载渲染/物理及模型主要显存。

## 实测证据

最终诊断job：`bf659331-0db2-4368-a028-6fa042a16b36`，Room000，π0.5 `cp_8788068a6984a796aed42ef1`，训练父场景，GPU1，step=0.02rad，velocity=0.4rad/s。

- 实际22帧、550物理子步、1.1仿真秒；人工式API停止，结果user_cancelled。
- float32下发目标：关节/夹爪范围越界0；连续子步速度越界0；最大0.39999745786190033rad/s；相邻动作帧最大0.01999981328845024rad。反馈年龄最大0.099865秒，底盘目标固定。
- 停止延迟3.0297秒；native与policy子进程actual_child_wait=true、exit0，之后/proc确认均已退出。
- 报告successRate=null，modelFailures=0、infrastructureFailures=0；这些不表示Pick/Place成功，也不表示模型泛化通过。
- diagnostics.zip服务器HTTP下载SHA256与清单一致，四路MP4及JSON完成归档。视频/轨迹留服务器，只拉回元数据和日志。

[最终运行状态](../runs/web_controls_20261021/revision2/diagnostic_status.json)、[实际命令审计与日志](../runs/web_controls_20261021/revision2/command_audit.json)、[API非法参数与排队取消](../runs/web_controls_20261021/revision2/api_validation.json)、[训练设备探针](../runs/web_controls_20261021/training_device_probe.json)。审计覆盖所有记录子步的范围及相邻子步速度；不把首个未记录前序命令推断为实测。

第一次v16诊断 `045d3e27-d1ae-4ad1-8a25-ae1481d8db5d` 暴露float32子步0.40000677rad/s超过0.4；已保留[失败审计](../runs/web_controls_20261021/audit_output.txt)。v17通过量化余量修复，不通过放宽限值消除失败。

## 验证与发布

- 本地70项Python、服务器70项Python检查通过，包含三模型适配路径、限值拒绝、float32插值、GPU参数、取消和错误保留；14项Node合同测试、现有UI静态回归通过。
- 最终Sites生产构建、offline构建和diff空白检查通过；统一规范同步检查通过。
- Sites源码commit `2bab3ecd1cf18136f27e05874e32db3d26e83f9b`；v15部署 `appgdep_6ad88741cf248191b87c67105c07a3f4` succeeded，2026-10-21 09:35UTC。
- 工作站v17 health=ok，旧服务确认退出；新web supervisor PID1402279、web1402280、cloud worker1402361是部署时取样，不表示永久存活。
- 浏览器确认10000、guard0、GPU下拉、训练GPU1复选框、全模型filter、Stop按钮和真实错误列表。浏览器当前未登录，因此未通过浏览器提交GPU作业；实际停止和运行验证走同一服务API，未绕过网站账户权限。

## 剩余边界

现行真机TOML仍缺失：登记归档范围与场景机械约束已执行，不能宣称已核实当前真机配置。此filter保证记录下发位置/速率范围，不等于实测关节永不超调、碰撞/力矩/加速度安全认证。历史夹爪反馈超调问题仍保留。

G0.5缺失夹爪输出时明确失败，GR00T缺权重不标原生成功；跨模型合同测试通过不等于三个模型均已跑通完整物理任务。未执行新训练或完整10000秒运行。

未登录页面会显示bootstrap401及受保护历史视频加载错误；已可在错误面板查看。用户登录后才能提交/停止自己的Site作业和查看受保护运行产物。

交互档案按显式本项目线程清单刷新至 `runs/web_controls_20261021/interactions`；本机本次可用1个源文件、50条消息，不代表所列历史线程均已获得。当前最终回复将在下轮刷新时收录。

[策略控制截图](../runs/web_controls_20261021/revision2/policy-controls.jpg) · [训练GPU截图](../runs/web_controls_20261021/revision2/training-gpu.jpg) · [发布记录](../runs/web_controls_20261021/revision2/deployment.json)。
