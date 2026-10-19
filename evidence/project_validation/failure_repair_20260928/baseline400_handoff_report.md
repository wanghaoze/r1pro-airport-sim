# Nested audit of 85 baseline contact handoff failures

Source: frozen `coverage_v4_20260928/runs/firstpass`, all 400 completed results. The independent script reads only `result.json` and `events.jsonl`; no HDF5 or labels are changed. Use `baseline400_handoff_nested_v2.json`; v2 correctly separates subsequent joining-arm failures from an earlier completed push.

| Actual inner cause | Cases | Share of 85 | Stage |
|---|---:|---:|---|
| `retained_contact_lost` | 56 | 65.9% | Push physically executing |
| `primitive_path_infeasible` | 19 | 22.4% | Push, zero motion, all candidates over time budget |
| `ik_unreachable` | 5 | 5.9% | Push, zero motion |
| `primitive_postcondition_failed` | 3 | 3.5% | Push completed movement, verification fails |
| `joining_arm_path_unavailable` | 2 | 2.4% | Subsequent approach after an earlier completed push |

There are 24 zero-motion push failures. Including the 2 subsequent joining-arm planning failures, 26/85 (30.6%) fail before motion in the current failing phase. These are not evidence of a physical support failure. The remaining 59 consist of 56 actual contact failures and 3 postconditions.

All 56 contact failures have **zero table contacts, retained right gripper force 9.815–15.419 N, and closed command aperture**. None is a finger-force loss. Of these, 51 begin after `PLACE_TRAY/open` and 5 after `ADJUST_TRAY/close`. Failures occur 1.25–2.65 s into push (quartiles 1.5875/1.875/2.275 s), not at initial handoff. This makes intermittent table support during translation the dominant remaining control issue. It does not prove a universal right-hand asymmetry: the original policy heavily uses the right hand.

All 19 path failures follow placement and list only `duration`; shortest candidates require 2.95–4.05 s versus 2.90 s available. Seventeen occur on operation 1 and two on operation 2. The 5 IK failures are source separation pushes, before motion; 4 right-arm and 1 left-arm goals miss by 16.6–22.1 mm. Two joining failures (291, 371) exhaust all 7 joining-arm offset goals with IK failure. Postconditions: cases 37 and 385 are separation pushes; case 232 is final placement push with only one accepted verification frame. All three have table support and strong retained gripping at the final sampled state; this does not establish what failed on the preceding verification frame.

## Actionable priorities

1. For the 56 actual support failures, test bounded feedback from real averaged table-normal force in one exact failed local continuation, preserving the original constraints. Previous timestep, servo damping, static preload, full-duration and all-loaded-command experiments did not establish a robust solution and should not be repeated as presumed fixes.
2. For the 19 pure duration failures, screen the complete retained-side push plus free-arm withdrawal before selecting placement/release setup. A bounded left/right retained-side comparison or completing free-arm clearance during an already budgeted release can change geometry and required path length. Both are hypotheses requiring all original collision/camera/contact and per-action timing checks; never grant a longer push or hide extra motion time. Replacing the withdrawal joint midpoint by Cartesian IK alone has already shown insufficient benefit.
3. For the 5 source separation IK failures and 2 joining failures, include the exact compensated push endpoint and subsequent opposite-arm approach in source-stance feasibility. Merely reaching the initial rim is insufficient. Reject the whole proposed stance before grasp if the following operation cannot be completed; use another existing bounded candidate.
4. For the 3 postconditions, inspect source separation blocker clearance in 37/385 and both terminal verification frames in 232. Do not turn one stable frame into two or remove blocker clearance. The current yaw-feedback work targets a different final-geometry problem and has not resolved these cases by evidence.

## Bounded next private experiment proposal

Use **v11 case 5's final push**, start frame 2463, tray 1, as a failed baseline. Existing exact raw1 replay has zero endpoint qpos/qvel error. Across the 53 complete intervals before the incomplete failure frame: table support fraction 80.151%, peak 45.415 N, longest real gap 6 ms, average load 12.108 N. In its last 0.6 s the per-frame mean table force is 8.60–10.58 N while individual peaks reach 45.4 N. Minimum tray height relative to the table ranges -0.157 to +0.099 mm; maximum roll/pitch is only 0.0342/0.0294 degrees. Therefore a raw instantaneous-force controller would chase impact spikes, and unconditional extra downward preload is not justified.

Proposed one candidate (not yet implemented or run): keep the original 20 Hz reference execution and physical timestep. Accumulate true signed table-normal impulse over each original 25-substep frame, use a two-frame moving mean, and take the first 0.25 s supported mean as the load reference. From 1.50 s to 2.00 s, at most 10 frame-boundary updates request an absolute normal endpoint offset `-clip(25 micrometers/N * (Fref-Fmean), -0.15 mm, +0.15 mm)`. This is a bounded bidirectional command offset, not cumulative pressure integration. Record real min_z and vertical velocity alongside force; reject further downward correction when average min_z is already more than 0.05 mm below its supported entry baseline. This conservative gate tests whether load deficit can be corrected without driving existing compression harder.

Every update must solve the retained TCP endpoint with unchanged horizontal/yaw goals, preserve free-arm endpoint, and join the currently executing reference's exact q/v/a to the new endpoint with zero terminal v/a over **its unchanged remaining motion time**. Check exact polynomial q/v/a/j extrema, original path/camera/grasp checks, original normal band, inverse dynamics and all runtime guards. If rejected, continue the currently accepted suffix; never jump back to the original curve after a previous update has been accepted. No waiting, physical parameter changes or additional time. Restore and reproduce the original failing push first, then run only this one candidate through release/retreat/verification if it survives. Report support fraction, peak/mean force, maximum/minimum height, longest real missing contact, accepted/rejected updates, all original failure codes and computation cost. A successful local operation would not count as a full Episode success.

The gain, window and gate above are an explicit diagnostic hypothesis, not established tuning. In particular, average-height compression may block most updates; that is a useful negative result rather than a reason to remove the gate or relax the contact criteria.
