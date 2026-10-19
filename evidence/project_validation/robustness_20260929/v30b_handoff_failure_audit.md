# v30b contact handoff actual failure audit

Snapshot13 finalized contact_handoff_aborted episodes:10 duration-infeasible temporary pushes,1 temporary support-loss,1 temporary postcondition failure,1 final-placement support-loss. This is a selected failure class, not a success-rate denominator. Representatives54,82,122 are all ordinary scenes. Read-only result/events plus last4 numeric samples; no new physics.

## Case54: temporary-buffer push path longer than budget

Operation1 tray0 temporary destination[.85,-.567241,.801]. Actual placement is staged105mm away at y-.462241, after lift selected outward60mm. Retained left13.47N/free right0N, table8, pose level at push boundaryframe879. Original withdrawn-hand/push path shortest3.8s, fraction.45 alternative4.0s, fraction.60 alternative4.2s; existing merge candidate shortest3.3s. All exceed2.9s motion availability inside original3s push budget. No push physics executed. The terminal original two-candidate detail omits already-tried alternatives, but events retain them. This is real reference timing infeasibility in the current four-knot motion, not IK/camera residual or a final acceptance typo. Increasing settle/grace cannot help.

## Case82: real contact instability, not150ms float rejection

Operation1 temporary tray0 push, retained left, failureframe660 at33s after1.2s push. Event shows75 physics steps exactly150ms, integer_time_allowed=True although the oldfloat comparison differs. Force11.94N and close command0 are intact. Nevertheless the retained guard also requires bottom gap within[-3,2]mm; time allowance alone never certifies support. Last recorded pre-action sample has no table contact, bottom gap1.637mm and supposedly released right hand8.30N. The terminal guard cannot be blamed on float timer because integer150ms was admitted; geometry/support failure is the remaining gate. Exact terminal bottom gap is not stored in the fault detail and is not invented here. Strong candidate cause is unintended free-hand contact while pushing/withdrawing, rather than insufficient grace.

## Case122: free hand recontacts and tips the tray

Operation1 temporary push; endframe674 after2.55s. Terminal postcondition stable_frames0, left/right forces20.680/17.793N, table contact1, tray body z.827704 versus table.8, bottom.799835, tilt about8.1deg. Position is only about23mm from temporary goal and yaw small, but the free hand is not released. The retained push postcondition explicitly requires free-side force<=.5N, so completion XY/yaw cannot accept it. Further blindly pushing while both fingertips load the tray risks tipping. This is an actual control/contact failure, not excessive final position precision.

## Bounded next proposal

The shared avoidable operation is the105mm final adjustment into a *temporary* buffer:12of13 are temporary, including all10duration failures. Before executing a buffer placement, consider whether the already-clear release/staging pose itself is a legal temporary buffer that clears the originally requested tray and respects protected trays, footprint, stack and clearance constraints. If so, declare that pose as the temporary operation destination before actual placement and verify it normally; do not pretend it reached the old destination. This could avoid an unnecessary retained push/withdrawal when no semantic final-slot requirement exists. It requires a bounded, explicit scheduler/context change and fresh complete episodes; current data do not prove it always applies.

If the temporary staging pose cannot preserve requested-tray clearance, retain the original plan/failure. Do not waive3s/force/tilt/penetration checks. An alternative control diagnosis would shorten free-arm withdrawal travel or split a separately budgeted, guarded released-arm clearance action before the push, but it must be specified honestly and physically verified; merely replacing the four-knot path or extending grace has no current evidence. The current400run remains untouched.
