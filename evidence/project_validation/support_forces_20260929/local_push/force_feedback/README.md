# v11 case 5: one bounded private force-feedback experiment

Source: frozen `robust_v11_20260929/runs/regression`, case 5, final push entry frame 2463, tray 1, right retained hand. Neither frozen release nor production code was changed. These are isolated operation continuations, not full Episode results.

The original continuation reproduces every recorded action/qpos/qvel exactly and fails with `retained_contact_lost` at 2.70 s. Its unrecorded terminal post-step state cannot be independently matched. The feedback candidate passes the push, release and retreat, but final stable verification fails with `push_accuracy_not_met`. It is therefore **not a repaired full operation**.

| Common first 2.70 simulation seconds | Original | Feedback |
|---|---:|---:|
| Physical substeps | 1350 | 1350 |
| Table-support fraction | 79.9259% | 80.8889% |
| Mean table normal force | 12.0587 N | 12.2413 N |
| Peak table normal force | 45.4149 N | 52.8381 N |
| Longest actual unsupported interval | 6 ms | 8 ms |
| Minimum height relative to table | -0.15676 mm | -0.15922 mm |
| Maximum height relative to table | +0.09904 mm | +0.12512 mm |

The candidate only improves support duty by 0.963 percentage points while force spikes and unsupported intervals worsen. Passing the original 20 Hz abort point does not establish more robust physical support. The whole-operation support fraction is deliberately not compared because the candidate continues through much longer stationary release/verification phases.

## Exact intervention and timing

`scripts/diagnostic_force_suffix.py` sums actual `mj_contactForce` reactions on the tray from the explicitly named table bodies. Contact force is transformed by `frame.T`, sign is reversed when the tray is geom1, and the resultant is projected onto the common upward table normal. Contacts with two tables are summed once each; fingers are excluded. The script checks that all table normals agree and are horizontal. No forces are invented from body weight or observation labels.

Only completed past frames initialize the reference: five frames, each exactly 25 original 2 ms substeps, with at least 90% real support. The actual reference was **8.28698 N**, reflecting the existing hand/table load distribution rather than the approximately 12 N total mean later in motion. Two completed-frame force means drive the bounded command offset. Consequently all ten requested corrections were **upward**, +30.26 to +52.04 micrometers, not additional downward preload. The causal initial-load reference proved materially different from the earlier planning assumption of approximately 12 N.

Ten updates at elapsed times 1.50–1.95 s were accepted. Each joins the current curve's exact q/v/a to the corrected endpoint over unchanged remaining time, with zero terminal velocity/acceleration. Maximum measured C2 boundary error is 5.56e-17. Exact derivative/joint bounds, original path/camera/grasp checks, the unchanged 0.25 mm normal band, inverse dynamics and runtime physical guards remain active. Rejected updates would retain the latest accepted suffix; the tests explicitly verify this behavior.

Push motion remains 2.75 s plus the original 0.10 s verification, yielding 2.85 s. The full candidate continuation runs 16.10 simulation seconds before the final accuracy failure. Final position error is 8.5688 mm, yaw +2.8727 degrees, both gripper forces are zero and table contact count is four; the original final geometric acceptance still rejects it.

Planning costs **9.333 wall-clock seconds** in total, 0.823–1.017 s per update. Candidate push planning/execution wall time is 14.334 s; full continuation wall time is 30.303 s. Original failed continuation costs 4.288 s. Physics timestep, substeps per frame and simulated motion deadlines are unchanged; there are no extra physics advances, waits, resets or physical-state assignments during planning. These offline update costs exceed the 50 ms control interval and are not evidence of real-time controller feasibility.

## Verification and interpretation

Five standalone tests check force-window causality and units, bidirectional saturation, compression rejection, preservation of the latest accepted suffix, and correctly signed summation across two tables while excluding fingers. All pass. The existing ten support-estimator tests also pass.

The initial candidate launch rejected an older frozen source-function shape before creating a runtime or executing motion. The adapter was corrected to preserve v11's exact inline `plan(...)` call and only replace its subsequent executor; `feedback_v2` is the sole executed feedback candidate, not a second parameter search.

This experiment also changes the shape of the remaining joint curve when fitting each C2 suffix. Its physical effect cannot be attributed solely to the small normal corrections. The subsequently authorized zero-gain control below tests this confounding directly. The observed outcome does not justify adopting force feedback as a production stability fix.

## Authorized zero-gain C2 control

One additional private control uses gain exactly zero while retaining the identical ten update times, causal force windows, IK endpoint solving, full checks and fixed remaining-time C2 refits. All ten zero-offset updates were accepted; there is no zero-offset shortcut that skips replanning. Six standalone tests now pass, including zero-gain behavior.

Over the common first 2.70 s, this control has support fraction **80.1481%**, mean force **12.2496 N**, peak **54.6296 N**, longest unsupported interval **8 ms**, and min/max relative height **-0.17714/+0.17289 mm**. It also passes the push in 2.85 s, then fails the final unchanged geometry check at 16.10 s with `push_accuracy_not_met` (position error 8.4094 mm, yaw +2.8271 degrees). Thus C2 refitting alone is sufficient to pass the original support abort point in this single restored case.

Relative to zero gain, actual force feedback adds only **0.7407 percentage points** of support duty, reduces the peak from 54.63 to 52.84 N, and leaves the longest unsupported interval at 8 ms. Both remain worse than the original 45.41 N/6 ms on these stability indicators. Neither produces a successful full operation. This is evidence against claiming that force feedback repaired the failure or materially stabilized support.

Zero-gain planning costs 8.340 wall-clock seconds; complete continuation costs 27.626 s. As before, simulation time and motion budgets are unchanged and these costs exceed a real-time 20 Hz implementation budget. Exact comparison data are saved in `comparison.json`; zero-gain events, summaries, generated candidate source and substep force evidence are in `local_full_push_v11case5_force_zero_gain`.
