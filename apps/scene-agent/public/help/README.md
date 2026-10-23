# R1 Pro Scene Studio — 网站使用 README

网站：[打开 R1 Pro Scene Studio](https://r1pro-scene-agent-haoze.exactmyna128.chatgpt.site/)

适用：2026-10-19 英文界面及 MSE 图表版本。本文用中文解释操作，按钮名称保留网页上的英文。网站由 ChatGPT Sites 托管，仿真、训练和评测由 GPU 服务器执行。

本文是操作手册，不是实时任务状态。进度、检查点、评测数值以网站最新采样和对应报告为准。

## 1. 先看 MSE：最快入口

**顶部 `Data & training` → 向下滚动 → `Evaluation & MSE` → 再向下找到 `Real TEST MSE` → `MSE figures & prediction traces`。**

1. 打开网站并登录。
2. 点击顶部的 **Data & training**。
3. 向下经过 **Current training** 和 **After training**，找到三个标签：**Data & recipe / Evaluation & MSE / Job queue**。
4. 点击 **Evaluation & MSE**。
5. 向下经过 **Fixed real-data MSE comparison** 和 **Isaac VLA closed loop** 两个提交区域，找到已有任务的 **Real TEST MSE** 或 **Real VAL MSE** 报告。
6. 在误差表格下找到 **MSE figures & prediction traces**，用 **Figure** 下拉框切换图表。

进入正确标签后，也可用浏览器 `Ctrl+F` 搜索 `MSE figures`，定位已显示在页面里的图表区域。

**如果你正在 `Run history`：这里列出任务状态和回执。`MSE comparison completed` 这一行不是图表入口，请按上面的路径切换页面。**

自动评测另有一个入口：**Data & training → After training → MSE comparison**。该区域展示对应训练任务最终检查点的自动评测；尚未完成时显示排队、阶段或 `No measured result yet.`。

### 图表与下载

| Figure 选项 / 按钮 | 用途 |
|---|---|
| Joint MSE (rad²) | 14 个手臂关节的均方误差 |
| Joint MSE in degrees (deg²) | 相同关节 MSE 换算为平方度 |
| Joint RMSE (deg) | 关节均方根误差，单位度 |
| Gripper MSE (mm²) | 左右夹爪的均方误差 |
| Gripper RMSE (mm) | 左右夹爪的均方根误差 |
| Episode 000… | 每个 episode 的 4×4 曲线：14 个关节与 2 个夹爪，真实值与各检查点预测值叠加 |
| 点击图片 | 新标签页打开原分辨率图片 |
| Download PNG | 下载当前选中的图片 |
| Per-joint metrics (CSV) | 下载各模型逐关节数值 |
| Download all figures (ZIP) | 下载整套图片、CSV 和来源说明 |

图表状态可能先显示 `Rendering`，再显示 `Uploading`，全部文件发布完成后显示 **Ready**。上传过程中只展示已经可读取的图片，CSV/ZIP 按实际就绪情况出现。

完整 Test 19-episode 报告会生成 **24 张图：5 张汇总图 + 19 张 episode 曲线**。不同 split 的 episode 数量不同。曲线显示每帧的首步预测，汇总 MSE 使用有效的 H20 目标；两者统计范围不同。手臂曲线用 rad，夹爪曲线用 mm，各通道纵轴独立。

下图为 2026-10-19 的界面示例，显示旧 100 步混合模型与 10,000 步纯真机模型的报告；用来说明操作位置，不代表当前最新模型结果。

![MSE 图表与下载位置](../../runs/web_english_autoeval_20261019_v1/production_mse_ready.png)

## 2. 登录与页面导航

首次使用点击右上角 **Sign in**，完成 ChatGPT 登录。浏览器与 Codex 的登录状态可能不同；在另一浏览器打开链接时，可能需要再次登录。

训练/评测提交和图表文件读取需要项目所有者账号。按钮不可用时，先确认登录身份、输入是否完整，以及页面是否已取得 GPU 数据。

| 顶部页面 | 在这里做什么 |
|---|---|
| Scene workspace | 查看实验室和机器人，修改房间初始位姿、颜色，保存版本与同步草稿 |
| Data & training | 查看训练进度，选数据和配比，创建训练，查看自动评测，提交/查看 MSE 与 VLA |
| Run history | 查看当前账号的任务回执、状态、时间和服务器产物目录 |

**Data & training** 页面从上到下依次是：

1. **Current training**：当前训练监控。
2. **After training**：训练后的自动 VLA/MSE 及结果。
3. **Data & recipe / Evaluation & MSE / Job queue**：配方、手动评测、任务队列。

浏览器较窄时内容会纵向排列，报告可能需要继续向下滚动。较宽的数值表格可横向滚动。

## 3. 编辑实验室与机器人场景

### 用左侧面板修改

1. 打开 **Scene workspace**。
2. 在 **Rooms** 选择 `00–31` 中的一个房间；需要批量修改时勾选 **Apply to all rooms**。
3. 在 **Object** 选择 **R1 Pro robot** 或 **Tray**。
4. 在 **Transform** 修改位置与朝向。位置字段单位为米 `m`，`Yaw` 单位为度 `°`。
5. 用 **Shell color / Tray color** 调整颜色，或点击 **Restore original colors** 恢复机器人和托盘原材质配色。
6. 手工编辑后点击 **Save version** 保存。`Unsaved changes` 表示仍有未保存的手工修改。

机器人面板修改底盘平面位置与朝向；托盘面板还包含 Z 高度。这里不提供机器人关节角度控制。默认实验室背景、黑银机器人、酒红托盘及原标识来自场景资源；颜色编辑作用于可编辑外观部分。

视图操作：拖动旋转、滚轮缩放、右键拖动平移。工具栏的 **Fit view** 重置取景，**Toggle grid** 开关网格，**Undo / Redo** 撤销或恢复手工编辑。

### 用 Scene Agent 对话修改

先选择房间，在右侧输入框发送一条明确指令。例如：

```text
Make the tray blue
Move the robot left 10 cm
Rotate the robot 15 degrees
Set robot yaw to 0 degrees
Room 3, make the tray #A15E6D
Make the tray blue in all rooms
Restore original colors
What is the training progress?
```

`left / right / forward / back` 以当前房间机器人的朝向为参照；`Rotate` 为相对转动，`yaw to` 为绝对朝向。未指定房间时使用当前选择。可以使用明确的中文指令，但上述英文例子与界面提示一致。

界面显示 **Basic commands** 时，使用的是明确指令解析。任意复杂对话需配置 GPT API；以页面模式标签为准。询问训练进度只查询状态，不会创建训练任务。

发送对话前，页面会先保存已有手工修改；成功的场景对话编辑会创建新版本。纯查询不会改变场景。修改完成后检查预览和版本号。

### 保存、导出与同步

| 操作 | 实际效果 |
|---|---|
| Save version | 保存网页场景版本 |
| Export | 下载当前编辑状态的场景 JSON；包含位姿/颜色和来源引用，不是 USD 场景包或训练数据 |
| Version history → Restore | 从历史状态创建一个新版本，保留旧历史；有未保存修改时先保存 |
| Sync to GPU | 先保存当前编辑，再提交 GPU 场景草稿；在 Run history 查看回执 |

**草稿同步成功不表示物理仿真已经执行或通过。** 当前同步不会修改正在运行的仿真/训练输入；原生颜色适配和物理预检仍需独立验证。网页中改出的场景也不会自动变成可训练数据集。

## 4. 配置并创建训练

入口：**Data & training → Data & recipe**。

1. 在 **Registered datasets** 勾选需要的数据集。
2. 在 **New training job** 调整 **Real / simulation sampling mix**。
3. 设置 **Training steps**。
4. 保留或取消 **Automatically evaluate the final checkpoint**。
5. 可先点击 **Save recipe** 记录计划，再点击 **Create training job** 正式提交。
6. 在 **Job queue** 查看新任务的回执、阶段和进度。

| 设置 | 含义 |
|---|---|
| Real 50% / Sim 50% | 训练采样的域比例；不是磁盘文件数量比例 |
| Real 0% | 只使用已选择的仿真来源 |
| Real 100% | 只使用真机数据 |
| Training steps | 实际梯度更新目标，支持 1–100,000 的整数 |
| Save recipe | 保存训练配置，尚未开始训练 |
| Create training job | 创建独立任务，等待服务器检查数据与 GPU 资源 |

配比支持 0–100% 整数。Real 大于 0 时必须选择 **Real Pick / Place**；Sim 大于 0 时必须至少选择一个已登记的仿真数据集。比例为 0 的域不会参与训练或归一化。

当前数据卡包括 **Real Pick / Place**、**Isaac · new 300 pairs**、**Isaac · narrow distribution**、**Isaac · wide distribution**。以网页实际登记项为准；网页暂不提供任意本地文件夹上传训练。真机 Train/Val/Test 和仿真父场景 split 保持原划分，只从 Train 采样。

每次点击 **Create training job** 都是在创建独立训练任务。提交后先查看队列回执，避免为查询进度再次提交。健康任务会继续执行，新任务等待 GPU；新配置不覆盖旧检查点。

当前训练范围是固定底盘 Pick/Place 的 BC/LoRA；配比或步数调整不等于开启 RL 或 DAgger。

## 5. 查看进度与训练后的自动评测

### Current training

在 **Data & training** 顶部查看：

- 实际已完成步数 / 总步数、百分比。
- **Remaining training**：剩余梯度计算时间估计。
- **Next checkpoint**：下一检查点里程碑。
- **Measured throughput**、最近 loss、已保存检查点。
- **Sample**：数据采样时间。

页面通常每 10 秒刷新。ETA 只覆盖剩余梯度计算，排除初始化、保存检查点、MSE、VLA；训练心跳失效时 ETA 会暂停。loss 是训练指标，不能替代 MSE 或任务成功率。

### After training

新训练默认勾选 **Automatically evaluate the final checkpoint**。训练成功结束、目标更新数达到要求、最终检查点完整保存后，服务器自动选择该任务的最新最终检查点，登记：

1. **32-room VLA**：Isaac 内纯模型 Pick/Place 闭环诊断。
2. **Paired real Test MSE**：与已登记的纯真机 10,000 步基线进行固定 Test 比较。
3. MSE 完成后自动生成图表并发布下载文件。

已有当前训练若尚未启用，可在 **After training** 点击 **Enable for current training**。显示 **Automatic evaluation enabled** 后无需再次提交；查看其 VLA 与 MSE 子项状态即可。

这些任务在 GPU 服务器持久运行，关闭网页后仍会继续。GPU 忙碌时先排队；训练完成不会立即等于评测结果就绪。

## 6. 手动提交 MSE 或 VLA

### MSE：选择已有检查点比较

入口：**Data & training → Evaluation & MSE → Fixed real-data MSE comparison**。

1. 选择 **Test · 19 real episodes** 或 **Val · 13 real episodes**。
2. 勾选 1–4 个完整保存、已登记的检查点。
3. 点击 **Run paired MSE**。
4. 在同页下方或 **Job queue** 查看状态，完成后查看误差表和图表。

比较使用同一 split 的全部观测帧、相同噪声和有效目标掩码。H20 指每次预测 20 帧动作；尾部 padding 和底盘通道不计入评分。

关节 MSE 用 **rad²**，夹爪 MSE 用 **mm²**，二者分开看。MSE/RMSE 通常越低越好；自动报告的 `Δ vs baseline` 为相对基线变化，负值表示误差下降。比较时同时核对模型名称、训练步数、数据配比和 split，不能将 100 步检查点的报告当成 10,000 步结果，也不能仅凭 MSE 宣称真机任务成功。

### VLA：Isaac 内纯模型闭环

入口：**Data & training → Evaluation & MSE → Isaac VLA closed loop**。

1. 在 **Model checkpoint** 选择一个检查点。
2. 在 **Room selection** 选择房间。
3. 设置 **Frame budget per action**，默认 200 帧；20 Hz 下相当于每动作 10 秒仿真时间，不是整个评测的墙钟耗时。
4. 点击 **Create VLA evaluation**，到 **Job queue** 查看进度与结果。

手动预算支持每动作 20–1200 帧。评测使用模型输出控制手臂和夹爪，底盘有显式固定掩码，无教师、IK 或自动纠正回退。当前 32 房间共享训练父场景，因此结果属于训练场景闭环诊断，不是未见场景泛化率，也不是真机执行。

自动评测结果的指标定义：

| 指标 | 如何理解 |
|---|---|
| Pick / Place success rate | `passed / (passed + model failures)`，同时显示实际分子与分母 |
| Model failures | 已形成模型结果，但物理任务未通过 |
| Infrastructure failures | 引擎/服务等基础设施未完成评测，单列且排除出模型成功率分母 |
| Evaluation coverage | 已得到模型结果的房间数 / 请求房间数 |
| Not measured | 尚无可计入成功率的模型结果，不代表 0% |

## 7. 常见状态与问题

| 显示 / 问题 | 解释与操作 |
|---|---|
| Awaiting GPU receipt / Received by GPU | 请求已提交或已接收，等待服务器继续处理 |
| Waiting for final checkpoint | 自动评测正在等待完整的最终训练检查点 |
| Waiting for GPU | 任务排队；查看已有任务和采样时间，无需重新创建任务 |
| Model initialization / Validating data | 正在初始化或校验，尚不能称为实际梯度训练 |
| Finished / completed | 流程已结束；继续读 MSE、成功数、失败原因，不能只看这个标签判断模型效果 |
| Failed / Needs attention | 查看消息、任务 ID 和产物目录；失败记录会保留 |
| GPU snapshot / Awaiting trainer update | 当前显示最后一次数据，检查采样时间和连接；不表示服务器进程一定已停止 |
| No measured result yet. | 该项评测还没有可展示的实测报告 |
| 图表是 Rendering / Uploading | 指标可能已完成，图表生成或传输仍在进行；等待 Ready |
| Figure export needs attention | 出图或上传失败；已有 MSE 指标仍可读取 |
| 找不到 MSE 图 | 确认已进入 Data & training 的 Evaluation & MSE 标签，并继续滚到已完成报告下方，见第 1 节 |
| 图中文字太小 | 点击图片打开原分辨率，或使用 Download PNG |
| 图表链接无权限 | 在当前浏览器登录项目所有者账号后，从网站重新打开 |
| 看不到别的账号提交的手动任务 | Run history / Job queue 展示当前账号任务；确认使用提交任务时的账号 |
| 场景同步后训练数据没变化 | Sync to GPU 只同步草稿；训练仍使用已登记且通过来源校验的数据集 |
| Scene changed… | 场景版本冲突；先导出需要保留的编辑，再刷新读取最新版本 |
| Save version 灰色 | 通常表示没有未保存修改、尚未登录或请求正在处理 |
| 顶部 v5 与网站发布版本不同 | 顶部 vN 是当前场景的保存版本，不是网站部署版本 |

当前页面没有通用的任务取消/终止按钮。排障时记录任务 ID、采样时间、检查点名称和错误信息，交由项目维护者核对服务器实际进程。

## 8. 操作路径速查与进一步阅读

| 目的 | 路径 |
|---|---|
| 看 MSE 图 | Data & training → Evaluation & MSE → 已完成的 Real TEST/VAL MSE → Figure |
| 下载所有图 | 同上 → Download all figures (ZIP) |
| 看最新训练的自动结果 | Data & training → After training |
| 新建配比训练 | Data & training → Data & recipe → New training job |
| 查看新任务进度 | Data & training → Job queue |
| 看提交回执 | Run history |
| 修改场景 | Scene workspace → Rooms / Object / Transform 或 Scene Agent |
| 恢复场景版本 | Version history → Restore |

- [实现与部署说明](../../apps/scene-agent/PROJECT.md)
- [统一任务规范](../SCENE_TASK_SPEC.md)
- [数据目录](../project/DATA_CATALOG.md)
- [实验状态与证据入口](../project/EXPERIMENT_STATUS.md)
- [英文网站与图表交付核验](../../runs/web_english_autoeval_20261019_v1/verification.json)

维护说明：本手册按当前页面和代码核对，文档更新不触发训练或修改场景。截图只作操作示例，运行结果以对应时间戳与原始报告为准。


## 2026-10-19 离线版与 ROS 2 更新

- 顶部 **Help** 随时查看说明；**Data & training → Evaluation & MSE** 查看 MSE 数值、逐关节曲线和 VLA 结果。结构化错误现在可读，不再使整个页面崩溃。
- **Reset selected** 恢复选中房间全部初始参数；**Reset all 32** 恢复全部房间，重置可撤销。
- 离线服务：http://100.104.0.108:9080，无需 ChatGPT 登录。源码与启动命令见 [WORKSTATION.md](WORKSTATION.md)。
- 批次表区分计划房间、通过来源对、冻结训练来源对、动作片段和未入训练溢出数。32 是每批计划数量，不代表全部通过或全部入训练。
- 离线版 **Model checkpoint paths** 可输入 π0.5、Galaxea AI G0.5、NVIDIA GR00T 路径。注册仅代表配置登记，不等于加载或任务通过。
- G0.5 当前指定 last.pt；夹爪 100 = 100% = 80 mm 全开。30 Hz 训练 / 20 Hz 诊断，非等时序公平比较。GR00T 尚需兼容关节动作检查点与映射。
- ROS 2 仿真专用 domain 86，/r1pro_sim/ 命名空间，图像、关节状态与动作通过请求 ID 关联，无教师、IK 或自动纠正回退。诊断不自动入训练。
