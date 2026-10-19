# Independent80mm held-IK proposal: design only

No production edit or new physical experiment. The four v31 full-episode failures do not establish a maximum residual for an entire feasible placement path: solver rejection truncates construction at the first point outside30/40mm. Residuals40.17/41.86mm are local censored observations, not evidence that42mm or80mm will complete the path.

## Necessary implementation distinction

The current completion helper computes max(original,min(cfg.ik_position_tolerance_m,completion_held_ik_position_tolerance_m)). Global ik_position_tolerance_m defaults40mm. Raising only field validation to80mm is ineffective. An explicitly declared held-only80mm candidate must use max(original,completion_held_ik_position_tolerance_m) when profile=completion_first, holding!=None and retained_contact=None; strict, empty arms and retained pushing remain unchanged. Field default remains22mm, validation upper bound becomes80mm, and the independent candidate config selects80mm. Keep original22mm seed scoring/order and only use the new bound after strict solutions fail, with unchanged8seeds/iterations. No auto escalation.

## What the existing guards prove and do not prove

Rigid-grasp consistency15mm/.10rad means both arms imply nearly the same object pose. It does not bound that shared pose's offset from the requested object pose. Both hands may consistently be80mm from the target. Absolute orientation.05rad, branch and joint range checks remain. Complete path shadow checks place the object at the left TCP-implied pose, so collision checking follows the predicted executed configuration rather than falsely checking the ideal target.

Actual servo execution still checks bilateral force/contact loss, carried support contact and tilt, collision/penetration, speed/power, camera, and configured physical deadline. These prevent quietly declaring execution valid merely because IK was admitted. They do not guarantee no transient undesired contact occurs before detection. This is a guarded simulation experiment, not a safety guarantee.

Task closure is independent: lift must physically rise15–20cm; separate alignment must reach actual accepted XY; place must physically support and release near its accepted staged pose; final all-tray stable released position50mm/yaw10deg and actual nonoverlap/gap are retained. An80mm common offset can fail these conditions. Larger IK tolerance may therefore exchange a planning failure for a truthful postcondition failure rather than improve completion. Existing servo-deflection50mm guard is a different error (command TCP versus measured TCP), remains unchanged, and must not be conflated with IK target residual.

## Avoid threshold chasing

Use one predeclared80mm candidate alongside the existing40mm control for the same exposed cases6/9, with unchanged chosen action budget and all other flags. Before execution, complete the entire path construction and original collision/rigidity/camera/dynamics validation. Record accepted absolute-error vectors, per-side maximum position residual across the whole selected path, maximum relative rigid error and predicted final object displacement from the task goal. Record early termination if any criterion fails; do not report a truncated path maximum as the complete-path maximum. Existing accepted_ik_solution_errors events expose norms but are not a complete selected-path certificate because they also cover seeds/probes later discarded; an explicit selected-plan diagnostic is needed for that statement.

If a full qualified reference exists, execute it normally in a new fresh attempt and report actual complete trajectory, terminal pose/contact and task/strict flags. Keep policy_deviation planning_only and conservative strict_success semantics. If it fails physical closure, inspect the actual residual direction/remaining task error before considering any new policy; do not keep increasing80mm. Do not replace actual success with any geometric preview or local continuation.

No new success is claimed; frozen v30b full400 and upcomingv32 timing/retry remain unaffected.
