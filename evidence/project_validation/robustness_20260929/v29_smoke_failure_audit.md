# v29 completion smoke: actual failure audit

Snapshot 2026-09-29T09:14:25.238282+00:00; queue stage `smoke_needs_repair`.
Finalized actual results 8/8; task_completed=3, strict_success=1. Pending indices: [].

No physics probe or rerun. Actual direct attempt result/events enter the outcome counts; targeted last41 H5 pose/contact samples were read only for the four finalized geometry failures. Previews are summarized as diagnostics and never counted as actual success. Missing results remain pending; completion-profile tasks and strict successes are separate metrics.

## Actual v29 outcomes

|Case|Task completed|Strict success|Warning events|Terminal nested failure|Last operation/phase|
|---|---|---|---:|---|---|
|4|True|False|1|none|3 / verified|
|5|False|False|0|push_accuracy_not_met|4 / verified|
|6|False|False|23|placement_needs_correction|2 / verified|
|7|False|False|1|push_accuracy_not_met|4 / verified|
|8|True|True|0|none|3 / verified|
|16|True|False|2|none|3 / verified|
|218|False|False|6|illegal_collision|4 / close|
|310|False|False|20|push_accuracy_not_met|4 / verified|

Failure groups: `{"push_accuracy_not_met": 3, "placement_needs_correction": 1, "illegal_collision": 1}`. Full result flags, acceptance deviations, warning-code counts/first/last warnings, terminal failure detail, last primitive failure and selected preview summaries remain in the paired JSON.

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

The smoke may take a different earlier decision path under completion-first; comparing these terminal old events alone cannot prove an identical-prefix causal outcome. Actual v29 reports will supersede these conditional expectations.

## Read-only terminal geometry diagnosis

Eight actual smoke results finalized: 3 task completions, 1 strict success; 5 failures. Case218 has illegal_collision and remains separate from geometry acceptance. No new physical trial was run.

|Case|Terminal reason|Position error mm|Yaw deg|Belt projected gap mm|Actual adjacent Euclidean gaps mm|Finding|
|---|---|---:|---:|---|---|---|
|5|push_accuracy_not_met|8.843|2.331|[7.588, -0.514]|[7.635, 15.42]|Rotated rectangles are disjoint despite negative belt projection; physical table support and release are present.|
|6|placement_needs_correction|4.724|0.085|[19.285, 15.0]|[434.664, 62.59]|Corner overhang only 0.116mm; COM supported, physical table contacts4, released/stationary.|
|7|push_accuracy_not_met|8.267|2.273|[9.375, -2.565]|[9.415, 15.881]|Rotated rectangles are disjoint despite negative belt projection; physical table support and release are present.|
|310|push_accuracy_not_met|11.391|2.043|[7.037, -7.812]|[8.187, 5.111]|Rotated rectangles are disjoint despite negative belt projection; physical table support and release are present.|

For5/7/310 the final41 samples have maximum penetration4.90/6.68/4.90 micrometres and no recorded illegal collision. Raw trace lacks pairwise tray contact lists, so this audit does not invent them. Case6 is only operation2: other trays are not yet in final slots and its large actual neighbour distances do not establish task completion.

Proposed v30 completion-only acceptance: COM within support table plus existing actual support/release/stable window; require all rotated footprint pairs SAT-disjoint and adjacent shortest Euclidean boundary distance at most effective5cm. Strict keeps full-footprint slot planning and belt-axis gap acceptance. Preserve strict deviations; do not relabel historical results or infer future full-episode success. Motion planning swept-footprint checks remain unchanged.
