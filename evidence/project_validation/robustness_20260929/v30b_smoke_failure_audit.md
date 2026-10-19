# v30b completion smoke: actual failure audit

Snapshot 2026-09-29T09:37:31.598815+00:00; queue stage `completion_full400`.
Finalized actual results 8/8; task_completed=6, strict_success=1. Pending indices: [].

No H5 read, physics probe, model/source change or rerun. Only actual direct attempt result/events enter this report. Previews are summarized as diagnostics and never counted as actual success. Missing results remain pending; completion-profile tasks and strict successes are separate metrics.

## Actual v30b outcomes

|Case|Task completed|Strict success|Warning events|Terminal nested failure|Last operation/phase|
|---|---|---|---:|---|---|
|4|True|False|1|none|3 / verified|
|5|True|False|22|none|4 / verified|
|6|False|False|46|ik_unreachable|4 / descend|
|7|True|False|23|none|4 / verified|
|8|True|True|0|none|3 / verified|
|16|True|False|2|none|3 / verified|
|218|False|False|6|illegal_collision|4 / close|
|310|True|False|42|none|4 / verified|

Failure groups: `{"ik_unreachable": 1, "illegal_collision": 1}`. Full result flags, acceptance deviations, warning-code counts/first/last warnings, terminal failure detail, last primitive failure and selected preview summaries remain in the paired JSON.

## Prior v28 step_preview failures: possible influence, not predictions

v28 step_preview completed28 actual cases,18 clean successes and10 failures. The new profile changes acceptance and bounded deviation handling; any improvement must be labeled task completion under the declared profile, not stricter control or old-contract success. Five of these10 failures belong to the8-case smoke:5,6,7,218,310. Indices147/156/160/256/304 are outside the smoke.

|Case|Actual prior failure/phase|Possible new-profile effect and uncertainty|
|---|---|---|
|5|push_accuracy_not_met / verified|Final push verification failed; declared position/yaw/gap tolerances may admit it. Error lacks exact failed metric, so no sufficiency claim; supported/released/stationary final window still required.|
|6|contact_handoff_aborted → primitive_postcondition_failed / adjust|Push postcondition stable_frames0 with table8/contact10.98N, recorded yaw -5.0658deg against0 target (slightly beyond strict5deg). New10deg may address this particular predicate, but later release/final outcome remains untested.|
|7|contact_handoff_aborted → retained_contact_lost / adjust|Retained table contact absent for exact 100 steps=200ms. New bounded300ms grace may pass this check if geometry/force remain valid; continued loss beyond300ms still fails. This changes policy, not actual support evidence.|
|147|push_accuracy_not_met / verified|Final push verification failed; declared position/yaw/gap tolerances may admit it. Error lacks exact failed metric, so no sufficiency claim; supported/released/stationary final window still required.|
|156|contact_handoff_aborted → retained_contact_lost / adjust|Retained table contact absent for exact 100 steps=200ms. New bounded300ms grace may pass this check if geometry/force remain valid; continued loss beyond300ms still fails. This changes policy, not actual support evidence.|
|160|contact_handoff_aborted → retained_contact_lost / adjust|Retained table contact absent for exact 100 steps=200ms. New bounded300ms grace may pass this check if geometry/force remain valid; continued loss beyond300ms still fails. This changes policy, not actual support evidence.|
|218|measured_joint_overspeed / pregrasp|Measured velocity ratio 1.01477208; within new1.05 ceiling at this instant. Sustained-excursion duration and later physical outcome remain unknown; max-speed alone is not completion.|
|256|contact_handoff_aborted → retained_contact_lost / adjust|Retained table contact absent for exact 100 steps=200ms. New bounded300ms grace may pass this check if geometry/force remain valid; continued loss beyond300ms still fails. This changes policy, not actual support evidence.|
|304|contact_handoff_aborted → retained_contact_lost / adjust|Retained table contact absent for exact 100 steps=200ms. New bounded300ms grace may pass this check if geometry/force remain valid; continued loss beyond300ms still fails. This changes policy, not actual support evidence.|
|310|measured_joint_overspeed / pregrasp|Measured velocity ratio 1.01309197; within new1.05 ceiling at this instant. Sustained-excursion duration and later physical outcome remain unknown; max-speed alone is not completion.|

The smoke may take a different earlier decision path under completion-first; comparing these terminal old events alone cannot prove an identical-prefix causal outcome. Actual v30b reports will supersede these conditional expectations.

## Final smoke outcome and new bottleneck

All8 actual episodes finalized:6 task_completed (4,5,7,8,16,310),1 strict_success (8),2 failures (6 IK;218 illegal_collision). This is smoke evidence for the declared completion profile, not a400-scene estimate or strict-success improvement.

The four targeted geometry cases have actual closed-loop evidence:5,7,310 completed their whole episodes. Case6 passed the former operation2 overhang boundary, completed operation3, then failed operation4 with a new placement reachability problem. No static SAT result is counted as an episode.

Case6: frame2977,148.85s, tray1→slot2, staged[.85,-.615,.8]. Arrival trayXY[.841795,-.254213] is about361mm away laterally; measured bilateral forces13.308/12.454N. Independent alignment planning rejected left22.344mm; combined descent planning rejected left39.599mm (rotation.042105rad). Both were before physical descent; no budget was consumed. The actual18-probe fallback ran:9 nominal-heading candidates rejected IK (best left22.030mm),9 measured payload-heading candidates (~89.87deg) rejected robot_geom_17/front_right table collision with52.503mm penetration. No correction was selected, so original planning failure was retained.

Source path: Machine.carry_place → primitives.place → _plan_place_descent/object_points → Runtime.cartesian.advance → solve_pair. This is a geometric reachability failure, not missed completion tolerances or missing fallback. Next bounded diagnostic should test whether a collision-free destination stance exists for this measured grasp, or whether grasp selection must account for destination serviceability. Merely widening IK tolerances or repeating all18 candidates is unsupported. Production full400 remains frozen and unaffected.

Case218 remains illegal_collision (robot_geom_45/tray_0__tray_contact_012,0.205mm penetration), recovery_used=True. It is not reclassified by footprint acceptance.
