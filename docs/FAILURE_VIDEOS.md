# 失败 case 头部视频取证

`scripts/collect_failure_videos.py` 为已结束失败 attempt 创建独立诊断证据，不修改 collection，不进入 LeRobot 或训练清单。每个 case 独立服务器进程，默认 2 个并发（最多 4 个）；单个失败不会中止其他下载。请在批次结束后运行：没有 `result.json` 的仍在运行 attempt 不作为完成案例。

服务器使用项目非 base Conda 环境。已冻结 release 的脚本也受规范哈希保护，不得覆盖；把新版诊断脚本放在服务器项目根 `tools` 下，通过 `--remote-script` 调用。工具设置 `AIRPORT_PROJECT_ROOT` / `PYTHONPATH` 指向原 release，确保物理回放依赖正确的冻结代码：

```powershell
.conda/experiment/python.exe scripts/collect_failure_videos.py collect `
  --host michelle@100.104.0.108 --identity <临时私钥路径> `
  --remote-project /absolute/project/release `
  --remote-script /absolute/project/tools/collect_failure_videos_20260929.py `
  --remote-python /home/michelle/miniconda3/envs/r1pro-tray/bin/python `
  --root /absolute/new/collection --release release_name --run run_name --workers 2
```

服务器产物位于该 release 的 `runs/failure_video_render/<collection路径哈希>/<scene_id>/<attempt>`；本机位于本项目 `runs/failure_videos/<release>/<run>/<scene_id>/<attempt>`。可重复 `--scene-id` 分配 case 子任务；避免多个子任务同时处理相同 attempt。密钥只以文件路径传给 SSH，不读取、不复制、不打包。

`--root` 也支持实验 campaign：自动遍历 `experiments/<batch>/<candidate>/<scene>/<attempt>`，使用其 `collection` 物理配置回放；本机 attempt 目录附加 `__<batch>__<candidate>` 防止覆盖同场景其他实验。已通过的局部 stage 不误计为失败。所有版本独立产物，不跨版本复用物理代码。本机下载保留至少 2 GiB 空闲；不足时保存下载失败日志，服务器视频继续保留，须释放空间后再次运行。

消融组使用 `--run ablation --variant baseline`（或 substep/payload/alternate），保存至 `release/ablation/<variant>/<scene>/<attempt>`，不同参数组不会覆盖。SSH exit255连接重置有限重试5次，间隔2/4/8/16秒；恢复连接时等待同case原render完成并复用它的结果，避免断线后重复渲染。死进程遗留锁明确报错，不能自动删除失败证据。文件下载亦有限重试，仍使用完整SHA校验。

## 视频与失败证据契约

- 双头部 `head_left.mp4`、`head_right.mp4` 均为原生 1920×1536、20 fps、H.264 CRF18，不裁剪、缩放、变速、贴字。腕部不渲染。
- 渲染前用项目 `select_r1pro_gpu.py` 按 PCI 身份把物理 GPU0 映射到 EGL ordinal，manifest 保留设备 UUID/PCI；不能把 EGL ordinal 0 当作 `nvidia-smi` GPU0。编码线程限制为每路2个，BLAS/OMP各1。
- 复用 `Replay(diagnostic=True)`：仅一次恢复初始积分状态，逐控制间隔执行 MuJoCo 积分并核对 qpos/qvel；不逐帧写姿态。修改仅限该 Replay 实例的相机选择，物理回放逻辑与误差阈值不变。
- 保留每个已记录观测，包括不完整动作间隔之前的最后观测；不捏造未记录的失败后状态。低纹理帧保留并计数。回放发散明确记录 `render_failed`，不通过瞬移掩盖。
- 复制 result、派生 events.json、原始 events.jsonl、segments、exception、task_dag（存在时），保留视频生成错误日志，manifest 标记 `simulation/program_generated` 和 `training_candidate=false`。原始 JSONL 含 primitive 执行与拒绝原因，不用派生语义事件替代它。
- 缺失 trace 或零观测分别记录 unavailable 原因，不能制造视频或算成“已获取视频”。编码完成后验证原生分辨率、fps、codec及帧数。

每个文件记录字节数和 SHA-256。下载先写 `.partial`，核对后原子改名；重启时跳过已正确下载的文件。服务器完整证据也核对来源 result/trace 哈希后复用。已有证据损坏或来源变化时拒绝覆盖，要求检查原因并使用新运行目录。崩溃遗留 `render.lock` 需先确认原进程已退出，再人工清理锁，不能盲目并发重渲染。

每例仅对缺失或校验未通过的文件建立一次 SSH tar 传输，减少多文件握手。传输按声明文件大小加 tar 固定开销限制总字节；同时为临时归档、逐文件解包及 2 GiB 预留检查空间。只接受 manifest 列出的安全 basename、普通文件和准确字节数，拒绝额外/重复条目、路径逃逸、软链接与硬链接；不使用通用解包命令。逐文件 SHA 通过才原子替换；已有正确文件不写入。归档成功后只删除本次可丢弃传输包，失败包、partial 与日志保留用于排查。

总清单 `index.json` 启动时列出全部 pending，每完成一个 case 原子刷新，独立记录 complete、unavailable、render_failed、download_failed；中断时也可看未完成名单。指定 `--scene-id` 的子任务使用独立 `index-<filter_hash>.json`，避免不同子任务覆盖总清单。默认按实际 trace 帧数从短到长调度，提高有限本机空间下的完整 case 覆盖。出现任何非 complete，collect 返回 2；诊断状态不能计入控制成功率。初始化失败没有可见轨迹时仍保留 case 目录和原因。网络错误不会把旧下载标记为当前通过。

## 本机逐 case 总索引

运行 `.conda/experiment/python.exe scripts/collect_failure_videos.py index --root runs/failure_videos --verify-hashes`，只读取已有文件并生成 `failure_video_index.json` / `failure_video_index.csv`，不复制或改写视频。索引合并每组总清单、分区清单、只读 `index-inventory.json` 与下载 manifest，按 release/run/variant/scene/attempt 隔离；campaign 额外保留 trial 和独立 attempt 目录。

每行列双头绝对路径及存在状态、预期 SHA、校验状态、控制失败原因、取证问题、服务器证据目录、源 collection 和 result/events 路径。使用 `--verify-hashes` 时重新校验当前本机文件；省略时明确标记 `verified_at_download`，不能当作此次重新核验。`server_only_or_partial` 表示已知服务器渲染完成但本机未完整通过；`pending` 的服务器状态为 `not_yet_verified`，不虚称服务器已有视频。`unavailable` 保留无 trace / 零观测的确切原因。索引是带 UTC 时间的快照，运行中的 case 后续需重新生成。

历史视频未收录原始日志时，用相同连接/路径参数运行 `supplement-events`（代替 `collect`，建议 `--workers 1`）。仅补已完成本机主证据的 case；主传输未结束标记 deferred，之后重试。该命令只读取服务器原 `events.jsonl` 并校验下载，**不启动 Replay、不重写已有 manifest/download.json、不复制视频**。独立 `events_supplement.json` 保存源路径、字节数、SHA 和下载状态，使用独立传输临时文件与日志；源日志缺失明确记为 unavailable。总索引新增 `events_jsonl_path`、SHA/校验状态、源路径和问题字段，与视频校验分开呈现。服务器原日志原样保留。
