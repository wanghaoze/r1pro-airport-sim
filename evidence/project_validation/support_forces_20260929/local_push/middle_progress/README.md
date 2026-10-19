# v18 feedback case 5 op4: withdrawal middle-knot progress

The original same-entry `.30` path was first reproduced and rejected before motion solely for duration: Cruise 5.70 s, Blended 3.00 s versus 2.90 s available. This recorded original rejection is required by the private runner before either candidate may run. Existing feasible paths are not replaced. Source: `robust_v18_20260929/runs/ablation/feedback`, case 5, op4/tray0, frame 3285.

Only the retained arm's joint interpolation fraction at the existing withdrawal intermediate knot changes. The free-arm goal still rises 10 cm and retracts horizontally 6 cm; the intermediate knot remains, as do all original bounds, camera/collision/grasp/inverse-dynamics checks and task acceptance.

| Middle progress | Planning outcome | Physics |
|---|---|---|
| .30 original | Fastest 3.00 s, rejected | None |
| .45 first candidate | Blended 58 frames = 2.90 s, full original plan checks pass | Selected for sole rollout |
| .60 second candidate | Cruise 9.90 s, Blended 2.95 s; rejected | None |

Planning-only success is deliberately encoded as `diagnostic_planning_accepted` in the diagnostic summary to stop before any execution. It is not a controller failure or a physical success label.

The .45 rollout completes push in **3.00 s exactly**: 2.90 s motion plus the original 0.10 s verification. It proceeds through release and retreat, then fails final stable geometric acceptance with `push_accuracy_not_met` at 16.15 s. Final position error is 9.2465 mm, yaw +2.5233 degrees, both gripper forces zero and eight true table contacts. Thus it resolves this local planning budget rejection but does not repair the whole operation.

The already-enabled frozen v18 yaw feedback observes +1.42277 degrees at 1.50 s and requests -1.5 degrees. Its candidate is rejected by the existing supported-normal band: at suffix fraction .40, command z=0.889020431 m falls 6.899 micrometers below the allowed lower bound 0.889027330 m. The .45 original suffix then continues as required. No normal tolerance was widened.

Whole continuation wall time is 22.472 s; push planning/execution wall time is 5.156 s. The force trace includes release and stationary verification, so its aggregate support fraction is not a comparable push-only stability metric. No full Episode or collection success is claimed.

Entry restoration follows the prior free-retreat-height diagnostic: frame 3285 is reconstructed from the final completed raw1 interval, after two neighboring interval ctrl/qpos/qvel checks match exactly. The entry itself has no independent recorded terminal state. The same reconstructed entry reproduces the original exact duration rejection. No frozen release, production package or collection was edited.

## Subsequently authorized single yaw-amplitude backtrack

On the already feasible .45 trajectory, one private experiment retains the full gain-2, max-1.5-degree request first. Only when the full request fails the normal-band check does it try 0.75 times that request, with identical duration and all original candidate checks. No other rejection triggers retry and no third scale exists. Three standalone tests verify these bounded semantics and exact fallback timing.

The full -1.5-degree candidate reproduces the 6.899-micrometer normal-band violation at suffix fraction .40. The -1.125-degree candidate also fails: command z=0.889023969 m at fraction .415, **3.361 micrometers below the unchanged lower bound**. Both are rejected. The .45 original suffix executes, and final pose, forces and support statistics exactly match the preceding .45 rollout: push passes in 3.00 s but full local verification fails at 16.15 s with `push_accuracy_not_met`.

The two planning attempts cost 0.464 and 0.431 wall-clock seconds; full continuation costs 20.572 s. Evidence is saved under `local_v18case5_op4_middle_0.45_backtrack`. This bounded retry did not produce an admissible correction or change the physical outcome. No further scales were tested and no production code was edited.

## Subsequently authorized 50-micrometer endpoint lift

One separate private candidate preserves the original -1.5-degree yaw request. Only after its original lower-normal-band rejection does it raise the feedback IK TCP endpoint's world Z by 50 micrometers. XY, orientation, remaining C2 duration, normal-band boundaries and every other check stay unchanged. An upper-band violation would not trigger this retry. Five standalone semantic tests pass, including unchanged XY/orientation and lower-band-only activation.

The retry is also rejected: at suffix fraction .405, command z=0.889026077 m is **1.25244 micrometers below the original lower limit 0.889027330 m**. This is the first rejected sample, not a claimed global maximum violation. The controller therefore runs the original .45 suffix. Full force CSV bytes are identical to the prior .45 rollout; within the same first 3.00 seconds, support is 79.8%, peak table force 62.5571 N and longest missing support 10 ms. None improves. Full local verification remains `push_accuracy_not_met` at 16.15 s.

Evidence is saved under `local_v18case5_op4_middle_0.45_lift50um`; wall time is 20.873 s. No larger endpoint lift, additional amplitude or changed guard was tried. No production code was modified.

## Final authorized 100-micrometer endpoint lift and stop

The last private candidate raises only the feedback TCP IK endpoint world Z by 100 micrometers, retaining the full -1.5-degree request, the .45 withdrawal knot, the original 1.40-second C2 suffix and the exact original normal band. Five diagnostic semantic tests pass. It also fails the lower-normal-band check, at suffix fraction .415: z=0.889024433 m versus lower bound 0.889027330 m, a first rejected-sample violation of 2.89679 micrometers. This is not a global maximum; the rejection sample changes across candidates, so these numbers do not establish a monotonic excursion trend.

| Endpoint world-Z lift | First rejected suffix fraction | Lower-band violation at that sample | Executed feedback |
|---|---:|---:|---|
| 0 micrometers | .400 | 6.89911 micrometers | No |
| 50 micrometers | .405 | 1.25244 micrometers | No |
| 100 micrometers | .415 | 2.89679 micrometers | No |

All three run the identical original .45 suffix: full force CSV files are byte-identical. Push completes in 3.00 seconds (2.90 motion + .10 original verification), but the complete local push/release/retreat/verify sequence fails `push_accuracy_not_met` at 16.15 seconds, final position error 9.2465 mm and yaw +2.5233 degrees. The common first-3-second support fraction is 79.8%, peak table force 62.5571 N and longest missing support 10 ms. The 100-micrometer run takes 18.914 wall-clock seconds; its two planning attempts take .390 and .395 seconds.

Evidence is in `local_v18case5_op4_middle_0.45_lift100um`; `endpoint_lift_comparison.json` retains all 0/50/100 outcomes. This endpoint-adjustment direction is stopped. No larger lift or other parameter is tried; no production/frozen release, collection, acceptance rule or timing budget changed. These are private local diagnostics, not full Episode successes. The earlier statement that no larger lift had been tested describes the state before this final separately authorized experiment.
