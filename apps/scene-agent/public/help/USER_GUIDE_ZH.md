# Scene Studio 从场景到训练和评估的完整操作手册

## 当前控件更新（2026-10-21）

单策略默认10000秒有限上限；总墙钟保护默认0表示关闭，初始化/推理超时和任务物理门仍有效。Stop policy提交停止请求，cancelled才表示已结束。仿真/渲染GPU与模型推理GPU可分别选择，训练页面可选一张或两张GPU。realtime为CPU PhysX+GPU渲染，baseline为GPU PhysX；两者都是NVIDIA Isaac Sim，Three.js只负责网页视图。

Joint interpolation filter对全部模型强制启用，四项软限制可在登记上界内调整并冻结到新run。下文旧Strict/可选裁剪表仅为历史行为，不能用于关闭当前filter。Errors & diagnostics显示浏览器/API/作业错误；所选运行可展开完整结构化堆栈、日志尾部与全日志错误摘录，结束后下载完整脱敏diagnostics.zip。超过上传上限的文件留工作站并显式报错。


适合第一次使用网站、不了解机器学习术语的读者。说明日期：2026-10-19（新加坡时间）。按钮保留网页英文，解释使用中文。

**最重要的一点：网页编辑的是场景初始配置。训练需要机器人实际执行后、通过检查的数据。保存场景、同步场景、开始评估，都不会自动把新数据加入训练集。**

本手册以项目当前网页源码和任务规范为依据。工作站版与云端版可能有发布差异，以页面实际出现的控件为准；这里不承诺服务器此刻在线。文档操作本身不启动采集、训练或评估。

## 阅读路线

- 第一次使用：先读第 1–3 节，理解页面与术语。
- 想修改或生成场景：读第 4 节。
- 想把新场景用于训练：读第 5–6 节，尤其是维护者交接部分。
- 已经有数据，想训练模型：读第 7–8 节。
- 想选模型和场景看机器人表现：读第 9–10 节。
- 想看预测误差、曲线和下载：读第 11–12 节。
- 出现报错或找不到结果：读第 13–14 节。

## 1. 先理解整条流程

把场景理解为“考场布置”，把采集数据理解为“带标准示范的练习题”，把模型理解为“学习后的机器人控制策略”。

```text
网页编辑房间初始位置、朝向、颜色
    ↓ Save version：保存网页版本
    ↓ Sync to GPU：发送场景草稿
服务器收到草稿（draft_synced）
    ↓ 下面这段需要维护者接入采集流程，当前没有一键网页按钮
场景适配与可达性预检 → 原生物理执行 Pick → Place
    ↓ 检查成功条件、原始视频、轨迹、来源及退出记录
合格完整来源对 → 分成 Pick 和 Place 两段 → 冻结数据清单
    ↓ 登记新数据集版本，并接入网页可选列表
Registered datasets 中可以选择该数据集
    ↓ Create training job
排队 → 数据校验 → 模型初始化 → 实际梯度训练 → 保存检查点
    ↓ 选择已完整保存的检查点
MSE 离线比较 / 单房间策略评估 / 多房间闭环评估
    ↓
查看数值、停止原因、视频和报告
```

**也可以直接使用已经登记的数据集，从第 7 节开始。** 不需要先编辑场景，更不需要重新生成已有的 300 对来源。

### 哪些操作现在可以直接在网页做

| 想做的事 | 当前入口或限制 |
|---|---|
| 修改现有 32 个房间的初态 | Scene workspace |
| 保存、恢复版本、导出场景 JSON | Save version / Version history / Export |
| 把草稿发送给 GPU 服务器 | Sync to GPU；只到草稿阶段 |
| 从任意新草稿一键采集并加入训练集 | 当前没有此网页入口，按第 5 节交给维护者 |
| 用已登记数据创建 π0.5 训练 | Data & training → Data & recipe |
| 查看批次来源、合格数、实际入训练数 | 32-room batch lineage |
| 选择一个房间和检查点，实时观察执行 | Policy evaluation |
| 选择多个房间评估 Pick/Place | Evaluation & MSE → Isaac VLA closed loop |
| 比较模型预测与真机示范动作 | Fixed real-data MSE comparison |
| 任意输入新任务、只测 Flush、训练 G0.5 或 GR00T | 当前训练/评估表单没有这些能力；模型路径登记不是训练入口 |

## 2. 打开网站并找到正确页面

### 2.1 两种网站入口

| 入口 | 使用方法 |
|---|---|
| [工作站网站](http://100.104.0.108:9080/) | 电脑需要能访问工作站所在网络。页面显示 Offline workstation · No sign-in 时，无需 ChatGPT 登录 |
| [云端 Scene Studio](https://r1pro-scene-agent-haoze.exactmyna128.chatgpt.site/) | 按提示 Sign in。GPU 作业提交和相关文件读取需要项目所有者身份 |

“离线版”表示网站服务运行在工作站，不表示服务器关机时还能使用。网页能打开，也不一定表示 GPU 后台已连接。

打开后先做三件事：

1. 看页面是否已加载房间和数据。
2. 看连接状态和 `Server sample` / `Sample` 时间；旧时间是最后快照。
3. 进入 `Run history`，确认自己要跟踪的任务是否已有回执。查看进度不需要再提交一次任务。

### 2.2 顶部五个页面

| 按钮 | 中文理解 | 最常见用途 |
|---|---|---|
| Scene workspace | 场景编辑台 | 改机器人/托盘初始位置，保存场景 |
| Policy evaluation | 单模型单房间评估 | 看本次实际执行、相机和本次视频 |
| Data & training | 数据与训练 | 选数据、训练、MSE、多房间评估 |
| Run history | 操作回执 | 查任务 ID、状态、时间、服务器产物目录 |
| Help | 帮助 | 查看网站内说明与已有下载入口 |

`Data & training` 页面很长。顶部先是下载区、`Current training`、`After training`，再往下才是 `Data & recipe / Evaluation & MSE / Job queue` 三个标签。找不到表单时先向下滚动。

## 3. 几个必须分清的名词

| 名词 | 用普通话解释 | 容易看错的地方 |
|---|---|---|
| Room / 房间 | 一个登记的场景实例及其初态 | 32 个房间不等于 32 个成功数据 |
| Draft / 草稿 | 尚未转成合格物理数据的场景配置 | 3D 预览漂亮不等于机器人能抓到 |
| Pair / 完整来源对 | 同一次真实仿真连续完成 Pick 和 Place 的合格来源 | 1 对通常导出 2 个动作片段 |
| Segment / 动作片段 | 一段 Pick 或一段 Place 的图像和动作记录 | 600 段不等于 600 对 |
| Episode | 一次记录/执行的序列 | 真机 episode 不一定是一整对 Pick/Place |
| Dataset / 数据集 | 已登记的一组来源、片段及清单 | 不是随便选一个视频文件夹 |
| Train / Val / Test | 学习用 / 开发验证用 / 最终测试用 | Val、Test 不拿回去训练 |
| Step / 更新步 | 模型参数真正更新一次 | 不是相机一帧，也不是一个房间 |
| Checkpoint / 检查点 | 某个训练阶段保存下来的模型及所需信息 | 路径登记成功不等于模型加载成功 |
| Loss | 训练时模型拟合数据的指标 | 不是任务成功率，也不是测试 MSE |
| MSE / RMSE | 预测动作与示范动作之间的误差 | 误差小不保证真实抓放成功 |
| Closed loop / 闭环 | 模型看当前图像，给动作，执行后再看新图像 | 与只对固定数据算误差不同 |
| Simulation time | 模拟器内机器人实际推进的时间 | 10 秒仿真可能花更长现实时间 |
| Wall time | 人在钟表上等了多久 | 包含加载、推理等待等耗时 |

## 4. 生成和修改一个场景草稿

### 4.1 选房间，再选物体

1. 点击 `Scene workspace`。
2. 在左侧 `Rooms` 点 `00`。这是后续评估页的 `Room 000`；`03` 对应 `Room 003`。
3. 首次练习不要勾选 `Apply to all rooms`，避免一次改动全部 32 个房间。
4. 在 `Object` 选择 `R1 Pro robot` 或 `Tray`。
5. 检查中间 3D 视图上方房间名，确认正在编辑正确的房间。

这里是在已登记的 32 个房间上编辑初态，不提供无限新增房间、任意导入 CAD 或调整桌子尺寸的按钮。

### 4.2 修改位置和角度

`Transform` 下的坐标是**绝对值**。例如，把 X 从 `0.30` 改为 `0.31`，表示沿 X 增加 1 厘米；直接填 `0.01` 则是把 X 设成 1 厘米处。

| 选择物体 | 可改字段 | 单位 |
|---|---|---|
| R1 Pro robot | X、Y、Yaw | X/Y 为米，Yaw 为度 |
| Tray | X、Y、Z、Yaw | X/Y/Z 为米，Yaw 为度 |

换算：`0.01 m = 1 cm`，`0.10 m = 10 cm`。Yaw 是水平方向转角，不是抬手角度。网页不提供机器人每个关节的角度编辑。

数字字段沿场景坐标轴变化；聊天中的 left/right 则沿当前机器人朝向解释。机器人旋转后，这两种移动方向可能不同。

**练习建议：先只改颜色，再尝试小幅位置变化并保存新版本。** 可输入数值不代表通过可达性、碰撞和任务检查；不要把预览里的可见位置当成合格抓取位。

### 4.3 修改颜色和观察视角

1. 选择机器人后用 `Shell color`，选择托盘后用 `Tray color`。
2. 点击色块或输入颜色选择器中的颜色。
3. 要恢复默认配色，点 `Restore original colors`；当前实现会恢复选中房间的机器人和托盘颜色。
4. 拖动旋转视角，滚轮缩放，右键拖动平移。
5. 找不到机器人时点工具栏 `Fit view`；鼠标停在图标上可辨认按钮名称。

`Toggle grid` 只切换辅助网格。调整观察角度不会改变机器人实际初态。网页材质预览和 Isaac 原生相机渲染有差异。

### 4.4 用右侧 Scene Agent 输入指令

先选择房间，再逐条输入。例如：

```text
Make the tray blue
Move the robot left 1 cm
Rotate the robot 5 degrees
Set robot yaw to 0 degrees
Make the tray blue in all rooms
Restore original colors
What is the training progress?
```

每次发送后检查房间、字段和预览。`Rotate` 是在原角度上加转角，`yaw to` 是设置绝对角度。未写 all rooms 时以当前选择为准。

页面显示 `Basic commands` 时只支持明确的基础指令解析，不要依赖一段复杂自然语言自动完成采集和训练。查询进度不会创建训练任务。发送聊天前会先保存未保存的手工编辑；成功的场景编辑会建立新版本。

### 4.5 保存、导出、恢复

| 你做什么 | 应该看到什么 | 得到什么 |
|---|---|---|
| 点击 Save version | `Version vN · Saved`，版本号更新 | 网页保存版本 |
| 点击 Export | 浏览器下载 JSON | 当前位姿、颜色、来源引用；不是视频或训练包 |
| 打开 Version history → Restore | 恢复后生成新版本 | 历史状态被复制成新版本，旧历史保留 |
| 点击 Reset selected rooms | 选中房间恢复原始初态与颜色 | 尚需 Save version 才保存 |
| 点击 Reset all 32 rooms | 每个房间恢复各自基线 | 全部房间重置，仍需保存 |

恢复历史前需要先保存未保存修改。Reset 之后可以用 Undo 撤销；Fit view 只改取景，不等于 Reset。顶部 `vN` 是场景版本，不是网站程序版本，也不是训练检查点。

### 4.6 同步到 GPU

1. 确认房间和版本无误。
2. 点击 `Sync to GPU`；网站会先保存当前编辑。
3. 切换 `Run history`。
4. 找到 `Sync scene draft` 回执，记录任务 ID、时间和产物目录。
5. 等待收到 `draft_synced` 或相应成功消息。

**到这里完成的是“服务器收到了场景草稿”。还没有执行机器人动作，也没有产生新的合格训练片段。** 服务器产物可包含 `native_config.draft.json` 和视觉颜色侧文件；修改后的物理预检需要重新做，颜色也需原生适配验证。

## 5. 新场景究竟怎样进入训练集

### 5.1 普通用户做到哪里

当前网站没有 `Generate dataset`、`Add scene to training` 这样的端到端按钮。保存新版本后，`Registered datasets` 不会自动增加一个数据集；评估该房间也不会自动把评估视频变成训练数据。

完成第 4 节后，把下面信息交给维护者即可，避免只说“把刚才那个场景拿去训练”：

```text
用途：将新场景采集成固定底盘 Pick/Place 数据。
网站入口：工作站版 / 云端版。
场景版本：v____。
房间编号：____。
修改内容：机器人/托盘位置、朝向、颜色的具体变化。
场景 JSON：已通过 Export 保存。
同步任务 ID：____。
同步回执：draft_synced / 尚未收到。
服务器草稿产物目录：____。
目标：新建独立数据集版本，保留已有数据和训练输入。
```

### 5.2 维护者实际要完成的七步

这部分解释服务器环节，不是网站隐藏按钮。配置和启动参数应来自已审阅的采集方案，不应把历史运行命令原样重启。

| 步骤 | 做什么 | 完成时应有的证据 |
|---|---|---|
| 1. 绑定初态 | 把草稿转换为该采集器接受的配置，登记父场景、split、版本 | 新配置、来源关系、初态记录 |
| 2. 预检 | 验证桌前站位、固定底盘和双臂整段可达性 | 预检报告；预检通过仍不是物理成功 |
| 3. 原生采集 | 实际执行 Pick，再从真实持盘末态连续执行 Place | 实际退出收据、物理结果、状态/控制轨迹、原生视频 |
| 4. 资格审核 | 核两长边接触、抬升/放置/释放/支撑、固定底盘、视频帧与轨迹对齐 | 独立资格报告，失败保留 |
| 5. 导出片段 | 分出 Pick 和 Place，绑定精确任务文本、相机、动作和时间窗 | 两段数据及其来源清单；准备录像另存 |
| 6. 冻结与缓存 | 只选择合格完整对，保留父 split，冻结 manifest 和 SHA，构建模型输入缓存 | 新版本清单、缓存与原始来源一致性证明 |
| 7. 登记并发布选择项 | 更新新 release 中的服务器登记、网站允许的数据集 ID 和显示信息 | 网页可选择新 ID；准备阶段能成功校验冻结输入 |

**第 7 步不能只在服务器放一个文件夹。** 当前网站的数据集 ID 有明确允许列表；后台登记、前端选择合同和快照需要配套接入。不能把新数据偷偷写到旧 `isaac300_20261017` 清单里。

维护者可从这些现有入口继续核对实现：

- [固定底盘采集入口](../../scripts/collect_isaac_fixed_pickplace.py)。
- [32 房间原生执行](../../scripts/run_isaac_parallel_pickplace.py)与[分片导出](../../scripts/export_isaac_parallel_pickplace.py)。
- [300 对生产监督入口](../../scripts/supervise_isaac_pickplace300.py)。
- [训练输入准备](../../scripts/studio_prepare_training.py)。
- [服务器数据登记](../../apps/scene-agent/gpu/dataset_registry.json)、[网站数据 ID 合同](../../apps/scene-agent/lib/core.ts)、[训练合同](../../apps/scene-agent/lib/training.ts)。

新动作流程、抓法、底盘范围或训练方案的取舍需按项目规则确认；普通故障可在保留失败证据后修复。完整验收条件见[统一任务规范](../SCENE_TASK_SPEC.md)，不能为了增加合格数自行放宽。

### 5.3 什么数据不能直接加入

未执行的草稿、仅通过预检的场景、失败来源、视频/轨迹未闭合的来源，以及诊断评估输出，都不能直接当合格训练数据。Place 必须有对应真实起点，不能把托盘摆到空中冒充前一段 Pick 的结果。

固定底盘网页分支的任务文本是 `Pick up the tray` 和 `Place the tray`。项目另有 `Flush tray to the left`，但不能把这套两动作数据称为包含 Flush 的完整三动作数据。

## 6. 查看数据集数量、来源和结构

### 6.1 先看每批到底有多少进入训练

路径：`Data & training → Data & recipe → 32-room batch lineage`。

| 列名 | 怎么读 |
|---|---|
| Batch | 采集批次；展开可看服务器来源目录 |
| Dataset / version | 这批归属哪个数据集版本 |
| Split | Train、Val 或 Test 的来源划分 |
| Requested rooms | 计划执行的房间数 |
| Qualified pairs | 经过审核的完整 Pick/Place 对数 |
| In training | 已被该冻结训练清单选中的对数 |
| Action segments | 对应动作片段数 |
| Qualified overflow | 已合格但未纳入这次冻结训练的余量 |

展开 `Frozen source evidence` 可以查看冻结清单路径和 SHA256。SHA256 可以理解为文件内容指纹，用来确认是不是同一份清单。

一个历史实测例子：2026-10-19 已记录的生产数据有 **313 对合格来源**，其中 **300 对冻结入训练 = 600 个动作片段**，另外 **13 对未进入该次训练**。它们是特定版本的数字，实时数量看页面清单，不能把 313 直接写成训练数。

### 6.2 再看 Registered datasets

卡片显示 REAL/SIM、数量和 Train/Val/Test。当前登记项包括：

| 显示名称 | ID | 含义 |
|---|---|---|
| Real Pick / Place | real_pickplace_v2 | 用户真机示范；134 episodes，Train 102 / Val 13 / Test 19 |
| Isaac · new 300 pairs | isaac300_20261017 | 新冻结 300 对，600 段，仿真 Train |
| Isaac · narrow distribution | isaac32_narrow_20261016 | 历史较窄分布，登记 30 对 |
| Isaac · wide distribution | isaac32_wide_20261016 | 历史较宽分布，登记 29 对 |

以上数量来自当前登记与历史核验，不代表新的采集正在运行。不要把真机 134 episodes 与仿真 300 pairs 直接当成同一种计数相加。旧 30+29 对也不能冒充新 300 对。

### 6.3 数据文件在逻辑上长什么样

下面是**关系示意，不是保证每个 run 都有相同目录名**。准确路径从 Batch、Frozen source evidence 或任务产物目录读取。

```text
父场景 parent_scene_id + split
└─ 某次采集批次 batch
   ├─ 房间初态、配置、随机种子、来源版本
   ├─ 原生执行记录：结果、事件、实际退出码
   ├─ 原始相机视频、状态与控制轨迹
   └─ 合格完整 Pick/Place 对
      ├─ Pick 片段：图像 + 状态 + 动作 + 任务文本
      └─ Place 片段：图像 + 状态 + 动作 + 任务文本
            ↓ 冻结选择
数据集 manifest + 内容指纹
            ↓ 对齐与缓存
训练输入缓存 + 仅由 Train 计算的归一化信息
            ↓ 独立训练任务
配方 + 进度/日志 + 模型检查点 + 评估报告
```

视频文件数可能更多，因为一个片段有多个相机。展示视角也不等于模型输入视角。模型策略读取的原生图像包括头部、左腕、右腕；网页单次评估还展示 overview。模型状态/动作合同为 19 通道，包含双臂、夹爪和底盘，具体绑定由检查点协议决定。

网站目前提供来源表和路径，不是通用文件管理器，也没有逐层神经网络结构浏览器。想看模型内部网络/LoRA 层配置，需要维护者读取该检查点的配置；不能用数据结构图代替模型网络结构。

## 7. 用现有训练集训练模型

### 7.1 一套可以照着填的示例

以下是界面填写示例，**不是保证效果最好的配方**：使用真机与新 300 对仿真数据，Real 50% / Sim 50%，10,000 步。

1. 打开 `Data & training`，向下点 `Data & recipe`。
2. 在 `Registered datasets` 中选中 `Real Pick / Place` 和 `Isaac · new 300 pairs`。
3. 如果历史 narrow/wide 卡片也被选中，且本次不打算使用，点击取消它们。
4. 在右侧 `New training job` 找到 `Real / simulation sampling mix`。
5. 点击 `50%` 预设，核对上方写着 `Real 50%`、`Sim 50%`。
6. 在 `Training steps` 输入 `10000`。
7. 按需求保留 `Automatically evaluate the final checkpoint`。
8. 可先点 `Save recipe` 查看保存的比例、步数与有效数据集数。
9. 确认无误后，点一次 `Create training job`。
10. 切换 `Job queue`，找到本次比例/步数及对应 ID 的任务。

**成功提交的标志是出现独立任务和队列回执。真正开始训练的标志是实际更新步数增长。** 如果只点 Save recipe，模型还没有开始学习。

### 7.2 配比怎么理解

| 设置 | 所需数据 | 实际含义 |
|---|---|---|
| Real 0% / Sim 100% | 至少一个仿真集 | 只从仿真训练来源采样 |
| Real 10% / Sim 90% | 真机集和仿真集 | 训练采样以仿真为主 |
| Real 50% / Sim 50% | 真机集和仿真集 | 两个来源域的采样比例各半 |
| Real 90% / Sim 10% | 真机集和仿真集 | 训练采样以真机为主 |
| Real 100% / Sim 0% | 真机集 | 只从真机 Train 采样 |

预设按钮的百分数指 **Real 比例**。滑块支持 0–100 的整数，不要求只用上述五个预设。这个比例是采样规则，不是把磁盘上两类文件数量改成一样多，也不是保证每一个小批次恰好同样比例。

某域比例为 0 时，即使其卡片仍选中，也不参与该训练的采样和归一化。真机比例大于 0 却没选真机集，或仿真比例大于 0 却没选仿真集，都会被拒绝。

### 7.3 其他字段说明

| 字段 | 含义 |
|---|---|
| Training steps | 目标实际更新次数，1–100000 整数；步数不是秒数 |
| π0.5 · LoRA | 当前网页创建的训练类型；不是通用模型家族选择器 |
| Batch / horizon 8 / 20 | 每批训练样本数与动作预测窗口，当前是显示项 |
| Action balanced · duration weighted | 域内按动作平衡、结合时长的采样规则 |
| Warmup | 初期学习率预热步数，由步数配置计算 |
| Registered parent · new optimizer | 从登记父权重初始化，使用新的优化器状态 |

创建新任务不会修改正在训练的任务。它也不是对当前模型直接“再加几步”的按钮。关闭浏览器后，已经在服务器接收并运行的后台任务可以继续；是否健康仍应看实际心跳和进度。

## 8. 查看训练进度，判断走到哪一步

### 8.1 先找对任务

`Current training` 是后台当前登记训练的总览，不要仅因为它显示 100% 就认为你刚创建的任务完成了。**自己新建的训练必须在 Job queue 按任务 ID、比例、目标步数核对。**

`Run history` 可查看跨类型回执；`Job queue` 主要列独立训练、MSE 和批量 VLA。单房间实时评估在 `Policy evaluation → Previous runs` 查看。

### 8.2 训练状态依次意味着什么

| 状态 | 到了哪一步 | 此时该怎么做 |
|---|---|---|
| Plan saved / planned | 配方已保存 | 想执行仍需 Create training job |
| Awaiting GPU receipt / queued | 网站已接收请求，等待 GPU 回执 | 留住 ID，先等回执 |
| Received by GPU / claimed | 后台已接收 | 继续看阶段 |
| Waiting for GPU / waiting_gpu | 资源或任务锁未释放 | 不要重复提交 |
| Validating data / preparing | 校验来源和准备输入 | 尚不是梯度训练 |
| Model initialization / initializing | 加载模型、编译或初始化 | 更新数可能仍为 0 |
| Gradient training / training | 模型在更新 | 看实际步数是否持续增加 |
| Saving checkpoint | 正在保存模型 | 等保存闭合，不拿半成品评估 |
| Checkpoint saved | 某个阶段的模型已保存 | 不一定已经达到目标总步数 |
| Finished / completed | 该流程结束 | 读实际更新、最终检查点、退出报告和后续评估 |
| Failed / blocked | 失败或需要处理 | 保存错误、ID 和产物目录，交给维护者 |

### 8.3 进度卡片逐项看

- `steps`：实际完成更新 / 目标更新，百分比来自这里。
- `Remaining training`：剩余梯度计算估计，通常给一个范围。
- `Next checkpoint`：下一个保存里程碑及其预计剩余时间。
- `Measured throughput`：实测每步耗时；不是保证以后每一步相同。
- `Saved`：已保存的更新里程碑。
- `Training loss · recent samples`：近期训练 loss 曲线，不是完整测试曲线。
- `Sample` / `Server sample`：采样时间，判断是不是旧数据。

通常约每 10 秒刷新训练状态。ETA 不包含初始化、保存模型、后续 MSE 和闭环评估，所以“剩余 0 秒训练”不等于“所有评估已完成”。心跳过期会暂停 ETA，保留最后数据；这不能证明远端进程已经停止。

### 8.4 自动评估

勾选自动评估后，要等实际目标更新完成、训练成功退出、最终检查点保存完整，才登记后续评估。到 `After training` 查看：

1. `32-room VLA`：登记场景上的 Pick/Place 闭环诊断。
2. `Paired real Test MSE`：与登记的纯真机 10000 步基线比较。
3. MSE 出图和下载文件发布状态。

已有当前训练可通过 `Enable for current training` 启用自动评估。它针对当前登记训练，不要把它当作任意历史模型的评估入口。历史模型使用手动表单。

## 9. 选择一个场景和模型，观察本次实际执行

### 9.1 单房间策略评估操作

1. 点击顶部 `Policy evaluation`。
2. 在 `New independent run → Room` 选择 `Room 000–031` 中一个。
3. 在 `Model checkpoint` 选择已完整保存的检查点；核对名称、训练来源和步数。
4. 在 `Action handling` 明确选择下面解释的处理模式。
5. 设置 `Maximum simulation duration (seconds)`，例如 `10`。
6. 通常先保留高级时间限制；确实需要时再展开 `Advanced time limits`。
7. 点击一次 `Start policy evaluation`。
8. 等待 Queued、Initializing，再观察实际帧和相机。

**这里选择登记房间的初始状态，不读取你刚在 Scene workspace 修改的草稿。** 两处选到同一个编号，也不能据此认为新草稿已经用于本次评估。新初态需要完成适配和登记流程。

### 9.2 任务如何选择

当前界面固定按 **Pick → Place** 连续执行，底盘固定；没有独立的任务文本下拉框。Place 从本次 Pick 的真实持盘状态继续，不是单独随机生成一个空中托盘。

因此当前可以选择“在哪个登记房间、用哪个模型、跑多久”，不能从此页面直接选择“只测 Flush”“任意新指令”或“只测 Place 的任意起点”。

### 9.3 Action handling 三个选项

| 选项 | 实际行为 | 结果怎么用 |
|---|---|---|
| Robot limits · bounded joints, speed and tracking guard | 显式关节/夹爪限幅，并施加已有速度、步长与跟踪保护 | 受保护诊断，不计纯模型成功率，也不自动入训练 |
| Strict · reject out-of-range actions | 输出越机械范围就拒绝执行并停止 | 用于查看严格原始策略表现；仍是当前登记场景诊断 |
| Limit-clipped diagnostic · excluded from pure model success | 对完整有限动作作显式范围裁剪，并保留原始/应用动作 | 用于诊断后续行为，不计纯模型成功率 |

当前源码及较新的工作站版默认 `Robot limits`；旧发布可能默认 Strict。**每次提交前看实际选项，不依赖记忆。** 受保护运行会标 `PROTECTED POLICY DIAGNOSTIC`。这些模式都不应把缺失的夹爪输出自动补成完整模型动作。

### 9.4 三种时间分别控制什么

| 设置 | 范围 | 含义 |
|---|---|---|
| Maximum simulation duration | 1–10000 秒整数（默认10000） | Pick 和 Place 共用的总执行仿真时间预算 |
| Single inference timeout | 1–300 秒整数 | 一次模型请求最多等多久 |
| Overall wall-clock guard | 0–604800 秒整数（默认0：关闭整体墙钟截止） | 整次运行现实时间保护，包含模型/Isaac 初始化 |

每仿真秒为 20 个动作帧。例如 10 秒预算最多 200 帧，是两动作合计。模型等待不消耗仿真时间，物理失败/模型错误/任务完成都可能提前停止，媒体封装可能在运行结束后继续。

不要通过增大仿真时间来处理 `policy_action_outside_mechanical_joint_range`：它是模型目标越界，不是时间不够。

### 9.5 画面与结果怎么看

3D 视图绑定的是原生实测物体位姿，四路相机是 `overview`、`head_left`、`left_wrist`、`right_wrist`。3D 网页几何与原生渲染可能不同，实际外观以原生相机为准。

重点看：已执行帧数、仿真秒数、现实耗时、模型请求耗时、`Pose sample age` 和 `Stop reason`。等待推理时可能没有新物理帧；画面停住不一定是网页坏了。

出现 `Ended` 后画面是最终记录状态，不是在继续执行。达到 `simulation_time_budget_reached` 只代表预算用完，不代表 Pick/Place 成功。对受保护诊断，还要保留诊断标记，不能把过程结束或“看起来完成”写成纯模型通过。

### 9.6 下载本次视频

1. 在 `Previous runs` 选择正确的任务 ID。
2. 向下到 `This run's result & downloads`。
3. 等该次编码器闭合后，下载本次 MP4 和 JSON 报告。
4. 核对房间、检查点、任务 ID，避免把静态示例视频当本次结果。

没有执行帧时没有动作视频。原生视频通常按 20Hz 仿真时间轴播放，现实等待耗时在报告中；标有 actual wall-clock video 的文件才按该说明查看现实速度。视频播放顺滑不能证明模型在现实时间达到 20Hz。

## 10. 选择多个场景做批量闭环评估

路径：`Data & training → Evaluation & MSE → Isaac VLA closed loop`。

1. `Policy transport` 选择 `ROS 2 topics · isolated simulation`；`Native file transport · π0.5` 是另一个 π0.5 传输入口，外部模型需 ROS 2。
2. `Model checkpoint` 选一个检查点。
3. 在 `Room selection` 点击要评估的房间；选中的按钮高亮。再次点击可取消。
4. 核对标题中的 `N/32`，至少保留一个房间。
5. 设置 `Frame budget per action`，默认 `200`，允许 `20–1200`。
6. 点击 `Create VLA evaluation`。
7. 到 `Job queue` 或同页下方找到本次报告。

这里的 200 帧是**每动作** 10 秒仿真预算；它与第 9 节“两动作共享总秒数”的设置不同。不要直接拿相同数值认为预算一样。

当前 32 个房间共享训练父场景，这测的是训练场景闭环诊断，不是未见场景泛化。想测试新父场景，需要先登记真正独立的测试来源，不能只换 room 编号或把 Train 标签改成 Test。

### 10.1 成功率和覆盖率

同时记录成功数、模型失败、基础设施失败、请求房间数和覆盖率。自动摘要的模型成功率采用 `passed / (passed + model failures)`，基础设施失败单列；具体报告还可能直接显示 `passedPairs / totalRooms`，须按其标签读分母。

例如请求 10 个房间，4 成功、4 模型失败、2 基础设施失败：有模型结果的 8 个房间内成功率为 50%，覆盖率为 80%，相对全部请求是 4/10。不能只报“50%成功”而省略另外 2 个房间未测成。这个例子仅说明计算方法。

无可计入模型结果时应显示未测量，不应把模型加载失败当 0% 任务成功率。受保护诊断另外统计，不混入严格纯模型成功率。

## 11. 用 MSE 查看预测是否接近示范动作

MSE 不执行机器人动作。它把固定真机数据中的图像和状态输入模型，再把预测动作与记录的示范动作比较。

### 11.1 提交一次比较

1. 打开 `Data & training → Evaluation & MSE`。
2. 找到 `Fixed real-data MSE comparison`。
3. 在 `Evaluation split` 选 `Val · 13 real episodes` 或 `Test · 19 real episodes`。
4. 勾选 1–4 个已保存的 π0.5 检查点。想比较新旧模型就同时选它们。
5. 核对步数和来源，避免将 100 步模型误认为 10000 步模型。
6. 点 `Run paired MSE`。
7. 等待同页下方 `Real VAL MSE` 或 `Real TEST MSE` 报告。

开发调整通常先看 Val；Test 用于固定最终比较，不反复据 Test 调整训练。当前网页的这套 MSE 协议仅支持登记的 π0.5，注册 G0.5/GR00T 不会自动获得同协议 MSE 能力。

### 11.2 四个数值列怎么读

| 列 | 含义 |
|---|---|
| H20 joints rad² | 14 个手臂关节在有效 20 步预测窗口中的误差 |
| H20 grippers mm² | 左右夹爪同窗口误差 |
| First-step joints rad² | 每次预测第一步的手臂误差 |
| First-step grippers mm² | 每次预测第一步的夹爪误差 |

同协议下通常越低越好。手臂与夹爪单位不同，不能把两个数相加比较。底盘通道和尾部填充不计评分。自动摘要中的 `Δ vs baseline` 为相对基线变化，负值代表误差降低。

比较模型时保留训练步数、初始化、配比、数据版本和 split；否则无法把差异简单归因于“仿真比例”。MSE 低也可能在物理闭环中失败，需要结合第 9–10 节的结果。

### 11.3 找到图表并下载

路径：`Data & training → Evaluation & MSE → 已完成的 Real TEST/VAL MSE → MSE figures & prediction traces`。

`Run history` 的 `MSE comparison completed` 回执不是图表页。进入正确标签后，可以用 `Ctrl+F` 搜索 `MSE figures`。

1. 在 `Figure` 下拉框选图。
2. 选 Joint MSE / Joint RMSE 看手臂，Gripper MSE / Gripper RMSE 看夹爪。
3. 选 `Episode ...` 看某段序列的 4×4 曲线。
4. 图片太小就点击图片打开原尺寸，或点 `Download PNG`。
5. 要数值表点 `Per-joint metrics (CSV)`；要整套点 `Download all figures (ZIP)`。

完整 Test19 通常生成 24 张图：5 张汇总 + 19 张 episode 图。Episode 曲线显示首步预测，汇总 MSE 使用有效 H20 目标，所以不能用一条曲线的视觉差异直接代替汇总指标。

状态 `Rendering → Uploading → Ready` 分别表示出图、传输、下载就绪。出图失败不一定推翻已完成的 MSE 数值；查看 `Figure export needs attention` 的具体说明。

## 12. 登记自己的模型检查点与区分下载内容

### 12.1 工作站版登记检查点

路径：`Data & training → Evaluation & MSE → Model checkpoint paths`。

1. 在 `Model family` 选择 π0.5、Galaxea AI G0.5 或 NVIDIA GR00T。
2. 在 `Gripper unit in checkpoint` 选择该模型真实使用的单位，不能凭感觉选。
3. 输入 **GPU 工作站上的绝对路径**。不是自己 Windows 的 `C:\...` 路径，也不是网页文件上传。
4. 点 `Register checkpoint path`。
5. 阅读返回状态，再到评估检查点列表选择它。

π0.5 需要完整检查点、模型配置、归一化和来源绑定。G0.5 还需要邻近配置与处理器文件；本项目已指定模型的 100% 对应 80mm 开口，但不能把这个映射套用到所有未知模型。GR00T 需要兼容的关节动作权重与映射，填写一个目录不会自动转换不兼容模型。配置细节见[工作站指南](WORKSTATION.md)。

注册、加载、推理、执行和任务通过是五个不同阶段。缺失夹爪输出、映射不完整或动作越界都可能阻止实际执行。G0.5 30Hz 训练/20Hz 诊断还要保留时序差异说明。

### 12.2 下载入口对照

| 下载入口 | 得到什么 |
|---|---|
| Scene workspace → Export | 场景编辑 JSON |
| Policy evaluation → This run's result & downloads | 所选独立评估的原生视频与报告 |
| MSE figures → Download PNG / CSV / ZIP | 误差图、逐关节数值及来源说明 |
| Help / Data & training 中的已有演示与源码下载 | 标明版本的演示/源码/启动资料，不能当新评估结果 |
| Batch 或任务中的服务器目录 | 路径信息，不等于浏览器已经下载训练集 |

源码包不等于模型权重包，也不包含全部训练视频。完整训练媒体和轨迹默认在服务器；需要哪些数据应按明确用途另行导出。

## 13. 常见问题按现象处理

| 现象 | 先检查 | 下一步 |
|---|---|---|
| 工作站网址拒绝连接 | 网络是否能到工作站，服务是否有新心跳 | 让维护者核进程身份与退出日志，不重复启动多份服务 |
| 云端按钮不可用 | 是否项目所有者登录、数据是否加载、必填项是否完整 | 使用正确账号并补齐选择 |
| Save version 灰色 | 有没有 Unsaved changes | 没改动时不用保存；加载/请求期间也可能禁用 |
| Scene changed 或版本冲突 | 是否另一窗口修改了版本 | 先 Export 留住当前编辑，再刷新最新版本 |
| Sync 成功但训练集没增加 | 是否只有 draft_synced | 按第 5 节完成采集与登记 |
| 修改房间后评估仍是原样 | 是否评估了登记初态 | 草稿尚未成为新评估场景，不要反复 Sync 期待自动生效 |
| 看见 32 个房间，却不足 32 对数据 | Requested 与 Qualified 是否不同 | 读失败和资格报告，保留真实计数 |
| 有 313 对但训练只用 300 对 | Frozen manifest 和 overflow | 该版本只冻结了 300 对，扩量用新版本 |
| 任务一直 Waiting for GPU | 前面是否有任务、采样时间是否新鲜 | 等待或让维护者检查，不重复提交 |
| 训练 0 步 | 是否 preparing / initializing | 等实际梯度开始；初始化不是训练成功 |
| 顶部训练完成，新任务还排队 | Current training 与新任务 ID 是否一致 | 以自己 Job queue 回执为准 |
| 进度不再更新 | Sample/心跳是否过期 | 记录最后采样时间；失联不等于进程停止 |
| 评估五帧就结束 | Stop reason 是否越关节限位 | 加时间无效；保留原始错误，按目的选择严格/诊断模式 |
| 运行到时间上限 | 仿真预算是否耗尽 | 预算结束不是成功，读取物理结果 |
| 画面卡住但 Model 显示推理 | 帧数、sample age 是否变化 | 等模型新回复，不凭静止画面判断崩溃 |
| Ended 后 3D 不动 | 是否 Final measured state | 正在看终态，选 Previous runs 或创建新的独立评估 |
| 没视频 | 是否 0 执行帧、是否仍封装、是否发布报错 | 零帧无动作视频；其他情况读 mediaError/报告 |
| 云端视频未发布 | 是否大小限制或上传失败 | 按报告定位工作站文件，不把缺下载当物理失败 |
| MSE 有数字没有图 | Rendering/Uploading/导出错误 | 等 Ready 或交维护者查出图，原数值仍可保留 |
| 找不到某个任务 | 是否同一网站、同一账号、正确页面 | 回执可能只展示近期任务；用已记录 ID/目录查 |

网站没有通用的“停止所有任务”按钮。需要终止时提供准确任务 ID，由维护者核对 PID、启动时间、命令和目录后处理；不要为了一个排队任务停止无关服务。

## 14. 三套最短操作路线

### 路线 A 只想看看已有模型会怎么动

`Policy evaluation → Room → Model checkpoint → Action handling → 仿真秒数 → Start policy evaluation → Stop reason → 本次视频和报告`。

最终记下：任务 ID、房间、模型、模式、执行帧数、停止原因和是否通过。Robot limits / clip 结果保留诊断标记。

### 路线 B 用现有数据训练一个新模型

`Data & training → Data & recipe → 选择数据集 → Real/Sim比例 → Training steps → 自动评估选项 → Create training job → Job queue → 最终检查点 → After training / 手动评估`。

最终确认：实际更新达到目标、检查点完整保存、训练退出结果、评估结果各自可查。不要只保存一张 loss 截图当交付。

### 路线 C 用自己修改的新场景训练

`Scene workspace → 编辑 → Save version → Export → Sync to GPU → 收集草稿回执 → 维护者适配/预检/采集/验收/冻结/登记 → Registered datasets 选择新版本 → 按路线 B 训练`。

这条路线中间存在维护者步骤，当前不能仅靠网页按钮连续完成。若以后新增了采集入口，应以新发布合同和实际验收更新本手册。

### 遇到问题时复制这份记录

```text
使用入口与发生时间：
页面和按钮：
任务 ID（尽量完整）：
房间编号 / 场景版本：
数据集版本 / Real-Sim比例 / 目标步数：
模型检查点：
Action handling（评估时）：
仿真预算 / 推理超时 / 墙钟保护：
当前阶段 / 实际步数或帧数：
最后 Sample 时间：
错误信息或 Stop reason 原文：
产物目录 / 报告文件：
```

## 15. 进一步阅读与维护依据

- [网站简明 README 与历史 MSE 界面示例](README.md)。
- [单房间评估与性能实测说明](POLICY_EVALUATION.md)。
- [工作站部署、模型路径及 ROS2](WORKSTATION.md)。
- [完整项目运行交接](../handoff/README.md)。
- [数据目录](../project/DATA_CATALOG.md)与[实验状态](../project/EXPERIMENT_STATUS.md)。
- [统一任务规范](../SCENE_TASK_SPEC.md)：本文不改变成功门、split 或动作合同。

按钮与行为核对入口：[场景页面](../../apps/scene-agent/app/page.tsx)、[训练面板](../../apps/scene-agent/app/TrainingPanel.tsx)、[批次来源表](../../apps/scene-agent/app/BatchCatalog.tsx)、[策略评估](../../apps/scene-agent/app/PolicyEvaluation.tsx)、[模型登记](../../apps/scene-agent/app/ModelConfig.tsx)。本手册没有重新执行 GPU 作业，历史数字不作为当前在线状态证明。
