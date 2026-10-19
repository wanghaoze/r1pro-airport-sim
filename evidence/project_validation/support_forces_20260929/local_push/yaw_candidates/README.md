# Case 5 final push: private yaw command diagnostic

These are isolated operation continuations, not complete Episode successes. Frozen source: `robust_v15b_20260929/runs/ablation/command`, case 5, frame 2466. Original push, release, retreat and verification were reproduced with zero action/qpos/qvel error over every recorded source frame. The source raw1 terminal post-step state is absent, so terminal exactness is explicitly unverified.

All candidates preserve physical parameters, the 20 mm feedforward cap, operation acceptance yaw 0, original physical guards and timing budgets. Only the private push target rotation changes. Production code and frozen collections were not changed.

| Target yaw compensation | Result | Final yaw | Final position error | Reserved neighbor/future gaps |
|---|---|---|---|---|
| 0 degrees | Final geometry fails | +2.76398 degrees | 8.628 mm | +3.641 / -2.288 mm |
| -1.5 degrees | Full local operation passes | +1.75391 degrees | 9.491 mm | +8.310 / +2.608 mm |
| -3 degrees | Retained table contact lost at 2.45 s | +0.80265 degrees at abort | 37.932 mm | Not final placement |
| -4.5 degrees | Planning rejected before execution | Unchanged | Unchanged | Not final placement |

The -1.5 degree candidate completes its push in 2.85 s and the full push/release/retreat/verify sequence in 15.10 s. At the end both gripper forces are zero and four real table contacts remain. The -4.5 degree candidate needs 4.35 s with the cruise path; the blended path exceeds the original normal band by 14.394 micrometers. Neither restriction was relaxed.

Original measured yaw progression, at seconds after push entry: 0: +0.13209 degrees; 0.5: +0.13304; 1.0: +0.13604; 1.5: +0.82400; 2.0: +1.32109; 2.5: +2.30993; 2.85: +2.76373. The dominant error accumulates during translation, not at entry. Original release changes position by only approximately 2.62 micrometers and yaw by 0.00025 degrees, excluding release recoil as the main cause.

Conclusion: this bounded experiment supports investigating online yaw control with continuous replanning, rather than a fixed negative compensation or a large gain on the tiny initial yaw error. It does not demonstrate a general control fix or full-scene success.

Reproduction: `scripts/diagnose_push_from_trace.py --full-push-operation --yaw-compensation-deg {-1.5,-3,-4.5}` against the frozen source. `scripts/summarize_yaw_diagnostic.py` reads the source yaw samples and completed candidate geometry. Subdirectories contain private candidate source, summary, event and substep-force evidence.

## One-shot measured-yaw C2 suffix

One additional independently authorized candidate uses actual yaw at 1.50 s: +0.823997 degrees. The command correction is `-clip(2*yaw_error, -1.5 degrees, +1.5 degrees)`, hence -1.5 degrees here. It builds a single quintic from the original curve's exact current q/v/a to the revised IK endpoint with zero terminal velocity and acceleration. Remaining duration is exactly 1.25 s; total reference motion remains 2.75 s, and the original 0.10 s verification makes the push 2.85 s. Failed validation would continue the original validated suffix, without changing physical state or timing.

All checks passed for this candidate. Boundary q/v/a errors are 0, 6.94e-18 and 5.55e-17; terminal errors are at most 6.53e-16. Exact polynomial extrema use real derivative roots plus interval endpoints. Peak velocity/acceleration/jerk ratios to the existing limits are 0.28450/0.28900/0.17782. Exact joint/gripper bounds, the original path collision/grasp/camera checks, the unchanged supported normal band, and inverse dynamics at 201 uniform samples plus analytical extremum times all passed. Runtime physical guards still execute at every original substep.

The complete local operation passed after 15.20 s, with yaw +1.73154 degrees, position error 9.4985 mm, reserved gaps +6.45179/+4.67995 mm, both gripper forces zero and four table contacts. A fresh original continuation again reproduced all recorded action/qpos/qvel exactly and failed the unchanged final geometry check. The candidate only supports this feedback direction in this one restored operation; it is not a complete-scene result or a general success-rate claim.

Implementation is private `scripts/diagnostic_yaw_suffix.py`, enabled by `--yaw-feedback-suffix` in the standalone runner. Three standalone mathematical tests verify C2 boundary conditions, exact extrema against dense samples, and rejection of implicit retiming. Evidence: `local_full_push_case5_c2_feedback` and `local_full_push_case5_c2_baseline`.
