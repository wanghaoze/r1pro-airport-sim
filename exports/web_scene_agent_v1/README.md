# Isaac 32 房间网页 Agent：第一阶段导出包

2026-10-17 · 默认场景经用户选择为最新 Isaac 32 房间 Pick/Place。此包是网页开发与后端接入的起点，包含可复制的 prompt、结构化执行协议和可运行的草稿/计划执行器。尚未创建网页、连接 LLM、部署服务或启动 GPU 训练。

## 文件入口

| 文件 | 用途 |
|---|---|
| [prompts/build_web_app.zh.md](prompts/build_web_app.zh.md) | 给网页开发 agent 的完整实施 prompt |
| [prompts/runtime_system.zh.md](prompts/runtime_system.zh.md) | 网页对话 agent 的 system prompt |
| [prompts/turn_templates.zh.md](prompts/turn_templates.zh.md) | 场景修改、训练选择、状态解释的逐轮模板 |
| [command.schema.json](command.schema.json) | 对话 agent 输出的 JSON Schema |
| [executor.py](executor.py) | 标准库执行器：读取快照、保存场景草稿、筛选数据并冻结训练计划 |
| [isaac_adapter.py](isaac_adapter.py) | 32 房间配置复制与 USD 视觉材质接入函数；尚未接入生产入口 |
| [examples](examples) | 可直接执行的 JSON 指令 |
| [run_examples.ps1](run_examples.ps1) / [run_examples.sh](run_examples.sh) | 本地执行命令 |

## 立即执行

在项目根用已有非 base 环境运行，无需安装依赖：

```powershell
.\.conda\experiment\python.exe exports/web_scene_agent_v1/executor.py --command exports/web_scene_agent_v1/examples/describe.json
.\.conda\experiment\python.exe exports/web_scene_agent_v1/executor.py --command exports/web_scene_agent_v1/examples/edit_room.json
.\.conda\experiment\python.exe exports/web_scene_agent_v1/executor.py --command exports/web_scene_agent_v1/examples/list_datasets.json
.\.conda\experiment\python.exe exports/web_scene_agent_v1/executor.py --command exports/web_scene_agent_v1/examples/plan_training.json
```

写入仅限 `runs/web_scene_agent/<request_id>/`。`command.json` 保存输入，`artifact.json` 保存草稿或冻结选择，`receipt.json` 保存 SHA 与状态。同一请求 ID/内容重复执行返回已有收据；改内容必须换 ID。已有文件损坏或不完整则拒绝覆盖。此行为不是分布式作业锁，也不是训练监督器。

网页后端可以 import `executor.execute(project_root, command)`；`project_root` 由服务端配置，不能从浏览器请求透传。LLM 只能提交这四种已实现的 op：

| op | 当前实际效果 |
|---|---|
| `scene.describe` | 返回场景合同及坐标格式，真实初始 32 房间配置需从服务器读取 |
| `scene.patch` | 保存指定房间的位姿/颜色草稿，尚不应用到运行中的物理场景 |
| `datasets.list` | 校验并读取本机登记的两份服务器归档元数据 |
| `training.plan` | 冻结所选完整 Pick/Place 对、来源、split 和请求配方，给出阻塞原因 |

`training.start`、任意 shell、SSH、任意文件路径和实时机器人控制不在当前协议内。网页开发 prompt 指定了后续 `training.start` 的实施要求，不把未实现工具交给运行时 LLM。

## 场景编辑约定

选中房间编号为 0–31；前端显示 `room_000` 等，API 传整数。所有位姿使用**房间局部坐标**。底盘 `[x_m, y_m, yaw_rad]`；托盘 `[x_m, y_m, z_m, yaw_rad]`；颜色为不透明 sRGB `#RRGGBB`。不要把 32 房间网格偏移加进策略状态。第一版支持底盘初始平面位姿，关节级编辑需另加具名映射/限位/碰撞资格，不能拿未支持字段冒充成功。

“把机器人向左移动10厘米”必须结合当前姿态解释机器人的左方向，转换后提交**绝对**房间局部坐标。未加载真实基准姿态时保留草稿，不编造默认姿态。编辑只作用于下一 episode 的初始配置；执行过程中底盘目标固定，Place 承接实际 Pick 末态。三桌位置尺寸、单盘数量、双臂对向长边、夹爪/手指、相机朝向、真实碰撞与质量惯量保持项目合同。

`isaac_adapter.materialize_config(...)` 将机器人位姿同时写入所选 case 的 `initial_base_world` 与 `fixed_base_world`，托盘 yaw 转为原生 wxyz 四元数。旧预检证明失效，新配置必须重新预检。颜色保持单独 sidecar，原有入口不会自动读取它。

在新的 Isaac 入口中，完成 `apply_lab_visuals`、32 房间克隆/材质重定位之后、第一次物理步之前调用 `apply_visual_colors`。路径白名单必须来自实际 stage 的可见纯视觉 mesh，机器人排除夹爪、手指、相机；托盘选择对应 `_RenderAppearance/Surface`。每房间单独绑定材质，避免共享材质把所有房间一起改色。该函数仅写 session layer，校验原碰撞/惯量/相机指纹；任何异常丢弃整个新 stage。需在服务器验证 RTX 是否显示 preview-purpose 材质、检查帧图及物理指纹后才能声称颜色已应用。SDK 函数未在本机执行。

## 数据与训练接入

本机可核验的 2026-10-16 快照：窄批 30 对/60 片段，宽批 29 对/58 片段；合计 59 对/118 片段/472 个四相机片段文件。每批 32 个候选房间不等于 32 个成功来源。全部为 train、专家控制、`simulation/program_generated`，仅 `fixed_base_pickplace_only`；既不是完整三动作，也不是 VLA 成功率。数据查询不会联系服务器，不声称这是实时最新总量。

当前示例只选择两份历史 sim 快照，因此计划返回 `blocked`：所选数据缺合法 val/test、服务器媒体/真实退出收据尚需复核、网页训练启动适配器尚未接通。JSON 正常生成时 CLI 退出码0只表示计划导出成功。`scripts/train_pi05_isaac_three_tray.py` 强制三个 task ID，不能直接用它训练这批两动作数据。不得把同一父 scene 随机拆成 train/val/test 来绕过缺口。

同日工作区已有 DEC-055 的独立新路线：`r1pro_teleop/vla/parallel_pickplace_training.py`、`scripts/train_pi05_parallel_real_mix.py` 与 `supervise_parallel_real_mix.py`，用于新增300对 + 真机50/50耗时加权BC。该路线保持真机val/test，sim仅作train扩增，不要求伪造sim val/test。本包未启动或改动该路线，59对旧快照不能代替它的新300对。后续网页接入应优先复用这些已出现的模块并核验实际报告；文件存在不等于已训练通过。

后续接入两动作 cache/BC 时使用现有官方 OpenPI 路径，精确两文本、19维动作/反馈、20Hz、四原生相机留存，模型三视角映射显式声明。仅 train 计算归一化/梯度，val/test 独立评测并注明评测域。冻结源清单/配方/父模型 SHA、记录真实梯度步数和检查点，不覆写原训练输入。真实来源/媒体验证、单实例监督、服务器实测通过后再启用 `training.start`；不能用 mock 的 loss 曲线当训练结果。

## 验证与边界

本机测试见 `tests/test_web_scene_agent_export.py`；本轮报告见 `runs/web_scene_agent_export_20261017_v1/validation.json`。测试覆盖指令输入、非法字段、路径隔离、请求重放、冻结选择、父场景 split、配置复制与位姿单位转换。测试不代表真实 USD 渲染、完整物理 episode 或实际 BC 训练通过。

权威合同仍为项目 `AGENTS.md` 与 `docs/SCENE_TASK_SPEC.md`；本包没有新设物理容差或更改已有成功标签。
