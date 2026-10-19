# 新增300对 Isaac Pick/Place 后台生产（2026-10-17）

范围：在原59对之外新增300条完整Pick→Place来源，导出600个动作片段。32房间单engine双GPU；仅新种子、桌前固定底盘、真实PhysX成功。此生产器不启动训练；所有父来源仍为train，不伪造val/test。较难单臂调盘不纳入本批。

服务器根：`/home/michelle/haoze/r1pro-airport-sim/runs/isaacsim_parallel_pickplace300_20261017_v1`。

- 控制脚本：`scripts/supervise_isaac_pickplace300.py`；CPU候选：`scripts/prepare_isaac_parallel_candidates.py`。
- 控制冻结目录：`releases/isaacsim_pickplace300_control_20261017_v1`；原生、验收及导出仍用`releases/isaacsim_parallel_live_20261016_code_v61`。
- 2026-10-17实际启动guard PID1996949/start_ticks43047257，监督PID1996950/start_ticks43047260；身份另存`guard.identity.json`、`supervisor.identity.json`，这些PID是启动快照，后续须核验。
- `production_status.json`记录每10秒心跳、阶段、实际合格数量、磁盘；`guard_status.json`、`guard.log`、`supervisor_attempt_N.log`记录外层生命周期。
- 每批`batch_NNN`含32房间、CPU候选/几何/完整IK预检、原生实际退出收据、独立导出退出收据、视频/trace与验收。
- 最多16批，每批最多128个CPU候选，取32个通过者；不同种子不回放旧轨迹。单批失败保留证据并进入下一批，不能无限重跑。
- 外层异常最多3次恢复，30/60/90秒退避；每批监督异常最多3次10/20/30秒退避。活跃子程序先等真实收据，闭合产物复用；有健康原生引擎时不另开引擎，独立全局/作业锁。
- 每批开始需至少40GiB空闲；空间不足停止，不删除旧产物。上一宽32批全部产物约330MiB，16批约5.2GiB，只是历史量级估算，不包括后续训练缓存。

接口：生成过程中`progress_manifest.json`为ready=false。只在累计300合格来源后写不可变`dataset_v1/manifest.json`和`data_ready.json`（最终SHA）。manifest schema=`parallel_pickplace_production/1`；`source_pairs=300`、`action_segments=600`、`pairs`为原导出catalog的`frozen_batches`条目，包括每pair manifest路径与2个完整segment。超出的合格pair记录为`unused_extra_pairs`，不重复计入目标；原59对计入数为0。父split全部train。

`batch_NNN/native/dataset_viewer.html`查看每批合格片段。总入口：http://100.104.0.108:8776/parallel_pickplace300_20261017_v1/index.html 。

历史两批吞吐83–87合格对/小时（物理、录制、导出，不含启动加载），300对初步预算4–5小时；尚非本轮实际完成ETA。必须依据本轮状态修订。

验证：非base本地`python -m pytest tests/test_isaac_pickplace300.py -q` 5通过，覆盖目标截取、历史源拒绝、重复来源、缺片段、split保持。生产已实际处于CPU预检，不能说已生成300条或已训练。
`2026-10-17 14:13 SGT`：首批32/32预检通过；实际原生PID2006582/start_ticks43059320，argv/cwd核验一致，状态room_grid_cloned。批监督PID2006580，当前完整来源仍0，未训练。
