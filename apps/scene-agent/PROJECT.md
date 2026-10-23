# R1 Pro Scene Studio

## 2026-10-19: English interface and automatic evaluation

The interface, system replies and basic English commands are now in English; existing Chinese commands remain supported. Historical receipts are translated only for display. After training, an enabled automatic evaluation selects the latest fully saved final checkpoint only after actual target updates and a successful training exit receipt. It runs the registered 32-room policy-only VLA diagnostic, then fixed real Test MSE against the registered real-only 10,000-step baseline. New training recipes enable this by default; current training has a separate owner-only activation.

`gpu/auto_evaluation.py` persists checkpoint selection and deterministic child IDs under the scheduler lock. Repeated polling and bridge restarts do not duplicate jobs. `app/AutoEvaluations.tsx` displays status, Pick/Place success numerator and denominator, infrastructure failures and coverage, plus joint/gripper MSE and percentage differences. Empty or incomplete evaluations do not show invented success rates. Videos and traces remain on the GPU. These 32 rooms share a training parent scene, so success is a diagnostic, not held-out generalization. The native launcher now inherits the existing approved Isaac bootstrap environment; old failed runs remain unchanged. Contract: root specification 1.175.

ChatGPT Sites 网页 + GPU 服务器主动轮询服务。站点保持平台当前访问范围；用户记录要求登录，GPU 作业提交仅限服务器配置的项目所有者。默认使用 2026-10-17 Isaac32 batch_001 登记初态。原始 CAD 网格用于静态可视预览，不能代替原生物理、相机或模型评测。

## 已实现

- 默认完整实验室原材质，机器人黑银分区、酒红托盘与浅色标识；辅助网格默认关闭。恢复原色支持选中房间或全部，保留版本与改色能力。浏览器室内光照仍为静态可视预览，不等同Isaac原生渲染。

- 32 房间、机器人底盘 XYZ 中的平面位置/Yaw、托盘 XYZ/Yaw、机器人外壳与托盘颜色。
- 明确中文指令解析；配置 Sites secret `OPENAI_API_KEY` 后使用 Responses API。未配置时页面标为基础指令模式。密钥只可经 OpenAI Developers 连接与原生 Sites secret 工具配置，不放浏览器。
- 用户隔离的 D1 草稿、版本历史、恢复、JSON 导出；修改以 revision 比较防止多窗口覆盖。
- 数据来源域与 train/val/test 可见；真机/仿真 0–100% 配比、登记数据集、1–100000 训练步数可配置。独立新任务排队，当前 DEC-055 训练不改；train-only 归一化，按时长加权 BC。
- 每10秒显示实际梯度进度、loss采样、检查点、当前阶段和分范围ETA；心跳过期暂停ETA，完成与断连明确区分。
- 已闭合检查点支持固定真实Val/Test配对MSE：全部20Hz帧、相同H20/noise/valid mask，关节rad²、夹爪mm²与首步分列。
- Isaac纯模型闭环：选房间/动作预算，固定底盘执行掩码、双臂夹爪原模型动作，无教师/IK回退。当前32房间属于train父场景，结果为诊断，不能称held-out泛化。
- GPU outbound poll / immutable job receipts / single-instance lock / heartbeat / real exit code；不执行任意 shell 或路径。

## 状态与边界

`scene.sync` -> queued -> claimed -> draft_synced：仅新目录 `native_config.draft.json` 与纯视觉颜色侧文件。旧预检失效；目前不启动原生仿真、不修改正在运行的32房间、不回灌训练数据。颜色侧文件尚需原生适配与前后物理/相机指纹验证。

`training.attach` -> attached_existing 或 blocked：复核 PID/start ticks/argv/cwd、状态与心跳后关联既有监督器。新增来源必须完整闭合、媒体/来源清单冻结等原门满足才由既有流程自动训练。旧关联入口不启动第二份训练或改变原数据、模型、容差；新增 training.create 在独立目录排队，等待GPU资源释放。

`training.plan` -> planned；`training.create` / `evaluation.mse` / `evaluation.vla` -> queued -> claimed -> waiting_gpu -> preparing/running -> completed/failed。completed为流程闭合，必须另读模型/物理结果。数量达标不等于来源复核通过，loss不等于成功率。

`gpu/studio_backend.py`登记数据、检查点并调度；`studio_job_runner.py`实际wait子进程，单GPU任务锁。项目脚本 `studio_prepare_training.py`、`studio_mse.py`、`studio_vla_evaluate.py`分别准备独立训练、离线配对和原生闭环。GPU源码使用独立release，不修改已有release、清单或checkpoint。

GPU 身份 `xinmatrix-scene-agent-v1`，调用 `/api/worker` 需要 Sites service bearer + `X-Worker-Token`。用户 API 只接受平台登录身份，service token 不被冒充用户。任务回执可重复确认，执行前查落盘收据避免重复；连续网络失败最多3次，保留最终退出与最后心跳。

## 开发和验证

Node >=22.13，项目自己的依赖目录。`npm run dev` 默认本机5173端口，预览登录使用 starter 的本地模拟身份。`npm run build` 生成 Workers 包；D1 使用 `db/schema.ts` / `drizzle/`。正式部署使用 Sites 原生发布工具，保持平台当前受众，不为服务连接扩大访问范围。GPU_OWNER_EMAIL / GPU_WORKER_TOKEN为服务端配置。

`node --experimental-strip-types --test tests/core.test.ts tests/training.test.ts` 验证指令范围、坐标单位、字段拒绝、训练门；项目非base Python运行 `gpu/test_worker.py` 验证回执幂等、新草稿隔离和监督器缺失拒绝。

新增训练合同以 `lib/training.ts` 与根统一规范1.174为准，历史v1导出仅供原场景草稿范围参考。模板与执行合同位于项目根 `exports/web_scene_agent_v1/`，本项目运行实现位于 `lib/`、`app/api/` 和 `gpu/worker.py`。精确场景约束见根 `docs/SCENE_TASK_SPEC.md`。

模型接口参考：[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)。模型输出仍须通过服务端字段验证，不可执行模型返回的命令字符串。

## MSE figure export — 2026-10-19

Completed evaluations produce immutable derived plots on the GPU host without rerunning inference: joint MSE in rad²/deg², joint RMSE in degrees, separate gripper MSE/RMSE, and every episode's 4×4 first-step trace. Saved arrays and protocol hashes are checked against measured reports. The bridge publishes PNG/CSV/ZIP artifacts to R2 with checksum keys; authenticated owner downloads are available from the training panel. Figure export state is independent of model evaluation success. Raw NPZ/video stays on the GPU host.
