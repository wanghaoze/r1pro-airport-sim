# 网页开发 Agent 执行 prompt

你在 r1pro-airport-sim 项目中实现一个可对话构建场景、选择训练数据并训练模型的网页工作台。用户已指定默认加载最新 Isaac 32 房间 Pick/Place 场景。先读 README.md、docs/INDEX.md、docs/SCENE_TASK_SPEC.md、memory/CURRENT.md、memory/DECISIONS.md、docs/project/MODULE_MAP.md、DATA_CATALOG.md、EXPERIMENT_STATUS.md；当前用户要求高于历史记录。

本次输入由调用方填充：

```text
PROJECT_ROOT={{项目绝对目录}}
EXPORT_ROOT={{PROJECT_ROOT}}/exports/web_scene_agent_v1
APP_ROOT={{PROJECT_ROOT}}/apps/scene-agent
SERVER_PROJECT_ROOT={{已确认的服务器项目目录}}
REGISTERED_NATIVE_CONFIG={{只读核实后的32房间配置路径和SHA；未知留空}}
LLM_PROVIDER={{服务端可用的模型服务；未知先用协议回放测试，不伪称已接通}}
```

先检查已有实现并复用。完成本地网页和服务端，再按实际授权部署；输出留在本项目。不要启动或中断任何旧采集/训练任务来做 UI 测试。

## 用户路径与界面

实现桌面三栏工作台：左侧场景树/32房间列表，中间全局网格或单房间3D视图，右侧 agent 对话与可编辑参数。顶部清楚显示场景分支、草稿版本、连接状态；数据和训练为第二工作区。窄屏使用抽屉/标签页。中文主界面，机器人、托盘、相机、桌子名称可辨认，颜色和位置编辑有预览、撤销、重做及版本差异。

3D视图从项目内实际资产转换获取；不要用方块代替机器人却宣称真实场景。首次资产尚未加载时显示“资源未加载”和来源状态。视图中的静态编辑预览、物理验证视频与模型执行结果有不同状态标签。展示真实来源录像可使用已有只读媒体服务；不为 UI 把全部视频复制到本机。共享时钟总览不能由异步片段拼成伪并行。

对话支持“把 room_003 的托盘改成蓝色”“机器人朝向转15度”“所有房间机器人外壳改成白色”等。读取当前状态后明确坐标和单位；自然语言相对量转绝对位姿。明确作用对象，默认选中房间，未选中则让用户选择。生成字段级 diff，后端校验并保存新草稿，然后更新预览。保持已经获准的低风险编辑直接执行；遇到抓法/动作流程/底盘范围/验收容差/训练方案取舍，提供实际原因、证据、选项和推荐，等待明确选择，期间可继续独立 UI 工作。

数据页显示来源域、场景版本、完整来源对数、动作段数、相机文件数、父场景数、split、动作集合、时间/相机/资格状态。先接入 executor.py 的两份已登记快照；读取服务器新目录后通过登记入口新增版本，不能接受 LLM 随意给路径。失败/诊断行可查看但不可训练。选中数据后生成冻结计划，显示预算、父模型和阻塞原因。训练页区分 data_ready、initializing、training、checkpoint_saved、evaluating、complete、failed、unreachable；展示真实更新数、loss、日志、checkpoint、scope和评测分母。

## 运行架构

前端可用 React/TypeScript + Three.js，后端采用项目独立非 base Python 环境中的 HTTP 服务。依赖是否已存在先检查；不改系统 Python 或 vendor。LLM密钥仅从后端环境读取，前端不保存密钥、SSH凭据或私钥。

复用 runtime_system.zh.md 和 command.schema.json。LLM 仅输出 allowlist JSON；后端调用 executor.execute，不直接执行模型生成的 shell/Python/SQL/文件路径。前端 schema 和后端类型校验均保留。服务端持有 project_root、数据登记表和实际 USD 路径白名单。每次调用绑定用户会话、request_id、版本号；并发编辑要防止旧版本覆盖，撤销产生新版本。以可测试的 fake LLM 做协议回放时页面明确“协议测试模式”。

建议 HTTP 约定（本导出包尚未启动 HTTP 服务）：

- `POST /api/chat`：真实模型工具调用循环，记录对外回复与已校验指令。
- `POST /api/commands`：仅允许当前 schema；成功返回收据，校验失败400，ID冲突409。
- `GET /api/scene`、`GET /api/datasets`：服务端权威状态/登记元数据。
- `GET /api/jobs/:id/events`：SSE进度及断线重连，不凭前端计时器增加梯度计数。

## Isaac 接入步骤

以 scripts/run_isaac_parallel_pickplace.py 的32房间、单engine/单PhysicsScene共享时钟为真实执行依据。通过已核实配置/identity.json获取 cases；保留每房间 parent_scene_id、parent_split、seed 与源SHA。用 isaac_adapter.materialize_config 生成新配置，在第一次物理步前设置初态；动作期间不瞬移，不挪底盘，不在 Pick/Place 间复位。

将 isaac_adapter.apply_visual_colors 接到新入口的视觉克隆之后；服务端只枚举真实纯视觉 mesh。机器人颜色编辑保留夹爪本体/手指/相机；托盘颜色仅修改渲染材质。USD新session layer、指纹前后相同、实际原生帧图验证齐备后才声明成功。不要复用共享材质导致未选中房间变化。

每次位姿变化使旧私有路径预检失效。先复用现有桌前/双臂长边预检，再跑新的完整 native episode，保持 2ms 物理步、20Hz控制/四相机及25子步。只有真实接触成功、Pick真实末态连续进入Place、原始录像/状态/动作/真实退出全部闭合的源可进入新数据版本。预检通过不能显示为任务成功。

## 两动作模型训练必须补齐的功能

先核验并复用当前 r1pro_teleop/vla/parallel_pickplace_training.py 的freeze/cache、scripts/train_pi05_parallel_real_mix.py和supervise_parallel_real_mix.py；它们属于DEC-055的新300对+真机50/50耗时加权BC。接入真实来源/cache/父模型和训练报告后再登记网页能力。已有授权保持，不另造相同训练任务。train_pi05_isaac_three_tray.py强制三任务，不要把两动作数据送入它、虚构Flush或修改旧训练输入。复用官方OpenPI、既有19维/20Hz投影、精确Pick/Place文本和train-only归一化。保留四相机原始证据，明确模型三视角映射。steps/batch等新变更才需要呈现具体配方与影响；有损恢复或资源抢占不能擅自进行。

本机2026-10-16两份快照全部为train且只有一个父scene，只选它们的纯sim示例计划缺合法val/test；补充其他合法父场景完整来源后才能满足该方案。DEC-055混合方案已有真机val/test，sim仅做train扩增，不额外要求sim holdout，不把该方案改为纯sim。新300对数量不能混入旧59对。若用户后来选择其他独立train-only试验，记录新的scope/授权和评测限制，不能暗中重划父场景或扩大成完整任务成功。

新增 training.start 前实现服务器worker单实例锁、PID/启动时间/argv/cwd核对、阶段/心跳/实际退出码、健康复用、输入SHA冻结与明确的stop范围。普通恢复沿项目已有最多3次逐次退避；物理候选仅登记方案。训练仅在真实梯度更新后标training；检查点保存与模型闭环通过分开。模型测试禁止教师、IK、逆动力学或自动纠正回退。训练停止/资源策略不能误杀无关服务。

## 验收和交付

先运行导出包测试，再测试场景编辑、撤销、单位、选中房间隔离、数据资格/split、重复请求、断线与日志恢复。实际测试颜色原生渲染与物理不变量、一个完整物理Pick/Place、冻结数据官方loader、服务器实际梯度与保存，分别附产物和失败原因。缺任何接口如实列为待完成，不用模拟动画/缓存/初始化替代。更新统一规范人工章节、状态/失败字典和项目专题，再执行 sync_task_spec、handoff catalog 与交互归档。交付可运行入口、环境命令、接口文档和具体测试证据。
