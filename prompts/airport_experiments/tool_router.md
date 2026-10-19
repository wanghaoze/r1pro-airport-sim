# Workflow and tool selection

Adapted from EmbodiedSWE eval/prompts/tool_router.md, revision d34837e (Apache-2.0).

1. Inspect existing failure audits, scene versions, code and `history()`. Read the nested
   cause of wrappers such as contact_handoff_aborted. Compare `failure_chain` and
   `underlying_failures`: a zero-motion path rejection inside a handoff wrapper is
   not observed loss of contact. Inspect primitive duration before assigning a
   physical cause. If visual geometry is needed, render
   with `scene_view` and actually open the images before making a visual claim.
2. Establish a fresh baseline, using disjoint development, regression and holdout groups.
   Reproduce known successes and representative failures. Include stacked and edge cases.
3. Declare stages. Save checkpoints only at settled, checked stage boundaries using
   `CheckpointTree.plan/save`. Keep integration state, targets, FSM/contact context and RNG.
   Each stage probe starts in a new process and explicitly declares fresh/checkpoint origin.
4. Choose the branch matching the uncertainty:
   - Different grasp side, stand-off family, ordering or contact strategy: named `sweep`.
   - A viable maneuver exists and only constants are uncertain: `search` (CMA-ES).
   - Neither condition holds: diagnose first. Increasing retries is not a diagnosis.
5. Strict campaigns keep their original guards. For the user's completion-first objective,
   declare the profile and budgets before running, score unique complete tasks first and
   time second, and report original strict conformance separately. Keep the profile's
   physical guards. Never reward a failure for running longer. Stage passes are separate.
6. Record observation, evidence path, hypothesis, rejected approaches and next experiment
   with `assess`; consult this history before trying another change.
7. Freeze the winning candidate and run `verify`: fresh baseline/candidate comparisons on
   protected regression cases and 2–3 untouched holdouts (the smoke minimum is one holdout).
   Report every lost baseline success. The strict campaign gate rejects such losses;
   completion-first comparisons prioritize aggregate complete tasks under a predeclared
   budget and expose regressions separately. A checkpoint probe cannot replace verification.
8. Integrate a verified improvement into a NEW code version/collection. Run relevant core
   tests before physical episodes. Keep failure evidence and original scene split. Export
   only through the existing independent native-video/LeRobot validation pipeline.

Launch long sweeps with `launch`, inspect `status` and logs, and wait for real results.
Do not equate a command's zero exit status with all episodes succeeding.

The campaign/sweep adapter retains its three-second contract and parameter allowlist.
For completion-first five-second/three-attempt candidates use a new frozen release with
`scripts/control_regression.py --config ... --output NEW_DIRECTORY`, selected preflight
and actual fresh Episodes. Close every selected scene's stopping budget and the runner
before treating its budget rate as final. Use `--all` for the full400 denominator;
development subset rates are explicitly separate. This route does not modify campaigns.

For this project's 70% target, require the all-400 gate before declaring the target
achieved. Strict historical campaigns use their predeclared stratified holdout and
preservation gates. Under the user's completion-first priority, predeclare development
ranking by unique completed tasks, first-attempt completions and cost; report lost and
added cases without silently retaining the old zero-regression veto. The small tool smoke minimum above only checks that
the experiment workflow runs. Freeze both code and candidate selection rules before
reading verification outcomes; record which holdouts have already been consumed.

Use `preflight --scene-ids ...` for a bounded development slice, and pass that same slice
to generation. New cases require their own preflight; registration is not validation.
For a pure duration failure, inspect limiting joints, derivatives and unnecessary path
reversals before changing geometry. A default-off, bounded structural fallback must retain
the original successful path and all timing, clearance and physical acceptance checks.

If auditing retained-support timeouts, distinguish a true interval greater than150ms
from floating accumulation at exactly150ms. Compare a frozen float baseline, an otherwise
identical integer-clock baseline and the integer-clock control candidate. Do not combine
their gains or silently reinterpret20Hz observations as continuous500Hz support.

For the September30 approximate mode, use the explicit approximate configs through
control_regression in a new release/run. Time is diagnostic; full tasks still require
real final release, table contact and stable layout. Keep strict planning first,
then test bounded alternatives as complete private references before actual execution.
Read the signed-gap and live-collision records together before calling a near-neighbour
case inaccurate or physically failed. Record the effective_acceptance_profile and
compare the conservative IK, expanded IK and legacy-handoff variants separately;
never pool their attempts to improve a single-config percentage. Use core tests,
representative full Episodes, then a fresh all400 budget before a 70% claim.


2026-09-30后续控制候选：`airport_approximate_completion_supported_push_retry3.json` 同一配置预声明首轮旧0.18m/15°推动，后两轮COM支撑0.6m/90°；每轮从登记初态完整运行，首个完成停止，结果记录effective_controller_policy和真实动作上限。v64原放置完整参考失败后可私有完整下降+释放20mm碰撞回退，选中记录严格偏差，初抓/导航/push规划仍保持原优先。静态候选通过不能计task_completed，近似验收成功和strict_success分开，必须全400完整预算闭合且至少280唯一任务完成才宣称达到用户70%目标。
