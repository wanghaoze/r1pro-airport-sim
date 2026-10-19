# Tools: Python API and CLI

Import from `r1pro_teleop.experiments.tools`; no Isaac or GPU physics dependency.

| Tool | Contract |
|---|---|
| `diagnose(source, output)` | Read result/events, preserve nested causes; exclusive new output |
| `init_campaign(source, output, development, holdout, regression)` | New collection, preserve ALL source splits, freeze code/assets/packages, preflight chosen scenes |
| `sweep(root, candidates, workers=2, repeats=1, stage=None, checkpoint=None)` | Independent MuJoCo child per candidate/scene/attempt; same scene and seed for comparisons; bounded timeout |
| `CheckpointTree(machine, root)` | `plan`, `save(stage, check)`, `restore(path)`, `run_stage`, `show`; restore only in fresh diagnostic runtime |
| `search(root, seed_summary, space, ...)` | CMA-ES; successful fresh development seed required; incumbent re-evaluated every generation |
| `assess(root, observation=..., evidence=..., hypothesis=..., next_action=..., outcome=...)` | Nonempty structured review; each record in an independent immutable JSON file |
| `history(root)` | Prior assessments, in time order |
| `scene_view(root, trace, output, frame=-1)` | Four native-resolution PNGs from recorded state; diagnostic snapshot, not continuous replay validation |
| `verify(root, candidate_spec, ...)` | One-shot frozen candidate vs baseline, fresh regression+holdout episodes; no export promotion |
| `report(root)` | Campaign provenance, sweep results and verification |

CLI: `python -m r1pro_teleop.experiments --help`. `launch --root ROOT --name NAME --
sweep --root ROOT --candidates FILE` starts detached; `status --root ROOT` reads progress.
An interrupted worker keeps partial HDF5 and logs. A new run ID is required for retries.

Candidate JSON: `{"name":"closer","strategy":"baseline","params":{"base_distance_delta_m":-0.02}}`.
Strategies: baseline, reverse_candidates, full_approach_preview. The preview strategy is
an experimental hypothesis, not an adopted repair (similar v5/v9 changes previously regressed).
Parameters: base distance ±.04 m, lateral ±.05 m, yaw ±.15 rad, rim offset ±.02 m.
These are bounded SEARCH ranges, not guarantees of reachable or safe motion. Original guards apply.
No settings for changing acceptance criteria, primitive time, speed caps, camera or physics.

The above restriction belongs to the campaign search adapter. User-authorized
completion-first policies use explicit frozen configs and the separate
`scripts/control_regression.py --config CONFIG --output NEW_DIRECTORY --indices ...`
runner (`--all` for all400). Its report includes declared primitive/attempt budgets,
first-attempt and within-budget unique-scene completion, strict clean success, recovery,
actual timing costs and selected/full-source budget closure. A finished subset is not a
finished full400 benchmark. Every attempt is a fresh physical Episode from registered
initial state; successful later attempts never overwrite earlier failure evidence.

Built-in stages: settled (fresh), approach (from settled checkpoint), lift (from approach).
Stages pass only if their check AND checkpoint stability pass. They never rank as complete episodes.
`--stage settled` creates checkpoints under each trial's `checkpoints/settled/`.
Supply that full path with `--checkpoint ... --stage approach` in a NEW sweep.
Stages cannot resume a Python stack or claim earlier trace frames as their own.
Custom stage logic must be added to the project before freezing a NEW campaign.

For CMA-ES, `--seed-summary` must be a development sweep summary from this campaign.
Use at least four population members. Bounds cannot exceed the adapter's allowlist.
The winner is only best in measured search comparisons; fresh verification is mandatory.

The explicit approximate configs add effective_acceptance_profile,
approximate_completion_enabled and approximate_deviation_counts to results. They
retain physical trace/video output even when ordinary BC export eligibility is false.
Worker wall timeout is disabled only for this mode; cancellation still terminates
children. This does not change campaign/sweep's original bounded search adapter.


2026-09-30后续控制候选：`airport_approximate_completion_supported_push_retry3.json` 同一配置预声明首轮旧0.18m/15°推动，后两轮COM支撑0.6m/90°；每轮从登记初态完整运行，首个完成停止，结果记录effective_controller_policy和真实动作上限。v64原放置完整参考失败后可私有完整下降+释放20mm碰撞回退，选中记录严格偏差，初抓/导航/push规划仍保持原优先。静态候选通过不能计task_completed，近似验收成功和strict_success分开，必须全400完整预算闭合且至少280唯一任务完成才宣称达到用户70%目标。
