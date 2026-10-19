# v28 key-case audit (completed actual Episodes)

Frozen archive SHA44ec0e8cef27bb62cbfab38dbafb79d9262bf95e0afb4dd3a0b7c823cb164416. Read only from robust_v28_20260929/runs/ablation. Source results and selected structured events saved in results_and_events.json. Four selected cases are not the complete28-case denominator.

| Case | step_preview final result | First remaining observed issue |
|---|---|---|
|6|FAIL32.10s, op1|Temporary buffer push completes2.55s but postcondition yaw about−5.066°, outside original5°. table8, retained left10.9806N. No integer/float boundary divergence. No physical preview or yaw feedback because temporary buffer is outside final-placement scope.|
|7|FAIL183.75s recorded, op4|Final actual push permits exact75physics steps=.15s although accumulated float age=.15000000000071623, then rejects100steps=.2s of absent20Hz table support. This is genuine remaining support failure.|
|218|FAIL124.40s, op4|Empty-arm pregrasp normal shortcut with headroom disabled: left joint5 measured1.785999rad/s>1.76 (+1.477%). Previousop3 yaw preview verified and actual terminal matched.|
|310|FAIL9.25s, op1|Empty-arm pregrasp normal shortcut with headroom disabled: left joint5 measured1.783042rad/s>1.76 (+1.309%). Never reaches old final-push duration failure.|

Case7 op3 selected yaw-feedback after original accuracy failure and command-reference support failure; actual verified local push and terminal match. Atop4 allthree preview candidates failed: original lost support, command-reference and yaw-feedback both finished local sequences then failed push accuracy. The defined fallback then ran original and reproduced support failure. No preview is counted as actual success; overall case7 failed.

All four float_baseline versus step_baseline outcomes and frame counts match:6 no_feasible_grasp_approach3538;7 same3919;218 primitive_path_infeasible563;310 cartesian_collision_or_wrist1268. None of those four baseline executions had a150ms-boundary mismatch, so do not attribute their outcomes to integer clock. step_preview differs in additional control/geometry settings; it is not a clock-only ablation.

Next authorized bounded experiment: fresh6/310 using exactly frozen step_preview config except empty_arm_shortcut_headroom_enabled=True. New external collection v28_preview_headroom_fresh_6_310, singleworker, maxattempt1, selectedpreflight2. No caps, budgets, physics or acceptance changes. Temporary-buffer feedback scope is not changed. Case7's remaining issue is after an accurately timed200ms support loss, so repeating floating-boundary fixes would target the wrong cause.

## Fresh headroom-only contrast completed

External config differs in exactly empty_arm_shortcut_headroom_enabled False→True; frozen archive SHA and per-source-file hashes are in headroom_driver.json. One worker, maxattempt1, selectedpreflight2(11.936s), complete generate109.906s. Both actual Episodes failed:6 at35.30s,706frames, same temporary-buffer yaw postcondition (table8, left10.9737N);310 at39.702s,795frames, leftjoint5 measured1.781772>1.76rad/s during post-place retreat. HeadroomTrue passed the former310 pregrasp overspeed at9.252s and completed first buffer placement, but did not produce complete success. Retreat has Cartesian-rise and tuck stages; the event stream logs headroom on the Cartesian shortcut but does not individually label the subsequent tuck, so do not attribute the later overspeed to a specific subsegment without trace analysis. Failure-video agent was given both actual result directories.

## Approved temporary-buffer yaw-feedback isolation: negative

Frozenv28, same case6 fresh headroomTrue entry frame655. Restored full recorded MuJoCo integration state, incoming prior control, retainedleft relation and integerclock16375physics steps/origin0/dt.002. Every preceding interval is complete with matching metadata dt/substeps; entry actual table support is positive, so missing_since/missing_step=None reproduces the original support-reset contract rather than clearing an active missing period. Runtime clock validator passes.

Original local push reproduces every recorded qpos/qvel/action exactly (max0) and final yaw−5.075224°, table8, left10.97369268N, primitive_postcondition_failed at2.55s. Recorded source has no next endpoint frame after failure, so this is exact recorded-prefix reproduction, not an independently recorded endpoint comparison.

Only candidate overrides push_yaw_feedback_enabled=True and push_yaw_feedback_scope='all' for this nonseparation temporary operation. Existing gain2,1.5s feedback time,1.5° amplitude and additive flag remain unchanged. At1.5s observedyaw−4.648962°, requested+1.5°. Both quintic and additive fail the existing normal-band check at suffixu=0: commandTCPz=.9049160876 versus allowed[.8968714085,.8973714085], exceeding upper bound by7.544679mm. Additive exact54node certificate passes v/a/j bounds; geometry rejects it. Both rejected candidates fall back to the original validated suffix; recorded qpos/qvel/action remain bit-identical and the same postcondition fails. Release/retreat/finalverify are correctly not reached after the physical primitive failure.

No broader buffer scope is justified by this result. Do not widen the normal band or call this an executed feedback improvement. Original/candidate summary, events and2ms forceCSV retained in v28_buffer_yaw_original and v28_buffer_yaw_candidate; no new sweep or production edit performed.
