# π0.5训练与DAG执行

最新状态（2026-10-05）：用户确认结束旧轮并释放GPU；2278645整组已终止，最终两卡0%利用率、无计算进程。363步未保存更新已丢弃，原10000步/final9999父模型保留。六动作文本与682片段映射已更新；官方CPU实际55→6且RGB/state/action/原文件哈希不变，新发布核心1465通过/1预期失败。新六动作配置仅准备，训练未重启。终止证据为`DUALGPU_DP_V3_USER_STOPPED.json`，此前paused/started记录保持历史。

当前状态（2026-10-05，用户要求暂停）：2278645整个训练进程组已SIGSTOP，最后日志363步、父子进程T；内存和显存保留，无新checkpoint保存，未恢复训练。`TRAINING_TEXT.txt`现为6类固定动作，`TRAINING_TEXT_SEGMENTS.tsv`保留682片段的canonical文本、原source文本/索引、场景和三路视频对应，旧55句另存training_text_snapshot。新`configs/vla_pi05_airport_native32_skill_only6_dualgpu_20261005.json`仅准备；原数据不改，实际加载时在tokenizer前归并。旧暂停进程仍是legacy，不能热换文本或冒称六动作模型已训练。以后需独立新run，从已核a677父权重及同norm初始化；DAG目标元数据不自动成为模型观测。

当前实际双卡运行（2026-10-05）：`runs/vla_20261005/bc_native32_skillmerged_dualgpu_10000_v3`，PID2278645，两RTX PRO 6000共同数据并行、mesh(2,1)/global batch8/每卡4，从真实a677父10000步权重继续，原norm及95,914帧数据保持。服务器核心1424通过/1预期失败，首真实step0 loss0.0017、grad_norm0.0583，已推进83步；两卡各约79GiB，同一PID、实际Socket通信和两key逐卡bits核验有证据。配置`configs/vla_pi05_airport_native32_skillmerged_dualgpu_dp_20261005.json`。10000步及final9999尚未完成，不称完整DAG成功率提高。当前实测约2.6秒/step，官方进度估余约7小时；比原单卡约0.85秒/step慢，不称双卡加速，保留已稳定训练不为未测优化中断。v1/v2失败保留；实际成功是DP与运行兼容配置组合，未隔离单个flag因果。数据目录与state/action/video位置已写根目录`TRAINING_DATA_LOCATION.txt`。

2026-10-05重新连接实测：上轮BC32已完成10000步并保存final9999，权重身份`sha256:a6771bf29a9c65371d771d5c0bc870bb22e03b7ccbe76592e935cd53ea386f6d`、norm f5均已复验。用户授权停止两卡GPU服务，实际已无计算进程；双卡同数据续训使用新`runs/vla_20261005`，FSDP2/global batch8、同数据逐帧/H5/XML和完整派生资源字节重新核验通过。首v1实际JAX识别两GPU及mesh(1,2)，但官方初始图像日志的sharded array hostcopy发生CUDA非法地址，尚无训练更新；失败日志和run保留，正在定位，不能称双卡训练已正常运行。数据路径见根目录`TRAINING_DATA_LOCATION.txt`；上轮posttraining监督因进程退出竞态失败，不能据模型保存宣称任务成功率。

最新进展（2026-10-01）：连续技能数据已实际完成682 episodes/95914真实帧/2046 H264流，32初始化/113起飞资格、852移除phase边界及682真正skill末端官方H20、原H5/XML/state19/action/来源覆盖和全部派生字节审计通过。抓取末端重复监督占比18.930%降至5.297%，未改原生视频、旧phase数据或最终任务验收。v20服务器核心1409通过/1预期失败、监督29项通过；真实10000步微调已启动，PID3232298，沿用已验证父模型5277与norm f5，step0 loss0.0053。当前尚未完成10000/final9999，服务仍旧3000模型；最终两组纯VLA完整任务及成功率待实测。v19宽锥实际0/1失败，双头各2555帧；v18课程实际3标签/21拒，双头各600帧，均已按真实失败入TXT。默认关闭的v21私有measured tracking资格候选正在新冻结核心核验，未将标签资格变化称控制改进。

此前进展（BC32v3派生完成前）：第二轮均衡DAgger真实训练3000步、final2999保存及服务恢复已核验，模型哈希5277cd4f…b5600ca；train4/val13/test2原初始化门槛下完整物理评估仍0/3，逆动力学均0。v15近似初始化候选.15rad/.01m在train4完成初始化和导航，但抓取2400ticks耗尽，完整0/1、4414帧、inverse0；两头原生视频均4414帧且逐帧/终态六项回放误差0。v16初始化底盘固定候选实际将底盘漂移限制到约0.22mm，但严格初始化仍失败，不能称机械臂精度或任务成功率改善；近似组继续完整任务测试。原16数据784分片/49470帧已逐值对源H5/XML核验；32场景扩容已核验复用26个来源，其余6个在新native32_v4目录渲染，尚未训练就绪。新BC32v3条件监督已启动等待，未开始训练。v16服务器核心1311通过/1预期失败，70%仍未达到。

v14r1包含 train-only 技能 curriculum DAgger、聚合/实际训练入口的上下文复核，以及默认关闭的按比例模型观测渲染。后者实际五frame×三view审计保持物理状态与视锥投影不变，三路RGB字节减少95.9%、render+resize样本约19.76→7.06ms；224像素仍有边缘域差，不能保证策略等价。当前完整评估继续native输入；技能监督在真实最终模型与完整纯评估后，顺序对比六技能并采集grasp/carry/place的实际访问状态标签，不重启模型或计作完整DAG成功。v15另加入真实父参数/同hash归一化/逐源段超集审计绑定的BC扩容warmstart，未启动32训练。v14首次漏辅助源码导致6测试失败；首次post监督遇旧socket关闭竞态停止，均保留原失败记录，新v14r1/new post_v2完整重测与真实模型恢复已完成。

本轮任务是仿真训练，不是实机数据。当前全400教师完成率193/400（48.25%）；π0.5已实际训练，但完整任务仍失败，须继续改进并闭环评估，不能预先保证70%。

v16近似初始化固定组也已实际失败：4443帧、初始化229/导航2043帧通过，抓取2400ticks耗尽、inverse0；双头各4443帧且回放六项误差0。只读证据显示抓取期间左手目标接触力恒0、底盘漂移约0.575/0.889m，而机械臂servo跟踪误差较小；新增默认关闭的`--grasp-base-hold`仅限制该节点的底盘参考，raw模型和实际物理证据保留，需新冻结测试及完整物理验证。服务另有默认10的`--denoising-steps 10/20/30/50`候选，记录实际官方sampler设置，当前运行服务未改；更多采样步数的效果仍待独立比较，不能据此宣称成功率提高。

数据入口 `scripts/prepare_vla_dataset.py` 生成JSONL分片索引，记录每个skill/phase对应原native四路视频的半开帧范围；`scripts/convert_vla_lerobot.py` 将已核验train片段转为官方LeRobot v2训练派生。动作是20Hz mobile19绝对目标，观测底盘由真实base qpos获得，模型使用head_left、left_wrist、right_wrist三视角224派生。原native视频保持原尺寸、帧率和物理回放证据，训练/验证/测试按scene隔离。

`train_pi05_airport.py --config JSON` 使用官方openpi固定快照加载项目内pi05_base参数，训练LoRA并记录normalization与实际checkpoint。完成后 `serve_pi05_airport.py --training-status RUN/training_status.json --port 8765` 恢复训练参数；只有真实恢复成功才发布fine_tuned及checkpoint内容身份。VLA配置的checkpoint_id必须与服务匹配。

DAG任务选择与验收保留。`motion_backend=pi05` 的navigate/push/grasp_lift/carry/place_release运动只调用模型+位置servo+MuJoCo forward物理积分，执行期没有IK、逆动力学或隐藏教师fallback；结果记录inverse_dynamics_calls和各skill实际物理完成。网络只接RGB、robot state与统一skill指令，高层调度/安全验收仍可用真值。

训练方法先BC LoRA，再simulation-expert DAgger：在learner当前真实访问状态私有克隆仿真，重新求专家并物理验证标签；原learner不回滚，oracle失败没有标签。每标签是单个真实首观测与专家action chunk，不复制为假视频。后续round从已训练父参数在新目录与原BC数据混合续训，纯VLA独立评估与专家查询分开。

FlowDAgger官方方案冻结基础policy，通过ODE反演纠正标签学习latent steering，与本轮更新π0.5 LoRA权重的DAgger不同：[Microsoft FlowDAgger](https://github.com/microsoft/FlowDAgger)。基础模型与训练接口来自 [Physical Intelligence openpi](https://github.com/Physical-Intelligence/openpi)。本项目不修改vendor；安装使用非base Conda，数据/权重/代码保留项目目录。

详细状态、失败规则、动作预算和质量语义见统一规范9.3。真实运行报告保存在 `runs/vla_20261001/`，规范与本文会随实际训练/评估结果更新。

verified_lift_takeoff规则2只用于已按approximate_completion完整成功、无恢复的program_generated专家。全程双侧力>0.5N、全部finite和完整interval，最后support后的持续airborne尾段及端点support0，端点抬升≥源配置completion_lift_min_m。允许早期0→supported→0抖动，但最后support及此前整个起飞区间距源frame0 min_z的绝对高度差≤声明的20mm；升高后回落触桌仍拒。资格保存support帧、airborne尾、nonmonotonic和实测高度，原review/严格偏差/collection均不改。服务器10个实际误拒片段规则2均通过，早期最大绝对高度差约1.075mm，这不意味着控制或成功率提升。

新configs/vla_pi05_airport_native16_v3_lora.json计划从真实base参数训练2000步（batch8、worker2、horizon20、save500），输出bc_native16_v3_2000。实际在16个初始化、58个lift资格及官方loader全部审计通过后启动，现已完成2000步保存final1999；结果与后续方案见当前进展。旧native16和native16_v2 partial转换停止保留，不与v3混用。

DAgger真实250步状态文件runs/vla_20261001/dagger_smoke4_250/training_status.json已核实checkpoint_saved，路径dagger_smoke4_250/checkpoints/pi05_airport_dagger_smoke4/training/249，使用父BC4参数和train归一化；这仅证明实际续训与保存，尚不证明任务完成或70%成功率。

服务器 `r1pro-vla` 非base Conda已安装固定openpi及LeRobot0.1.0并通过真实GPU JAX探测。2026-10-01首批四场景核验得到205个train片段；全400来源23956条分片仍保留各自质量与训练就绪标记。首轮250步LoRA设置25步warmup，不能以启动训练或数据转换冒充已保存权重。新release规范check及91项VLA测试通过，后续结果以实际训练状态文件和物理评估为准。

实际部署v7已通过1153项核心测试与1项预期失败，16场景v3转换已启动，2000步训练监督在完整覆盖及官方loader核验后才启动。DAgger250的新3例诊断完整0/3、inverse0：两例因合法实测肘姿超出保守指令margin被rate初始化误拒，一例原始预测超projection envelope。后续修复分离网络target的保守边界与rate中间参考的机械范围，连续收回并保存首次真实差分，不跳变qpos或参考；尚待新物理验证。

v8实际3例初始肘margin均连续3步恢复、inverse0，但任务仍0/3。进一步发现夹爪servo关闭command0与实际双指机械min约4mm被混淆：专家原动作0经MuJoCo原有actuatorctrl饱和合法执行，不应把训练标签改成实测下限。v9恢复相同command语义并明确参考边界、实测机械范围和饱和机制；尚待新纯物理测试。

完整BC16评估将明确使用候选 --actuator-saturation --reference-rate-limit --rate-fraction 0.5；有限模型预测裁剪到合法servo命令范围并连续执行，原始预测、裁剪量和实际轨迹均留证。此模式改变执行器容错，未放宽完整任务物理验收；尚待训练权重与闭环实测，不能宣称70%。

2026-10-01实际更新：native16_v3已完整核验784episode/49470帧/2352H264视频，16初始化和58lift资格全部保留（首4 14/14）。BC2000已进入真实参数更新，step0 loss0.1285、step100 loss0.0728；worker2/项目内JAX缓存正常，当前尚未保存最终权重。冻结v10服务器核心1162通过、1预期失败，posttraining监督等待真实step1999后恢复模型并评估train4/val13/test2；尚不能称任务成功或达70%。启动证据见runs/vla_deploy_20261001/BC_NATIVE16_V3_TRAINING_START_OBSERVATION.json。

2026-10-01最终保存实测：BC16完成2000步，官方checkpoint1999 finalize及params/train_state已核验，真实服务PID1441468独立返回与文件一致的checkpoint身份sha256:78c575c57d5c4fc6e0271e2ddc8f3a18c6a10e45cfab7df485b7e43e66130487，H20/mobile19/20Hz。已执行324个真实预测分片；纯VLA三例评估正在运行，首train4尚处初始化，不将模型保存、loss下降或接口响应当任务成功。证据runs/vla_deploy_20261001/BC_NATIVE16_V3_FINAL_SAVE_AND_LIVE_MODEL.json。新评估与原生双头视频监督在服务器新目录运行，TXT维护服务器路径，不下载全量视频；下一轮仅train fresh-state DAgger标签。

BC16首完整物理结果已核验：train4/val13/test2实际0/3，均vla_operation_step_budget_exhausted，2440帧/122sim秒、2400模型控制ticks，操作数0，inverse_dynamics_calls0且pure_vla_no_inverse_dynamics_verifiedTrue。初始化预测偏离目标；数据state/action/time/prompt逐值匹配，608初始化帧仅占49470帧的1.229%，未发现坐标串位或重复归一化。后续针对技能采样与fresh-state纠正训练；3000步是待实训方案，不能写成效果改善。三例六路原生head视频正在服务器连续物理回放，保留原失败和权重。证据runs/vla_deploy_20261001/BC_NATIVE16_V3_PURE_EVAL_SUMMARY.json。

冻结v12实际服务器核心1177通过/1预期失败，规范check通过。此前v11有6项视频监督测试因辅助源码漏打包失败，保留报告、不用作训练发布；v12已包含依赖并全量重跑。新增技能均衡采样仅训练阶段开关，原norm及仿真守卫不变；服务器Torch真实16000抽样中初始化2645次（原期望197），不代表控制成功。DAgger round1在v10独立新目录实际采集train4/7/8/12，96查询上限；专家短初始化动作保留但H<20不进当前训练，尚待足够标签与下一3000步实际训练。

round2真实训练在新目录bc_native16_v3_dagger_round2_v13_3000_v1，父BC16 final1999/norm、.25DAgger+.75六skill均衡、3000steps/save500/warmup300/worker2；actual complete标签88、原安全拒8，全部init技能。posttraining supervisor1505022等final2999后真实加载，并以v13同三scene纯VLA评估；video supervisor1506958等实际报告生成成功/失败双头，localwatch仅刷新TXT。具体预算与未完成状态见规范1.51。

实际训练step0 loss0.0047/step100 0.0107/step400 0.0082，训练中不能比较为完成率改善；官方CPU loader独立probe确认WeightedRandomSampler、BC每skill总mass.125、DAgger init mass.25，主trainer最终audit仍待保存。EGL实际枚举1才映射physicalGPU0，CUDA trainer1514306与service1441468确在GPU0；所有新render/纯eval监督纠正EGL并记录PID验证，旧完成视频不改，误绑定partial保留failed。独立6skill（同专家唯一初态）基线模型完成1/6：navigate163ticks；init/carry/place/push240预算，grasp157相机guard。旧push episode5缺局部操作目的地是fixture故障，保留零执行记录但不算模型失败；补选有完整可证操作的episode34，后续对比固定0/1/34/2/13/15，不计full任务成功。
