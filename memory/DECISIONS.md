# 用户决定与替代关系

## DEC-WEB-007 · 2026-10-19 网站使用 README

active/scoped-documentation，当前线程`01a14879-8f16-7240-8783-7b5d16fea0a7`用户要求“生成如何使用site的readme”。补充DEC-WEB-005/006的操作文档，不替代训练/评测方案。交付[网站使用 README](../docs/site/README.md)：中文说明配英文按钮名，优先说明MSE入口/图表下载，覆盖场景编辑、数据配比、训练进度、自动最终检查点评测、手动MSE/VLA及状态排障。按当前源码和已有页面核验截图编写；截图明确为历史示例，不据此宣称当前运行结果。本次仅文档与导航索引更新，无网站重部署、训练或服务器操作。

## DEC-WEB-005 · 2026-10-19 英文界面、训练后最新检查点自动评测

active/scoped-web-evaluation，来源`interaction-4e15d8c26e319302`，线程`01a14879-8f16-7240-8783-7b5d16fea0a7`。用户要求网站先换英文并交付一版，然后训练完成自动用最新检查点做VLA和MSE，成功率/对比结果回显。扩展DEC-WEB-004的手选检查点评测为当前及后续新训练的自动最终检查点流程；保留0–100%配方、固定真机Val/Test、仿真纯模型、原任务物理门和train父场景诊断scope。执行默认32房间/200帧每动作/固定Test19，对比已有纯真机10000步基线；新任务可显式关闭自动评测。无真机控制、停止无关服务、重标旧失败或改变网站受众授权。实际交付证据`runs/web_english_autoeval_20261019_v1`。

## DEC-WEB-004 · 2026-10-17 实时训练控制台、自选配比及评测

active/scoped-web-training，来源 `interaction-867f427f03150e54` 与确认 `interaction-9d053a959a6ec3d7`，线程 `01a14879-8f16-7240-8783-7b5d16fea0a7`。用户要求实时预计训练时间/进度、自选配比、VLA验证、MSE比较，并明确批准真机/仿真0–100%、登记数据集/步数；独立新任务不覆盖当前训练；Isaac纯模型闭环，MSE使用固定真机Val/Test。替代DEC-WEB-002/规范1.172的网页仅固定50/50关联限制，保留DEC-055当前正在执行的冻结300对/50:50/10000步及原父split。无真机控制、教师回退、旧标签改写或站点受众变更授权。VLA当前32房间为train场景诊断，不能报held-out泛化。实现和实际回执见 `runs/web_training_console_20261017_v1`；已排队不等于执行/验证通过。


## DEC-WEB-003 · 2026-10-17 默认显示实验室原材质

active/scoped-web-visual，来源`interaction-df35b13c672c77d5`，线程`01a14879-8f16-7240-8783-7b5d16fea0a7`。用户附图并要求“初始应该是实验室和机器人真实环境的着色的样子”。替代首版隐藏房间/灰色默认预览；默认保留原实验室背景、黑银机器人、酒红托盘和标识，再允许对话改色与恢复原色。参考图作为外观要求，不改变三桌单盘、初态/动作/碰撞或既有训练授权。源实验室是已有项目视觉资源，非新实测重建；浏览器静态光照不能宣称Isaac渲染或物理等价。交付证据目录`runs/web_scene_agent_materials_20261017_v1`；部署结果以收据为准。

## DEC-DOC-20261016-EN · 英文专业PDF交接版

active/scoped-documentation，来源`interaction-531d669c0beb5c52`，线程`01a14304-2b97-7b41-882a-29f50f9ad41b`，用户2026-10-16要求英文PDF，先介绍项目探索尝试，再整理启动、训练、生成、服务器与机器人操作，风格专业严谨。扩展DEC-047的交付格式，沿用本线程直接SSH交接要求，不替代任何实验方案或动作授权。交付43页PDF、可编辑英文源稿、232脚本/132配置冻结附录及证据/检查收据；只描述截止时间的实测，未验证事项明确标注。无凭据值入文档或memory。PDF路径`output/pdf/R1Pro_Project_Review_and_Operations_Handover_EN.pdf`，构建和维护见`docs/handoff/PDF_BUILD.md`。

整理2026-10-09；ID来源是 [messages.jsonl](interactions/messages.jsonl) 中的实际交互ID。时间按Asia/Singapore的日期归纳。长原文/审批保留在按日档案；表内只存决策及替代关系，非逐字转录。

| 决定ID | 日期 | 决定 | 状态 / 替代关系 | 原文interaction ID |
|---|---|---|---|---|
| DEC-001 | 09-28 | 对比EmbodiedSWE并移植实验/优化架构、tools/prompt到MuJoCo，在非base Conda服务器尝试 | 历史实施目标；不是当前成功证据 | `interaction-30c9d1d6b08f7258` |
| DEC-002 | 09-29 | 完整轨迹成功率目标≥70%，子agent并行修复，失败视频本机按case存 | 视频下载部分被DEC-003替代；70%未证实达标 | `interaction-4bcfe9dbbf142df0` |
| DEC-003 | 09-30 | 成功/失败视频留服务器，按类别/原因维护本机TXT一行一路径 | active，替代批量下载 | `interaction-58d67fa71f3bf886` |
| DEC-004 | 09-30 | 生成时间不作必要约束、允许近似精度/碰撞，放下可在桌上方2cm内松手 | active，具体物理限制以规范和后续决定为准 | `interaction-8109c50a69a1354b` |
| DEC-005 | 10-01 | π0.5训练，保留DAG，用模型替代动作求解，希望FlowDAgger/DAgger | active目标；当前先BC，未做DAgger不能宣完成 | `interaction-aa4a1d1df7532a24` |
| DEC-006 | 10-05 | 暂停训练、减少文本；允许结束未保存本轮更新、释放GPU | scoped历史授权，不是当前任意杀服务授权 | `interaction-00debd79576cbb0a`、`interaction-40d165e63948716d` |
| DEC-007 | 10-05 | 只完整任务成功来源重切片；carry按三个最终槽位，buffer不训练 | 槽位/八类被DEC-008替代；完整来源规则保留 | `interaction-6c5683a0d9d25e09`、`interaction-16612c9296eadee2` |
| DEC-008 | 10-05 | 单tray；原桌尺寸不变；空拿/空放/载荷推动；三个固定英文文本 | active，三桌细化见DEC-009 | `interaction-bb60ce50ad35cb5d`、`interaction-8957d76674ad836f` |
| DEC-009 | 10-06 | 前2后1桌；随机初位姿/seed/split；取放双臂夹相对长边，完整三段来源 | active；当时横向目标由DEC-011替代 | `interaction-f7d10fe0e804fbbc` |
| DEC-010 | 10-06 | 桌前是可搜索区域，允许桌间移动；取消固定carry终点站位覆盖、联合抓姿站位搜索 | active，不允许桌侧操作 | `interaction-8fe7dddc2e333365` |
| DEC-011 | 10-06 | 长轴平行机器人水平前向；可单臂预调整后双握，准备纳入Pick，模型必须学习 | active，替代robot-left横向目标 | `interaction-ce632e837dbf4724` |
| DEC-012 | 10-06 | 阻塞先定位，报告确认原因/猜测/方案，涉及任务取舍等用户决定 | active治理规则 | `interaction-c5516ff43a1a3b07` |
| DEC-013 | 10-06 | 允许微小瞬时越界；位置误差不需1mm，5cm内；底盘漂移允许5cm | active，仅已有明确阶段/参数，不授权任意取消物理验收 | `interaction-a9bcc597115004cb`、`interaction-165b935d630bc1a3`、`interaction-dafb0ee3fbc50a44` |
| DEC-014 | 10-06 | 右推→左稳定夹持→右松→真实盘左移≥3cm→松手稳定即完成，取消必须到桌左端 | active，明确为用户改完成定义，旧失败不重标 | `interaction-2a7a70dfe7bf9f2f` |
| DEC-015 | 10-06 | 独立后台完整链；首批合法split闭合后自动BC；防重复/心跳/有限3次恢复/新候选与失败留证 | active；GPU不停止无关服务 | `interaction-94b5cbfa2ee530ee`、`interaction-65d4d5edcc3de790` |
| DEC-016 | 10-07 | 独立free_run 600秒；三文本各200秒、检查不提前终止，真实模型动作、四相机，不计成功率 | scoped，仅诊断；20Hz数学上12000帧，旧“约6000”已按真实时间修正 | `interaction-088bdcd061ed7f08` |
| DEC-017 | 10-07 | 三动作按动作分3目录；至少200训练视频；先直接可达随机初态，调向另批 | active生产路线，不能宣单臂预调整数据已完成 | `interaction-1edf3161418c6839`、`interaction-6bd136fb9f7314df`、`interaction-2022d5db1e8e6289` |
| DEC-018 | 10-07 | 去腕部相机遮挡；允许载荷接触；夹爪本体外观壳保留 | active V4视觉，替代删夹爪外观V3 | `interaction-bb9204db86883ebc`、`interaction-1268601f4224401e`、`interaction-086dc3c5599661b3` |
| DEC-019 | 10-08 | 继续AffordVLA与π0.5训练对比，未启动则启动，提供实时百分比/ETA命令 | 已交付独立拿取scope：完成训练/50+50评测；模型失败根因未定位 | `interaction-76b3e1a0dc8a70ce` |
| DEC-020 | 10-08 | PTY查看失败修复；核查下载/训练/结果，给两个模型视频目录 | 已交付SSH-T查看、服务器媒体/轨迹；拿取50/50与0/50范围受限 | `interaction-f988dc170478b0bc`、`interaction-caefa3501d0859b9` |
| DEC-021 | 10-09 | 项目memory治理：记录交互，生成新AGENTS，按模块/数据/要求组织文档 | 已完成首次治理，持续维护 | `interaction-8d5895ecb55cd12e` |
| DEC-022 | 10-09 | 用GalaxeaVLA真机Pick/Place数据算仿真模型MSE，真机＋少量sim训练后看sim表现 | 当前active，离线数据训练与仿真测试；不含真机执行 | `interaction-c51ffebd053c496f` |
| DEC-023 | 10-09 | 夹爪80表示80mm总开口宽度 | active数据转换合同：mm→m；真实反馈不裁剪 | `interaction-19403a00e039c75b` |

## 不能从旧授权推导的行为

- SSH临时公钥续期回复只作用于当轮授权，不允许自行延长期限；密钥内容不进memory。
- 停止训练/停止某服务是历史特定请求，后续监督要求明确“不停止无关服务”。
- 旧横向摆盘、三个槽位、必须推到桌最左端、删除夹爪壳均保留历史但不执行。
- 因改完成定义得到新成功，不是控制精度提高；旧失败和旧检查点证据不能修改。

新决定追加DEC-024及以后；涉及替代时保留本表旧行，用superseded/scoped和目标ID注明。

- 2026-10-09本轮用户决定：目标为MobaXterm从外网无需VPN访问服务器SSH命令行；取代本轮中间网页/视频访问选项，不授权公开视频目录。原文interaction ID待本轮显式线程归档关联；网络配置尚未实施。

- 2026-10-09公网SSH部署授权：用户明确要求部署，并确认EC2实例关联弹性IP47.130.167.160；采用公网EC2跳板及GPU发起的仅loopback反向SSH，不公开视频或改训练。新访问密钥与专用隧道账号用于本轮明确公网访问目标，原实验临时授权未延长。原文见本线程交互档案。

- 2026-10-09用户授权迁移自己的EC2/GPU连接到另一台电脑：补充独立EC2会话、提供可用迁移压缩包及prompt。包内包含所需两把登录私钥，由用户自行可信渠道传输，不上传外部平台；不包含实验临时授权密钥或GPU专用隧道私钥。

- DEC-024（2026-10-12，本线程最新用户消息）：只用真机数据微调π0.5，保留train/test隔离并评测，不再做AffordVLA；增加数据结构/归一化/亮度及原论文的失败分析。本轮替代DEC-022的90/10混合采样，不改历史运行。按已有离线真机授权解释为留出动作预测评测，不新增真机执行授权。

- DEC-025（2026-10-12）：按test_last图样比较纯真机和混合π0.5，生成全部对应图；样例数据只作参考，两项目检查点在原共享test19评测，不改变训练或原split。

- DEC-026（2026-10-12）：用户授权将纯真机与混合两个已保存π0.5检查点在同批仿真场景闭环比较，录制视频/轨迹并报告成功率，禁止教师或IK回退。本轮扩展DEC-025离线图表为仿真执行，不授权实机控制或重训。沿用原V4 test10场景的Pick/Place独立阶段初态，共20动作/模型，50秒模型预算，不宣完整三动作成功率。

- DEC-027（2026-10-12，`interaction-72139b82a5f1d9ec`）：先做real2sim，在仿真中复现真机Pick/Place；代码高内聚低耦合，支持迁移IsaacSim与Genesis。新增离线真机示范回放scope，优先级覆盖当前聊天训练方向；不停止其他聊天的健康闭环比较、不重训、不控制真机。原完整三动作任务与冻结数据不变。
- DEC-028（2026-10-12，`interaction-366f27719b55a3ba`）：用户选择独立真机一致模型，替代“只在旧固定腰部/窄肘限模型中诊断”的候选；允许新版本恢复腰部、按来源URDF核正关节定义。不是授权由数据任意扩限，也不是确认所选URDF与硬件/接触参数已经标定。真实环境配准来源（实测参数或原视频近似）已询问，当前尚未收到选择。

- DEC-029（2026-10-12，`interaction-d194ebd9ced7b26c`、`interaction-901c9187cdd93448`）：用户选择实测标定，替代DEC-028中未决的配准来源选项；指定聊天01a0e72f-3107-74f3-8216-6fe65a45071f查找。不能默认改用视频估计。已完成可用历史与资源追溯，尚未找到完整实测物体位姿；具体已找到的场景参数与缺项见calibration_lookup_20261012.json。

- DEC-030（2026-10-12，`interaction-8f6d70db73d9c579`，用户“这些你估计”）：active；替代DEC-029的仅实测限制，授权估计缺失桌盘/底盘相对位姿和Place持盘初态。保留现有三桌与托盘几何，单独新run验证物理接触；估计不等于已标定，不修改真机命令、抓法或验收门；仿真有效驱动拟合须单列，不能称真机硬件标定。DEC-029来源检索结论保留。

- DEC-031（2026-10-12，`interaction-2515acf485e6049b`，用户明确回复）：active/scoped；用户允许仅在独立real2sim模型中按源URDF重建四个夹指碰撞形状并验证释放。此范围替代原碰撞保持限制；旧场景、外观、惯量、相机、真机原命令和旧标签不改。不扩大为其他物体/夹爪本体碰撞修改授权。

## DEC-033 2026-10-12 本线程执行一致性优先

用户要求先修复真机/仿真腰部、关节限位和夹爪映射，使用原始真机轨迹回放，展示Pick/Place视频及真实结果；暂不重新训练。继承独立real2sim隔离和旧证据保留。此轮新候选real2sim_execution_alignment_20261012_v1修正遗漏的URDF夹指轴/限位/力限，沿用v8估计配准；不改变数据或验收门。

## DEC-034 2026-10-12 Place持盘诊断继续

用户授权继续定位并修复放下初始位姿、夹爪接触及驱动差异，保持原始轨迹、尺寸与验收，修后回放Pick/Place并提供视频；暂不训练。此轮限于独立real2sim初态拟合与原命令物理回放，不动模型权重和冻结数据。

## DEC-035 2026-10-13 双模型真机配置与停止键

active/scoped：用户授权mixed与real-only π0.5真机尝试，workstation server/robot client，原run/scheduler/filter不改、新增配置；后续明确server增加急停按键、任务改Pick up the tray。替代仅离线授权在本轮范围的限制，不授权绕过filter/硬件急停或更改模拟验收。控制停止E/空格、默认锁定/失联拒绝不等同硬件急停。当前传感器缺失，只读接口探测0控制发布，等待live驱动/现场初态；来源本轮原文于交互档案（刷新后可查）。

## DEC-036 2026-10-13 真机夹爪提交0–80mm饱和

active/scoped：用户明确选择“按0–80 mm限幅并记录”。仅新server输出夹爪提交边界＋新client显式range0..80；保留原模型输出及限幅证据，不100→80比例缩放、不改原filter源码/臂门、模型/训练/norm。替代本轮“不裁剪夹爪”的限制，其余安全/真实性条件不变；旧90步日志与超范围失败保留。用户新授权原文在交互归档，限幅不是模型改进或成功率提高。

## DEC-037 2026-10-13 保留tracking停止门与SDK诊断

active：用户选择“保留停止门，补SDK诊断”。原0.25/速度/年龄/夹爪门、故障锁定与无人自动重跑不变；新增SDK原生反馈与ROS发布证据、拒绝后1秒被动观察，不授权自动恢复或改变成功定义。诊断增强不称物理根因已修复。

## DEC-038 2026-10-15 新模型真机/仿真50%采样

active/scoped：用户要求“再帮我训练一个模型，模拟和真机按50%混合”。新增独立π0.5 BC实验，不替换旧90/10或real-only模型/数据。按样本每batch4+4而非文件比例，沿用90/10父sim10000初始化及训练配方、新optimizer、冻结数据选择与新train-only norm，独立GPU0。训练后离线MSE不授权新模型自动真机执行；未执行DAgger不得称DAgger。

## DEC-039 2026-10-15 Isaac Sim实验迁移

用户要求接入Isaac Sim并迁移实验。独立原生引擎/资产运行目录，保留现有MuJoCo与所有数据/模型；原三动作、抓法、底盘/碰撞和验收授权不变。导入成功不是物理任务或模型成功；不授权自动替换真机服务。



## DEC-040 2026-10-15 完整Isaac实验包含训练数据

用户明确“完整实验，包括训练数据”，扩大DEC-039的迁移实施范围。新原生完整成功来源重新记录、切三动作、冻结split、接入BC和纯模型闭环；不把旧MuJoCo视频/成功标签转成Isaac。其余任务/控制/容差、真机部署边界不变。当前尚未产生合格原生数据，不授权跳过物理验收。


## DEC-041 2026-10-15 新增三托盘Isaac新版载荷交接数据与训练

用户要求找旧三托盘管线并迁移、拆分训练；两次明确选择“合并为三类动作”“改为新版带载交接流程”。此分支替代旧八文本与旧push_adjust语义，不把旧193源改标签当新数据；三个精确原文保持，装载排除训练，保留三盘调度/槽位元数据与父split，重复动作按cycle/tray分段。单托盘分支独立保留；未授权放宽物理条件或自动部署真机。新合格来源为0时waiting_for_data，先完整原生新任务成功再训练BC。

## DEC-042 2026-10-15 三盘原生完整demo优先与自动BC接线

active，延续DEC-041，不替代其动作/物理条件。用户原文interaction-854ad8380e387879（本线程2026-10-15T10:19:40.395Z）要求接通带载交接控制器和完整验收，先实际完整Isaac demo展示，再后台三动作生成、检查后自动π0.5训练，不停在空目录/资产预检。普通质量/惯量、夹指联动、接触过滤和站位路径转换错误可在新版本修复，不能更改旧失败或以预检代替成功。真实状态与证据见[三盘专题](../docs/project/ISAACSIM_THREE_TRAY_20261015.md)，当前原生实测未全任务通过时仍waiting_for_data。

## DEC-043 2026-10-16 创新与商业价值评估范围

scoped/requested_assessment，来源interaction-73eed6670635b3f6，线程01a140f7-4256-72c0-8353-26b28efacd73。用户要求分析项目工业/学术创新、实际经济利益和预期收入；仅授权本轮咨询分析，不替代DEC-038至DEC-042的既有实验，也不是批准商业转向、对外联系、报价或真机操作。研究方向、人民币客单价/收入/成本均明确为助手建议或情景假设，等待用户未来选择；记录详runs/innovation_commercial_assessment_20261016/assessment.json。没有新的已批准实施方案。


## DEC-044 2026-10-16 原速快速取放、多位姿与MuJoCo视觉一致

明确计时选择来源：interaction-0ab852d4e79ac8d7（本线程2026-10-15T19:05:49.153Z）。

active/scoped，用户最新要求Isaac按MuJoCo机器人颜色与实验室配置，画面更好、快速夹起/放下、多位姿且考虑真机域差异；异步回答明确“夹起、放下各约3秒（推荐）”，桌间移动单独计时。新独立fast_pickplace_benchmark先真实物理视频与速度分布报告；不覆盖已有三盘完整数据、训练和失败，不用加速播放冒充物理提速，不把多位姿教师演示称模型鲁棒性已提高。继承真实动力学/双臂相对长边/桌前规划等现有授权；必要取舍仍先报告。3秒计时的预备站位/预备臂姿排除项必须一并说明，原四相机与单位保留，新外部相机只展示。只用real train参考速度，旧完整任务BC自动条件仍有效，新快速诊断不隐式混入训练。

## DEC-045 2026-10-16 橡胶夹垫与全过程平稳性修正优先

来源：interaction-a23eb6032f877b27（本线程2026-10-15T19:52:30.975Z）。

active，补充DEC-044并替代“端点通过即可交付平稳视频”的助手判断。用户明确真机夹爪贴橡胶、摩擦力大，要求修复托盘不稳和控制时序抖动，不希望看到不平稳托盘。先主动定位，普通实现/接触迁移错误在新版本修复；不得以终态落桌掩盖全过程大幅倾斜，不改旧结果，不伪造剩余轨迹或绑定托盘。继续争取各约3秒；若确需延长动作、换抓法或改变任务条件，按既有规则先给证据/选项由用户决定。当前未指定新的硬倾角或角速度门，不能自行宣称某阈值由用户批准。旧v3派发停止、已启动原生进程正常闭合；独立v4/v5修复候选，尚未通过全过程审阅前不得称修复完成，不自动加入训练。涉及橡胶的抗扭接触仅名义源参数迁移，未实测真机材料/软垫厚度，不冒充真实标定。


## DEC-046 · 2026-10-16 先平稳取放、后恢复原BC

用户选择“先验证平稳取放，再恢复BC（推荐）”。授权结束本项目仍为0梯度更新的初始化，释放资源给真实平稳性验证；无已完成步损失，不停无关服务。视频真实验证后自动按原冻结数据、父模型和配置恢复。替代此前并行保持该BC初始化的资源安排；未取消训练目标。服务器证据：`runs/isaacsim_three_tray_workflow_20261015_v1/pipeline_v15/user_deferred_initialization_20261016.json`，包含原状态与进程身份；恢复须修复非base CUDA12.9 ptxas的PATH遗漏。

## DEC-047 · 2026-10-16 项目运行交接文档

scoped/documentation，来源 `interaction-35ee70bb65c764a7`，线程 `01a14304-2b97-7b41-882a-29f50f9ad41b`。用户要求整理全部启动、训练、生成脚本，做成 README 可交接文档，包括服务器与机器人启动。新增根 README、docs/handoff 操作手册、全量静态脚本/配置目录及示例；本轮允许必要只读核对，不替代 DEC-046 资源安排，不构成新训练/仿真/真机动作启动指令。旧 README 说明归档保留；真实配置/环境与阶段证据见 runs/documentation_handoff_20261016/server_inventory.json，文档结构核对见同目录 validation.json。未重新实测的机器人驱动/相机启动入口明确标待现场核验，不猜测命令。

## DEC-048 · 2026-10-16 交接只保留直接 SSH

active/scoped-documentation，来源 `interaction-e82d3ac0f69ee3a7`，当前线程用户进一步指定只通过 `michelle@xinmatrix`、`100.104.0.108` 交接，替代 DEC-047 中此前采用的连接说明与访问脚本目录范围。文档使用默认22端口、交互密码登录；监控与键盘控制在服务器执行。用户已提供登录凭据，具体值不保存于memory、README、命令或示例，交互归档按既有规则脱敏。旧运行证据与服务不因此删除、改配或重启；没有新物理/训练/真机控制授权。


## DEC-048 · 2026-10-16 固定底盘Pick优先、Place非固定持盘初态

来源interaction-a902e74fad25287f，本线程2026-10-16T04:57:54.128Z。

用户要求后续固定机器人生成Pick，再生成Place；Place初态不是固定姿态，可能来自VLA Pick后的真实状态。实施解释已对外说明：采集前底盘就位，正式两动作中底盘目标固定；逐来源先Pick再Place物理续接，分动作目录，不在两者之间复位/改盘pose，不回到标准持盘臂姿。允许在专项中改变盘XY/yaw和实际抬升高度，保持原对向长边、原生摩擦/平稳控制与3秒目标；不是永久取消三桌正式任务的站位搜索/桌间移动。

本批先用专家Pick的真实多样末态（明确非VLA）；尚未采集到VLA持盘状态，不把人为摆姿态或专家生成标成模型执行。将来真实VLA来源须带checkpoint、原始动作与真实持盘资格，模型失败不隐式回退。新两动作专项分别导出pick_up_the_tray/place_the_tray，只接受完整成功且媒体/轨迹闭合的Pick-Place对，不能冒充含Flush的完整三盘源；原健康三盘BC及冻结数据不改。证据目录runs/isaacsim_fixed_pickplace_20261016_v1，首次两候选是出口验证，不称大规模或模型鲁棒性通过。


## DEC-049 · 2026-10-16 并行网格采集成本方案待选

scoped/proposal_request。用户提出单engine网格房间、多机器人多托盘并行采集录像，允许低画质，要求先算成本给选项。A8/B16/C32仅候选；B推荐不等于已获批准。规模、相机分辨率、安装适配、暂缓当前双卡BC资源安排尚待选择，不停止健康作业、不改任务动作/接触/物理步长、不把预算吞吐当实测。估算及来源见runs/isaac_parallel_collection_plan_20261016_v1/estimate.json。


## DEC-050 · 2026-10-16 选择C并行采集与扩大初态覆盖

active/scoped，用户明确选择C：32房间、单engine、双GPU渲染、优先规模；包含开发期旧作业继续、独占跑分/采集前保存已有梯度再暂缓本项目双卡BC、结束后原配置恢复的资源安排。替代DEC-049的待选状态，A/B预算保留不当实测。物理仍500Hz、控制/录像20Hz、真实接触与双臂相对长边不变，低清四原视角保留比例/FOV/外参。先4→8→16→32原生验证，不能以复制进程冒充单engine，也不能以重放记录位姿代替真实物理。

用户随后明确初始tray位置/水平朝向差异要更大；不能直接抓取时先实际单臂调盘再双臂拿起，纳入Pick同一文本片段。此要求替代本专项此前“只收直接可达初态、调向另批”的采样限制；不取消单臂预调整的实际接触/碰撞验收。Place从每次真实Pick后的不同双臂/腕/盘位姿连续执行，不复位成统一持盘姿态。专家和真实VLA来源分标；未来模型必须自行完成预调整，无隐式教师。当前尚无VLA Pick末态采集，也未完成单臂调盘原生验证。


DEC-050来源补充：C选择原文interaction-25953339e3777e1b（2026-10-16T05:28:02.959Z）；扩大托盘初态及Place机器人初态原文interaction-8625ef85e5b8ca66（05:31:06.869Z）；均为01a11fa0-3cad-7053-9d17-104420949e84项目线程。新大角度原生调向未通过时不接纳数据，用户未授权新增容差；桌前底盘跨episode变化的澄清尚未答。


## DEC-051 2026-10-16：桌前跨episode底盘位置/朝向变化（active）

用户答复“包括桌前底盘初始站位和朝向（推荐，扩大大角度托盘的可操作范围）”。替代DEC-050及1.164中底盘变化待答部分；不替代动作内底盘目标固定、禁止桌侧操作和真实5cm漂移门。联合搜索站位/双臂抓姿，仍需真实单臂准备的样本保留Pick完整时间。Place继承不同实际Pick末态，无统一姿态复位；尚无VLA末态来源，专家不得称模型。原文interaction-8cc319d8cab197b9，2026-10-16T06:16:24.012Z，thread 01a11fa0-3cad-7053-9d17-104420949e84，已由本轮交互导出收录。


## DEC-052 2026-10-16：调盘后双臂待机复位，所有动作底盘固定

用户明确调盘松开后复位再拿取；答复复位为“双臂回初始待机姿态”。只通过真实关节控制，张开夹爪、桌面稳定支撑、不修改盘实际位姿、不移动底盘，纳入Pick。所有动作含准备底盘固定，初态靠近桌并面向桌；替代本专项旧navigate准备段。DEC-051跨episode初始站位可变保留，但每次必须在动作开始前初始化，不得边执行边挪底盘。Place仍承接真实Pick末态，不在两段之间复位。新规则不追改旧失败或冻结BC输入。

## DEC-053 2026-10-16：直接可达泛化生产与调盘并行

用户明确不再死磕调盘，先将能跑通泛化场景做数据生成，问题与生成管线并行。替代DEC-050中本轮需先攻克大角度调盘再扩产的优先级；保留调盘研究，不宣称直接可达子集覆盖不可达初态。新底盘固定/两动作真实连续/成功和媒体闭合/split/冻结数据规则不变。

## DEC-054 2026-10-16：结束本轮BC优先生产

用户答复“结束停滞训练，优先生成”。此前已通知200步长等待后恢复223；随后已说明这是主动让出资源并记录实际停止步数。实际248步停止、100步已保存，放弃未保存148步；原权重/数据不改，采集后恢复100步。仅此本项目训练授权，不能停止无关服务。

## 2026-10-16 停止串行采集
用户明确“已有串行采集先关掉”，替代保持串行继续的要求；停止该采集及自动恢复队列，保留已有10对20片段和未闭合case现场，为方案C释放资源。证据：runs/isaac_serial_stop_20261016_v1/result.json。

## DEC-055 · 2026-10-17：新增300对与50/50耗时加权BC

用户要求继续生成300条并混合训练，增加耗时优化；本轮按新增300完整固定底盘Pick/Place对、600动作片段执行，之前59对不重复计数。沿方案C32房间单engine双GPU，不改变真实物理/接触/固定底盘和失败验收。真机/新Isaac各50%按每batch样本数，保持原真机来源split与sim父train，不能将同父变体伪分val/test。数据冻结检查后自动开始独立新模型训练，不覆盖旧数据或checkpoint。

用户异步明确选择“先做耗时加权BC，暂不做RL”，替代本轮候选“BC后真正RL耗时奖励”。方法是训练域/动作内按完整真实片段耗时加权模仿学习，非环境奖励、非RL/DAgger；不加常数耗时项冒充有效梯度，不加速视频、不删除必要准备或稳定段，不把较低loss称更快执行。权重只拟合train、保持50/50与动作平衡，模型快慢仍需实际闭环测量。


## DEC-WEB-001 · 2026-10-17：先导出网页Agent模板与指令，默认Isaac32

active/scoped-export。来源为当前用户请求及异步选择，thread=01a14879-8f16-7240-8783-7b5d16fea0a7。用户要网页agent支持对话构建场景（机器人位姿/颜色、托盘颜色等）和选择数据训练模型，本轮先导出prompt模板及执行指令代码；默认场景明确选“最新Isaac32房间Pick/Place”，替代本线程最初暂定三桌单盘首版建议。该选择不替代既有物理规则、三桌原布局或DEC-055独立300对+真机混合授权。

已导出范围：新草稿/数据查询/冻结训练计划、配置/视觉集成函数及网页实施prompt；未启动服务/训练、未授权新真机动作。执行器不接受任意shell和实时pose重置，当前场景编辑只作用新episode初态。旧59对示例与新300对混合分开，真机val/test可服务既有混合评测，不伪造sim holdout。证据入口exports/web_scene_agent_v1/README.md、runs/web_scene_agent_export_20261017_v1/validation.json；交互原文由本轮显式thread归档。

## DEC-WEB-002 · 2026-10-17：创建并部署Sites项目，GPU执行后台

active/scoped。当前用户“OK，你来创建项目放到GPT服务器上”；异步明确“ChatGPT Sites托管网页，GPU服务器负责仿真/训练”。替代DEC-WEB-001的仅导出阶段范围，保留默认最新Isaac32房间Pick/Place和原有训练/物理合同。授权创建私有网页项目、连接现有GPU后台，未授权公开分享、真机动作、新训练配方或停止无关服务。当前网页实现初态/颜色草稿、版本、数据选择、训练计划和关联DEC-055监督器；原生视觉适配/物理执行仍须实测，不能把同步草稿称新仿真数据。当前thread=01a14879-8f16-7240-8783-7b5d16fea0a7；交互原文通过显式thread union归档，证据在runs/web_scene_agent_deploy_20261017。

## DEC-WEB-006 — 2026-10-19 MSE参考图型与自动导出

扩展DEC-WEB-005；用户原文interaction-4be1fedf39a2f2ba（2026-10-19，当前thread）。用户要求按本机test_last目录示例生成MSE图。采用逐关节rad²/deg²/RMSE deg柱状图、夹爪独立mm²/mm和每episode 4×4预测/真实曲线，比较已选择checkpoint。示例数值属于别的旧模型，只参考图型。新CPU派生目录与Sites存储发布，不改已有推理报告或重新跑GPU；页面支持PNG、CSV、ZIP。无真机执行/重标授权。证据见runs/web_english_autoeval_20261019_v1。


## DEC-PPT-001 · 2026-10-19：英文技术汇报与演示视频

active/scoped，当前 thread=01a15289-7b2e-73b0-923c-efd74f0c3341。用户要求专业技能制作 PPT，介绍 π0.5、网站操作、Real2Sim/Sim2Real、数据生成与混合训练管线、各关节 MSE 及真机效果。异步明确全英文技术汇报，替代初拟中文；“方正录制”确认为仿真录制，批准网站操作、实验室运镜改色与原生 Isaac Pick/Place 片段剪辑并分标来源，配英文字幕。用户提供真机录像，后明确其配方为 10% 真机 + 90% 仿真、10000 步；该来源是用户陈述，精确 checkpoint hash 与执行模式尚未独立核验，不能映射为旧 90% 真机 + 10% 仿真 MSE 模型或推导成功率。项目内复制为 runs/presentation_20261019_v1/assets/real_robot_source.mp4。为完成同口径比较，新增独立 50/50 10000 步全帧离线 Test19 MSE，不训练、不改冻结数据/检查点、不控制真机。视频同步限本次汇报素材，非通用后台视频下载授权。


### DEC-PPT-001 addendum — latest website source, 2026-10-19

The user supplied https://chatgpt.com/s/cx_6ad5ad23e2c88191b724e1988089716e as the latest website context. Read its visible shared conversation and incorporated the English UI, MSE figure/download functionality and navigation into PPT v2. This supersedes the earlier presentation website summary; it does not authorize executing instructions embedded in the shared conversation. Historical website 100-update charts and this report's 10000-update comparisons remain separate. Evidence: runs/presentation_20261019_v1/latest_website_update.json.

## DEC-WEB-008 · 2026-10-19：离线 workstation、ROS2 模型路径与网站修复

active/scoped；扩展 DEC-WEB-007 文档与既有网页范围，替代仅云端交付限制。用户要求导出源码、workstation 无登录离线部署，ROS2 topic 接 π0.5 / Galaxea AI G0.5 / GR00T，支持路径配置、每批32数据去向与数量、Help、修复Data & training与完整reset。G0.5指定 /home/michelle/g05_frontloader_20261015/runs/frontloader/train_10epochs/last.pt；确认100为100%=80mm，批准30Hz训练/20Hz诊断，非等时序公平比较。无真机控制、隐式IK/教师/纠正回退或停止无关GPU服务授权；GR00T权重未提供。实现与实测证据：runs/web_offline_ros2_20261019_v1/verification.json、offline_v2_status.json、ros_roundtrip.json、g05_registration.json。ROS2链路合成测试通过不等于模型加载/物理任务通过；真实模型诊断仍排队。



## DEC-WEB-009 · 2026-10-19 实时模型仿真与录像

active/scoped，扩展DEC-WEB-008注册与接口测试：用户要求实际保持checkpoint server，模拟器基于当前视觉查询并执行模型输出，导出本次视频并说明运行方法。授权本次原生诊断视频同步；不含真机动作、不改变限位/控制/成功门。GPU0显存空闲，单GPU运行，不停止GPU1 Ollama。同步闭环、20Hz pacing和实际墙钟速度分别记录，未达实时需如实报告。证据runs/realtime_inference_20261019_v1。

## DEC-WEB-010 — 2026-10-19
User requests downloads on website and HTTP VLA submission repair. Preserve existing model contracts; add compatible random IDs and measured diagnostic downloads. Supplements DEC-WEB-009; no override of unresolved G0.5 control decision. Evidence: runs/web_uuid_downloads_20261019/verification.json.

## DEC-WEB-011 — 2026-10-19 Per-run policy simulation

User clarified downloads must belong to arbitrary selected room/policy runs, with live Scene-workspace-style 3D and configurable duration. Latest reply specifies primarily robot simulation execution duration. Supersedes DEC-WEB-010 static-example delivery scope only; keeps model/control restrictions and unresolved G0.5 missing-gripper decision. Total simulation action frames exclude inference waits; advanced request and wall guards remain separate. No diagnostic data automatically enters training. Implementation and measured limitations: docs/site/POLICY_EVALUATION.md; runs/web_live_policy_20261019_v1/verification.json.

2026-10-19 DEC-WEB-011 maintenance: user reported workstation connection refused; restored service and isolated bridge failure from website availability. No changes to simulation/model contracts. Evidence runs/web_connection_recovery_20261019.

## DEC-WEB-012 — 2026-10-19 Fast explicit diagnostic repair

User requested fixing5-frame stopping and misleading live display. After explicit strict/clipping options, user replied “最快的解决修复方法”. Implemented opt-in labelled clipping diagnostic as fastest observation workaround; strict default unchanged. Supersedes no-clipping restriction only for explicitly selected clip_diagnostic, with raw/applied correction evidence and exclusion from pure-model success/training. No real-hardware action authorized. Physics timestep/contact rules unchanged. Native40-frame test reaches configured2s, speed still below realtime. Evidence runs/web_policy_stop_20261019/verification.json.
