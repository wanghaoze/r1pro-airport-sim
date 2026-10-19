# Private v19 case 218: preserve alignment command-grasp reference

Frozen source/controller: `robust_v19_20260929`, `runs/ablation/alternate_align`, case 218, frame 648. The recorded integration state is immediately before the final transport alignment. No production, v20, collection, contact/camera threshold, material, servo, or timing change.

## Exact original control comparison

The unmodified place function reproduces all 60 recorded 20 Hz alignment frames with maximum qpos, qvel and action errors exactly zero. After 3.00 s alignment, place fails before descent motion with the same `cartesian_collision_or_wrist`: collision None, right camera ahead 1.307690 mm < original 2 mm. The source does not independently record the terminal frame 708; exactness is asserted only for the recorded prefix and matching failure diagnostics.

## Sole candidate and physical outcome

Only the second `continue_loaded_reference(r)` call immediately after transition to place/descend is omitted in a private function copy. The command-grasp relationship established before alignment is retained. The real horizontal target, measured start semantics, preload, IK/path/rigid/collision/camera/inverse-dynamics checks, all runtime guards, release logic and acceptance remain unchanged. There is no new wait or time budget.

The candidate's alignment also exactly matches the recorded prefix. It then completes:

| Stage | Simulation duration | Outcome |
|---|---:|---|
| transport_align | 3.00 s | Original alignment |
| place | 2.85 s | Real table support and partial release accepted |
| retained push | 2.95 s | Original physical guards pass |
| final release, retreat, stable verify | Remaining 7.50 s | Original operation verification passes |
| Complete local continuation | 16.30 s | Returned without Fault |

After final release, the ordinary retreat IK is unreachable, so the **existing** `supported_release_retreat_fallback` runs only after table support and both hands released. It retreats to `r.tucked`, then original `verify_operation` passes. This fallback must not be omitted from the result or described as a fallback-free trajectory.

Final position error is 9.96335 mm, yaw -0.62279 degrees, both gripper forces zero and eight real table contacts. The task is a temporary buffer operation (`slot=-1`), so the runner's `final_slot_geometry_ready=False` is not the applicable acceptance criterion. `Machine.push` invokes the original `verify_operation`: position, yaw, tilt, <=.01 m/s speed, table contact and released forces must remain valid for the original stable interval. It returned successfully. This is not a complete Episode or evidence of a 70% success rate.

Wall time: original 4.885 s; candidate 22.750 s. Aggregate candidate table force peak is 77.988 N; the 4.094 s longest no-table-contact interval includes the intended airborne alignment/descent and must not be misreported as retained-support loss. No support-force improvement is claimed from that aggregate.

Evidence subdirectories retain original/candidate `summary.json`, `events.json`, `forces.csv` and exact private place source. The private runner is `scripts/diagnose_alignment_reference.py` (syntax compiled locally). Historical counters/wall budget are not fully restored; original runtime physical guards remain enabled, and the original recorded prefix matches exactly. This single result supports testing the double-reference-reconstruction hypothesis across more complete Episodes before production adoption.
