# Airport MuJoCo experiment agent contract

You improve the R1 Pro airport tray controller using measured simulation evidence.
Read AGENTS.md, README.md, docs/SCENE_TASK_SPEC.md and this directory's tool_router.md.
All output is simulation/program_generated. This environment has no real robot driver.

The deliverable is a reviewed code/config patch, an immutable campaign, assessments,
fresh end-to-end verification, and a report of successes, failures and timing.
The tools run experiments; they do not themselves call an LLM or autonomously edit code.
Codex or another explicitly authorized coding agent supplies hypotheses and patches.

Use r1pro_teleop.experiments.tools and the CLI documented in tools.md. Do not import
EmbodiedSWE or depend on humanvideo. Do not modify an existing collection or vendor.
Run/install only in a non-base Conda environment. Freeze a new campaign after code changes.

Strict runs retain their original criteria. On 2026-09-29 the user explicitly prioritized
complete simulated tasks over strict precision and tracking conformance. New runs may
use the declared completion_first profile with bounded tolerances and logged strict
deviations. Report task completion and strict clean success separately; a profile change
is not evidence of improved control. Never silently change an existing run's criteria.
Collision, camera integrity, penetration, finite dynamics and final stable support remain
required; do not turn off physical simulation to produce a completed trajectory.
For completion_first, use disjoint rotated footprints and their actual boundary distance
for placement gaps, not a single belt-axis enclosing projection. A small supported
overhang is acceptable when the center remains over a table and actual released stable
support is verified. Keep the original projected/full-footprint strict result separately;
planning sweeps and collision geometry are unchanged.
For the explicit 2026-09-30 user-authorized approximate_completion mode, section 6.1
of SCENE_TASK_SPEC.md overrides the ordinary completion limits above. Generation,
phase, Episode and primitive elapsed time are diagnostic, not failure conditions.
Use finite rolling reference-search windows; keep nominal execution pacing rather
than stretching motion to the search ceiling or suddenly accelerating a former path.
Keep strict planning clearance first. Record bounded live collision/support/precision
deviations instead of rejecting a complete trajectory solely for intermediate drift.
Nonfinite dynamics, severe penetration, cameras and joint structure remain guarded.
Release may begin only when the measured collision-vertex bottom is within 2cm of
the table; real gravity/contact execution must still end with three released stable
trays approximately at the front goals. The approximate operation/reservation/final
layers use the same signed footprint gap with overlap cap min(configured collision
penetration, 20mm), checking every tray pair. Ordinary profiles stay unchanged.
Approximate task completion is separate from strict success and ordinary BC eligibility;
only strict_success without recovery may mark an approximate trace training_candidate.
Compare declared configs independently and preserve every failed attempt/video.
Do not claim better control solely because acceptance is broader. A 70% claim still
requires all400 fresh unique-scene results and closed attempt budgets.

No grasp welding, object teleportation, external forces or hidden resets within episodes.
Checkpoint restore is allowed ONLY at the start of a separate diagnostic stage process.
Checkpoint stages never count as complete-task success or enter training datasets.
Final verification always starts from the original registered scene and runs forward.

Report the declared primitive budget and its exclusions in every timing report. Strict
runs retain three seconds. Completion-first runs may explicitly declare up to six seconds
in a fresh collection; the current retry candidates use five seconds. Record an original
strict deviation when actual physical execution exceeds three seconds, not merely because
the configured budget is longer. Initial grasp, base navigation, push release/retreat,
final stability, and CPU planning are excluded;
ordinary endpoint alignment has a separate budget. Full-episode time includes physical
navigation/grasp/settling. Do not promise all scenes are feasible in three seconds.

Do not tune on the held-out group. Verification freezes the candidate before exposing
held-out results. After a failed verification, those scenes are development evidence;
another optimization cycle requires a new untouched holdout and a new campaign.
Report known regressions even if aggregate success increases. A partial improvement or
passing tests is not full physical success. Native video/export acceptance is a separate gate.

The optional physical push preview uses independent model/data/controller copies at a
supported live boundary. Try the original policy first and at most three declared control
policies; execute the selected policy once on the unchanged live state. Preserve failed
preview evidence separately. Preview passes never count as actual episode successes, and
preview time consumes the original attempt wall budget. Report measured planning cost;
do not call this real-time control. Never checkpoint an active preview or temporary policy.

Development may preflight only its explicitly selected registered scenes. Every selected
scene must pass the unchanged full preflight before generation; retain all 400 source IDs,
split and hashes, and report unchecked scenes as unchecked. A 70% claim requires fresh
complete results for all 400 unique scenes and at least 280 completed tasks under the
declared acceptance profile and attempt budget. Report recovery and strict clean success
alongside that rate. An enriched regression subset is not a full-source estimate.

With multiple attempts, stop a completion-first scene at its first actual completed task,
including a completed physical recovery. Keep BC export qualification separate. Report
first-attempt completion, unique completed scenes within the declared budget, total
attempts and physical/wall costs. A final budget rate requires closed scene budgets and
a finished runner; 400 initial results do not close three-attempt runs. Retain every failed
attempt and its native head-camera evidence even if a later attempt succeeds.

The optional 80mm held-IK bound is a planning candidate, not a completion certificate.
Keep the original seed search first, empty-arm and retained-contact tolerances unchanged,
and actual grip/lift/collision/final-placement checks active. A returned solver query can
later be discarded; do not describe its residual as the maximum of an executed path.
The default-off direct-buffer policy may explicitly select a different temporary landing
point with proven source/blocker context. Record that policy change, execute the new
operation physically and preserve the final three-slot goals.

Completion-first may use a bounded adaptive reservation for the last unfinished tray.
Its absolute target stays within the original nominal tolerance; keep already placed
trays fixed, carry that target into the actual next operation, and validate the complete
task against the original goals. Geometric reservation evidence does not prove future
grasp, IK or contact success. Save reservation identity in checkpoints and isolate it
in private previews. A free-hand opening candidate must still pass full trajectory
planning and execute physically within the declared action budget.

Compare complete geometric candidate sets before using relaxed IK as a fallback.
Accepting the first relaxed direction can bypass a later original feasible direction
and regress a previously completed task. Report such regressions, not only new successes.

The optional retained-support integer clock corrects only the inclusive150ms numeric
boundary while preserving the original20Hz contact observations. It never resets on
substep recontacts. Keep float-clock and integer-clock baselines separate and report
changed decisions explicitly; numerical acceptance corrections are not evidence of
improved contact dynamics. Checkpoint/preview copies must preserve the complete active
clock context and reject inconsistent or missing enabled-clock state.


2026-09-30后续控制候选：`airport_approximate_completion_supported_push_retry3.json` 同一配置预声明首轮旧0.18m/15°推动，后两轮COM支撑0.6m/90°；每轮从登记初态完整运行，首个完成停止，结果记录effective_controller_policy和真实动作上限。v64原放置完整参考失败后可私有完整下降+释放20mm碰撞回退，选中记录严格偏差，初抓/导航/push规划仍保持原优先。静态候选通过不能计task_completed，近似验收成功和strict_success分开，必须全400完整预算闭合且至少280唯一任务完成才宣称达到用户70%目标。
