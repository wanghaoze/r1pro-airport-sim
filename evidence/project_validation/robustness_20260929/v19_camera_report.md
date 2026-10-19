# v19 camera-planning failure audit

Read-only source: `robust_v19_20260929/runs/ablation`; no v20 or production edits. Private projections are planning evidence, not physical trajectories or task successes.

## Classification

| Variant/case | Failure | Context | Motion in failed primitive |
|---|---|---|---|
| alternate_align and alternate_feedback / 218 | Pure camera-front planning rejection | First place/descend, frame 708 (35.40 s) | 0 s |
| alternate_align and alternate_feedback / 4 | Pure camera-front planning rejection | Place/descend, frame 2703 (135.15 s) | 0 s |
| alternate_align and alternate_feedback / 310 | Measured joint overspeed | After place, free retreat; 39.702 s | Actual execution |
| baseline / 310 | Pure camera-front planning rejection | Second operation place/descend, frame 1268 (63.40 s) | 0 s |
| baseline / 218 | primitive_path_infeasible | 28.15 s; older alignment/path barrier | No comparable descent |
| baseline / 4 | Complete clean success | 158.25 s | Complete episode |

All camera failures have `collision=None`, positive wrist-upright dots and empty self-view hits. The rejecting right-camera forward projections are respectively 1.30769 mm, 1.62205 mm and 1.45283 mm versus the unchanged >2 mm contract. They are candidate IK states, not physically executed camera violations. 310's alternate variants instead exceed left_arm_joint5's 1.76 rad/s cap with 1.78177 rad/s during retreat; this must remain a separate dynamics issue.

## Predicted versus physical loaded posture

Exact recorded screening states reproduce the original qualified candidate and frame budgets using frozen v19 code. Sampling each accepted predicted path at 201 points gives these right-camera minima:

| Case | Predicted alignment minimum | Predicted descent minimum | Actual place-entry camera | Command place-entry camera | Actual tray pitch at place entry |
|---|---:|---:|---:|---:|---:|
| 218 | 10.029 mm | 9.743 mm | 6.312 mm | 4.415 mm | +5.977 degrees |
| 4 | 5.810 mm | 5.810 mm | 8.224 mm | 5.810 mm | -5.501 degrees (tray yaw 179.878 degrees) |
| baseline 310 | Not screened | Not screened | 6.513 mm | 4.308 mm | -2.368 degrees |

Measured TCP-command displacement at entry is left/right 20.658/14.312 mm (218), 18.691/20.166 mm (4), and 20.048/18.024 mm (310); these reproduce logged compliance-reference values. All live entry camera projections remain above 2 mm. Failure appears only when the next descent reconstructs the command relationship against the tilted actual tray, then requests a horizontal tray target.

The predictor's `_project` advances ideal rigid geometry to the alignment endpoint, yielding a horizontal predicted payload; subsequent `continue_loaded_reference` thus does not include the actual residual loaded tilt. In live execution, tray pitch remains approximately 5.5–6 degrees after alignment for 4/218. The next horizontalization commands additional wrist rotation. This explains a concrete predictor/live mismatch and supports investigation of bounded loaded-pose uncertainty or a different feasible grasp/transport posture. It does not establish that simply increasing the 2 mm planning threshold fixes the problem: case 218 originally had 7.743 mm predicted clearance above that threshold and still failed. Do not reduce the physical threshold or change camera transforms.

Entry measurements reconstruct the terminal completed interval using actual recorded controls, supporting raw1 constant controls and raw2 per-substep journals. The terminal state itself is not independently recorded. Matching original logged TCP deflections provides a consistency check; this audit does not claim a fully independently observed terminal replay.

## Four authorized private yaw projections, case 218 only

At the reconstructed real zero-motion place-failure entry, frozen `qualify_placement` probes current base yaw offsets with XY, tray destination, IK/path/rigid/camera/dynamic checks and budgets unchanged. The predictor includes a new high alignment before descent; therefore the current-base diagnostic is not represented as an exact replay of the original direct place planning call. All four are rejected before any physical navigation:

| Base yaw offset | First rejected right camera projection | Collision |
|---|---:|---|
| +.05 rad | 1.775 mm | None |
| -.05 rad | -2.325 mm | None |
| +.10 rad | -.104 mm | None |
| -.10 rad | .946 mm | None |

The unchanged-base predictor also rejects at 1.976 mm. No candidate qualifies, no navigation or local physical rollout is performed, and no broader scan is authorized or run. Route safety is consequently not certified by these geometric projections.

Evidence: `v19_camera_events.json`, `v19_camera_states_compact.json`, `v19_camera_prediction_compact.json`, `v19_camera_yaw_candidates_compact.json`. Diagnostic scripts are `scripts/diagnose_v19_camera_{events,states,prediction,yaw}.py` and server diagnostictools copies. No collection label or acceptance changed.
